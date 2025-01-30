import aiohttp
import logging
import json
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
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

async def get_news_by_text(text: str, days: int = 7) -> Dict[str, Any]:
    """
    Получает связанные новости через несколько источников
    
    Args:
        text: Текст для поиска
        days: За сколько последних дней искать
    """
    try:
        all_sources = []
        
        async with aiohttp.ClientSession() as session:
            # 1. NewsAPI (основной источник, +30% доверия)
            news_params = {
                'q': text,
                'apiKey': CONFIG["NEWS_API_KEY"],
                'sortBy': 'publishedAt',
                'language': 'ru',
                'from': (datetime.now() - timedelta(days=days)).isoformat(),
                'pageSize': 5
            }
            
            async with session.get('https://newsapi.org/v2/everything', params=news_params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('articles'):
                        for article in data['articles']:
                            all_sources.append({
                                'title': article.get('title'),
                                'url': article.get('url'),
                                'source': f"NewsAPI: {article.get('source', {}).get('name')}",
                                'date': article.get('publishedAt'),
                                'confidence': 0.3  # Высокий уровень доверия
                            })
            
            # 2. Yandex News API (+15% доверия)
            yandex_params = {
                'text': text,
                'api_key': CONFIG.get("YANDEX_NEWS_API_KEY"),
                'lang': 'ru',
                'limit': 5,
                'sort_by': 'date'  # Сортировка по дате
            }
            
            async with session.get('https://news.yandex.ru/api/v1/search', params=yandex_params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('items'):
                        for item in data['items']:
                            all_sources.append({
                                'title': item.get('title'),
                                'url': item.get('url'),
                                'source': f"Yandex: {item.get('source', {}).get('name')}",
                                'date': item.get('published_date'),
                                'confidence': 0.15  # Средний уровень доверия
                            })
            
            # 3. RSS ленты (+20% доверия)
            rss_feeds = [
                'https://lenta.ru/rss',
                'https://www.vedomosti.ru/rss/news',
                'https://tass.ru/rss/v2.xml',
                'https://ria.ru/export/rss2/index.xml',
                'https://www.interfax.ru/rss.asp'
            ]
            
            for feed_url in rss_feeds:
                try:
                    async with session.get(feed_url) as response:
                        if response.status == 200:
                            feed_text = await response.text()
                            import feedparser
                            feed = feedparser.parse(feed_text)
                            
                            for entry in feed.entries[:5]:
                                # Проверяем, есть ли текст новости в заголовке или описании
                                entry_text = f"{entry.get('title', '')} {entry.get('description', '')}"
                                if any(word.lower() in entry_text.lower() for word in text.split()):
                                    all_sources.append({
                                        'title': entry.get('title'),
                                        'url': entry.get('link'),
                                        'source': f"RSS: {feed.feed.get('title', feed_url)}",
                                        'date': entry.get('published'),
                                        'confidence': 0.2  # Средний уровень доверия
                                    })
                except Exception as e:
                    logger.error(f"Ошибка при парсинге RSS {feed_url}: {e}")
        
        # Анализируем все источники через GPT для определения релевантности
        analysis_prompt = f"""
        Проанализируйте новость и найденные источники:
        
        Исходная новость: {text}
        
        Найденные источники:
        {json.dumps(all_sources, ensure_ascii=False, indent=2)}
        
        Для каждого источника определите:
        1. Релевантность к исходной новости (0-100%)
        2. Актуальность по дате публикации
        3. Достоверность источника
        4. Надежность источника (оцените по шкале от 1 до 10)
        
        Верните только релевантные источники (релевантность > 70%) в формате JSON:
        {{
            "relevant_sources": [
                {{
                    "title": str,        // заголовок новости
                    "url": str,          // URL источника
                    "source": str,       // название источника
                    "date": str,         // дата публикации
                    "relevance_score": int,   // релевантность (0-100)
                    "reliability_score": int, // надежность (1-10)
                    "content_match": str      // краткое описание совпадения контента
                }}
            ],
            "summary": {{
                "total_sources": int,          // общее количество проверенных источников
                "relevant_sources": int,        // количество релевантных источников
                "average_relevance": float,     // средняя релевантность
                "most_reliable_source": str,    // самый надежный источник
                "verification_level": str,      // уровень проверки (высокий/средний/низкий)
                "is_verified": bool            // подтверждена ли информация
            }}
        }}"""
        
        analysis_result = await get_gpt_response(
            system_prompt="""Вы - эксперт по анализу новостных источников.
            
            При оценке источников учитывайте:
            1. Релевантность содержания (сравнивайте ключевые факты)
            2. Авторитетность источника (РИА, ТАСС, Интерфакс считаются наиболее надежными)
            3. Актуальность по времени (новость должна быть не старше указанного периода)
            4. Пересечение информации между источниками (если факты подтверждаются в нескольких источниках)
            
            Возвращайте только действительно релевантные источники с подробным описанием совпадений.""",
            user_prompt=analysis_prompt
        )
        
        return json.loads(analysis_result)
        
    except Exception as e:
        logger.error(f"Ошибка при получении новостей: {e}", exc_info=True)
        return {
            "relevant_sources": [],
            "summary": {
                "total_sources": 0,
                "relevant_sources": 0,
                "average_relevance": 0,
                "most_reliable_source": None,
                "verification_level": "низкий",
                "is_verified": False
            }
        }

async def get_gpt_response(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4-turbo-preview",
    temperature: float = 0.3,
    max_tokens: Optional[int] = None
) -> str:
    """
    Получает ответ от GPT API с обработкой ошибок и ретраями
    
    Args:
        system_prompt: Системный промпт
        user_prompt: Пользовательский промпт
        model: Модель GPT
        temperature: Температура генерации
        max_tokens: Максимальное количество токенов
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
        
        if max_tokens:
            params["max_tokens"] = max_tokens
            
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
async def get_cached_chat_info(chat_id: str, max_age: int = 300) -> Optional[Dict[str, Any]]:
    """
    Получает закэшированную информацию о чате
    
    Args:
        chat_id: ID чата
        max_age: Максимальный возраст кэша в секундах
    """
    try:
        info = await get_telegram_chat_info(chat_id)
        if "error" not in info:
            return info
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении кэшированной информации: {e}")
        return None

async def analyze_post_content(
    text: str,
    is_news: bool = False,
    timezone: float = 0
) -> Dict[str, Any]:
    """
    Комплексный анализ контента поста
    
    Args:
        text: Текст поста
        is_news: Является ли пост новостным
        timezone: Часовой пояс
    """
    try:
        # Проверка модерации
        moderation_result = await get_gpt_response(
            system_prompt="""Проверьте текст на соответствие правилам модерации:
            1. Орфографические и грамматические ошибки
            2. Спам и повторы
            3. Читабельность текста (оцените по шкале от 1 до 10)""",
            user_prompt=text
        )
        
        # Если это новость, проверяем актуальность
        actuality_result = None
        if is_news:
            local_time = datetime.now() + timedelta(hours=timezone)
            actuality_result = await get_gpt_response(
                system_prompt="""Проверьте актуальность новости с учетом:
                1. Временной релевантности
                2. Важности события
                3. Категории новости""",
                user_prompt=f"Текст: {text}\nВремя: {local_time.isoformat()}"
            )
            
        return {
            "moderation": json.loads(moderation_result),
            "actuality": json.loads(actuality_result) if actuality_result else None,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Ошибка при анализе контента: {e}", exc_info=True)
        return {
            "error": str(e),
            "status": "error",
            "moderation": {
                "has_errors": False,
                "errors": f"Ошибка проверки: {str(e)}",
                "categories": {
                    "spelling": False,
                    "grammar": False,
                    "spam": False,
                    "readability": {
                        "score": 5,
                        "level": "средний"
                    }
                },
                "details": {
                    "spelling_details": "",
                    "grammar_details": "",
                    "spam_details": "",
                    "readability_details": "Не удалось проанализировать"
                }
            }
        } 