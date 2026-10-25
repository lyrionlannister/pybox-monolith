"""Endpoint de carga masiva de cuotas (CSV/XLSX) para un portafolio."""

import uuid
from typing import Annotated

from fastapi import BackgroundTasks, HTTPException, Query, UploadFile, status

from core.config.api_router import APIRouter
from core.config.logger import logger
from core.security.constants.permissions import PORTFOLIO_UPLOAD_UPDATE
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import (
    require_org_admin,
    require_org_visibility,
)
from identity.organizations.dependencies import OrgServiceDep
from receivables.portfolios.dependencies import PortfolioServiceDep
from receivables.portfolios.installment_background_tasks import (
    installments_and_notify,
    uploading_installments,
)
from receivables.portfolios.utils.file_utils import validate_portfolio_file

router = APIRouter(prefix="/portfolios", tags=["Plan de cuotas"])


@router.post(
    "/upload-csv/installments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
    summary="Cargar plan de cuotas desde CSV/XLSX",
    description=(
        "Crea o actualiza cuotas de créditos ya existentes en el portafolio, "
        "identificados por número de crédito. Una fila marcada como pago total "
        "cierra las cuotas pendientes del crédito y lo desactiva."
    ),
)
async def upload_installments(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: CurrentSession,
    portfolio_service: PortfolioServiceDep,
    org_service: OrgServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> None:
    portfolio = await portfolio_service.get_by_id(portfolio_id)
    org_id_str = str(portfolio.organization_id)

    require_org_visibility(session, org_id_str, "Portafolio no encontrado")
    require_org_admin(session, org_id_str)
    if not session.is_global:
        org_entry = session.orgs.get(org_id_str)
        if org_entry and PORTFOLIO_UPLOAD_UPDATE not in org_entry.permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Sin permiso para cargar el plan de cuotas"
            )
    await org_service.ensure_verified(portfolio.organization_id)

    filename = validate_portfolio_file(file)

    if portfolio_id in uploading_installments:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Ya hay una carga de cuotas activa para este portafolio.",
        )

    file_bytes = await file.read()
    uploading_installments.add(portfolio_id)
    logger.info(
        "[installments] archivo leído | tamaño=%d bytes | portfolio=%s",
        len(file_bytes),
        portfolio_id,
    )

    background_tasks.add_task(
        installments_and_notify,
        file_bytes=file_bytes,
        filename=filename,
        portfolio_id=portfolio_id,
        organization_id=portfolio.organization_id,
        user_id=session.user_id,
    )
    return None
