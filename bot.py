import json
import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from utils.database import load_json, save_json
from utils.logging import setup_logger
from utils.checks import (
    check_text_length, 
    check_spelling, 
    check_post_metrics, 
    check_news_actuality,
    check_content_moderation
)
from openai import OpenAI
from telethon import TelegramClient
from datetime import datetime, timedelta
import aiohttp
from utils.api import set_bot_getter
import time

# Настройка логирования
logger = setup_logger()

# Загрузка конфигурации
with open("config.json") as config_file:
    CONFIG = json.load(config_file)

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

# Загрузка данных о каналах
channels = load_json("channels.json")

# Глобальная переменная для отслеживания состояния
waiting_for_channel = False

# Добавляем в начало файла инициализацию клиента Telethon
client = TelegramClient('bot_session', CONFIG["API_ID"], CONFIG["API_HASH"])

# Функция для сохранения данных
def save_channels():
    save_json("channels.json", channels)


# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    try:
        await message.reply(
            "Привет! Я бот для отслеживания каналов.\n"
            "Используй /help, чтобы узнать, что я умею."
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await message.reply("Произошла ошибка при обработке вашего запроса.")


# Команда /help
@dp.message(Command("help"))
async def help_command(message: types.Message):
    try:
        await message.reply(
            "📋 Список команд:\n\n"
            "- `/start` - начать работу с ботом\n"
            "- `/help` - получить помощь\n"
            "- `/add_channel` - добавить канал для отслеживания\n"
            "   Примеры:\n"
            "   `/add_channel @channel +05:00`\n"
            "   `/add_channel -100123456789 -02:30`\n"
            "- `/cancel` - отменить текущую операцию\n"
            "- `/channels` - управление каналами\n"
            "- `/stats` - статистика по каналам\n\n"
            "**Связь с разработчиком:**\n"
            "Telegram: [t.me/ctrltg](t.me/ctrltg)\n"
            "Сайт: [whomever.tech](https://whomever.tech)",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}", exc_info=True)
        await message.reply("Произошла ошибка при обработке вашего запроса.")


# Добавление канала
@dp.message(Command("add_channel"))
async def add_channel_command(message: types.Message):
    try:
        # Проверяем, есть ли параметры в команде
        args = message.text.split(maxsplit=1)
        if len(args) > 1:
            # Если есть параметры, пробуем добавить канал сразу
            await process_channel_with_timezone(message, args[1])
        else:
            # Если нет параметров, запускаем стандартный процесс
            global waiting_for_channel
            waiting_for_channel = True
            await message.reply(
                "Отправьте ID или username канала, который нужно добавить.\n"
                "Формат: @username +05:00 или -100123456789 -02:30"
            )
    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply("Произошла ошибка при добавлении канала.")

async def process_channel_with_timezone(message: types.Message, channel_id: str, timezone: float):
    """Обрабатывает добавление канала с часовым поясом"""
    try:
        # Получаем информацию о канале
        chat = await bot.get_chat(channel_id)
        chat_info = await bot.get_chat_member_count(channel_id)
        
        # Конвертируем в int для форматирования
        subscribers = int(chat_info)
        
        # Формируем сообщение с информацией о канале
        channel_info = (
            f"ℹ️ Информация о канале:\n"
            f"📌 Название: {chat.title}\n"
            f"👥 Подписчиков: {subscribers:,}\n"
            f"🕒 Часовой пояс: {timezone:+.2f}"
        )
        
        await message.reply(channel_info)

    except Exception as e:
        logger.error(f"Ошибка при получении информации о канале {channel_id}: {e}")
        await message.reply("Не удалось получить информацию о канале. Убедитесь, что:\n"
                          "1. Бот добавлен в канал как администратор\n"
                          "2. У бота есть права на просмотр статистики канала\n"
                          "3. Канал существует и доступен")


# Перемещаем обработчик команды /channels перед общим обработчиком
@dp.message(Command("channels"))
async def list_channels(message: types.Message):
    try:
        if not channels:
            await message.reply("Список отслеживаемых каналов пуст.")
            return

        text = "Список отслеживаемых каналов:\n\n"
        # Создаем список кнопок правильным способом для aiogram 3.x
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

        # Создаем клавиатуру правильным способом
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить канал", callback_data=f"delete:{channel_id}")],
            [InlineKeyboardButton(text="🕒 Изменить часовой пояс", callback_data=f"timezone:{channel_id}")],
            [InlineKeyboardButton(
                text=f"📰 Новостной канал: {'✅' if channel_data['is_news'] else '❌'}",
            callback_data=f"toggle_news:{channel_id}"
            )]
        ])

        await callback_query.message.edit_text(
            f"📌 Управление каналом: {channel_id}\n"
            f"📑 Название: {channel_data.get('title', 'Неизвестно')}\n"
            f"🕒 Часовой пояс: {channel_data['timezone']:+.2f}\n"
            f"📰 Новостной канал: {'Да' if channel_data['is_news'] else 'Нет'}\n"
            f"👥 Подписчиков: {channel_data['subscribers']:,}",
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


# Статистика по каналам
@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    """Показывает статистику каналов"""
    try:
        stats_text = "📊 Статистика каналов:\n\n"
        for chat_id, data in channels.items():
            channel_info = await bot.get_chat(chat_id)
            stats_text += (
                f"📌 {channel_info.title}\n"
                f"👥 Подписчиков: {data.get('subscribers', 0):,}\n"
                f"🕒 Часовой пояс: {data.get('timezone', 0):+.2f}\n"
                f"📰 Новостной: {'✅' if data.get('is_news', False) else '❌'}\n\n"
            )
        await message.reply(stats_text)
    except Exception as e:
        logger.error(f"Ошибка при выводе статистики: {e}")
        await message.reply("Ошибка при получении статистики")


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

# Обновляем функцию main
async def main():
    await client.start()  # Вход в систему
    logger.info("Клиент Telethon подключен.")
    print("Бот запущен...")
    # Запускаем задачу обновления подписчиков
    asyncio.create_task(update_subscribers_count())
    # Запускаем бота и диспетчер
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
    """Обрабатывает новые посты в каналах"""
    try:
        chat_id = str(message.chat.id)
        logger.info(f"Получен новый пост из канала {message.chat.title or chat_id}")
        
        # Ищем канал по chat_id
        channel_data = None
        for channel_id, data in channels.items():
            if str(data.get('chat_id')) == chat_id:
                channel_data = data
                break
                
        if not channel_data:
            logger.error(f"Канал {chat_id} не найден в базе")
            return
            
        # Проверяем текст через OpenAI
        if message.text:
            logger.info("Этап 1: Проверка контента")
            content_check = await check_content_moderation(message.text)
            logger.info(f"Результат проверки контента: {content_check}")
            
            if content_check.get("has_errors", False):
                logger.info(f"Этап 1: Найдены проблемы в контенте")
                
                # Формируем подробное описание проблем
                error_details = "Найдены следующие проблемы:\n\n"
                
                if content_check.get("categories", {}).get("spelling"):
                    error_details += "📝 Орфографические ошибки:\n"
                    error_details += content_check.get("details", {}).get("spelling_details", "Не указано") + "\n\n"
                    
                if content_check.get("categories", {}).get("grammar"):
                    error_details += "📚 Грамматические ошибки:\n"
                    error_details += content_check.get("details", {}).get("grammar_details", "Не указано") + "\n\n"
                    
                if content_check.get("categories", {}).get("spam"):
                    error_details += "🔄 Повторы в тексте:\n"
                    error_details += content_check.get("details", {}).get("spam_details", "Не указано") + "\n\n"
                
                readability = content_check.get("categories", {}).get("readability", {})
                error_details += f"📊 Читабельность текста:\n"
                error_details += f"Оценка: {readability.get('score', 0)}/10\n"
                error_details += f"Уровень: {readability.get('level', 'не определен')}\n"
                error_details += content_check.get("details", {}).get("readability_details", "Не указано")
                
                await notify_admins(
                    channel_data,
                    message,
                    error_type="Проблемы с контентом",
                    error_details=error_details
                )
                return
            logger.info("Этап 1: Проверка контента успешна")
            
            # Проверяем актуальность новости
            if channel_data.get("is_news", False):
                logger.info("Этап 2: Проверка актуальности новости")
                
                # Получаем дату поста с учетом часового пояса канала
                timezone_offset = channel_data.get('timezone', 0)
                post_date = message.date + timedelta(hours=timezone_offset)
                
                actuality_check = await check_news_actuality(message.text, post_date)
                if not actuality_check.get("is_actual", False):
                    logger.info("Этап 2: Новость неактуальна")
                    
                    # Формируем подробное описание проблемы
                    error_details = (
                        f"📅 Время публикации: {post_date.strftime('%H:%M')} (UTC{timezone_offset:+.2f})\n"
                        f"🕒 Локальное время: {datetime.now().strftime('%H:%M')}\n"
                        f"📌 Категория: {actuality_check.get('news_type', 'не определена')}\n"
                        f"❗️ Важность: {actuality_check.get('importance_level', 'не определена')}\n\n"
                        f"❌ Причина: {actuality_check.get('reason', 'Не указана')}\n\n"
                        f"📊 Анализ источников:\n"
                        f"• Всего источников: {actuality_check.get('source_reliability', {}).get('total_sources', 0)}\n"
                        f"• Надежных источников: {actuality_check.get('source_reliability', {}).get('reliable_sources', 0)}\n"
                        f"• Средняя надежность: {actuality_check.get('source_reliability', {}).get('average_score', 0):.1f}/10\n\n"
                        f"⏰ Временная релевантность:\n"
                        f"• Свежесть: {'✅ Свежая' if actuality_check.get('time_relevance', {}).get('is_recent', False) else '❌ Устаревшая'}\n"
                        f"• Возраст: {actuality_check.get('time_relevance', {}).get('hours_ago', 0)} часов\n"
                        f"• Найдено упоминаний: {actuality_check.get('time_relevance', {}).get('matches_found', 0)}\n\n"
                        f"🔍 Проверка информации:\n"
                        f"• Статус: {'✅ Подтверждено' if actuality_check.get('verification', {}).get('is_verified', False) else '❌ Не подтверждено'}\n"
                        f"• Уровень проверки: {actuality_check.get('verification', {}).get('verification_level', 'не определен')}\n\n"
                        f"📰 Подтверждающие источники:\n"
                    )
                    
                    # Добавляем список источников с кликабельными ссылками
                    sources = actuality_check.get('verification', {}).get('sources', [])
                    if sources:
                        for source in sources:
                            if isinstance(source, dict):
                                title = source.get('title', 'Без названия')
                                url = source.get('url', '')
                                source_name = source.get('source', '').split(': ')[-1]
                                reliability = source.get('reliability_score', 0)
                                if url:
                                    error_details += f"• [{title}]({url})\n  📍 {source_name} (надежность: {reliability}/10)\n"
                            elif isinstance(source, str) and 'http' in source:
                                error_details += f"• [Источник]({source})\n"
                            else:
                                error_details += f"• {source}\n"
                    else:
                        error_details += "Источники не найдены\n"
                    
                    error_details += f"\n📋 Правило: {'допускаются вчерашние новости' if post_date.hour < 12 else 'новости должны быть сегодняшними'}"
                    
                    await notify_admins(
                        channel_data,
                        message,
                        error_type="Неактуальная новость",
                        error_details=error_details,
                        parse_mode="Markdown"  # Добавляем поддержку Markdown для ссылок
                    )
                    return
                logger.info("Этап 2: Проверка актуальности успешна")
            
            # Запускаем отложенную проверку метрик
            logger.info("Этап 3: Запуск отложенной проверки метрик")
            asyncio.create_task(check_post_metrics_later(chat_id, message.message_id))
            
    except Exception as e:
        logger.error(f"Ошибка при обработке поста: {e}", exc_info=True)


@dp.message(lambda message: waiting_for_channel)
async def process_channel_addition(message: types.Message):
    """Обрабатывает добавление канала"""
    try:
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
        chat = await bot.get_chat(channel_id)
        chat_info = await bot.get_chat_member_count(channel_id)
        
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

    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply("Произошла ошибка при добавлении канала.")


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

        # Собираем все возможные метрики
        metrics = {
            'views': getattr(message, 'views', 0),
            'reactions': 0,
            'forwards': getattr(message, 'forwards', 0),
            'replies': getattr(message, 'replies', 0) if hasattr(message, 'replies') else 0,
            'post_author': getattr(message, 'post_author', None),
            'date': message.date.isoformat() if hasattr(message, 'date') else None,
        }

        # Получаем реакции
        if hasattr(message, 'reactions') and message.reactions:
            reactions_data = []
            total_reactions = 0
            for reaction in message.reactions.results:
                reaction_count = reaction.count
                total_reactions += reaction_count
                reactions_data.append({
                    'emoji': str(reaction.reaction),
                    'count': reaction_count
                })
            metrics['reactions'] = total_reactions
            metrics['reactions_details'] = reactions_data
            
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

async def check_post_metrics_later(chat_id: str, message_id: int):
    """Проверяет метрики поста через некоторое время"""
    try:
        logger.info(f"Запуск отложенной проверки метрик для поста {message_id} в канале {chat_id}")
        
        # Ищем канал по chat_id
        channel_info = None
        for channel_id, data in channels.items():
            if str(data.get('chat_id')) == chat_id:
                channel_info = data
                logger.info(f"Найден канал: {data.get('title')} (id: {chat_id})")
                break
        
        if channel_info is None:
            logger.error(f"Канал {chat_id} не найден в конфигурации")
            return
        
        subscribers_count = channel_info.get('subscribers', 0)
        
        logger.info(f"Требования к метрикам:")
        logger.info(f"- Подписчиков: {subscribers_count}")
        logger.info(f"- Требуемые просмотры: {max(1, round(subscribers_count * 0.1))} (10% от подписчиков)")

        # Ждем указанное время перед проверкой метрик
        logger.info("Ожидание 60 секунд перед проверкой метрик...")
        await asyncio.sleep(60)
        
        # Получаем актуальные метрики через Telethon
        logger.info("Получение метрик...")
        metrics = await get_post_metrics(chat_id, message_id)
        
        if metrics:
            views = metrics.get('views', 0)
            reactions = metrics.get('reactions', 0)
            forwards = metrics.get('forwards', 0)
            
            # Рассчитываем требуемые значения
            required_views = max(1, round(subscribers_count * 0.1))
            required_reactions = max(1, round(views * 0.06))
            required_forwards = max(1, round(views * 0.01))
            
            logger.info(f"Текущие метрики:")
            logger.info(f"- Просмотры: {views}/{required_views} ({views/required_views*100:.1f}%)")
            logger.info(f"- Реакции: {reactions}/{required_reactions} ({reactions/required_reactions*100:.1f}%)")
            logger.info(f"- Пересылки: {forwards}/{required_forwards} ({forwards/required_forwards*100:.1f}%)")

            # Проверяем метрики
            metrics_ok, issues = await check_post_metrics(
                views=views,
                reactions=reactions,
                forwards=forwards,
                subscribers=subscribers_count,
                channel_name=channel_info.get('title', chat_id),
                message_id=message_id,
                message_text="",  # Не используется в проверке метрик
                message_url=f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
            )
            
            if not metrics_ok:
                logger.warning("Метрики не соответствуют требованиям!")
                
                # Проверяем каждую метрику
                views_ok = views >= required_views
                reactions_ok = reactions >= required_reactions
                forwards_ok = forwards >= required_forwards
                
                message = (
                    f"⚠️ Недостаточная активность в посте!\n\n"
                    f"Канал: {channel_info.get('title', chat_id)}\n"
                    f"ID поста: {message_id}\n\n"
                    f"📊 Текущие метрики:\n"
                    f"👁 Просмотры: {views}/{required_views} ({views/required_views*100:.1f}%) {('✅' if views_ok else '❌')}\n"
                    f"👍 Реакции: {reactions}/{required_reactions} ({reactions/required_reactions*100:.1f}%) {('✅' if reactions_ok else '❌')}\n"
                    f"↗️ Пересылки: {forwards}/{required_forwards} ({forwards/required_forwards*100:.1f}%) {('✅' if forwards_ok else '❌')}\n"
                    f"💬 Ответы: {metrics.get('replies', 0)}\n\n"
                )
                
                # Добавляем список проблем
                if not metrics_ok:
                    message += "❗️ Проблемы:\n"
                    if not views_ok:
                        message += f"• Низкие просмотры: {views} из {required_views} (норма: 10% от подписчиков)\n"
                    if not reactions_ok:
                        message += f"• Низкие реакции: {reactions} из {required_reactions} (норма: 6% от просмотров)\n"
                    if not forwards_ok:
                        message += f"• Низкие пересылки: {forwards} из {required_forwards} (норма: 1% от просмотров)\n"
                    message += "\n"
                
                message += f"🔗 Ссылка: https://t.me/c/{str(chat_id)[4:]}/{message_id}"
                
                if metrics.get('reactions_details'):
                    message += "\n\n📝 Детали реакций:\n"
                    for reaction in metrics['reactions_details']:
                        message += f"{reaction['emoji']}: {reaction['count']}\n"
                
                await notify_admins(channel_info, message)
            else:
                logger.info("Метрики соответствуют требованиям")

    except Exception as e:
        logger.error(f"Ошибка при проверке метрик: {e}", exc_info=True)

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

if __name__ == "__main__":
    asyncio.run(main())
