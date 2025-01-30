import json
import logging

# Загрузка данных из JSON
def load_json(file_path):
    try:
        with open(file_path, "r", encoding='utf-8') as f:
            data = json.load(f)
        logging.getLogger(__name__).info(f"Данные успешно загружены из {file_path}")
        return data
    except FileNotFoundError:
        logging.getLogger(__name__).info(f"Файл {file_path} не найден, создаем новый")
        return {}
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка при загрузке данных из {file_path}: {e}", exc_info=True)
        return {}

# Сохранение данных в JSON
def save_json(file_path, data):
    try:
        with open(file_path, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.getLogger(__name__).info(f"Данные успешно сохранены в {file_path}")
    except Exception as e:
        logging.getLogger(__name__).error(f"Ошибка при сохранении данных в {file_path}: {e}", exc_info=True)
