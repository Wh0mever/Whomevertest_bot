import logging
from typing import Dict, Any, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения функции получения бота
_bot_getter: Optional[Callable] = None

def set_bot_getter(getter: Callable):
    """Устанавливает функцию для получения экземпляра бота"""
    global _bot_getter
    _bot_getter = getter

async def get_telegram_chat_info(chat_id: str) -> Dict[str, Any]:
    """
    Получает информацию о Telegram чате/канале
    
    Args:
        chat_id: ID чата/канала
    """
    try:
        if not _bot_getter:
            raise RuntimeError("Bot getter not set")
            
        bot = _bot_getter()
        chat = await bot.get_chat(chat_id)
        members_count = await bot.get_chat_member_count(chat_id)
        
        return {
            "id": str(chat.id),
            "title": chat.title,
            "username": chat.username,
            "type": chat.type,
            "members_count": int(members_count),
            "description": chat.description,
            "invite_link": chat.invite_link,
            "is_forum": getattr(chat, "is_forum", False),
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о чате {chat_id}: {e}", exc_info=True)
        return {
            "error": str(e),
            "status": "error"
        } 