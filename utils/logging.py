import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logger(log_file='bot.log', error_file='errors.log', debug_file='debug.log'):
    # Создаем основной логгер
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Устанавливаем самый подробный уровень для логгера

    # Форматтер для логов
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Обработчик для всех логов (RotatingFileHandler с максимальным размером файла)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # Обработчик для ошибок
    error_handler = RotatingFileHandler(
        error_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # Обработчик для отладочной информации
    debug_handler = RotatingFileHandler(
        debug_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    ))

    # Обработчик для консоли
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Добавляем все обработчики к логгеру
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(debug_handler)
    logger.addHandler(console_handler)

    # Добавляем дополнительные методы для удобства
    def log_success(msg, *args, **kwargs):
        logger.info(f"✅ {msg}", *args, **kwargs)
    
    def log_warning(msg, *args, **kwargs):
        logger.warning(f"⚠️ {msg}", *args, **kwargs)
    
    def log_error(msg, *args, **kwargs):
        logger.error(f"❌ {msg}", *args, **kwargs)
    
    def log_api_call(endpoint, method, response_status, duration):
        logger.debug(
            f"API Call: {method} {endpoint} - "
            f"Status: {response_status} - "
            f"Duration: {duration:.2f}ms"
        )

    def log_bot_action(action, details, success=True):
        status = "✅" if success else "❌"
        logger.info(f"Bot Action {status} - {action}: {details}")

    # Добавляем методы к логгеру
    logger.success = log_success
    logger.api_call = log_api_call
    logger.bot_action = log_bot_action

    # Логируем запуск логгера
    logger.info("=" * 50)
    logger.info(f"Логгер запущен {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    return logger
