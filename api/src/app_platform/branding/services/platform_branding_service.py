"""Gestión (lectura/reemplazo) del logo global de la plataforma."""

import uuid

from fastapi import HTTPException, Response, UploadFile, status

from app_platform.branding.models.platform_branding_model import PlatformBrandingModel
from app_platform.branding.repository.platform_branding_repository import (
    PlatformBrandingRepository,
)
from app_platform.branding.schemas.platform_branding_schemas import (
    PlatformBrandingResponse,
)
from app_platform.documents.services.document_service import DocumentService

# Prefijo del dominio en la clave del objeto (`<dominio>/<dueno>/<uuid><ext>`), mismo
# esquema que ORGANIZATION_DOCUMENT_STORAGE_DOMAIN pero sin dueño real: el logo global
# no pertenece a ninguna organización ni usuario puntual.
PLATFORM_BRANDING_STORAGE_DOMAIN = "plataforma"
PLATFORM_BRANDING_OWNER_ID = "global"


class PlatformBrandingService:
    def __init__(
        self, repo: PlatformBrandingRepository, document_service: DocumentService
    ):
        self._repo = repo
        self._document_service = document_service

    async def get_singleton(self) -> PlatformBrandingModel:
        branding = await self._repo.get_singleton()
        if branding is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Configuración de plataforma no inicializada",
            )
        return branding

    async def replace_logo(
        self, file: UploadFile, uploaded_by: uuid.UUID
    ) -> PlatformBrandingModel:
        """Espejo de OrganizationService.replace_document: el logo anterior se da de
        baja al final y no antes -- si la subida del nuevo falla, la plataforma se
        queda con el que tenía en vez de sin ninguno.

        Usa `store()` (no `store_generated()`): el logo es una subida de usuario real,
        no un artefacto generado por la propia API, así que debe pasar por el límite de
        tamaño y la verificación de magic bytes igual que cualquier otra."""
        branding = await self.get_singleton()
        document = await self._document_service.store(
            file=file,
            domain=PLATFORM_BRANDING_STORAGE_DOMAIN,
            owner_id=PLATFORM_BRANDING_OWNER_ID,
            uploaded_by=uploaded_by,
        )
        previous_document_id = branding.logo_document_id
        branding.logo_document_id = document.id
        updated = await self._repo.update(branding)

        if previous_document_id is not None and previous_document_id != document.id:
            await self._document_service.delete_by_id(previous_document_id)
        return updated

    async def get_logo_content(
        self, document_id: uuid.UUID, requested_by: uuid.UUID
    ) -> Response:
        """Entrega el logo global. Ownership resuelto contra la fila singleton (mismo
        chequeo 1:1 que profile-photo/content contra la fila del usuario): 404 salvo
        que `document_id` sea EXACTAMENTE el logo vigente."""
        branding = await self.get_singleton()
        if (
            branding.logo_document_id is None
            or branding.logo_document_id != document_id
        ):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "La plataforma no tiene logo configurado"
            )
        document = await self._document_service.get_by_id(document_id)
        if document is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "La plataforma no tiene logo configurado"
            )
        return await self._document_service.to_content_response(document, requested_by)

    @staticmethod
    def to_response(branding: PlatformBrandingModel) -> PlatformBrandingResponse:
        return PlatformBrandingResponse(logo_document_id=branding.logo_document_id)
