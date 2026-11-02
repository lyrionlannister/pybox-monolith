"""Acceso a datos de las credenciales de pasarela de cobro de una organización."""

import uuid

from sqlalchemy import select, update

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesGatewayProvider,
)
from receivables.payment_gateways.models.payment_gateway_credential_model import (
    OrganizationGatewayCredentialModel,
)


class OrganizationGatewayCredentialRepository(
    SoftDeleteRepositoryBase[OrganizationGatewayCredentialModel]
):
    model_class = OrganizationGatewayCredentialModel

    async def get_by_organization_and_provider(
        self, organization_id: uuid.UUID, provider: ReceivablesGatewayProvider
    ) -> OrganizationGatewayCredentialModel | None:
        result = await self.session.execute(
            select(OrganizationGatewayCredentialModel).where(
                OrganizationGatewayCredentialModel.organization_id == organization_id,
                OrganizationGatewayCredentialModel.provider == provider,
                OrganizationGatewayCredentialModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self, organization_id: uuid.UUID
    ) -> list[OrganizationGatewayCredentialModel]:
        result = await self.session.execute(
            select(OrganizationGatewayCredentialModel).where(
                OrganizationGatewayCredentialModel.organization_id == organization_id,
                OrganizationGatewayCredentialModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_active_by_organization(
        self, organization_id: uuid.UUID
    ) -> OrganizationGatewayCredentialModel | None:
        """La pasarela activa de la organización para el checkout de autoservicio (ver
        `ReceivablesGatewayResolver.get_active_for_organization`). El invariante "a lo
        sumo una activa por organización" lo impone
        `OrganizationGatewayCredentialManagementService` al activar una credencial
        (desactiva las demás) — `order_by` + `limit(1)` es solo defensivo por si ese
        invariante no se cumplió todavía sobre datos existentes."""
        result = await self.session.execute(
            select(OrganizationGatewayCredentialModel)
            .where(
                OrganizationGatewayCredentialModel.organization_id == organization_id,
                OrganizationGatewayCredentialModel.is_active.is_(True),
                OrganizationGatewayCredentialModel.deleted_at.is_(None),
            )
            .order_by(OrganizationGatewayCredentialModel.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def deactivate_all(
        self, organization_id: uuid.UUID, exclude_id: uuid.UUID | None = None
    ) -> None:
        """Mantiene el invariante "a lo sumo una credencial activa por organización"
        (ver `get_active_by_organization`) — se llama ANTES de activar una credencial
        nueva o existente."""
        stmt = update(OrganizationGatewayCredentialModel).where(
            OrganizationGatewayCredentialModel.organization_id == organization_id,
            OrganizationGatewayCredentialModel.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(OrganizationGatewayCredentialModel.id != exclude_id)
        await self.session.execute(stmt.values(**self._touch(is_active=False)))

    async def get_by_lookup_key(
        self, provider: ReceivablesGatewayProvider, lookup_key: str
    ) -> OrganizationGatewayCredentialModel | None:
        """Para webhooks de pasarelas cuyo payload trae un identificador de comercio
        resoluble por igualdad (ver skill `wompi-gateway`, Paso 7 — no todas lo traen,
        confirmar caso por caso antes de depender de esto)."""
        result = await self.session.execute(
            select(OrganizationGatewayCredentialModel).where(
                OrganizationGatewayCredentialModel.provider == provider,
                OrganizationGatewayCredentialModel.lookup_key == lookup_key,
                OrganizationGatewayCredentialModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
