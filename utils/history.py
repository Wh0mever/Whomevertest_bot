import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
from .database import load_json, save_json

logger = logging.getLogger(__name__)

class CheckHistory:
    def __init__(self, file_path: str = "check_history.json"):
        self.file_path = file_path
        self.history = self._load_history()

    def _load_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """Загружает историю проверок из файла"""
        try:
            return load_json(self.file_path)
        except Exception as e:
            logger.error(f"Ошибка при загрузке истории: {e}")
            return {}

    def _save_history(self):
        """Сохраняет историю проверок в файл"""
        try:
            save_json(self.file_path, self.history)
        except Exception as e:
            logger.error(f"Ошибка при сохранении истории: {e}")

    def add_check_result(self, chat_id: str, check_type: str, passed: bool, details: Dict[str, Any]):
        """Добавляет результат проверки в историю"""
        if chat_id not in self.history:
            self.history[chat_id] = []

        check_record = {
            "timestamp": datetime.now().isoformat(),
            "type": check_type,
            "passed": passed,
            "details": details
        }

        self.history[chat_id].append(check_record)
        self._save_history()

    def get_channel_stats(self, chat_id: str, hours: int = 48) -> Dict[str, Any]:
        """Получает статистику проверок канала за указанное количество часов"""
        if chat_id not in self.history:
            return {
                "content_checks": 0,
                "content_fails": 0,
                "metric_checks": 0,
                "metric_fails": 0
            }

        date_from = datetime.now() - timedelta(hours=hours)
        
        content_checks = 0
        content_fails = 0
        metric_checks = 0
        metric_fails = 0

        for check in self.history[chat_id]:
            check_time = datetime.fromisoformat(check["timestamp"])
            if check_time >= date_from:
                if check["type"] == "content":
                    content_checks += 1
                    if not check["passed"]:
                        content_fails += 1
                elif check["type"] == "metrics":
                    metric_checks += 1
                    if not check["passed"]:
                        metric_fails += 1

        return {
            "content_checks": content_checks,
            "content_fails": content_fails,
            "metric_checks": metric_checks,
            "metric_fails": metric_fails
        }

    def cleanup_old_records(self, days: int = 7):
        """Удаляет старые записи"""
        date_from = datetime.now() - timedelta(days=days)
        
        for chat_id in self.history:
            self.history[chat_id] = [
                check for check in self.history[chat_id]
                if datetime.fromisoformat(check["timestamp"]) >= date_from
            ]
        
        self._save_history() 