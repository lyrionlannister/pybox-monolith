"""Endpoints de portafolios: alta, edición, carga masiva y estadísticas."""

import uuid
from typing import Annotated

from fastapi import BackgroundTasks, Depends, HTTPException, Query, UploadFile, status

from app_platform.countries.enums.country_enums import Nationality
from app_platform.dashboard.schemas.dashboard_schemas import (
    MonthlySendsResponse,
    SendStatusCountsResponse,
)
from app_platform.documents.utils.upload_limits import read_within_limit
from core.config.api_router import APIRouter
from core.config.logger import logger
from core.security.constants.permissions import (
    ORG_PORTFOLIOS,
    PORTFOLIO_UPLOAD_NEW,
    PORTFOLIO_UPLOAD_UPDATE,
)
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import (
    require_admin_or_org,
    require_global_admin,
    require_org_admin,
    require_org_visibility,
    require_permission,
    require_portfolio_access,
)
from core.security.rate_limit import rate_limit
from identity.onboarding.dependencies import CurrentOrg
from identity.organizations.dependencies import OrgServiceDep
from receivables.portfolios.constants.portfolio_csv_constants import (
    MAX_CSV_UPLOAD_BYTES,
)
from receivables.portfolios.background_tasks import (
    append_and_notify,
    process_and_notify,
    update_and_notify,
    uploading_orgs,
)
from receivables.portfolios.dependencies import (
    PortfolioServiceDep,
    PortfolioUserAccessServiceDep,
)
from receivables.portfolios.models.portfolio_daily_counter_config_model import (
    PortfolioDailyCounterConfigModel,
)
from receivables.portfolios.models.portfolio_model import PortfolioModel
from receivables.portfolios.schemas.portfolio_schemas import (
    PortfolioAccessEntry,
    PortfolioAccessReplaceRequest,
    PortfolioDailyCounterConfigResponse,
    PortfolioDailyCounterConfigSyncRequest,
    PortfolioDailyCounterConfigUpdateRequest,
    PortfolioResponse,
    PortfolioStatsResponse,
    PortfolioUpdateRequest,
)
from receivables.portfolios.utils.file_utils import validate_portfolio_file

router = APIRouter(prefix="/portfolios", tags=["Portafolios"])

_csv_rate_limit = Depends(rate_limit("csv-upload", max_attempts=10, window_seconds=60))


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get(
    "/", response_model=list[PortfolioResponse], summary="Listar portafolios accesibles"
)
async def list_portfolios(
    session: CurrentSession,
    service: PortfolioServiceDep,
    organization_id: Annotated[uuid.UUID | None, Query(alias="organizationId")] = None,
    is_active: Annotated[bool | None, Query(alias="isActive")] = None,
) -> list[PortfolioModel]:
    selected_org_id = organization_id

    if not session.is_global:
        if selected_org_id is None:
            if not session.orgs:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "El usuario no pertenece a ninguna organización",
                )
            selected_org_id = uuid.UUID(next(iter(session.orgs)))
        require_admin_or_org(ORG_PORTFOLIOS, session, str(selected_org_id))

    return await service.list_accessible_portfolios(session, selected_org_id, is_active)


@router.post(
    "/upload-csv",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
    summary="Crear portafolio desde CSV/XLSX",
    dependencies=[_csv_rate_limit],
)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: CurrentSession,
    org: CurrentOrg,
    org_service: OrgServiceDep,
    portfolio_name: Annotated[str | None, Query(alias="portfolioName")] = None,
    organization_id: Annotated[uuid.UUID | None, Query(alias="organizationId")] = None,
    country_id: Annotated[Nationality | None, Query(alias="countryId")] = None,
) -> None:
    logger.info(
        "[portfolio] upload-csv recibido | organization_id=%s portfolio_name=%s",
        organization_id,
        portfolio_name,
    )

    selected_org_id = organization_id or (org.id if org is not None else None)
    if selected_org_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "El usuario no pertenece a ninguna organización"
        )
    require_permission(PORTFOLIO_UPLOAD_NEW, session, str(selected_org_id))
    await org_service.ensure_verified(selected_org_id)

    filename = validate_portfolio_file(file)

    if selected_org_id in uploading_orgs:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Ya estás cargando un portfolio, intenta más tarde.",
        )

    file_bytes = await read_within_limit(file, MAX_CSV_UPLOAD_BYTES)
    uploading_orgs.add(selected_org_id)
    logger.info(
        "[portfolio] archivo leído | tamaño=%d bytes | org=%s",
        len(file_bytes),
        selected_org_id,
    )

    background_tasks.add_task(
        process_and_notify,
        file_bytes=file_bytes,
        filename=filename,
        organization_id=selected_org_id,
        portfolio_name=(portfolio_name or "").strip() or None,
        country=country_id,
        user_id=session.user_id,
    )
    return None


@router.post(
    "/upload-csv/append",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
    summary="Agregar registros al portafolio desde CSV/XLSX",
    dependencies=[_csv_rate_limit],
)
async def upload_csv_append(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    session: CurrentSession,
    portfolio_service: PortfolioServiceDep,
    org_service: OrgServiceDep,
    access_service: PortfolioUserAccessServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> None:
    portfolio = await portfolio_service.get_by_id(portfolio_id)
    org_id_str = str(portfolio.organization_id)

    require_org_visibility(session, org_id_str, "Portafolio no encontrado")
    require_permission(PORTFOLIO_UPLOAD_UPDATE, session, org_id_str)
    # Además del permiso: un miembro con acceso restringido solo toca sus portafolios.
    await require_portfolio_access(
        session, org_id_str, portfolio_id, access_service.check_access
    )
    await org_service.ensure_verified(portfolio.organization_id)

    filename = validate_portfolio_file(file)

    if portfolio.organization_id in uploading_orgs:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Ya hay una carga activa para esta organización.",
        )

    file_bytes = await read_within_limit(file, MAX_CSV_UPLOAD_BYTES)
    uploading_orgs.add(portfolio.organization_id)

    background_tasks.add_task(
        append_and_notify,
        file_bytes=file_bytes,
        filename=filename,
        portfolio_id=portfolio_id,
        organization_id=portfolio.organization_id,
        user_id=session.user_id,
    )
    return None


@router.post(
    "/upload-csv/update",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
    summary="Actualizar portafolio existente desde CSV/XLSX",
    dependencies=[_csv_rate_limit],
)
async def upload_csv_update(
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
                status.HTTP_403_FORBIDDEN, "Sin permiso para actualizar el portafolio"
            )
    await org_service.ensure_verified(portfolio.organization_id)

    filename = validate_portfolio_file(file)

    if portfolio.organization_id in uploading_orgs:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Ya hay una carga activa para esta organización.",
        )

    file_bytes = await read_within_limit(file, MAX_CSV_UPLOAD_BYTES)
    uploading_orgs.add(portfolio.organization_id)

    background_tasks.add_task(
        update_and_notify,
        file_bytes=file_bytes,
        filename=filename,
        portfolio_id=portfolio_id,
        organization_id=portfolio.organization_id,
        user_id=session.user_id,
    )
    return None


@router.get(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="Obtener portafolio por ID",
)
async def get_portfolio(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> PortfolioModel:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    await require_portfolio_access(
        session,
        str(portfolio.organization_id),
        portfolio_id,
        access_service.check_access,
    )
    return portfolio


@router.patch(
    "/{portfolio_id}", response_model=PortfolioResponse, summary="Actualizar portafolio"
)
async def update_portfolio(
    portfolio_id: uuid.UUID,
    data: PortfolioUpdateRequest,
    session: CurrentSession,
    service: PortfolioServiceDep,
) -> PortfolioModel:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    return await service.update_portfolio(portfolio_id, data)


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar portafolio",
)
async def delete_portfolio(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
) -> None:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    await service.delete_portfolio(portfolio_id)


@router.post(
    "/{portfolio_id}/restore",
    status_code=status.HTTP_200_OK,
    response_model=PortfolioResponse,
    summary="Restaurar portafolio",
    description="Solo administradores globales.",
)
async def restore_portfolio(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
) -> PortfolioModel:
    require_global_admin(session)
    return await service.restore_portfolio(portfolio_id)


@router.get(
    "/{portfolio_id}/stats",
    response_model=PortfolioStatsResponse,
    summary="Obtener estadísticas del portafolio",
)
async def get_portfolio_stats(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> PortfolioStatsResponse:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    await require_portfolio_access(
        session,
        str(portfolio.organization_id),
        portfolio_id,
        access_service.check_access,
    )
    return await service.get_stats(portfolio_id)


@router.get(
    "/{portfolio_id}/monthly-sends",
    response_model=MonthlySendsResponse,
    summary="Envíos mensuales de una campaña del portafolio en los últimos 12 meses",
)
async def get_portfolio_monthly_sends(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
    campaign_id: Annotated[uuid.UUID, Query(alias="campaignId")],
) -> MonthlySendsResponse:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    await require_portfolio_access(
        session,
        str(portfolio.organization_id),
        portfolio_id,
        access_service.check_access,
    )
    return await service.get_monthly_sends(portfolio_id, campaign_id)


@router.get(
    "/{portfolio_id}/send-status-counts",
    response_model=SendStatusCountsResponse,
    summary="Conteo de contactos por status de envío en el portafolio",
)
async def get_portfolio_send_status_counts(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> SendStatusCountsResponse:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    await require_portfolio_access(
        session,
        str(portfolio.organization_id),
        portfolio_id,
        access_service.check_access,
    )
    return await service.get_send_status_counts(portfolio_id)


@router.get(
    "/{portfolio_id}/access",
    response_model=list[PortfolioAccessEntry],
    summary="Listar usuarios con acceso al portafolio",
)
async def list_portfolio_access(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> list:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    return await access_service.list_portfolio_access(portfolio_id)


@router.put(
    "/{portfolio_id}/access",
    response_model=list[PortfolioAccessEntry],
    summary="Reemplazar lista de acceso al portafolio",
)
async def replace_portfolio_access(
    portfolio_id: uuid.UUID,
    body: PortfolioAccessReplaceRequest,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> list:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    return await access_service.replace_access(
        portfolio_id,
        portfolio.organization_id,
        body.user_ids,
        session.user_id,
    )


@router.get(
    "/{portfolio_id}/daily-counter-config",
    response_model=PortfolioDailyCounterConfigResponse | None,
    summary="Obtener configuración del contador diario",
)
async def get_daily_counter_config(
    portfolio_id: uuid.UUID,
    session: CurrentSession,
    service: PortfolioServiceDep,
    access_service: PortfolioUserAccessServiceDep,
) -> PortfolioDailyCounterConfigModel | None:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    await require_portfolio_access(
        session,
        str(portfolio.organization_id),
        portfolio_id,
        access_service.check_access,
    )
    return await service.get_daily_counter_config(portfolio_id)


@router.patch(
    "/{portfolio_id}/daily-counter-config",
    response_model=PortfolioDailyCounterConfigResponse,
    summary="Actualizar configuración del contador diario",
)
async def update_daily_counter_config(
    portfolio_id: uuid.UUID,
    data: PortfolioDailyCounterConfigUpdateRequest,
    session: CurrentSession,
    service: PortfolioServiceDep,
) -> PortfolioDailyCounterConfigModel:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    return await service.update_daily_counter_config(
        portfolio_id, data, session.user_id
    )


@router.post(
    "/{portfolio_id}/daily-counter-config/sync",
    response_model=PortfolioDailyCounterConfigResponse,
    summary="Sincronizar manualmente el contador diario",
)
async def sync_daily_counter_config(
    portfolio_id: uuid.UUID,
    data: PortfolioDailyCounterConfigSyncRequest,
    session: CurrentSession,
    service: PortfolioServiceDep,
) -> PortfolioDailyCounterConfigModel:
    portfolio = await service.get_by_id(portfolio_id)
    require_org_visibility(
        session, str(portfolio.organization_id), "Portafolio no encontrado"
    )
    require_org_admin(session, str(portfolio.organization_id))
    return await service.sync_daily_counter_config(portfolio_id, data, session.user_id)
