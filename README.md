# Telegram Channel Tracker Bot

Бот для отслеживания активности и метрик в Telegram-каналах с возможностью проверки контента и настройки индивидуальных метрик для каждого канала.

## Основные возможности

- ✅ Мониторинг активности каналов
- 📊 Отслеживание метрик постов (просмотры, реакции, пересылки)
- 🔍 Проверка качества контента
- ⚙️ Индивидуальные настройки метрик для каждого канала
- 📈 Подробная статистика и KPI
- 🕒 Автоматические проверки метрик

## Требования

- Python 3.8+
- Telegram API ключи (API_ID и API_HASH)
- OpenAI API ключ для проверки контента
- Токен Telegram бота

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/Wh0mever/Whomevertest_bot.git
cd Whomevertest_bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `config.json` со следующей структурой:
```json
{
    "API_TOKEN": "YOUR_BOT_TOKEN",
    "API_ID": "YOUR_API_ID",
    "API_HASH": "YOUR_API_HASH",
    "OPENAI_API_KEY": "YOUR_OPENAI_API_KEY",
    "ADMIN_IDS": [],
    "UPDATE_INTERVALS": {
        "SUBSCRIBERS": 3600
    },
    "POST_SETTINGS": {
        "MIN_VIEWS_PERCENT": 10.0,
        "MIN_REACTIONS_PERCENT": 6.0,
        "MIN_FORWARDS_PERCENT": 15.0,
        "METRICS_CHECK_DELAY": 86400,
        "TEXT_CHECK_DELAY": 0
    }
}
```

## Использование

1. Запустите бота:
```bash
python bot.py
```

2. Добавьте бота в администраторы вашего канала
3. Используйте команду /start для начала работы
4. Настройте метрики и начните отслеживание

## Команды

- `/start` - Начало работы с ботом
- `/help` - Справка по использованию
- `/add_channel` - Добавление нового канала
- `/channels` - Управление каналами
- `/stats` - Общая статистика
- `/allstats` - Расширенная статистика
- `/kpi` - KPI статистика
- `/check_pending` - Проверка отложенных метрик

## Метрики

- 👁 Просмотры: настраиваемый % от подписчиков
- 👍 Реакции: настраиваемый % от просмотров
- ↗️ Пересылки: настраиваемый % от просмотров

## Поддержка

По всем вопросам обращайтесь:
- Telegram: [@ctrltg](https://t.me/ctrltg)
- GitHub: [Wh0mever](https://github.com/Wh0mever)
- Сайт: [whomever.tech](https://whomever.tech) 