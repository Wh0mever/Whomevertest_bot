import logging
from .config import CONFIG

logger = logging.getLogger(__name__)

async def notify_admins(channel_data, message_text, bot, super_admin_id, original_message=None):
    """Отправляет уведомление админам канала"""
    try:
        # Проверяем настройки уведомлений
        if not CONFIG["NOTIFICATIONS"]["NOTIFY_ON_ERRORS"]:
            logger.info("Уведомления об ошибках отключены в настройках")
            return
            
        admin_ids = channel_data.get('admins', [])
        logger.info(f"Отправка уведомлений админам: {admin_ids}")
        
        if not admin_ids:
            logger.warning("Нет администраторов для уведомления")
            return

        # Отправляем уведомление админам канала
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, message_text)
                logger.info(f"Уведомление отправлено админу {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")

        # Отправляем копию супер-админу только если:
        # 1. Он не является админом канала
        # 2. Включена настройка SEND_TO_OWNER
        if (super_admin_id not in admin_ids and 
            CONFIG["NOTIFICATIONS"]["SEND_TO_OWNER"]):
            try:
                super_admin_message = (
                    f"[Копия уведомления]\n"
                    f"👤 Канал администрируется: {', '.join(str(admin) for admin in admin_ids)}\n\n"
                    f"{message_text}"
                )
                await bot.send_message(super_admin_id, super_admin_message)
                logger.info("Уведомление продублировано супер-админу")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления супер-админу: {e}")

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}") 