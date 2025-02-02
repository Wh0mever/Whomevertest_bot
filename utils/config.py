import json
from pathlib import Path

def load_config():
    """Загружает конфигурацию из файла config.json"""
    config_path = Path("config.json")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise Exception(f"Ошибка при загрузке конфигурации: {e}")

# Загружаем конфигурацию при импорте модуля
CONFIG = load_config()

# Проверяем наличие необходимых ключей
required_keys = [
    "API_TOKEN",
    "API_ID",
    "API_HASH",
    "OPENAI_API_KEY"
]

for key in required_keys:
    if key not in CONFIG:
        raise KeyError(f"В конфигурации отсутствует обязательный ключ: {key}") 