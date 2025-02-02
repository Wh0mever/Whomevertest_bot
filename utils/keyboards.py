from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает основную клавиатуру бота"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="📈 Расширенная Статистика")
            ],
            [
                KeyboardButton(text="➕ Добавить канал"),
                KeyboardButton(text="📋 Список каналов")
            ],
            [
                KeyboardButton(text="📊 Статистика KPI"),
                KeyboardButton(text="📬 Проверить отложенные")
            ],
            [
                KeyboardButton(text="❓ FAQ")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard 