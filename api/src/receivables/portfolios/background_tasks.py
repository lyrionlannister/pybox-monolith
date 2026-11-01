"""Procesa la carga masiva de portafolio en background y notifica al terminar."""

import uuid

from app_platform.countries.enums.country_enums import Nationality
from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from app_platform.notifications.services.notification_service import NotificationService
from core.cache.cache_service import cache_service
from core.config.logger import logger
from core.database.database import db
from core.sse.sse_emitter import sse_emitter
from receivables.portfolios.services.portfolio_csv_service import PortfolioCsvService

uploading_orgs: set[uuid.UUID] = set()

# Estas funciones corren vía BackgroundTasks, después de que la respuesta ya salió.
# FastAPI cierra las dependencias `yield` (incluida la sesión de BD de la request,
# que además hace su commit ahí) ANTES de ejecutar los background tasks, no después
# — es el orden que documenta FastAPI. Por eso cada una abre su PROPIA sesión con
# `db.get_session()` en vez de recibir un service ya armado con la sesión de la
# request: reusarla no lanza error (SQLAlchemy abre una transacción nueva sola),
# pero nadie vuelve a hacer commit sobre ella y los cambios se pierden en silencio.


async def process_and_notify(
    file_bytes: bytes,
    filename: str,
    organization_id: uuid.UUID,
    portfolio_name: str | None,
    country: Nationality | None,
    user_id: uuid.UUID,
) -> None:
    logger.info(
        "[portfolio] background task iniciado | org=%s nombre=%s",
        organization_id,
        portfolio_name,
    )

    await sse_emitter.emit(
        user_id,
        "job_progress",
        {
            "type": "portfolio_upload",
            "status": "started",
            "processed": 0,
            "total": 0,
        },
    )

    async def _progress(processed: int, total: int) -> None:
        await sse_emitter.emit(
            user_id,
            "job_progress",
            {
                "type": "portfolio_upload",
                "status": "processing",
                "processed": processed,
                "total": total,
            },
        )

    try:
        async with db.get_session() as session:
            service = PortfolioCsvService(session)
            notification_service = NotificationService(session)
            result = await service.process_csv(
                file_bytes=file_bytes,
                filename=filename,
                organization_id=organization_id,
                portfolio_name=portfolio_name,
                country=country,
                on_progress=_progress,
            )
            logger.info(
                "[portfolio] process_csv terminado | procesados=%d fallidos=%d",
                result.processed_rows,
                result.failed_rows,
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
                title="Portafolio listo",
                body=f"{result.processed_rows} registros procesados{failed_note}.",
                category=NotificationCategory.PORTFOLIO,
                notif_type=notif_type,
                link=(
                    f"/my-companies/portfolios?org={organization_id}"
                    f"&portfolioId={result.portfolio_id}"
                ),
                details={
                    "creditos": result.creditos,
                    "titulares": result.titulares,
                    "codeudores": result.codeudores,
                    "clientes_unicos": result.clientes_unicos,
                },
            )
        await cache_service.bust(f"portfolio:stats:{result.portfolio_id}")
        logger.info("[portfolio] notificación enviada al usuario %s", user_id)
    except Exception:
        logger.exception(
            "[portfolio] error en background task | org=%s", organization_id
        )
    finally:
        uploading_orgs.discard(organization_id)
        logger.info("[portfolio] org liberada del set activo | org=%s", organization_id)


async def append_and_notify(
    file_bytes: bytes,
    filename: str,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    logger.info(
        "[portfolio-append] background task iniciado | portfolio=%s", portfolio_id
    )

    await sse_emitter.emit(
        user_id,
        "job_progress",
        {
            "type": "portfolio_append",
            "status": "started",
            "processed": 0,
            "total": 0,
        },
    )

    async def _progress(processed: int, total: int) -> None:
        await sse_emitter.emit(
            user_id,
            "job_progress",
            {
                "type": "portfolio_append",
                "status": "processing",
                "processed": processed,
                "total": total,
            },
        )

    try:
        async with db.get_session() as session:
            service = PortfolioCsvService(session)
            notification_service = NotificationService(session)
            result = await service.append_csv(
                portfolio_id, file_bytes, filename, on_progress=_progress
            )
            logger.info(
                "[portfolio-append] terminado | procesados=%d fallidos=%d",
                result.processed_rows,
                result.failed_rows,
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
                title="Datos agregados al portafolio",
                body=f"{result.processed_rows} registros procesados{failed_note}.",
                category=NotificationCategory.PORTFOLIO,
                notif_type=notif_type,
                link=(
                    f"/my-companies/portfolios?org={organization_id}"
                    f"&portfolioId={portfolio_id}"
                ),
                details={
                    "creditos": result.creditos,
                    "titulares": result.titulares,
                    "codeudores": result.codeudores,
                    "clientes_unicos": result.clientes_unicos,
                },
            )
        await cache_service.bust(f"portfolio:stats:{portfolio_id}")
    except Exception:
        logger.exception("[portfolio-append] error | portfolio=%s", portfolio_id)
    finally:
        uploading_orgs.discard(organization_id)


async def update_and_notify(
    file_bytes: bytes,
    filename: str,
    portfolio_id: uuid.UUID,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    logger.info(
        "[portfolio-update] background task iniciado | portfolio=%s", portfolio_id
    )

    await sse_emitter.emit(
        user_id,
        "job_progress",
        {
            "type": "portfolio_update",
            "status": "started",
            "processed": 0,
            "total": 0,
        },
    )

    async def _progress(processed: int, total: int) -> None:
        await sse_emitter.emit(
            user_id,
            "job_progress",
            {
                "type": "portfolio_update",
                "status": "processing",
                "processed": processed,
                "total": total,
            },
        )

    try:
        async with db.get_session() as session:
            service = PortfolioCsvService(session)
            notification_service = NotificationService(session)
            result = await service.update_csv(
                portfolio_id, file_bytes, filename, on_progress=_progress
            )
            logger.info(
                "[portfolio-update] terminado | procesados=%d fallidos=%d",
                result.processed_rows,
                result.failed_rows,
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
                title="Portafolio actualizado",
                body=f"{result.processed_rows} registros procesados{failed_note}.",
                category=NotificationCategory.PORTFOLIO,
                notif_type=notif_type,
                link=(
                    f"/my-companies/portfolios?org={organization_id}"
                    f"&portfolioId={portfolio_id}"
                ),
                details={
                    "creditos": result.creditos,
                    "titulares": result.titulares,
                    "codeudores": result.codeudores,
                    "clientes_unicos": result.clientes_unicos,
                },
            )
        await cache_service.bust(f"portfolio:stats:{portfolio_id}")
    except Exception:
        logger.exception("[portfolio-update] error | portfolio=%s", portfolio_id)
    finally:
        uploading_orgs.discard(organization_id)
