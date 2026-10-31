"""Procesa la carga masiva de cuotas en background y notifica al terminar."""

import uuid

from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from app_platform.notifications.services.notification_service import NotificationService
from core.config.logger import logger
from core.database.database import db
from receivables.portfolios.services.installment_csv_service import (
    InstallmentCsvService,
)

uploading_installments: set[uuid.UUID] = set()


async def installments_and_notify(
    file_bytes: bytes,
    filename: str,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    # Sesión propia: la de la request ya hizo commit+close antes de que este task
    # corriera (FastAPI cierra las dependencias `yield` antes de ejecutar
    # BackgroundTasks). Ver el mismo comentario en background_tasks.py.
    logger.info("[installments] background task iniciado | portfolio=%s", portfolio_id)
    try:
        async with db.get_session() as session:
            service = InstallmentCsvService(session)
            notification_service = NotificationService(session)
            result = await service.upload(portfolio_id, file_bytes, filename)
            logger.info(
                "[installments] terminado | procesados=%d fallidos=%d creadas=%d "
                "actualizadas=%d liquidados=%d",
                result.processed_rows,
                result.failed_rows,
                result.cuotas_creadas,
                result.cuotas_actualizadas,
                result.creditos_liquidados,
            )

            failed_note = (
                f", {result.failed_rows} fallidos" if result.failed_rows > 0 else ""
            )
            notif_type = (
                NotificationType.ERROR
                if result.failed_rows == result.total_rows
                else (
                    NotificationType.WARNING
                    if result.failed_rows > 0
                    else NotificationType.SUCCESS
                )
            )
            await notification_service.create_notification(
                user_id=user_id,
                title="Plan de cuotas cargado",
                body=(
                    f"{result.cuotas_creadas} cuotas nuevas, "
                    f"{result.cuotas_actualizadas} actualizadas, "
                    f"{result.creditos_liquidados} créditos "
                    f"liquidados{failed_note}."
                ),
                category=NotificationCategory.PORTFOLIO,
                notif_type=notif_type,
                link=(
                    f"/my-companies/portfolios?org={organization_id}"
                    f"&portfolioId={portfolio_id}"
                ),
                details={
                    "cuotasCreadas": result.cuotas_creadas,
                    "cuotasActualizadas": result.cuotas_actualizadas,
                    "creditosLiquidados": result.creditos_liquidados,
                },
            )
    except Exception:
        logger.exception("[installments] error | portfolio=%s", portfolio_id)
    finally:
        uploading_installments.discard(portfolio_id)
