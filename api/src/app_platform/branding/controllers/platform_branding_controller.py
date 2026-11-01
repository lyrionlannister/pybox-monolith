"""Endpoints de la marca global de la plataforma (logo público)."""

import uuid
from typing import Annotated

from fastapi import File, HTTPException, Response, UploadFile, status

from app_platform.branding.dependencies import PlatformBrandingServiceDep
from app_platform.branding.schemas.platform_branding_schemas import (
    PlatformBrandingResponse,
)
from app_platform.documents.utils.document_naming import resolve_content_type
from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import require_global_admin

router = APIRouter(prefix="/platform/branding", tags=["Branding de plataforma"])


@router.get(
    "",
    response_model=PlatformBrandingResponse,
    summary="Ver la configuración de marca de la plataforma",
    description="Cualquier usuario autenticado puede leerla: es el logo de fallback "
    "para quien no pertenece a ninguna organización.",
)
async def get_platform_branding(
    _: CurrentSession,
    service: PlatformBrandingServiceDep,
) -> PlatformBrandingResponse:
    branding = await service.get_singleton()
    return service.to_response(branding)


@router.patch(
    "/logo",
    response_model=PlatformBrandingResponse,
    summary="Reemplazar el logo global de la plataforma",
    description="Solo administradores globales.",
)
async def update_platform_logo(
    session: CurrentSession,
    service: PlatformBrandingServiceDep,
    file: Annotated[UploadFile, File(description="Imagen a subir")],
) -> PlatformBrandingResponse:
    require_global_admin(session)

    if resolve_content_type(file.filename) == "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "El logo debe ser una imagen (PNG, JPG o WebP)",
        )

    updated = await service.replace_logo(file=file, uploaded_by=session.user_id)
    return service.to_response(updated)


@router.get(
    "/documents/{document_id}/content",
    summary="Descargar el logo global de la plataforma",
    description="Cualquier sesión autenticada puede verlo (fallback de branding para "
    "quien no tiene organización). Si el id no es el del logo vigente responde 404.",
    response_class=Response,
)
async def get_platform_logo_content(
    document_id: uuid.UUID,
    session: CurrentSession,
    service: PlatformBrandingServiceDep,
) -> Response:
    return await service.get_logo_content(document_id, session.user_id)
