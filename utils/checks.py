import re
import json
import logging
import requests
from openai import OpenAI
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple
import aiohttp
from .config import CONFIG
import asyncio
from utils.logging import setup_logger
from .notifications import notify_admins

# Настройка логирования
logger = setup_logger()

# Проверка орфографии и содержания
async def check_spelling(text: str, api_key: str) -> dict:
    """Проверяет текст на ошибки и читабельность"""
    try:
        # Проверяем входные данные
        if not text or not text.strip():
            return {
                "has_errors": False,
                "categories": {
                    "spelling": False,
                    "grammar": False,
                    "readability": {
                        "score": 7,
                        "level": "легкий"
                    }
                },
                "details": {
                    "spelling_details": "",
                    "grammar_details": "",
                    "readability_details": ""
                },
                "improvements": {
                    "corrections": [],
                    "structure": [],
                    "readability": [],
                    "engagement": []
                },
                "moderation_decision": "/true_go"
            }
            
        client = OpenAI(api_key=api_key)

        system_prompt = """Вы – профессиональный корректор русского языка.

Проанализируйте текст и верните ответ в формате JSON.
Ваш ответ ДОЛЖЕН быть валидным JSON-объектом.

ВАЖНО: Отмечайте ТОЛЬКО РЕАЛЬНЫЕ ошибки!
Если вы не уверены на 100% что это ошибка - НЕ отмечайте её.
НЕ ПРИДУМЫВАЙТЕ ошибки там, где их нет.

СТРОГО ИГНОРИРУЙТЕ (не считать ошибками):
1. Правильные слова и формы:
   - Все правильные формы глаголов ("наглотался", "сделать")
   - Все падежные формы ("сбора", "влаги")
   - Правильные формы множественного числа
   - Правильные окончания прилагательных

2. Имена собственные:
   - Названия городов и мест ("Гатчина", "Старая Деревня")
   - Имена, фамилии, отчества
   - Названия организаций

3. Специальные элементы:
   - Аббревиатуры (ЖКХ, ТЭК, МЧС)
   - Числа и единицы измерения (-5°С, +10%)
   - Знаки препинания в конце слов
   - Эмодзи и спецсимволы
   - Ссылки и URL
   - Форматирование текста (**, __, ~~)

Отмечать ТОЛЬКО явные ошибки:
1. Орфографические:
   - Пропущенные буквы ("троллейбус" → "тролейбус")
   - Неправильное написание слов
   - Явные опечатки

2. Грамматические:
   - Обрыв слова ("сделат" вместо "сделать")
   - Неверное согласование
   - Неправильное управление

Если найдены ЛЮБЫЕ ошибки, предложите конкретные рекомендации по улучшению поста:
1. Исправление найденных ошибок
2. Улучшение структуры текста
3. Повышение читабельности
4. Усиление вовлеченности аудитории

Верните JSON-объект в следующем формате:
{
    "has_errors": boolean,
    "categories": {
        "spelling": boolean,
        "grammar": boolean,
        "readability": {
            "score": number,
            "level": "легкий" | "средний" | "сложный"
        }
    },
    "details": {
        "spelling_details": [список ТОЛЬКО РЕАЛЬНЫХ орфографических ошибок],
        "grammar_details": [список ТОЛЬКО РЕАЛЬНЫХ грамматических ошибок],
        "readability_details": "анализ читабельности"
    },
    "improvements": {
        "corrections": [список исправлений ошибок],
        "structure": [рекомендации по структуре],
        "readability": [советы по улучшению читабельности],
        "engagement": [идеи для повышения вовлеченности]
    },
    "moderation_decision": "/true_go" | "/false_no"
}

Решение по модерации:
Если читабельность ≥7:
  - Игнорируем все ошибки (орфографические и грамматические)
  - Всегда возвращаем "/true_go"
Если читабельность <7:
  - Проверяем все ошибки (орфографические и грамматические)
  - Если есть ошибки → "/false_no"
  - Если нет ошибок → "/true_go"
"""

        response = client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0,
            response_format={ "type": "json_object" }
        )
        
        result = response.choices[0].message.content
        try:
            # Очищаем от markdown-форматирования
            if result.startswith('```json'):
                result = result[7:-3]
            
            parsed_result = json.loads(result.strip())
            
            # Всегда показываем найденные ошибки в уведомлении
            has_grammar_errors = parsed_result["categories"]["grammar"]
            has_spelling_errors = parsed_result["categories"]["spelling"]
            readability_score = parsed_result["categories"]["readability"]["score"]
            
            # Устанавливаем has_errors в True, если есть любые ошибки (для отображения)
            parsed_result["has_errors"] = has_grammar_errors or has_spelling_errors
            
            # Решение о модерации принимаем по новой логике
            if readability_score >= 7:
                # При хорошей читабельности игнорируем все ошибки
                parsed_result["moderation_decision"] = "/true_go"
            else:
                # При плохой читабельности смотрим на все ошибки
                parsed_result["moderation_decision"] = "/true_go" if not (has_grammar_errors or has_spelling_errors) else "/false_no"
            
            # Для обратной совместимости
            parsed_result["decision"] = parsed_result["moderation_decision"]
            
            return parsed_result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа: {result}")
            logger.error(f"Детали ошибки: {str(e)}")
            return {
                "has_errors": False,
                "categories": {
                    "spelling": False,
                    "grammar": False,
                    "readability": {
                        "score": 7,
                        "level": "легкий"
                    }
                },
                "details": {
                    "spelling_details": "",
                    "grammar_details": "",
                    "readability_details": ""
                },
                "improvements": {
                    "corrections": [],
                    "structure": [],
                    "readability": [],
                    "engagement": []
                },
                "moderation_decision": "/true_go",
                "decision": "/true_go"
            }
            
    except Exception as e:
        logger.error(f"Ошибка при проверке текста: {e}", exc_info=True)
        return {
            "has_errors": False,
            "categories": {
                "spelling": False,
                "grammar": False,
                "readability": {
                    "score": 7,
                    "level": "легкий"
                }
            },
            "details": {
                "spelling_details": "",
                "grammar_details": "",
                "readability_details": ""
            },
            "improvements": {
                "corrections": [],
                "structure": [],
                "readability": [],
                "engagement": []
            },
            "moderation_decision": "/true_go",
            "decision": "/true_go"
        }

async def get_post_metrics(client, chat_id: int, message_id: int) -> Dict[str, int]:
    """Получает метрики поста через Telethon"""
    try:
        # Получаем сообщение
        message = await client.get_messages(int(chat_id), ids=message_id)
        if not message:
            logger.error(f"Сообщение {message_id} не найдено в канале {chat_id}")
            return None
            
        # Получаем метрики
        views = message.views if hasattr(message, 'views') else 0
        forwards = message.forwards if hasattr(message, 'forwards') else 0
        
        # Безопасное получение реакций
        reactions = 0
        if hasattr(message, 'reactions') and message.reactions and hasattr(message.reactions, 'results'):
            reactions = sum(reaction.count for reaction in message.reactions.results)
        
        logger.info(f"Собраны метрики для поста {message_id}:")
        logger.info(f"- Просмотры: {views}")
        logger.info(f"- Реакции: {reactions}")
        logger.info(f"- Пересылки: {forwards}")
        
        return {
            "views": views,
            "reactions": reactions,
            "forwards": forwards
        }
    except Exception as e:
        logger.error(f"Ошибка при получении метрик: {e}", exc_info=True)
        return None

async def analyze_metrics_with_gpt(metrics_data: dict, api_key: str) -> dict:
    """Анализирует метрики поста через GPT."""
    try:
        import openai
        import json
        
        openai.api_key = api_key
        
        # Подготавливаем данные для анализа
        subscribers = metrics_data["channel_info"]["subscribers"]
        views = metrics_data["metrics"]["views"]
        reactions = metrics_data["metrics"]["reactions"]
        forwards = metrics_data["metrics"]["forwards"]
        
        # Рассчитываем минимальные требования
        min_views = max(1, int(subscribers * 0.1))  # 10% от подписчиков
        min_reactions = max(1, int(views * 0.06))   # 6% от просмотров
        min_forwards = max(1, int(views * 0.15))    # 15% от просмотров
        
        # Рассчитываем проценты выполнения
        views_percent = (views / min_views * 100) if min_views > 0 else 0
        reactions_percent = (reactions / min_reactions * 100) if min_reactions > 0 else 0
        forwards_percent = (forwards / min_forwards * 100) if min_forwards > 0 else 0
        
        # Формируем список проблем
        issues = []
        if views < min_views:
            issues.append(f"Недостаточно просмотров (требуется минимум {min_views:,})")
        if reactions < min_reactions:
            issues.append(f"Мало реакций (требуется минимум {min_reactions:,})")
        if forwards < min_forwards:
            issues.append(f"Мало пересылок (требуется минимум {min_forwards:,})")
        
        # Формируем результат анализа
        analysis_result = {
            "metrics_ok": len(issues) == 0,
            "metrics": {
                "views": {
                    "current": views,
                    "required": min_views,
                    "percent": views_percent
                },
                "reactions": {
                    "current": reactions,
                    "required": min_reactions,
                    "percent": reactions_percent
                },
                "forwards": {
                    "current": forwards,
                    "required": min_forwards,
                    "percent": forwards_percent
                }
            },
            "issues": issues
        }
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"Ошибка при анализе метрик через GPT: {e}")
        return None

async def check_post_metrics(views: int, reactions: int, subscribers: int, forwards: int, 
                           channel_name: str, message_id: int, message_text: str, 
                           message_url: str, api_key: str) -> tuple[bool, list[str], dict]:
    """Проверяет метрики поста через GPT"""
    try:
        # Подготавливаем данные для анализа
        metrics_data = {
            "channel_info": {
                "name": channel_name,
                "subscribers": subscribers,
                "message_id": message_id,
                "message_url": message_url
            },
            "metrics": {
                "views": views,
                "reactions": reactions,
                "forwards": forwards
            },
            "norms": {
                "views_percent": 10,      # 10% от подписчиков
                "reactions_percent": 6,    # 6% от просмотров
                "forwards_percent": 15     # 15% от просмотров
            }
        }
        
        # Анализируем через GPT
        analysis = await analyze_metrics_with_gpt(metrics_data, api_key)
        if not analysis:
            return False, ["Ошибка анализа метрик"], {}
            
        # Формируем данные для уведомления
        notification_data = {
            "channel_name": channel_name,
            "message_id": message_id,
            "message_url": message_url,
            "message_text": message_text[:500] + "..." if len(message_text) > 500 else message_text,
            "metrics": analysis["metrics"],
            "issues": analysis["issues"],
            "is_ok": analysis["metrics_ok"],
            "summary": analysis["summary"],
            "recommendations": analysis["recommendations"]
        }
        
        return analysis["metrics_ok"], analysis["issues"], notification_data
        
    except Exception as e:
        logger.error(f"Ошибка при проверке метрик: {e}", exc_info=True)
        return False, [f"Ошибка проверки: {str(e)}"], {}

async def analyze_post_with_gpt(metrics_data: dict, api_key: str) -> dict:
    """Анализирует метрики поста через GPT (Этап 2 - через 24 часа)"""
    try:
        client = OpenAI(api_key=api_key)
        
        system_prompt = """Ты — эксперт по анализу контента в Telegram. 
        Проанализируй метрики поста и верни результат строго в формате JSON:
        {
            "success": boolean,
            "score": число от 1 до 10,
            "analysis": {
                "views": {
                    "status": "ok/warning/error",
                    "score": число от 1 до 10,
                    "details": "анализ просмотров"
                },
                "reactions": {
                    "status": "ok/warning/error",
                    "score": число от 1 до 10,
                    "details": "анализ реакций"
                },
                "forwards": {
                    "status": "ok/warning/error",
                    "score": число от 1 до 10,
                    "details": "анализ пересылок"
                }
            },
            "summary": {
                "short": "краткий вывод в одну строку",
                "detailed": "подробный анализ в 2-3 предложения"
            },
            "recommendations": [
                "список конкретных рекомендаций по улучшению"
            ]
        }"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(metrics_data, ensure_ascii=False)}
            ],
            temperature=0,
            response_format={ "type": "json_object" }
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Формируем уведомление
        notification = (
            f"📊 Анализ метрик\n\n"
            f"📈 Общая оценка: {result['score']}/10\n"
            f"💡 {result['summary']['short']}\n\n"
            f"📋 Подробный анализ:\n{result['summary']['detailed']}\n\n"
            f"📊 Метрики:\n"
            f"👁 Просмотры ({result['analysis']['views']['score']}/10): "
            f"{result['analysis']['views']['details']}\n"
            f"❤️ Реакции ({result['analysis']['reactions']['score']}/10): "
            f"{result['analysis']['reactions']['details']}\n"
            f"🔄 Пересылки ({result['analysis']['forwards']['score']}/10): "
            f"{result['analysis']['forwards']['details']}\n"
        )
        
        if not result["success"] and result["recommendations"]:
            notification += "\n💡 Рекомендации:\n"
            notification += "\n".join(f"• {rec}" for rec in result["recommendations"])
        
        result["notification"] = notification
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при анализе метрик: {e}")
        return None

async def check_post_metrics_later(client, bot, chat_id: int, message_id: int, 
                                 channel_name: str, subscribers: int, admin_ids: List[int],
                                 super_admin_id: int) -> None:
    """Запускает отложенную проверку метрик поста"""
    try:
        logger.info(f"Запуск отложенной проверки метрик для поста {message_id} в канале {chat_id}")
        
        # Ждем 30 секунд перед проверкой метрик
        logger.info(f"⏳ Ожидание 86400 секунд перед проверкой метрик")
        await asyncio.sleep(86400)  # 86400 секунд
        
        # Получаем метрики
        metrics = await get_post_metrics(client, chat_id, message_id)
        if not metrics:
            return
            
        # Подготавливаем данные для анализа
        metrics_data = {
            "channel_info": {
                "name": channel_name,
                "subscribers": subscribers
            },
            "metrics": {
                "views": metrics["views"],
                "reactions": metrics["reactions"],
                "forwards": metrics["forwards"]
            }
        }
        
        # Анализируем через GPT
        analysis = await analyze_metrics_with_gpt(metrics_data, CONFIG["OPENAI_API_KEY"])
        if not analysis:
            return
            
        # Если есть проблемы, отправляем уведомление через основную функцию в bot.py
        if not analysis["metrics_ok"]:
            message_url = f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
            notification = (
                f"⚠️ Анализ метрик поста\n\n"
                f"📊 Канал: {channel_name}\n"
                f"🔗 {message_url}\n\n"
                f"📈 Метрики:\n"
                f"👁 Просмотры: {analysis['metrics']['views']['current']}/{analysis['metrics']['views']['required']} "
                f"({analysis['metrics']['views']['percent']:.1f}%)\n"
                f"❤️ Реакции: {analysis['metrics']['reactions']['current']}/{analysis['metrics']['reactions']['required']} "
                f"({analysis['metrics']['reactions']['percent']:.1f}%)\n"
                f"🔄 Пересылки: {analysis['metrics']['forwards']['current']}/{analysis['metrics']['forwards']['required']} "
                f"({analysis['metrics']['forwards']['percent']:.1f}%)\n\n"
            )
            
            if analysis["issues"]:
                notification += f"❌ Проблемы:\n" + "\n".join(f"• {issue}" for issue in analysis["issues"])
            
            # Используем переданный экземпляр бота
            for admin_id in admin_ids:
                try:
                    await bot.send_message(admin_id, notification)
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке метрик: {e}", exc_info=True)

