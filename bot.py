import json
import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, Text
from utils.database import load_json, save_json
from utils.logging import setup_logger
from utils.checks import (
    check_spelling,
    check_post_metrics,
    check_text_length
)
from openai import OpenAI
from telethon import TelegramClient
from datetime import datetime, timedelta
import aiohttp
from utils.api import set_bot_getter
from utils.keyboards import get_main_keyboard
from typing import List, Dict, Any
from utils.config import CONFIG

# Настройка логирования
logger = setup_logger()

# Загрузка конфигурации
with open("config.json") as config_file:
    CONFIG = json.load(config_file)

# Загрузка данных о каналах и истории
channels = load_json("channels.json", default={})
history = load_json("history.json", default={})

# Функции для сохранения данных
def save_channels():
    save_json("channels.json", channels)

def save_history():
    save_json("history.json", history)

# В начале файла, где определены константы
CONFIG.update({
    "METRICS_CHECK_DELAY": 3600,  # 1 час
    "TEXT_CHECK_DELAY": 0,  # Мгновенная проверка
    "REACTION_CHECK_DELAY": 86400,  # 24 часа
})

bot = Bot(token=CONFIG["API_TOKEN"])

# В aiogram 3.x Dispatcher инициализируется через словарь, без передачи бота как позиционного аргумента
dp = Dispatcher()

# Регистрируем бота в диспетчере
dp.bot = bot

# Глобальная переменная для отслеживания состояния
waiting_for_channel = False

# Добавляем в начало файла инициализацию клиента Telethon
client = TelegramClient('bot_session', CONFIG["API_ID"], CONFIG["API_HASH"])

# Загружаем конфигурацию
ADMIN_IDS = CONFIG.get('ADMIN_IDS', [])

# В начале файла добавим структуру для хранения отложенных проверок
pending_checks = {}

# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    try:
        await message.reply(
            "Привет! Я бот для отслеживания каналов.\n"
            "Используй кнопки или команды для управления.",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await message.reply("Произошла ошибка при обработке вашего запроса.")


# Команда /help и кнопка FAQ
@dp.message(Command("help"))
@dp.message(Text(text="❓ FAQ"))
async def help_command(message: types.Message):
    try:
        await message.reply(
            "📋 Список команд и возможностей:\n\n"
            "➕ Добавить канал - добавление нового канала\n"
            "📋 Список каналов - управление каналами\n"
            "📊 Статистика - основная статистика\n"
            "📈 Расширенная Статистика - подробный отчет за 48 часов\n\n"
            "**Требования к постам:**\n"
            "1️⃣ Этап проверки контента:\n"
            "   • Орфография и грамматика\n"
            "   • Спам и повторы\n"
            "   • Читабельность текста\n\n"
            "2️⃣ Этап проверки метрик (через 24 часа):\n"
            "   • Просмотры: 10% от подписчиков\n"
            "   • Реакции: 6% от просмотров\n"
            "   • Пересылки: 15% от просмотров\n\n"
            "**Связь с разработчиком:**\n"
            "Telegram: [t.me/ctrltg](t.me/ctrltg)\n"
            "Сайт: [whomever.tech](https://whomever.tech)",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде help/FAQ: {e}", exc_info=True)
        await message.reply("Произошла ошибка при обработке вашего запроса.")


# Добавление канала (команда и кнопка)
@dp.message(Command("add_channel"))
@dp.message(Text(text="➕ Добавить канал"))
async def add_channel_command(message: types.Message):
    """Обработчик команды добавления канала"""
    try:
        global waiting_for_channel
        waiting_for_channel = True
        await message.reply(
            "Отправьте ID или username канала, который нужно добавить.\n"
            "Формат: @username +05:00 или -100123456789 -02:30\n\n"
            "Для отмены используйте команду /cancel"
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply("Произошла ошибка при добавлении канала.")


# Список каналов (команда и кнопка)
@dp.message(Command("channels"))
@dp.message(Text(text="📋 Список каналов"))
async def list_channels(message: types.Message):
    try:
        if not channels:
            await message.reply("Список отслеживаемых каналов пуст.")
            return

        text = "Список отслеживаемых каналов:\n\n"
        buttons = [[InlineKeyboardButton(
                    text=channel_id,
                    callback_data=f"manage_channel:{channel_id}"
        )] for channel_id in channels.keys()]
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.reply(text, reply_markup=keyboard)
        logger.info(f"Отображен список каналов для пользователя {message.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка при управлении каналами: {e}", exc_info=True)
        await message.reply("Произошла ошибка при управлении каналами.")


# Обработчик callback_query для управления каналом
@dp.callback_query(lambda c: c.data and c.data.startswith("manage_channel:"))
async def manage_channel(callback_query: types.CallbackQuery):
    try:
        logger.info(f"Запрос на управление каналом: {callback_query.data}")
        channel_id = callback_query.data.split(":")[1]
        channel_data = channels[channel_id]

        # Получаем текущие настройки метрик
        metrics = channel_data.get('metrics', {
            'views_percent': CONFIG['POST_SETTINGS']['MIN_VIEWS_PERCENT'],
            'reactions_percent': CONFIG['POST_SETTINGS']['MIN_REACTIONS_PERCENT'],
            'forwards_percent': CONFIG['POST_SETTINGS']['MIN_FORWARDS_PERCENT']
        })

        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить канал", callback_data=f"delete:{channel_id}")],
            [InlineKeyboardButton(text="🕒 Изменить часовой пояс", callback_data=f"timezone:{channel_id}")],
            [InlineKeyboardButton(
                text=f"📰 Новостной канал: {'✅' if channel_data['is_news'] else '❌'}",
                callback_data=f"toggle_news:{channel_id}"
            )],
            [InlineKeyboardButton(text="📊 Настройки метрик", callback_data=f"metrics_settings:{channel_id}")]
        ])

        await callback_query.message.edit_text(
            f"📌 Управление каналом: {channel_id}\n"
            f"📑 Название: {channel_data.get('title', 'Неизвестно')}\n"
            f"🕒 Часовой пояс: {channel_data['timezone']:+.2f}\n"
            f"📰 Новостной канал: {'Да' if channel_data['is_news'] else 'Нет'}\n"
            f"👥 Подписчиков: {channel_data['subscribers']:,}\n\n"
            f"📊 Настройки метрик:\n"
            f"👁 Просмотры: {metrics['views_percent']}% от подписчиков\n"
            f"👍 Реакции: {metrics['reactions_percent']}% от просмотров\n"
            f"↗️ Пересылки: {metrics['forwards_percent']}% от просмотров",
            reply_markup=keyboard
        )
        logger.info(f"Меню управления каналом {channel_id} отображено")
    except Exception as e:
        logger.error(f"Ошибка при управлении каналом: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при управлении каналом", show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("delete:"))
async def delete_channel(callback_query: types.CallbackQuery):
    try:
        channel_id = callback_query.data.split(":")[1]
        if channel_id in channels:
            del channels[channel_id]
            save_channels()
            await callback_query.message.edit_text(
                f"✅ Канал {channel_id} удалён из списка отслеживаемых."
            )
            logger.info(f"Канал {channel_id} успешно удален")
            await callback_query.answer("Канал успешно удален")
        else:
            await callback_query.answer("Канал не найден", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при удалении канала: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при удалении канала", show_alert=True)


@dp.callback_query(lambda c: c.data.startswith("timezone:"))
async def set_timezone(callback_query: types.CallbackQuery):
    try:
        channel_id = callback_query.data.split(":")[1]
        # Создаем кнопки для часовых поясов
        buttons = []
        row = []
        for tz in range(-12, 13):
            row.append(InlineKeyboardButton(
                text=f"{tz:+d}",
                callback_data=f"set_tz:{channel_id}:{tz}"
            ))
            if len(row) == 6:  # По 6 кнопок в ряду
                buttons.append(row)
                row = []
        if row:  # Добавляем оставшиеся кнопки
            buttons.append(row)
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback_query.message.edit_text(
            f"Выберите часовой пояс для канала {channel_id}:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при установке часового пояса: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при установке часового пояса", show_alert=True)


@dp.callback_query(lambda c: c.data.startswith("set_tz:"))
async def confirm_timezone(callback_query: types.CallbackQuery):
    try:
        _, channel_id, tz = callback_query.data.split(":")
        channels[channel_id]["timezone"] = int(tz)
        save_channels()
        await callback_query.message.reply(f"Часовой пояс для канала {channel_id} установлен: {tz:+d}")
    except Exception as e:
        logger.error(f"Ошибка при подтверждении часового пояса: {e}")
        await callback_query.message.reply("Произошла ошибка при подтверждении часового пояса.")


@dp.callback_query(lambda c: c.data.startswith("toggle_news:"))
async def toggle_news_status(callback_query: types.CallbackQuery):
    try:
        channel_id = callback_query.data.split(":")[1]
        channels[channel_id]["is_news"] = not channels[channel_id]["is_news"]
        save_channels()
        await callback_query.message.reply(
            f"Статус новостного канала для {channel_id}: {'Да' if channels[channel_id]['is_news'] else 'Нет'}"
        )
    except Exception as e:
        logger.error(f"Ошибка при изменении статуса новостного канала: {e}")
        await callback_query.message.reply("Произошла ошибка при изменении статуса канала.")


# Статистика (команда и кнопка)
@dp.message(Command("stats"))
@dp.message(Text(text="📊 Статистика"))
async def stats_command(message: types.Message):
    try:
        stats_text = "📊 Статистика каналов:\n\n"
        for chat_id, data in channels.items():
            channel_info = await bot.get_chat(chat_id)
            stats_text += (
                f"📌 {channel_info.title}\n"
                f"👥 Подписчиков: {data.get('subscribers', 0):,}\n"
                f"🕒 Часовой пояс: {data.get('timezone', 0):+.2f}\n\n"
            )
        await message.reply(stats_text)
    except Exception as e:
        logger.error(f"Ошибка при выводе статистики: {e}")
        await message.reply("Ошибка при получении статистики")


# Расширенная статистика (команда и кнопка)
@dp.message(Command("allstats"))
@dp.message(Text(text="📈 Расширенная Статистика"))
async def extended_stats_command(message: types.Message):
    try:
        stats_text = "📈 Расширенная статистика за 48 часов:\n\n"
        
        for chat_id, data in channels.items():
            try:
                channel_info = await bot.get_chat(chat_id)
                stats_text += f"📌 {channel_info.title}\n"
                stats_text += f"👥 Подписчиков: {data.get('subscribers', 0):,}\n\n"
                
                # Получаем статистику из истории
                channel_posts = {k: v for k, v in history.items() 
                               if k.startswith(f"{chat_id}_") and 
                               (datetime.now() - datetime.fromisoformat(v['date'])).total_seconds() <= 48*3600}
                
                total_posts = len(channel_posts)
                failed_content = len([k for k, v in channel_posts.items() 
                                    if v.get("has_errors", False)])
                failed_metrics = len([k for k, v in channel_posts.items() 
                                    if v.get("metrics_failed", False)])
                
                stats_text += "🔍 Проверки контента:\n"
                stats_text += f"• Всего постов: {total_posts}\n"
                stats_text += f"• Не прошли проверку: {failed_content}\n"
                content_success_rate = ((total_posts - failed_content) / total_posts * 100 
                                      if total_posts > 0 else 0)
                stats_text += f"• Процент успеха: {content_success_rate:.1f}%\n\n"
                
                stats_text += "📊 Проверки метрик:\n"
                stats_text += f"• Всего проверок: {total_posts}\n"
                stats_text += f"• Не прошли проверку: {failed_metrics}\n"
                metrics_success_rate = ((total_posts - failed_metrics) / total_posts * 100 
                                      if total_posts > 0 else 0)
                stats_text += f"• Процент успеха: {metrics_success_rate:.1f}%\n\n"
                
                stats_text += "➖➖➖➖➖➖➖➖➖➖\n\n"
                
            except Exception as e:
                logger.error(f"Ошибка при получении статистики канала {chat_id}: {e}")
                continue
        
        await message.reply(stats_text)
        
    except Exception as e:
        logger.error(f"Ошибка при выводе расширенной статистики: {e}")
        await message.reply("Ошибка при получении расширенной статистики")


# Запуск бота
async def update_subscribers_count():
    while True:
        try:
            for channel_id, data in channels.items():
                try:
                    if "chat_id" in data:
                        count = await bot.get_chat_member_count(data["chat_id"])
                        channels[channel_id]["subscribers"] = count
                        logger.info(f"Обновлено количество подписчиков для {channel_id}: {count}")
                except Exception as e:
                    logger.error(f"Ошибка при обновлении подписчиков канала {channel_id}: {e}")
            save_channels()
        except Exception as e:
            logger.error(f"Ошибка при обновлении подписчиков: {e}")
        await asyncio.sleep(CONFIG["UPDATE_INTERVALS"]["SUBSCRIBERS"])  # Используйте значение из конфигурации

# Добавим функцию для периодической проверки
async def check_pending_metrics_periodically():
    """Периодически проверяет отложенные метрики"""
    while True:
        try:
            results = await check_pending_metrics()
            
            # Если есть результаты, отправляем их админам
            if results and ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    try:
                        # Отправляем общую статистику
                        summary = (
                            f"📊 Результаты автоматической проверки метрик:\n\n"
                            f"Проверено постов с недостаточными метриками: {len(results)}\n\n"
                        )
                        await bot.send_message(admin_id, summary)
                        
                        # Отправляем детальные результаты
                        for result in results:
                            await bot.send_message(admin_id, result['message'])
                            
                    except Exception as e:
                        logger.error(f"Ошибка отправки результатов админу {admin_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Ошибка при периодической проверке метрик: {e}")
            
        # Ждем 5 минут перед следующей проверкой
        await asyncio.sleep(300)

# Обновим функцию main
async def main():
    await client.start()  # Вход в систему
    logger.info("Клиент Telethon подключен.")
    print("Бот запущен...")
    
    # Запускаем фоновые задачи
    asyncio.create_task(update_subscribers_count())
    asyncio.create_task(check_pending_metrics_periodically())
    
    # Запускаем бота
    await dp.start_polling(bot)


@dp.message(Command("cancel"))
async def cancel_command(message: types.Message):
    global waiting_for_channel
    if waiting_for_channel:
        waiting_for_channel = False
        await message.reply("Добавление канала отменено.")
    else:
        await message.reply("Нет активных операций для отмены.")


# Обработчик для новых постов в каналах
@dp.channel_post()
async def handle_channel_post(message: types.Message):
    """Обработчик новых постов в каналах"""
    try:
        chat_id = str(message.chat.id)
        if chat_id not in channels:
            return

        # Получаем информацию о канале
        channel_info = await bot.get_chat(chat_id)
        subscribers = channels[chat_id].get('subscribers', 0)
        
        # Проверяем длину текста
        if message.text and len(message.text) > 500:
            logger.warning(f"Пост в канале {chat_id} превышает 500 символов!\n"
                         f"Длина текста: {len(message.text)} символов")
            
        # Проверяем контент на ошибки
        has_errors = False
        if message.text:
            spelling_result = await check_spelling(message.text, CONFIG["OPENAI_API_KEY"])
            has_errors = spelling_result.get("has_errors", False)
            
            if has_errors:
                logger.info(f"Результат проверки контента: {spelling_result}")
                logger.info("Этап 1: Найдены проблемы в контенте")
                
                # Отправляем уведомление админам
                admin_ids = CONFIG.get("ADMIN_IDS", [])
                if admin_ids:
                    logger.info(f"Отправка уведомлений админам: {admin_ids}")
                    
                    message_text = (
                        f"📢 Проблемы с контентом\n\n"
                        f"Канал: {chat_id}\n"
                        f"Пост: {message.message_id}\n\n"
                        f"Подробности: {spelling_result['errors']}"
                    )
                    
                    for admin_id in admin_ids:
                        try:
                            await bot.send_message(admin_id, message_text)
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
                else:
                    logger.warning("Список админов пуст, уведомления не отправлены")
                    
        # Сохраняем пост для последующей проверки метрик
        post_data = {
            'message_id': message.message_id,
            'chat_id': chat_id,
            'text': message.text if message.text else '',
            'date': datetime.now().isoformat(),
            'url': f"https://t.me/c/{str(chat_id)[4:]}/{message.message_id}",
            'subscribers': subscribers,
            'has_errors': has_errors
        }
        
        history[f"{chat_id}_{message.message_id}"] = post_data
        save_history()
        
        # Планируем проверку метрик через 24 часа
        asyncio.create_task(
            check_post_metrics_later(
                chat_id=chat_id,
                message_id=message.message_id,
                delay_seconds=CONFIG["POST_SETTINGS"]["METRICS_CHECK_DELAY"]
            )
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке поста: {e}", exc_info=True)


@dp.message(lambda message: waiting_for_channel)
async def process_channel_addition(message: types.Message):
    """Обрабатывает добавление канала"""
    try:
        global waiting_for_channel
        
        # Разбираем входные данные
        parts = message.text.split()
        if len(parts) < 1:
            await message.reply("Неверный формат. Используйте: @username +05:00 или -100123456789 -02:30")
            return

        channel_id = parts[0]
        timezone = 0  # Значение по умолчанию

        # Если указан часовой пояс
        if len(parts) > 1:
            try:
                # Парсим часовой пояс
                tz_str = parts[1]
                sign = 1 if tz_str[0] == '+' else -1
                if ':' in tz_str:
                    hours, minutes = map(int, tz_str[1:].split(':'))
                    timezone = sign * (hours + (minutes / 60))
                else:
                    timezone = float(tz_str)
                logger.info(f"Установлен часовой пояс {timezone:+.2f} для канала {channel_id}")
            except ValueError:
                await message.reply("Неверный формат часового пояса. Используйте: +05:00 или -02:30")
                return

        # Проверяем формат канала
        if not (channel_id.startswith('@') or channel_id.startswith('-100')):
            await message.reply("Неверный формат. ID канала должен начинаться с '@' или '-100'")
            return

        if channel_id in channels:
            await message.reply("Этот канал уже отслеживается.")
            return

        # Получаем информацию о канале
        try:
            chat = await bot.get_chat(channel_id)
            chat_info = await bot.get_chat_member_count(channel_id)
            
            # Проверяем права бота в канале
            bot_member = await bot.get_chat_member(chat.id, bot.id)
            if not bot_member.can_read_messages:
                await message.reply(
                    "❌ У бота нет прав для чтения сообщений в этом канале.\n"
                    "Пожалуйста, добавьте бота в администраторы канала с правами:\n"
                    "- Чтение сообщений\n"
                    "- Просмотр статистики"
                )
                return
                
        except Exception as e:
            await message.reply(
                "❌ Не удалось получить информацию о канале.\n"
                "Возможные причины:\n"
                "1. Канал не существует\n"
                "2. Бот не добавлен в канал\n"
                "3. У бота нет необходимых прав\n\n"
                "Убедитесь, что:\n"
                "- Канал существует\n"
                "- Бот добавлен в канал как администратор\n"
                "- У бота есть права на чтение сообщений и просмотр статистики"
            )
            return
        
        # Конвертируем в int для форматирования
        subscribers = int(chat_info)
        
        # Добавляем информацию о канале
        channels[channel_id] = {
            "timezone": timezone,
            "is_news": True,  # По умолчанию считаем канал новостным
            "subscribers": subscribers,
            "title": chat.title,
            "posts": [],
            "chat_id": chat.id,
            "admins": [message.from_user.id]  # Добавляем ID администратора
        }
        save_channels()
        
        # Формируем сообщение с информацией о канале
        channel_info = (
            f"✅ Канал успешно добавлен!\n\n"
            f"📌 Канал: {channel_id}\n"
            f"📑 Название: {chat.title}\n"
            f"👥 Подписчиков: {subscribers:,}\n"
            f"🕒 Часовой пояс: {timezone:+.2f}"
        )
        
        await message.reply(channel_info)
        logger.info(f"Канал {channel_id} добавлен с часовым поясом {timezone}, подписчиков: {subscribers}")
        
        # Сбрасываем состояние ожидания
        waiting_for_channel = False

    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply(
            "❌ Произошла ошибка при добавлении канала.\n"
            "Пожалуйста, проверьте:\n"
            "1. Правильность введенного ID/username канала\n"
            "2. Наличие бота в канале\n"
            "3. Права бота в канале"
        )
    finally:
        # Сбрасываем состояние ожидания даже в случае ошибки
        waiting_for_channel = False


async def get_post_metrics(chat_id: str, message_id: int) -> dict:
    """Получает метрики поста (просмотры и реакции) используя Telethon"""
    try:
        logger.info(f"Начинаем получение метрик для поста {message_id} в канале {chat_id}")
        
        # Проверяем подключение к Telethon
        if not client.is_connected():
            logger.info("Telethon не подключен, выполняем подключение...")
            await client.connect()
            
        if not await client.is_user_authorized():
            logger.info("Пользователь не авторизован, выполняем авторизацию...")
            await client.start()
            
        logger.info("Telethon подключен и авторизован")

        # Пробуем получить сущность канала
        try:
            channel_entity = await client.get_entity(int(chat_id))
            logger.info(f"Получена сущность канала: {channel_entity.title} (id: {channel_entity.id})")
        except ValueError as e:
            logger.error(f"Ошибка при получении сущности канала: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении канала: {e}")
            return None

        # Получаем сообщение
        try:
            message = await client.get_messages(channel_entity, ids=message_id)
            if not message:
                logger.error(f"Сообщение {message_id} не найдено")
                return None
            logger.info(f"Получено сообщение {message_id}")
        except Exception as e:
            logger.error(f"Ошибка при получении сообщения: {e}")
            return None

        # Инициализируем метрики с безопасными значениями по умолчанию
        metrics = {
            'views': getattr(message, 'views', 0) or 0,
            'reactions': 0,
            'forwards': getattr(message, 'forwards', 0) or 0,
            'replies': getattr(message, 'replies', 0) if hasattr(message, 'replies') else 0,
            'post_author': getattr(message, 'post_author', None),
            'date': message.date.isoformat() if hasattr(message, 'date') else None,
        }

        # Безопасное получение реакций
        try:
            if hasattr(message, 'reactions') and message.reactions:
                reactions_data = []
                total_reactions = 0
                if hasattr(message.reactions, 'results'):
                    for reaction in message.reactions.results:
                        try:
                            reaction_count = getattr(reaction, 'count', 0) or 0
                            total_reactions += reaction_count
                            reactions_data.append({
                                'emoji': str(getattr(reaction, 'reaction', '?')),
                                'count': reaction_count
                            })
                        except Exception as e:
                            logger.error(f"Ошибка при обработке реакции: {e}")
                            continue
                    
                metrics['reactions'] = total_reactions
                metrics['reactions_details'] = reactions_data
        except Exception as e:
            logger.error(f"Ошибка при получении реакций: {e}")
            # Оставляем значения по умолчанию
            
        logger.info(f"Собраны метрики для поста {message_id}:")
        logger.info(f"- Просмотры: {metrics['views']}")
        logger.info(f"- Реакции: {metrics['reactions']}")
        logger.info(f"- Пересылки: {metrics['forwards']}")
        logger.info(f"- Ответы: {metrics['replies']}")
        if metrics.get('reactions_details'):
            logger.info("- Детали реакций:")
            for reaction in metrics['reactions_details']:
                logger.info(f"  • {reaction['emoji']}: {reaction['count']}")

        return metrics

    except Exception as e:
        logger.error(f"Ошибка при получении метрик поста {message_id} из канала {chat_id}: {e}", exc_info=True)
        return None

async def check_post_metrics_later(
    chat_id: str,
    message_id: int,
    delay_seconds: int
):
    """Добавляет пост в очередь на проверку метрик"""
    try:
        # Проверяем существование канала
        if chat_id not in channels:
            logger.error(f"Канал {chat_id} не найден в конфигурации")
            return

        check_time = datetime.now() + timedelta(seconds=delay_seconds)
        
        # Инициализируем структуру для канала, если её нет
        if chat_id not in pending_checks:
            pending_checks[chat_id] = {}
        
        # Проверяем, не существует ли уже проверка для этого поста
        if message_id in pending_checks[chat_id]:
            logger.warning(f"Проверка для поста {message_id} в канале {chat_id} уже запланирована")
            return
        
        # Сохраняем информацию о посте
        pending_checks[chat_id][message_id] = {
            'check_time': check_time,
            'added_time': datetime.now(),
            'retries': 0  # Добавляем счетчик попыток
        }
        
        logger.info(f"Пост {message_id} из канала {chat_id} добавлен в очередь на проверку метрик")
        logger.info(f"Запланированное время проверки: {check_time}")
        
    except Exception as e:
        logger.error(f"Ошибка при планировании проверки метрик для поста {message_id} в канале {chat_id}: {e}")

# Добавим функцию для проверки отложенных метрик
async def check_pending_metrics(force: bool = False) -> List[Dict[str, Any]]:
    """Проверяет все отложенные метрики"""
    results = []
    current_time = datetime.now()
    
    try:
        for chat_id in list(pending_checks.keys()):
            if chat_id not in channels:
                logger.error(f"Канал {chat_id} не найден в конфигурации, пропускаем проверки")
                continue
                
            for message_id in list(pending_checks[chat_id].keys()):
                try:
                    check_data = pending_checks[chat_id][message_id]
                    
                    # Проверяем количество попыток
                    if check_data.get('retries', 0) >= 3:
                        logger.warning(f"Превышено количество попыток для поста {message_id} в канале {chat_id}")
                        del pending_checks[chat_id][message_id]
                        continue
                    
                    # Проверяем, пришло ли время для проверки или это принудительная проверка
                    if not force and current_time < check_data['check_time']:
                        continue
                        
                    # Получаем информацию о канале
                    try:
                        channel_info = await bot.get_chat(chat_id)
                        subscribers = channels[chat_id].get('subscribers', 0)
                    except Exception as e:
                        logger.error(f"Ошибка при получении информации о канале {chat_id}: {e}")
                        check_data['retries'] = check_data.get('retries', 0) + 1
                        continue
                    
                    # Получаем актуальные метрики
                    metrics = await get_post_metrics(chat_id, message_id)
                    if not metrics:
                        logger.error(f"Не удалось получить метрики для поста {message_id} из канала {chat_id}")
                        check_data['retries'] = check_data.get('retries', 0) + 1
                        continue
                    
                    # Получаем данные поста из истории
                    post_key = f"{chat_id}_{message_id}"
                    if post_key not in history:
                        logger.error(f"Пост {post_key} не найден в истории")
                        del pending_checks[chat_id][message_id]
                        continue
                    
                    post_data = history[post_key]
                    
                    try:
                        # Запускаем проверку метрик
                        metrics_result = await check_post_metrics(
                            views=metrics['views'],
                            reactions=metrics['reactions'],
                            forwards=metrics['forwards'],
                            subscribers=subscribers,
                            channel_name=channel_info.title,
                            message_id=message_id,
                            message_text=post_data.get('text', ''),
                            message_url=post_data.get('url', ''),
                            settings=channels[chat_id]
                        )
                        
                        # Обновляем историю
                        post_data.update({
                            'metrics': metrics,
                            'metrics_check_time': current_time.isoformat(),
                            'metrics_passed': metrics_result["passed"],
                            'metrics_details': metrics_result["details"],
                            'metrics_failed': not metrics_result["passed"]
                        })
                        history[post_key] = post_data
                        save_history()
                        
                        if not metrics_result["passed"]:
                            metrics_details = metrics_result["details"]["metrics"]
                            result_message = (
                                f"⚠️ Недостаточная активность в посте!\n\n"
                                f"Канал: {channel_info.title}\n"
                                f"🔗 {post_data['url']}\n\n"
                                f"📊 Текущие метрики:\n"
                                f"👁 Просмотры: {metrics_details['views']['current']}/{metrics_details['views']['required']} "
                                f"({metrics_details['views']['percent']:.1f}%) "
                                f"{'✅' if metrics_details['views']['passed'] else '❌'}\n"
                                
                                f"👍 Реакции: {metrics_details['reactions']['current']}/{metrics_details['reactions']['required']} "
                                f"({metrics_details['reactions']['percent']:.1f}%) "
                                f"{'✅' if metrics_details['reactions']['passed'] else '❌'}\n"
                                
                                f"↗️ Пересылки: {metrics_details['forwards']['current']}/{metrics_details['forwards']['required']} "
                                f"({metrics_details['forwards']['percent']:.1f}%) "
                                f"{'✅' if metrics_details['forwards']['passed'] else '❌'}\n"
                            )
                            
                            if metrics_result["details"]["issues"]:
                                result_message += "\n❗️ Проблемы:\n"
                                for issue in metrics_result["details"]["issues"]:
                                    result_message += f"• {issue}\n"
                                    
                            results.append({
                                'channel_name': channel_info.title,
                                'message': result_message
                            })
                        
                        # Удаляем проверенный пост из очереди
                        del pending_checks[chat_id][message_id]
                        
                    except Exception as e:
                        logger.error(f"Ошибка при проверке метрик поста {message_id}: {e}")
                        check_data['retries'] = check_data.get('retries', 0) + 1
                        continue
                        
                except Exception as e:
                    logger.error(f"Ошибка при обработке поста {message_id}: {e}")
                    continue
                    
            # Очищаем пустые каналы
            if not pending_checks[chat_id]:
                del pending_checks[chat_id]
                
    except Exception as e:
        logger.error(f"Ошибка при проверке отложенных метрик: {e}")
        
    return results

# Добавим команду и обработчик для проверки отложенных метрик
@dp.message(Command("check_pending"))
@dp.message(Text(text="📬 Проверить отложенные"))
async def check_pending_command(message: types.Message):
    """Проверяет все отложенные метрики"""
    try:
        # Получаем количество отложенных проверок
        total_pending = sum(len(posts) for posts in pending_checks.values())
        
        if total_pending == 0:
            await message.reply("📭 Нет отложенных проверок метрик.")
            return
            
        # Отправляем начальное сообщение
        status_message = await message.reply(
            f"🔄 Начинаю проверку {total_pending} отложенных постов...\n"
            "Это может занять некоторое время."
        )
        
        # Запускаем проверку
        results = await check_pending_metrics(force=True)
        
        if not results:
            await status_message.edit_text(
                f"✅ Проверка завершена!\n"
                f"Все {total_pending} постов соответствуют требованиям."
            )
            return
            
        # Отправляем результаты проверки
        summary = f"📊 Результаты проверки:\n\n"
        summary += f"Всего проверено: {total_pending}\n"
        summary += f"Не соответствуют требованиям: {len(results)}\n\n"
        
        await status_message.edit_text(summary)
        
        # Отправляем детальные результаты для каждого поста
        for result in results:
            await message.reply(result['message'])
            
    except Exception as e:
        logger.error(f"Ошибка при проверке отложенных метрик: {e}")
        await message.reply("❌ Произошла ошибка при проверке отложенных метрик.")

async def notify_admins(channel_data, message, error_type=None, error_details=None, parse_mode=None):
    """Отправляет уведомление админам канала"""
    try:
        admin_ids = channel_data.get('admins', [])
        logger.info(f"Отправка уведомлений админам: {admin_ids}")
        
        if not admin_ids:
            logger.warning("Нет администраторов для уведомления")
            return

        # Формируем сообщение в зависимости от типа уведомления
        if isinstance(message, str):
            # Если передана строка (для уведомлений о метриках)
            message_text = message
        else:
            # Если передан объект сообщения (для других уведомлений)
            message_text = (
                f"📢 {error_type}\n\n"
                f"Канал: {channel_data.get('title', 'Неизвестно')}\n"
                f"Пост: {message.message_id}\n"
            )
            
            if error_details:
                message_text += f"\nПодробности: {error_details}\n"
                
            # Добавляем ссылку на пост
            post_link = f"https://t.me/c/{str(message.chat.id)[4:]}/{message.message_id}"
            message_text += f"\nСсылка на пост: {post_link}"
        
        logger.info(f"Подготовлено сообщение для админов: {message_text}")

        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, message_text, parse_mode=parse_mode)
                logger.info(f"Уведомление отправлено админу {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")

async def update_channel_info(chat_id: str):
    """Обновляет информацию о канале"""
    try:
        # Получаем информацию о канале
        chat = await bot.get_chat(chat_id)
        subscribers_count = await bot.get_chat_member_count(chat_id)
        
        # Конвертируем GetChatMemberCount в int
        subscribers_count = int(subscribers_count)
        
        logger.info(f"Получена информация о канале: {chat.title}, подписчиков: {subscribers_count}")
        
        # Обновляем или создаем запись в channels
        if chat_id not in channels:
            channels[chat_id] = {
                "title": chat.title,
                "subscribers": subscribers_count,  # Теперь это int
                "required_views": 0,
                "required_reactions": 0,
                "timezone": 0,
                "is_news": False,
                "admins": [],
                "posts": [],
                "chat_id": chat.id
            }
        else:
            channels[chat_id].update({
                "title": chat.title,
                "subscribers": subscribers_count,  # Теперь это int
                "chat_id": chat.id
            })
            
        save_channels()
        logger.info(f"Информация о канале {chat_id} успешно обновлена")
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении информации о канале {chat_id}: {e}")


# В начале файла после инициализации бота
def get_bot():
    return bot

set_bot_getter(get_bot)

# Добавляем обработчик для KPI статистики
@dp.message(Command("kpi"))
@dp.message(Text(text="📊 Статистика KPI"))
async def kpi_stats_command(message: types.Message):
    """Показывает KPI статистику по каналам"""
    try:
        stats_text = "📊 KPI Статистика каналов:\n\n"
        
        for chat_id, data in channels.items():
            try:
                channel_info = await bot.get_chat(chat_id)
                
                # Получаем статистику из истории
                channel_posts = {k: v for k, v in history.items() if k.startswith(f"{chat_id}_")}
                total_posts = len(channel_posts)
                failed_posts = len([k for k, v in channel_posts.items() 
                                  if v.get("has_errors", False)])
                
                # Вычисляем процент успешных постов
                success_rate = ((total_posts - failed_posts) / total_posts * 100 
                              if total_posts > 0 else 0)
                
                stats_text += (
                    f"📌 {channel_info.title}\n"
                    f"Всего постов: {total_posts}\n"
                    f"Успешных: {total_posts - failed_posts}\n"
                    f"Процент успеха: {success_rate:.1f}%\n\n"
                )
                
            except Exception as e:
                logger.error(f"Ошибка при получении статистики канала {chat_id}: {e}")
                stats_text += f"❌ Ошибка получения статистики для канала {chat_id}\n\n"
        
        await message.reply(stats_text)
        
    except Exception as e:
        error_message = f"Ошибка при формировании статистики: {e}"
        logger.error(error_message)
        await message.reply(error_message)

# Добавляем обработчик для настройки метрик
@dp.callback_query(lambda c: c.data and c.data.startswith("metrics_settings:"))
async def metrics_settings(callback_query: types.CallbackQuery):
    try:
        channel_id = callback_query.data.split(":")[1]
        channel_data = channels[channel_id]
        metrics = channel_data.get('metrics', {
            'views_percent': CONFIG['POST_SETTINGS']['MIN_VIEWS_PERCENT'],
            'reactions_percent': CONFIG['POST_SETTINGS']['MIN_REACTIONS_PERCENT'],
            'forwards_percent': CONFIG['POST_SETTINGS']['MIN_FORWARDS_PERCENT']
        })

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"👁 Просмотры: {metrics['views_percent']}%",
                callback_data=f"set_metric:views:{channel_id}"
            )],
            [InlineKeyboardButton(
                text=f"👍 Реакции: {metrics['reactions_percent']}%",
                callback_data=f"set_metric:reactions:{channel_id}"
            )],
            [InlineKeyboardButton(
                text=f"↗️ Пересылки: {metrics['forwards_percent']}%",
                callback_data=f"set_metric:forwards:{channel_id}"
            )],
            [InlineKeyboardButton(
                text="🔄 Сбросить к значениям по умолчанию",
                callback_data=f"reset_metrics:{channel_id}"
            )],
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"manage_channel:{channel_id}"
            )]
        ])

        await callback_query.message.edit_text(
            f"📊 Настройка метрик для канала {channel_id}\n\n"
            f"Текущие значения:\n"
            f"👁 Просмотры: {metrics['views_percent']}% от подписчиков\n"
            f"👍 Реакции: {metrics['reactions_percent']}% от просмотров\n"
            f"↗️ Пересылки: {metrics['forwards_percent']}% от просмотров\n\n"
            "Нажмите на метрику для изменения",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при настройке метрик: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при настройке метрик", show_alert=True)

# Обработчик для установки конкретной метрики
@dp.callback_query(lambda c: c.data and c.data.startswith("set_metric:"))
async def set_metric_value(callback_query: types.CallbackQuery):
    try:
        _, metric_type, channel_id = callback_query.data.split(":")
        
        # Создаем кнопки с процентами
        percents = [5, 10, 15, 20, 25, 30, 40, 50]
        buttons = []
        row = []
        
        for percent in percents:
            row.append(InlineKeyboardButton(
                text=f"{percent}%",
                callback_data=f"apply_metric:{metric_type}:{channel_id}:{percent}"
            ))
            if len(row) == 4:  # По 4 кнопки в ряду
                buttons.append(row)
                row = []
        
        if row:  # Добавляем оставшиеся кнопки
            buttons.append(row)
            
        # Добавляем кнопку "Назад"
        buttons.append([InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"metrics_settings:{channel_id}"
        )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        metric_names = {
            'views': 'просмотров',
            'reactions': 'реакций',
            'forwards': 'пересылок'
        }
        
        await callback_query.message.edit_text(
            f"Выберите процент для {metric_names[metric_type]}:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при установке значения метрики: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка", show_alert=True)

# Обработчик для применения выбранного значения метрики
@dp.callback_query(lambda c: c.data and c.data.startswith("apply_metric:"))
async def apply_metric_value(callback_query: types.CallbackQuery):
    try:
        _, metric_type, channel_id, percent = callback_query.data.split(":")
        percent = float(percent)
        
        # Инициализируем метрики, если их нет
        if 'metrics' not in channels[channel_id]:
            channels[channel_id]['metrics'] = {
                'views_percent': CONFIG['POST_SETTINGS']['MIN_VIEWS_PERCENT'],
                'reactions_percent': CONFIG['POST_SETTINGS']['MIN_REACTIONS_PERCENT'],
                'forwards_percent': CONFIG['POST_SETTINGS']['MIN_FORWARDS_PERCENT']
            }
        
        # Обновляем значение метрики
        metric_mapping = {
            'views': 'views_percent',
            'reactions': 'reactions_percent',
            'forwards': 'forwards_percent'
        }
        
        channels[channel_id]['metrics'][metric_mapping[metric_type]] = percent
        save_channels()
        
        await callback_query.answer(f"Значение установлено: {percent}%")
        # Возвращаемся к настройкам метрик
        await metrics_settings(callback_query)
        
    except Exception as e:
        logger.error(f"Ошибка при применении значения метрики: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка", show_alert=True)

# Обработчик для сброса метрик к значениям по умолчанию
@dp.callback_query(lambda c: c.data and c.data.startswith("reset_metrics:"))
async def reset_metrics(callback_query: types.CallbackQuery):
    try:
        channel_id = callback_query.data.split(":")[1]
        
        # Сбрасываем к значениям по умолчанию
        channels[channel_id]['metrics'] = {
            'views_percent': CONFIG['POST_SETTINGS']['MIN_VIEWS_PERCENT'],
            'reactions_percent': CONFIG['POST_SETTINGS']['MIN_REACTIONS_PERCENT'],
            'forwards_percent': CONFIG['POST_SETTINGS']['MIN_FORWARDS_PERCENT']
        }
        save_channels()
        
        await callback_query.answer("Метрики сброшены к значениям по умолчанию")
        # Возвращаемся к настройкам метрик
        await metrics_settings(callback_query)
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе метрик: {e}", exc_info=True)
        await callback_query.answer("Произошла ошибка при сбросе метрик", show_alert=True)

if __name__ == "__main__":
    asyncio.run(main())
