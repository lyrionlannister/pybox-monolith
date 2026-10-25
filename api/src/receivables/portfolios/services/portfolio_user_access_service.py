"""Gestión de accesos delegados de usuarios a portafolios específicos."""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from receivables.portfolios.models.portfolio_user_access_model import (
    PortfolioUserAccessModel,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)


class PortfolioUserAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = PortfolioUserAccessRepository(session)
        self._portfolio_repo = PortfolioRepository(session)
        self._membership_repo = OrganizationMembershipRepository(session)

    async def _require_portfolio_of_org(
        self, portfolio_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        """El controller valida que el llamante sea admin de `organization_id`,
        pero el `portfolio_id` viene del path: sin esto, un admin de la org A
        podría operar sobre un portafolio de la org B. 404 (no 403) para no
        confirmar que existe."""
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None or portfolio.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado")

    async def _require_member(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        memberships = await self._membership_repo.get_by_user_id(user_id)
        if not any(m.organization_id == organization_id for m in memberships):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")

    async def check_access(
        self, user_id: uuid.UUID, portfolio_id: uuid.UUID, org_id: str
    ) -> bool:
        try:
            organization_id = uuid.UUID(str(org_id))
            portfolio_uuid = uuid.UUID(str(portfolio_id))
        except ValueError:
            return False
        return await self._repo.check_active_access(
            user_id, portfolio_uuid, organization_id
        )

    async def grant_access(
        self,
        user_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        granted_by: uuid.UUID,
    ) -> PortfolioUserAccessModel:
        await self._require_portfolio_of_org(portfolio_id, organization_id)
        await self._require_member(user_id, organization_id)

        existing = await self._repo.get_by_user_and_portfolio(user_id, portfolio_id)
        if existing is not None:
            if existing.is_active:
                return existing
            existing.is_active = True
            existing.revoked_at = None
            existing.granted_by = granted_by
            existing.granted_at = datetime.utcnow()
            return await self._repo.update(existing)

        return await self._repo.add(
            PortfolioUserAccessModel(
                user_id=user_id,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
                granted_by=granted_by,
            )
        )

    async def revoke_access(
        self, user_id: uuid.UUID, portfolio_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        await self._require_portfolio_of_org(portfolio_id, organization_id)
        existing = await self._repo.get_by_user_and_portfolio(user_id, portfolio_id)
        if existing is None or not existing.is_active:
            return
        existing.is_active = False
        existing.revoked_at = datetime.utcnow()
        await self._repo.update(existing)

    async def get_user_portfolios(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[PortfolioUserAccessModel]:
        return await self._repo.get_active_by_user_and_org(user_id, organization_id)

    async def revoke_all_for_user_in_org(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> None:
        accesses = await self._repo.get_active_by_user_and_org(user_id, organization_id)
        now = datetime.utcnow()
        for access in accesses:
            access.is_active = False
            access.revoked_at = now
            await self._repo.update(access)

    async def list_org_portfolios_with_access_status(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str, bool]]:
        await self._require_member(user_id, organization_id)
        all_portfolios = await self._portfolio_repo.get_active_by_organization_id(
            organization_id
        )
        active_accesses = await self._repo.get_active_by_user_and_org(
            user_id, organization_id
        )
        granted_ids = {a.portfolio_id for a in active_accesses}
        return [(p.id, p.name, p.id in granted_ids) for p in all_portfolios]

    async def list_portfolio_access(
        self, portfolio_id: uuid.UUID
    ) -> list[PortfolioUserAccessModel]:
        return await self._repo.get_by_portfolio_id(portfolio_id)

    async def replace_access(
        self,
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_ids: list[uuid.UUID],
        granted_by: uuid.UUID,
    ) -> list[PortfolioUserAccessModel]:
        # Validado una sola vez: `grant_access`/`revoke_access` lo repiten por
        # llamada (misma consulta, mismo portafolio) porque también se usan sueltos.
        await self._require_portfolio_of_org(portfolio_id, organization_id)

        memberships = await self._membership_repo.get_by_user_ids(user_ids)
        member_user_ids = {
            m.user_id for m in memberships if m.organization_id == organization_id
        }
        missing = [u for u in user_ids if u not in member_user_ids]
        if missing:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")

        existing = await self._repo.get_by_portfolio_id(portfolio_id)
        existing_by_user = {a.user_id: a for a in existing}
        new_set = set(user_ids)
        now = datetime.utcnow()

        for user_id, access in existing_by_user.items():
            if user_id not in new_set and access.is_active:
                access.is_active = False
                access.revoked_at = now
                await self._repo.update(access)

        result = []
        for user_id in user_ids:
            access = existing_by_user.get(user_id)
            if access is not None:
                if not access.is_active:
                    access.is_active = True
                    access.revoked_at = None
                    access.granted_by = granted_by
                    access.granted_at = now
                    access = await self._repo.update(access)
                result.append(access)
                continue
            result.append(
                await self._repo.add(
                    PortfolioUserAccessModel(
                        user_id=user_id,
                        portfolio_id=portfolio_id,
                        organization_id=organization_id,
                        granted_by=granted_by,
                    )
                )
            )

        return result
