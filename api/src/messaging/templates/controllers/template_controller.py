"""Endpoints de plantillas de mensajería: alta, edición y variables disponibles."""

import uuid
from typing import Annotated

from fastapi import Query, status

from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import require_global_admin
from messaging.templates.dependencies import (
    TemplateServiceDep,
    TemplateVariableServiceDep,
)
from messaging.templates.enums.template_enums import TemplateChannel
from messaging.templates.schemas.template_schemas import (
    TemplateCreateRequest,
    TemplateListResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateSendRequest,
    TemplateSendResponse,
    TemplateUpdateRequest,
    TemplateVariableOption,
)

router = APIRouter(prefix="/templates", tags=["Plantillas"])


@router.get(
    "/", response_model=TemplateListResponse, summary="Listar plantillas del portafolio"
)
async def list_templates(
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    channel: Annotated[TemplateChannel | None, Query(alias="channel")] = None,
    search: Annotated[
        str | None, Query(description="Búsqueda por nombre de plantilla")
    ] = None,
    sort: Annotated[str, Query(description="Campo de orden: name | status")] = "name",
    sort_order: Annotated[
        str, Query(alias="sort_order", pattern="^(asc|desc)$")
    ] = "asc",
) -> TemplateListResponse:
    templates, total = await service.list_by_org(
        portfolio_id, page, page_size, session, channel, search, sort, sort_order
    )
    return TemplateListResponse(
        items=[TemplateResponse.model_validate(t) for t in templates],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/variables",
    response_model=list[TemplateVariableOption],
    summary="Listar variables disponibles para construir el contenido de una plantilla",
)
async def list_template_variables(
    _session: CurrentSession,
    service: TemplateVariableServiceDep,
) -> list[TemplateVariableOption]:
    return await service.list_available_variables()


@router.get(
    "/options",
    response_model=list[TemplateResponse],
    summary="Listar todas las plantillas del portafolio sin paginar (uso en selects)",
)
async def list_template_options(
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
    channel: Annotated[TemplateChannel | None, Query(alias="channel")] = None,
) -> list[TemplateResponse]:
    templates = await service.list_all_by_org(portfolio_id, session, channel)
    return [TemplateResponse.model_validate(t) for t in templates]


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="Obtener plantilla por ID",
)
async def get_template(
    template_id: uuid.UUID,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> TemplateResponse:
    template = await service.get_by_id(template_id, portfolio_id, session)
    return TemplateResponse.model_validate(template)


@router.post(
    "/",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear plantilla",
)
async def create_template(
    body: TemplateCreateRequest,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> TemplateResponse:
    template = await service.create(portfolio_id, body, session)
    return TemplateResponse.model_validate(template)


@router.patch(
    "/{template_id}", response_model=TemplateResponse, summary="Actualizar plantilla"
)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdateRequest,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> TemplateResponse:
    template = await service.update(template_id, portfolio_id, body, session)
    return TemplateResponse.model_validate(template)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar plantilla (soft delete)",
)
async def delete_template(
    template_id: uuid.UUID,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> None:
    await service.delete(template_id, portfolio_id, session)


@router.post(
    "/{template_id}/restore",
    status_code=status.HTTP_200_OK,
    summary="Restaurar plantilla",
    description="Solo administradores globales.",
)
async def restore_template(
    template_id: uuid.UUID,
    session: CurrentSession,
    service: TemplateServiceDep,
) -> TemplateResponse:
    require_global_admin(session)
    template = await service.restore(template_id)
    return TemplateResponse.model_validate(template)


@router.post(
    "/{template_id}/preview",
    response_model=TemplatePreviewResponse,
    summary="Previsualizar plantilla renderizada con variables de prueba",
)
async def preview_template(
    template_id: uuid.UUID,
    body: TemplatePreviewRequest,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> TemplatePreviewResponse:
    return await service.preview(template_id, portfolio_id, body, session)


@router.post(
    "/{template_id}/send",
    response_model=TemplateSendResponse,
    summary="Enviar una plantilla de EMAIL de prueba al propio correo",
)
async def send_template(
    template_id: uuid.UUID,
    body: TemplateSendRequest,
    session: CurrentSession,
    service: TemplateServiceDep,
    portfolio_id: Annotated[uuid.UUID, Query(alias="portfolioId")],
) -> TemplateSendResponse:
    return await service.send(template_id, portfolio_id, body, session)
