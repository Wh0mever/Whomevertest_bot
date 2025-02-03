# 📊 Telegram Channel Analytics Bot

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.3.0-blue.svg)](https://docs.aiogram.dev/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Telegram](https://img.shields.io/badge/Telegram-Channel-blue.svg)](https://t.me/ctrltg)

## 📝 Описание

Профессиональный бот для аналитики и мониторинга Telegram-каналов. Автоматизирует процесс контроля качества контента и отслеживания метрик эффективности постов.

### 🔑 Ключевые возможности

- 📈 **Мониторинг метрик**
  - Просмотры постов
  - Реакции пользователей
  - Количество пересылок
  - Динамика подписчиков

- 📝 **Анализ контента**
  - Проверка орфографии и грамматики
  - Оценка читабельности текста
  - Выявление спам-контента
  - Рекомендации по улучшению

- ⚙️ **Гибкая настройка**
  - Индивидуальные часовые пояса
  - Настраиваемые пороги метрик
  - Персонализированные уведомления
  - Мультиканальное управление

## 🚀 Установка

1. **Клонирование репозитория**
```bash
git clone https://github.com/wh0mever/whomevertest_bot.git
cd whomevertest_bot
```

2. **Установка зависимостей**
```bash
pip install -r requirements.txt
```

3. **Настройка конфигурации**
```bash
cp config.example.json config.json
# Отредактируйте config.json, добавив необходимые токены
```

## ⚙️ Конфигурация

Создайте файл `config.json` со следующей структурой:

```json
{
    "API_TOKEN": "ваш_токен_бота",
    "API_ID": "ваш_api_id",
    "API_HASH": "ваш_api_hash",
    "OPENAI_API_KEY": "ваш_ключ_openai",
    "UPDATE_INTERVALS": {
        "SUBSCRIBERS": 3600,
        "METRICS": 86400
    },
    "POST_SETTINGS": {
        "MAX_LENGTH": 2000
    }
}
```

## 🎯 Использование

### 🤖 Команды бота

- `/start` - Начало работы с ботом
- `/help` - Справка по командам
- `/add_channel` - Добавление канала
- `/channels` - Управление каналами
- `/stats` - Статистика каналов

### 📊 Метрики и нормы

- **Просмотры**: 10% от количества подписчиков
- **Реакции**: 6% от количества просмотров
- **Пересылки**: 15% от количества просмотров

## 🔧 Техническая реализация

### 🏗 Архитектура

```
telegram_channel_tracker/
├── bot.py              # Основной файл бота
├── config.json         # Конфигурация
├── requirements.txt    # Зависимости
└── utils/
    ├── __init__.py
    ├── api.py         # API интеграции
    ├── checks.py      # Проверки контента
    ├── database.py    # Работа с данными
    └── logging.py     # Логирование
```

### 🔄 Процесс работы

1. **Мониторинг постов**
   - Автоматическое отслеживание новых публикаций
   - Анализ текста через OpenAI API
   - Сбор метрик через Telegram API

2. **Анализ метрик**
   - Сбор данных через 24 часа после публикации
   - Сравнение с нормативами
   - Генерация отчетов

3. **Уведомления**
   - Мгновенные алерты при проблемах с текстом
   - Отчеты по метрикам через 24 часа
   - Еженедельная статистика

## 🔒 Безопасность

- Защита от несанкционированного доступа
- Шифрование конфиденциальных данных
- Безопасное хранение токенов
- Логирование всех действий

## 🔍 Мониторинг и отладка

### 📝 Логи

```bash
tail -f logs/bot.log
```

### 🐛 Отладка

```bash
python -m debugpy --listen 5678 bot.py
```

## 📈 Производительность

- Асинхронная обработка запросов
- Оптимизированное использование API
- Кэширование данных
- Минимизация нагрузки на сервер

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для фичи (`git checkout -b feature/amazing_feature`)
3. Зафиксируйте изменения (`git commit -m 'Add amazing feature'`)
4. Отправьте изменения в репозиторий (`git push origin feature/amazing_feature`)
5. Создайте Pull Request

## 📞 Поддержка

- **Telegram**: [@ctrltg](https://t.me/ctrltg)
- **Сайт**: [whomever.tech](https://whomever.tech)
- **Email**: support@whomever.tech

## 📄 Лицензия

Распространяется под лицензией MIT. Смотрите файл [LICENSE](LICENSE) для получения дополнительной информации.

## 👨‍💻 Автор

- **Whomever**
  - [GitHub](https://github.com/wh0mever)
  - [Telegram](https://t.me/ctrltg)
  - [Website](https://whomever.tech)

## 🙏 Благодарности

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenAI API](https://openai.com/blog/openai-api)
- [Aiogram](https://docs.aiogram.dev/)
- [Telethon](https://docs.telethon.dev/) 
