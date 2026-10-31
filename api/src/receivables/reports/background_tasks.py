"""Ejecuta un reporte en background y notifica al usuario cuando termina."""

import uuid

from fastapi import HTTPException

from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from app_platform.notifications.services.notification_service import NotificationService
from app_platform.schema_manager.services.dml_service import DmlService
from core.config.logger import logger
from core.database.database import db
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.reports.repository.report_execution_repository import (
    ReportExecutionRepository,
)
from receivables.reports.repository.report_repository import ReportRepository
from receivables.reports.schemas.report_schemas import ReportExecuteRequest
from receivables.reports.services.report_service import ReportService


async def execute_and_notify(
    report_id: uuid.UUID,
    organization_id: uuid.UUID,
    request: ReportExecuteRequest,
    user_id: uuid.UUID,
) -> None:
    # Sesión propia: la de la request ya hizo commit+close antes de que este task
    # corriera (FastAPI cierra las dependencias `yield` antes de ejecutar
    # BackgroundTasks). Ver el mismo comentario en portfolios/background_tasks.py.
    logger.info(
        "[report] background task iniciado | report=%s org=%s",
        report_id,
        organization_id,
    )
    try:
        async with db.get_session() as session:
            service = ReportService(
                report_repo=ReportRepository(session),
                execution_repo=ReportExecutionRepository(session),
                dml_service=DmlService(session),
                portfolio_repo=PortfolioRepository(session),
            )
            notification_service = NotificationService(session)
            result = await service.execute(report_id, organization_id, request, user_id)
            await notification_service.create_notification(
                user_id=user_id,
                title="Reporte generado",
                body=f"El archivo '{result['file_name']}' está listo para descargar.",
                category=NotificationCategory.REPORT,
                notif_type=NotificationType.SUCCESS,
                link=f"/my-companies/reports?reportId={report_id}",
                details={
                    "report_id": str(report_id),
                    "file_name": result["file_name"],
                    "document_id": (
                        str(result["document_id"]) if result["document_id"] else None
                    ),
                    "rows": result["rows"],
                },
            )
        logger.info(
            "[report] completado | report=%s filas=%d", report_id, result["rows"]
        )
    except HTTPException as exc:
        logger.error(
            "[report] error al ejecutar | report=%s detalle=%s", report_id, exc.detail
        )
        async with db.get_session() as session:
            await NotificationService(session).create_notification(
                user_id=user_id,
                title="Error al generar reporte",
                body="No fue posible generar el reporte. Intenta de nuevo.",
                category=NotificationCategory.REPORT,
                notif_type=NotificationType.ERROR,
                link=f"/my-companies/reports?reportId={report_id}",
            )
    except Exception:
        logger.exception("[report] error inesperado | report=%s", report_id)
        async with db.get_session() as session:
            await NotificationService(session).create_notification(
                user_id=user_id,
                title="Error al generar reporte",
                body="No fue posible generar el reporte. Intenta de nuevo.",
                category=NotificationCategory.REPORT,
                notif_type=NotificationType.ERROR,
                link=f"/my-companies/reports?reportId={report_id}",
            )
