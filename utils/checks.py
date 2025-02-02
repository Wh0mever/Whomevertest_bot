import json
import logging
from openai import OpenAI
from datetime import datetime, timedelta
from typing import Dict, Any, List
import asyncio
from .config import CONFIG

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
) -> Dict[str, Any]:
    """Проверяет метрики поста на соответствие требованиям канала"""
    issues = []
    
    # Используем настройки канала, если они есть, иначе берем из общей конфигурации
    if settings and 'metrics' in settings:
        min_views_percent = settings['metrics'].get('views_percent', CONFIG['POST_SETTINGS']['MIN_VIEWS_PERCENT'])
        min_reactions_percent = settings['metrics'].get('reactions_percent', CONFIG['POST_SETTINGS']['MIN_REACTIONS_PERCENT'])
        min_forwards_percent = settings['metrics'].get('forwards_percent', CONFIG['POST_SETTINGS']['MIN_FORWARDS_PERCENT'])
    else:
        min_views_percent = CONFIG['POST_SETTINGS'].get('MIN_VIEWS_PERCENT', 10.0)
        min_reactions_percent = CONFIG['POST_SETTINGS'].get('MIN_REACTIONS_PERCENT', 6.0)
        min_forwards_percent = CONFIG['POST_SETTINGS'].get('MIN_FORWARDS_PERCENT', 15.0)
    
    # Устанавливаем минимальные значения
    min_views = max(1, round(subscribers * (min_views_percent / 100)))  # Минимум X% от подписчиков
    min_reactions = max(1, round(views * (min_reactions_percent / 100)))   # Минимум Y% от просмотров
    min_forwards = max(1, round(views * (min_forwards_percent / 100)))    # Минимум Z% от просмотров

    # Проверяем метрики
    if views < min_views:
        issues.append(
            f"Низкое количество просмотров: {views} (минимум {min_views}, {min_views_percent}% от подписчиков)"
        )
    
    if reactions < min_reactions:
        issues.append(
            f"Низкое количество реакций: {reactions} (минимум {min_reactions}, {min_reactions_percent}% от просмотров)"
        )
        
    if forwards < min_forwards:
        issues.append(
            f"Низкое количество пересылок: {forwards} (минимум {min_forwards}, {min_forwards_percent}% от просмотров)"
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
    
    return {
        "passed": metrics_ok,
        "details": {
            "metrics": {
                "views": {
                    "current": views,
                    "required": min_views,
                    "percent": (views/min_views*100),
                    "passed": views >= min_views
                },
                "reactions": {
                    "current": reactions,
                    "required": min_reactions,
                    "percent": (reactions/min_reactions*100),
                    "passed": reactions >= min_reactions
                },
                "forwards": {
                    "current": forwards,
                    "required": min_forwards,
                    "percent": (forwards/min_forwards*100),
                    "passed": forwards >= min_forwards
                }
            },
            "issues": issues
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
