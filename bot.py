import json
import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from utils.database import load_json, save_json
from utils.logging import setup_logger
from utils.checks import check_spelling, check_post_metrics, analyze_metrics_with_gpt
from utils.notifications import notify_admins
from telethon import TelegramClient
from datetime import datetime, timedelta
import aiohttp
from utils.api import set_bot_getter
import time
from utils.config import CONFIG
import re

# ID супер-админа
SUPER_ADMIN_ID = 1914567632

# Настройка логирования
logger = setup_logger()

# Загрузка конфигурации
with open("config.json") as config_file:
    CONFIG = json.load(config_file)

# В начале файла, где определены константы
CONFIG.update({
    "METRICS_CHECK_DELAY": 86400,  # 24 часа
    "TEXT_CHECK_DELAY": 0  # Мгновенная проверка
})

bot = Bot(token=CONFIG["API_TOKEN"])
dp = Dispatcher()
dp.bot = bot

# Загрузка данных о каналах
channels = load_json("channels.json")

# Глобальная переменная для отслеживания состояния
waiting_for_channel = False
waiting_for_timezone = False
current_channel = None
current_channel_title = None

# Добавляем в начало файла инициализацию клиента Telethon
client = TelegramClient('bot_session', CONFIG["API_ID"], CONFIG["API_HASH"])

# Функция для сохранения данных
def save_channels():
    save_json("channels.json", channels)

@dp.message(Command("start"))
async def start_command(message: types.Message):
    try:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал")],
                [KeyboardButton(text="📋 Мои каналы")],
                [KeyboardButton(text="📊 Статистика")],
                [KeyboardButton(text="❓ Помощь")]
            ],
            resize_keyboard=True,
            persistent=True
        )
        
        await message.reply(
            "Привет! Я бот для отслеживания каналов.\n"
            "Выберите действие или используйте команды из меню:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await message.reply("Произошла ошибка при обработке вашего запроса.")

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

@dp.message(Command("add_channel"))
async def add_channel_command(message: types.Message):
    try:
        global waiting_for_channel
        waiting_for_channel = True
        await message.reply(
            "Отправьте ID или username канала, который нужно добавить.\n"
            "Формат: @username +05:00 или -100123456789 -02:30"
        )
    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply("Произошла ошибка при добавлении канала.")

@dp.message(Command("channels"))
async def channels_command(message: types.Message):
    """Обработчик команды /channels"""
    await handle_my_channels(message)

@dp.message(lambda message: message.text == "📋 Мои каналы")
async def handle_my_channels(message: types.Message):
    try:
        if not channels:
            await message.reply(
                "📋 Список каналов пуст.\n"
                "Нажмите кнопку '➕ Добавить канал' чтобы добавить новый канал.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="➕ Добавить канал")],
                        [KeyboardButton(text="◀️ Назад")]
                    ],
                    resize_keyboard=True
                )
            )
            return

        keyboard = []
        for channel_id, data in channels.items():
            channel_name = data.get('title', 'Неизвестно')
            keyboard.append([KeyboardButton(text=f"📌 {channel_name}")])
        keyboard.append([KeyboardButton(text="◀️ Назад")])
        
        await message.reply(
            "📋 Выберите канал для управления:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=keyboard,
                resize_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"Ошибка при отображении списка каналов: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: message.text.startswith("📌 "))
async def handle_channel_settings(message: types.Message):
    try:
        channel_title = message.text[2:].strip()  # Убираем эмодзи и пробелы
        channel_id = None
        channel_data = None
        
        for cid, data in channels.items():
            if data.get('title') == channel_title:
                channel_id = cid
                channel_data = data
                break
                
        if not channel_data:
            await message.reply("Канал не найден")
            return
            
        keyboard = [
            [KeyboardButton(text="🕒 Изменить часовой пояс")],
            [KeyboardButton(text="🗑 Удалить канал")],
            [KeyboardButton(text="◀️ Назад к списку")]
        ]
        
        # Формируем ссылку на канал
        channel_link = f"https://t.me/{channel_data.get('username', channel_id[1:])}" if channel_id.startswith('@') else f"https://t.me/c/{str(channel_data['chat_id'])[4:]}"
        
        text = (
            f"⚙️ Настройки канала {channel_title}\n\n"
            f"👥 Подписчиков: {channel_data.get('subscribers', 0):,}\n"
            f"🕒 Часовой пояс: {channel_data.get('timezone', 0):+.2f}\n"
            f"🔗 Ссылка: {channel_link}"
        )
        
        await message.reply(
            text,
            reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек канала: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: message.text == "➕ Добавить канал")
async def handle_add_channel_button(message: types.Message):
    """Обработчик кнопки добавления канала"""
    await add_channel_command(message)

@dp.message(lambda message: message.text == "🕒 Изменить часовой пояс")
async def change_timezone_handler(message: types.Message):
    try:
        global waiting_for_timezone, current_channel
        waiting_for_timezone = True
        
        # Получаем текущий канал из сообщения
        channel_title = None
        for cid, data in channels.items():
            if data.get('title') == message.text[2:].strip():  # Убираем эмодзи
                current_channel = cid
                channel_title = data.get('title')
                break
                
        if not current_channel:
            await message.reply(
                "Ошибка: канал не найден",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад")]],
                    resize_keyboard=True
                )
            )
            return
            
        await message.reply(
            "Отправьте новый часовой пояс в формате: +05:00 или -02:30",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="◀️ Назад к настройкам")]],
                resize_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"Ошибка при запросе часового пояса: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: waiting_for_timezone and message.text not in ["◀️ Назад", "◀️ Назад к настройкам"])
async def process_timezone_change(message: types.Message):
    """Обработчик изменения часового пояса"""
    try:
        global waiting_for_timezone, current_channel
        
        # Проверяем формат часового пояса
        timezone_str = message.text
        if not re.match(r'^[+-]\d{2}:\d{2}$', timezone_str):
            await message.reply(
                "Неверный формат часового пояса. Используйте формат: +05:00 или -02:30",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад к настройкам")]],
                    resize_keyboard=True
                )
            )
            return
            
        # Конвертируем строку в число
        sign = -1 if timezone_str[0] == '-' else 1
        hours, minutes = map(int, timezone_str[1:].split(':'))
        timezone = sign * (hours + minutes / 60)
        
        # Обновляем часовой пояс канала
        if current_channel and current_channel in channels:
            channels[current_channel]['timezone'] = timezone
            save_channels()
            
            await message.reply(
                f"✅ Часовой пояс успешно изменен на {timezone_str}",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад к настройкам")]],
                    resize_keyboard=True
                )
            )
            
            # Сбрасываем состояние
            waiting_for_timezone = False
            current_channel = None
        else:
            await message.reply(
                "Ошибка: канал не найден",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад")]],
                    resize_keyboard=True
                )
            )
            
    except Exception as e:
        logger.error(f"Ошибка при изменении часового пояса: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(Command("stats"))
async def stats_command(message: types.Message):
    """Обработчик команды /stats"""
    await handle_stats(message)

@dp.message(lambda message: message.text == "📊 Статистика")
async def handle_stats(message: types.Message):
    try:
        stats_text = "📊 Статистика каналов:\n\n"
        if not channels:
            stats_text = "Нет отслеживаемых каналов"
        else:
            for chat_id, data in channels.items():
                stats_text += (
                    f"📌 {data.get('title', chat_id)}\n"
                    f"👥 Подписчиков: {data.get('subscribers', 0):,}\n"
                    f"🕒 Часовой пояс: {data.get('timezone', 0):+.2f}\n\n"
                )
        
        await message.reply(
            stats_text,
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="◀️ Назад")]],
                resize_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"Ошибка при отображении статистики: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: message.text == "◀️ Назад")
async def back_to_main_menu(message: types.Message):
    """Обработчик кнопки Назад - возврат в главное меню"""
    try:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал")],
                [KeyboardButton(text="📋 Мои каналы")],
                [KeyboardButton(text="📊 Статистика")],
                [KeyboardButton(text="❓ Помощь")]
            ],
            resize_keyboard=True
        )
        await message.reply("Выберите действие:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при возврате в главное меню: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: message.text == "❓ Помощь")
async def handle_help(message: types.Message):
    """Обработчик кнопки Помощь"""
    await help_command(message)

@dp.message(lambda message: message.text == "🗑 Удалить канал")
async def handle_delete_channel(message: types.Message):
    try:
        if not channels:
            await message.reply(
                "Список отслеживаемых каналов пуст.\n"
                "Сначала добавьте канал с помощью кнопки '➕ Добавить канал'",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад")]],
                    resize_keyboard=True
                )
            )
            return

        text = "Выберите канал для удаления:\n\n"
        keyboard = []
        
        for channel_id, data in channels.items():
            text += f"📌 {data.get('title', channel_id)}\n"
            text += f"ID: {channel_id}\n\n"
            keyboard.append([KeyboardButton(text=f"❌ {channel_id}")])
        
        keyboard.append([KeyboardButton(text="◀️ Назад")])
        
        await message.reply(
            text,
            reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Ошибка при отображении списка каналов для удаления: {e}")
        await message.reply("Произошла ошибка при обработке запроса")

@dp.message(lambda message: message.text.startswith("❌ "))
async def confirm_delete_channel(message: types.Message):
    try:
        channel_id = message.text[2:]  # Убираем "❌ "
        
        if channel_id in channels:
            channel_title = channels[channel_id].get('title', channel_id)
            del channels[channel_id]
            save_channels()
            
            await message.reply(
                f"✅ Канал {channel_title} успешно удален",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="➕ Добавить канал")],
                        [KeyboardButton(text="◀️ Назад")]
                    ],
                    resize_keyboard=True
                )
            )
        else:
            await message.reply(
                "Канал не найден",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="◀️ Назад")]],
                    resize_keyboard=True
                )
            )
            
    except Exception as e:
        logger.error(f"Ошибка при удалении канала: {e}")
        await message.reply("Произошла ошибка при удалении канала")

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
        await asyncio.sleep(CONFIG["UPDATE_INTERVALS"]["SUBSCRIBERS"])

async def main():
    await client.start()
    logger.info("Клиент Telethon подключен.")
    print("Бот запущен...")
    asyncio.create_task(update_subscribers_count())
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

@dp.message(Command("cancel"))
async def cancel_command(message: types.Message):
    global waiting_for_channel
    if waiting_for_channel:
        waiting_for_channel = False
        await message.reply("Добавление канала отменено.")
    else:
        await message.reply("Нет активных операций для отмены.")

@dp.channel_post()
async def handle_channel_post(message: types.Message):
    """Обрабатывает новые посты в каналах"""
    try:
        chat_id = str(message.chat.id)
        logger.info(f"Получен новый пост из канала {message.chat.title or chat_id}")
        
        channel_data = None
        for channel_id, data in channels.items():
            if str(data.get('chat_id')) == chat_id:
                channel_data = data
                break
                
        if not channel_data:
            logger.error(f"Канал {chat_id} не найден в базе")
            return

        # Проверяем текст
        if message.text:
            # Проверка орфографии и содержания
            spelling_result = await check_spelling(message.text, CONFIG["OPENAI_API_KEY"])
            
            # Проверяем решение GPT
            if spelling_result["decision"] == "/false_no":
                error_message = f"📝 Результаты проверки поста:\n\n"
                error_message += f"📌 Канал: {channel_data.get('title', chat_id)}\n"
                error_message += f"🔢 ID поста: {message.message_id}\n"
                error_message += f"🔗 Ссылка: https://t.me/c/{str(chat_id)[4:]}/{message.message_id}\n\n"
                error_message += f"📄 Текст поста:\n{message.text[:200]}{'...' if len(message.text) > 200 else ''}\n\n"
                
                has_serious_issues = False
                
                # Проверка орфографии
                if spelling_result["categories"]["spelling"]:
                    error_message += "🔍 Орфографические ошибки:\n"
                    spelling_details = spelling_result['details']['spelling_details']
                    if isinstance(spelling_details, list):
                        spelling_details = "\n".join(map(str, spelling_details))
                    for error in (spelling_details.split('\n') if isinstance(spelling_details, str) else spelling_details):
                        if isinstance(error, str) and error.strip():
                            error_message += f"• {error.strip()}\n"
                    error_message += "\n"
                    has_serious_issues = True
                
                # Проверка грамматики с детальным выводом
                if spelling_result["categories"]["grammar"]:
                    error_message += "📝 Грамматические ошибки:\n"
                    grammar_details = spelling_result['details']['grammar_details']
                    if isinstance(grammar_details, list):
                        grammar_details = "\n".join(map(str, grammar_details))
                    for error in (grammar_details.split('\n') if isinstance(grammar_details, str) else grammar_details):
                        if isinstance(error, str) and error.strip():
                            error_message += f"• {error.strip()}\n"
                    error_message += "\n"
                    has_serious_issues = True
                
                # Проверка читабельности
                readability = spelling_result["categories"]["readability"]
                error_message += (
                    f"📚 Читабельность: {readability['score']}/10\n"
                    f"Уровень: {readability['level']}\n"
                    f"{spelling_result['details']['readability_details']}\n"
                )
                
                # Добавляем рекомендации по улучшению
                if "improvements" in spelling_result:
                    improvements = spelling_result["improvements"]
                    if any(improvements.values()):
                        error_message += "\n💡 Рекомендации по улучшению:\n"
                        
                        if improvements["corrections"]:
                            error_message += "\n✍️ Исправления:\n"
                            error_message += "\n".join(f"• {correction}" for correction in improvements["corrections"])
                            
                        if improvements["structure"]:
                            error_message += "\n\n📝 Структура текста:\n"
                            error_message += "\n".join(f"• {suggestion}" for suggestion in improvements["structure"])
                            
                        if improvements["readability"]:
                            error_message += "\n\n📚 Читабельность:\n"
                            error_message += "\n".join(f"• {tip}" for tip in improvements["readability"])
                            
                        if improvements["engagement"]:
                            error_message += "\n\n🎯 Вовлечение аудитории:\n"
                            error_message += "\n".join(f"• {idea}" for idea in improvements["engagement"])
                
                if has_serious_issues:
                    await notify_admins(channel_data, error_message, bot, SUPER_ADMIN_ID, message)
                
        # Запускаем отложенную проверку метрик
        logger.info("Запуск отложенной проверки метрик")
        asyncio.create_task(check_post_metrics_later(client, bot, chat_id, message.message_id, 
                                                   channel_data.get('title', chat_id), 
                                                   channel_data.get('subscribers', 0), 
                                                   channel_data.get('admins', []),
                                                   SUPER_ADMIN_ID))
            
    except Exception as e:
        logger.error(f"Ошибка при обработке поста: {e}", exc_info=True)

@dp.message(lambda message: waiting_for_channel)
async def process_channel_addition(message: types.Message):
    """Обрабатывает добавление канала"""
    try:
        parts = message.text.split()
        if len(parts) < 1:
            await message.reply("Неверный формат. Используйте: @username +05:00 или -100123456789 -02:30")
            return

        channel_id = parts[0]
        timezone = 0

        if len(parts) > 1:
            try:
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

        if not (channel_id.startswith('@') or channel_id.startswith('-100')):
            await message.reply("Неверный формат. ID канала должен начинаться с '@' или '-100'")
            return

        if channel_id in channels:
            await message.reply("Этот канал уже отслеживается.")
            return

        chat = await bot.get_chat(channel_id)
        chat_info = await bot.get_chat_member_count(channel_id)
        
        subscribers = int(chat_info)
        
        channels[channel_id] = {
            "timezone": timezone,
            "subscribers": subscribers,
            "title": chat.title,
            "posts": [],
            "chat_id": chat.id,
            "admins": [message.from_user.id]
        }
        save_channels()
        
        channel_info = (
            f"✅ Канал успешно добавлен!\n\n"
            f"📌 Канал: {channel_id}\n"
            f"📑 Название: {chat.title}\n"
            f"👥 Подписчиков: {subscribers:,}\n"
            f"🕒 Часовой пояс: {timezone:+.2f}"
        )
        
        # Отправляем уведомление админу канала
        await message.reply(channel_info)
        
        # Отправляем уведомление супер-админу
        if message.from_user.id != SUPER_ADMIN_ID:
            super_admin_notification = (
                f"🆕 Добавлен новый канал!\n\n"
                f"👤 Добавил: {message.from_user.full_name} (ID: {message.from_user.id})\n\n"
                f"{channel_info}"
            )
            try:
                await bot.send_message(SUPER_ADMIN_ID, super_admin_notification)
                logger.info(f"Уведомление о новом канале отправлено супер-админу")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления супер-админу: {e}")
        
        logger.info(f"Канал {channel_id} добавлен с часовым поясом {timezone}, подписчиков: {subscribers}")

    except Exception as e:
        logger.error(f"Ошибка при добавлении канала: {e}", exc_info=True)
        await message.reply("Произошла ошибка при добавлении канала.")

async def get_post_metrics(client, chat_id: str, message_id: int) -> dict:
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

async def check_post_metrics_later(client, bot, chat_id: str, message_id: int, channel_title: str, subscribers: int, admins: list, super_admin_id: int):
    """Проверяет метрики поста через 24 часа"""
    try:
        # Ищем канал по chat_id
        channel_info = None
        for channel_id, data in channels.items():
            if str(data.get('chat_id')) == chat_id:
                channel_info = data
                break
        
        if channel_info is None:
            logger.error(f"Канал {chat_id} не найден в конфигурации")
            return
            
        # ЭТАП 1: Проверка текста
        logger.info(f"🔄 ЭТАП 1: Проверка текста поста {message_id}")
        try:
            # Получаем сообщение через Telethon
            message = await client.get_messages(int(chat_id), ids=message_id)
            if message and message.text:
                spelling_result = await check_spelling(message.text, CONFIG["OPENAI_API_KEY"])
                if spelling_result["has_errors"]:
                    error_message = f"📝 Результаты проверки поста:\n\n"
                    error_message += f"📌 Канал: {channel_title}\n"
                    error_message += f"🔢 ID поста: {message_id}\n"
                    error_message += f"🔗 Ссылка: https://t.me/c/{str(chat_id)[4:]}/{message_id}\n\n"
                    error_message += f"📄 Текст поста:\n{message.text[:200]}{'...' if len(message.text) > 200 else ''}\n\n"
                    
                    has_serious_issues = False
                    
                    # Проверка орфографии
                    if spelling_result["categories"]["spelling"]:
                        error_message += "🔍 Орфографические ошибки:\n"
                        spelling_details = spelling_result['details']['spelling_details']
                        if isinstance(spelling_details, list):
                            spelling_details = "\n".join(map(str, spelling_details))
                        for error in (spelling_details.split('\n') if isinstance(spelling_details, str) else spelling_details):
                            if isinstance(error, str) and error.strip():
                                error_message += f"• {error.strip()}\n"
                        error_message += "\n"
                        has_serious_issues = True
                    
                    # Проверка грамматики с детальным выводом
                    if spelling_result["categories"]["grammar"]:
                        error_message += "📝 Грамматические ошибки:\n"
                        grammar_details = spelling_result['details']['grammar_details']
                        if isinstance(grammar_details, list):
                            grammar_details = "\n".join(map(str, grammar_details))
                        for error in (grammar_details.split('\n') if isinstance(grammar_details, str) else grammar_details):
                            if isinstance(error, str) and error.strip():
                                error_message += f"• {error.strip()}\n"
                        error_message += "\n"
                        has_serious_issues = True
                    
                    # Проверка читабельности
                    readability = spelling_result["categories"]["readability"]
                    error_message += (
                        f"📚 Читабельность: {readability['score']}/10\n"
                        f"Уровень: {readability['level']}\n"
                        f"{spelling_result['details']['readability_details']}\n"
                    )
                    
                    if has_serious_issues:
                        await notify_admins(channel_info, error_message, bot, super_admin_id, message)
        except Exception as e:
            logger.error(f"Ошибка при проверке текста: {e}")
            
        # Ждем 30 секунд перед проверкой метрик
        logger.info(f"⏳ Ожидание 86400 секунд перед проверкой метрик")
        await asyncio.sleep(86400)  # 86400 секунд
            
        # ЭТАП 2: Проверка метрик
        logger.info(f"🔄 ЭТАП 2: Проверка метрик поста {message_id}")
        try:
            metrics = await get_post_metrics(client, chat_id, message_id)
            if not metrics:
                logger.error(f"Не удалось получить метрики для поста {message_id}")
                return

            # Подготавливаем данные для анализа
            metrics_data = {
                "channel_info": {
                    "name": channel_title,
                    "subscribers": subscribers
                },
                "metrics": metrics
            }
            
            # Анализируем метрики
            analysis = await analyze_metrics_with_gpt(metrics_data, CONFIG["OPENAI_API_KEY"])
            if not analysis:
                logger.error("Не удалось проанализировать метрики")
                return
                
            logger.info(f"✅ Анализ метрик завершен для поста {message_id}")
                
            # Отправляем уведомление только если есть проблемы
            if not analysis.get("metrics_ok", False):
                message_url = f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
                notification = (
                    f"⚠️ Анализ метрик поста\n\n"
                    f"📊 Канал: {channel_title}\n"
                    f"🔗 {message_url}\n\n"
                    f"📈 Метрики:\n"
                )
                
                metrics_info = analysis.get("metrics", {})
                for metric_name, metric_data in metrics_info.items():
                    if isinstance(metric_data, dict):
                        current = metric_data.get("current", 0)
                        required = metric_data.get("required", 0)
                        percent = (current / required * 100) if required > 0 else 0
                        
                        emoji = "👁" if metric_name == "views" else "❤️" if metric_name == "reactions" else "🔄"
                        name_ru = "Просмотры" if metric_name == "views" else "Реакции" if metric_name == "reactions" else "Пересылки"
                        
                        notification += (
                            f"{emoji} {name_ru}: {current}/{required} ({percent:.1f}%)\n"
                            f"{'✅' if percent >= 100 else '❌'} "
                            f"Норма: {required}\n\n"
                        )
                
                if "issues" in analysis:
                    notification += "❌ Проблемы:\n" + "\n".join(f"• {issue}" for issue in analysis["issues"])
                
                # Отправляем уведомление админам
                for admin_id in admins:
                    try:
                        await bot.send_message(admin_id, notification)
                        logger.info(f"📤 Отправлено уведомление админу {admin_id}")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
            else:
                logger.info(f"✅ Все метрики в норме для поста {message_id}")
        except Exception as e:
            logger.error(f"Ошибка при проверке метрик: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке метрик: {e}", exc_info=True)

def get_bot():
    return bot

set_bot_getter(get_bot)

if __name__ == "__main__":
    asyncio.run(main())
