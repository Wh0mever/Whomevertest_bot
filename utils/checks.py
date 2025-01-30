import re
import json
import logging
import requests
from openai import OpenAI
from datetime import datetime, timedelta
from .api import get_news_by_text, get_gpt_response
from typing import Dict, Any, List, Tuple
import aiohttp
from .config import CONFIG  # Добавляем импорт в начало файла
import asyncio

# Настройка логирования
logger = logging.getLogger(__name__)

# Проверка текста на длину
def check_text_length(text: str, max_length: int = 500) -> bool:
    return len(text) <= max_length

# Проверка орфографии и содержания
async def check_spelling(text: str, api_key: str) -> dict:
    """Проверяет текст на ошибки и читабельность"""
    try:
        client = OpenAI(api_key=api_key)
        system_prompt = """Вы - профессиональный редактор и модератор контента. 
        Проанализируйте текст по следующим критериям:
        
        1. Орфографические и грамматические ошибки
           - Проверьте правописание слов
           - Проверьте пунктуацию
           - Проверьте согласование слов
           - Укажите конкретные ошибки и правильные варианты
           
        2. Спам и повторы
           - Повторяющиеся фразы или абзацы
           - Бессмысленные повторы текста
           - Копипаста одного и того же содержания
           
        3. Читабельность текста (по шкале от 1 до 10)
           - Оцените сложность восприятия текста
           - Проверьте структуру предложений
           - Оцените логичность изложения
           - Проанализируйте длину предложений
           - Оцените использование профессиональных терминов
        
        Ответ предоставьте в формате JSON:
        {
            "has_errors": boolean,
            "errors": "подробное описание найденных проблем",
            "categories": {
                "spelling": boolean,  // орфография
                "grammar": boolean,   // грамматические ошибки
                "spam": boolean,      // спам и повторы
                "readability": {
                    "score": number,  // оценка от 1 до 10
                    "level": string   // "легкий"/"средний"/"сложный"
                }
            },
            "details": {
                "spelling_details": "найденные орфографические ошибки с исправлениями",
                "grammar_details": "найденные грамматические ошибки с исправлениями",
                "spam_details": "описание найденных повторов",
                "readability_details": "подробный анализ читабельности текста"
            }
        }"""

        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0
        )
        
        result = response.choices[0].message.content
        try:
            parsed_result = json.loads(result)
            
            # Формируем понятное описание проблем
            if parsed_result["has_errors"]:
                error_details = []
                if parsed_result["categories"]["spelling"]:
                    error_details.append("- Орфографические ошибки")
                if parsed_result["categories"]["grammar"]:
                    error_details.append("- Грамматические ошибки")
                if parsed_result["categories"]["spam"]:
                    error_details.append("- Спам и повторы")
                
                readability = parsed_result["categories"]["readability"]
                if readability["score"] < 5:
                    error_details.append(f"- Низкая читабельность текста (оценка: {readability['score']}/10)")
                
                parsed_result["errors"] = "\n".join(error_details)
            
            return parsed_result
            
        except json.JSONDecodeError:
            logger.error(f"Ошибка парсинга JSON ответа: {result}")
            return {
                "has_errors": True,
                "errors": "Обнаружены проблемы в тексте",
                "categories": {
                    "spelling": False,
                    "grammar": False,
                    "spam": True,
                    "readability": {
                        "score": 5,
                        "level": "средний"
                    }
                },
                "details": {
                    "spelling_details": "",
                    "grammar_details": "",
                    "spam_details": "Обнаружены повторы текста",
                    "readability_details": "Средний уровень читабельности"
                }
            }
    except Exception as e:
        logger.error(f"Ошибка при проверке текста: {e}", exc_info=True)
        return {
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
            }
        }

# Проверка метрик поста
async def check_post_metrics(
    views: int,
    reactions: int,
    subscribers: int,
    forwards: int,
    channel_name: str,
    message_id: int, 
    message_text: str,
    message_url: str,
    settings: dict = None
) -> tuple[bool, list[str]]:
    """Проверяет метрики поста на соответствие требованиям канала"""
    issues = []
    
    # Устанавливаем минимальные значения
    min_views = max(1, round(subscribers * 0.1))  # Минимум 10% от подписчиков
    min_reactions = max(1, round(views * 0.06))   # Минимум 6% от просмотров
    min_forwards = max(1, round(views * 0.01))    # Минимум 1% от просмотров

    # Проверяем метрики
    if views < min_views:
        issues.append(
            f"Низкое количество просмотров: {views} (минимум {min_views}, 10% от подписчиков)"
        )
    
    if reactions < min_reactions:
        issues.append(
            f"Низкое количество реакций: {reactions} (минимум {min_reactions}, 6% от просмотров)"
        )
        
    if forwards < min_forwards:
        issues.append(
            f"Низкое количество пересылок: {forwards} (минимум {min_forwards}, 1% от просмотров)"
        )
    
    # Формируем подробный отчет
    metrics_ok = len(issues) == 0
    
    if not metrics_ok:
        logger.warning(
            f"Пост {message_url} не соответствует метрикам:\n"
            f"Канал: {channel_name}\n"
            f"Подписчиков: {subscribers}\n"
            f"Просмотров: {views}/{min_views} ({views/min_views*100:.1f}%)\n"
            f"Реакций: {reactions}/{min_reactions} ({reactions/min_reactions*100:.1f}%)\n"
            f"Пересылок: {forwards}/{min_forwards} ({forwards/min_forwards*100:.1f}%)\n"
            f"Проблемы:\n" + "\n".join(issues)
        )
    
    return metrics_ok, issues

# Проверка актуальности новости
async def check_news_actuality_internal(text: str, local_time: datetime, post_time: datetime) -> dict:
    """
    Внутренняя функция для проверки актуальности новости.
    
    Args:
        text (str): Текст новости
        local_time (datetime): Локальное время проверки
        post_time (datetime): Время публикации
        
    Returns:
        dict: Результат проверки
    """
    try:
        # Получаем новости через News API
        news_api_response = await get_news_by_text(text)
        
        sources = []
        if news_api_response.get("articles"):
            sources = [article["url"] for article in news_api_response["articles"][:3]]
        
        # Формируем промпт для GPT
        system_prompt = """Вы - эксперт по анализу новостного контента.
                        
                        При анализе учитывайте:
                        - Для новостей ДО 12:00 допустимы вчерашние события
                        - После 12:00 - только сегодняшние, кроме срочных
                        - Для срочных новостей (военные действия, важные заявления) - всегда актуально
                        - Для остальных - не старше 6 часов
                        
                        Если новость старше указанного времени, обязательно укажите примерную дату события."""
                        
        user_prompt = f"""Проанализируйте актуальность новости:
                        Текст: {text}
                        Локальное время: {local_time.strftime('%H:%M')}
                        Время публикации: {'после' if post_time.hour >= 12 else 'до'} 12:00
                        Найденные источники: {sources}
                        
                        Верните ответ в формате JSON:
                        {{
                            "is_actual": true/false,
                            "reason": "причина решения с указанием примерной даты события, если новость не актуальна",
                            "category": "срочная/обычная",
                            "importance_level": "высокая/средняя/низкая",
                            "sources": [источники],
                            "estimated_date": "примерная дата события в формате YYYY-MM-DD",
                            "days_difference": "разница в днях между событием и текущей датой"
                        }}"""
                        
        # Получаем ответ от GPT
        gpt_response = await get_gpt_response(system_prompt, user_prompt)
        
        # Парсим JSON-ответ
        result = json.loads(gpt_response)
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при проверке актуальности новости: {e}", exc_info=True)
        return {
            "is_actual": True,
            "reason": f"Ошибка при проверке: {str(e)}",
            "category": "обычная",
            "importance_level": "средняя",
            "sources": [],
            "estimated_date": None,
            "days_difference": None
        }

async def check_news_actuality(text: str, date: datetime) -> dict:
    """
    Проверяет актуальность новости через несколько источников и анализирует их через GPT
    
    Args:
        text: Текст новости
        date: Дата публикации
    """
    try:
        # 1. Получаем новости из всех источников
        news_data = await get_news_by_text(text[:100], days=7)
        
        # 2. Анализируем результаты через GPT
        analysis_prompt = f"""
        Проанализируйте новость и найденные источники:
        
        Новость: {text}
        Дата публикации: {date.strftime('%Y-%m-%d %H:%M')}
        
        Найденные источники:
        {json.dumps(news_data, ensure_ascii=False, indent=2)}
        
        На основе предоставленных источников определите:
        1. Актуальность новости
        2. Достоверность информации
        3. Категорию новости
        4. Важность события
        
        При анализе учитывайте:
        - Для новостей ДО 12:00 допустимы вчерашние события
        - После 12:00 - только сегодняшние, кроме срочных
        - Для срочных новостей (военные действия, важные заявления) - всегда актуально
        - Для остальных - не старше 6 часов
        
        Верните результат в формате JSON:
        {{
            "is_actual": bool,          // актуальна ли новость
            "reason": str,              // причина решения
            "news_type": str,           // тип новости (срочная/обычная/анонс)
            "importance_level": str,     // важность (высокая/средняя/низкая)
            "source_reliability": {{     // надежность источников
                "total_sources": int,    // общее количество источников
                "reliable_sources": int, // количество надежных источников
                "average_score": float   // средний балл надежности
            }},
            "time_relevance": {{        // временная релевантность
                "is_recent": bool,      // новость свежая
                "hours_ago": int,       // сколько часов прошло
                "matches_found": int    // сколько совпадений найдено
            }},
            "verification": {{          // проверка информации
                "is_verified": bool,    // информация подтверждена
                "verification_level": str, // уровень проверки
                "sources": [str]        // список источников
            }}
        }}"""
        
        result = await get_gpt_response(
            system_prompt="""Вы - эксперт по анализу новостного контента.
            
            При анализе учитывайте:
            1. Пересечение информации в разных источниках
            2. Авторитетность и надежность источников
            3. Временную релевантность
            4. Важность и срочность новости
            
            Для срочных новостей:
            - Проверяйте несколько источников
            - Учитывайте официальные заявления
            - Оценивайте общественную значимость
            
            Для обычных новостей:
            - Строго следите за временными рамками
            - Проверяйте актуальность информации
            - Оценивайте необходимость публикации""",
            user_prompt=analysis_prompt
        )
        
        return json.loads(result)

    except Exception as e:
        logger.error(f"Ошибка при проверке актуальности: {e}")
        return {
            "is_actual": False,
            "reason": "Ошибка при проверке",
            "news_type": "неопределен",
            "importance_level": "низкая",
            "source_reliability": {
                "total_sources": 0,
                "reliable_sources": 0,
                "average_score": 0
            },
            "time_relevance": {
                "is_recent": False,
                "hours_ago": 0,
                "matches_found": 0
            },
            "verification": {
                "is_verified": False,
                "verification_level": "не проверено",
                "sources": []
            }
        }

async def check_content_moderation(text: str) -> dict:
    """Проверяет контент на наличие ошибок"""
    try:
        client = OpenAI(api_key=CONFIG["OPENAI_API_KEY"])
        
        system_prompt = """Проверьте текст на следующие проблемы:
        1. Орфографические и грамматические ошибки
        2. Спам и повторяющийся контент
        3. Читабельность текста (оцените по шкале от 1 до 10)
        
        Верните результат строго в формате JSON:
        {
            "has_errors": boolean,
            "errors": "описание найденных проблем",
            "categories": {
                "spelling": boolean,
                "grammar": boolean,
                "spam": boolean,
                "readability": {
                    "score": number,
                    "level": string
                }
            },
            "details": {
                "spelling_details": "найденные орфографические ошибки",
                "grammar_details": "найденные грамматические ошибки",
                "spam_details": "найденные повторы",
                "readability_details": "анализ читабельности"
            }
        }"""

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
        )
        
        result = response.choices[0].message.content
        if isinstance(result, str):
            result = json.loads(result)
            
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при проверке контента: {e}", exc_info=True)
        return {
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
