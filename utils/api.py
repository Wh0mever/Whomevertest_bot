import logging
import json
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from openai import OpenAI
from .config import CONFIG
from functools import lru_cache
import asyncio

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения функции получения бота
_bot_getter: Optional[Callable] = None

def set_bot_getter(getter: Callable):
    """Устанавливает функцию для получения экземпляра бота"""
    global _bot_getter
    _bot_getter = getter

async def get_gpt_response(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4-turbo-preview",
    temperature: float = 0.3
) -> str:
    """
    Получает ответ от GPT API с обработкой ошибок
    
    Args:
        system_prompt: Системный промпт
        user_prompt: Пользовательский промпт
        model: Модель GPT
        temperature: Температура генерации
    """
    try:
        client = OpenAI(api_key=CONFIG["OPENAI_API_KEY"])
        
        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
            
        # Используем run_in_executor для синхронного вызова
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(**params)
        )
        
        logger.debug(f"GPT ответ получен, токенов использовано: {response.usage.total_tokens}")
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Ошибка при запросе к GPT API: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "status": "error",
            "details": "Ошибка при получении ответа от GPT"
        })

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

@lru_cache(maxsize=100)
async def get_cached_chat_info(chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Получает закэшированную информацию о чате
    
    Args:
        chat_id: ID чата
    """
    try:
        info = await get_telegram_chat_info(chat_id)
        if "error" not in info:
            return info
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении кэшированной информации: {e}")
        return None 