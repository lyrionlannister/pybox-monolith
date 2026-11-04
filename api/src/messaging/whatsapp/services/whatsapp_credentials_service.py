"""Alta y consulta de las credenciales de WhatsApp Business de una organización."""

import uuid

from fastapi import HTTPException, status

from core.security.policies.security_policies import (
    require_global_admin,
    require_org_admin,
)
from identity.users.schemas.user_session_schema import UserSession
from messaging.whatsapp.models.whatsapp_org_credentials_model import (
    WhatsAppOrgCredentialsModel,
)
from messaging.whatsapp.repository.whatsapp_org_credentials_repository import (
    WhatsAppOrgCredentialsRepository,
)
from messaging.whatsapp.schemas.whatsapp_credentials_schemas import (
    WhatsAppOrgCredentialsRequest,
)


class WhatsAppCredentialsService:
    def __init__(self, repo: WhatsAppOrgCredentialsRepository) -> None:
        self._repo = repo

    async def get(
        self, organization_id: uuid.UUID, user_session: UserSession
    ) -> WhatsAppOrgCredentialsModel:
        require_org_admin(user_session, str(organization_id))
        credentials = await self._repo.get_by_organization(organization_id)
        if credentials is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "La organización no tiene un número de WhatsApp configurado",
            )
        return credentials

    async def upsert(
        self,
        organization_id: uuid.UUID,
        data: WhatsAppOrgCredentialsRequest,
        user_session: UserSession,
    ) -> WhatsAppOrgCredentialsModel:
        # Solo staff global: el token/WABA de Meta es de la plataforma, y un admin de
        # organización podría declarar el número de otra organización.
        require_global_admin(user_session)
        owner = await self._repo.get_by_phone_number_id(data.phone_number_id)
        if owner is not None and owner.organization_id != organization_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ese número de WhatsApp ya está asignado a otra organización.",
            )
        existing = await self._repo.get_by_organization(organization_id)
        if existing is not None:
            existing.phone_number_id = data.phone_number_id
            existing.display_name = data.display_name
            existing.active = data.active
            return await self._repo.update(existing)
        return await self._repo.add(
            WhatsAppOrgCredentialsModel(
                organization_id=organization_id,
                phone_number_id=data.phone_number_id,
                display_name=data.display_name,
                active=data.active,
            )
        )
