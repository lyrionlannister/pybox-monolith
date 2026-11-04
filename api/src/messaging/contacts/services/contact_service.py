"""Consulta de contactos (envíos) de un deudor, agrupados por canal."""

import uuid
from math import ceil

from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.contacts.schemas.contact_schemas import (
    ContactResponse,
    ContactsByChannelGroup,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)


class ContactService:
    def __init__(
        self, repo: ContactRepository, portfolio_repo: PortfolioRepository
    ) -> None:
        self._repo = repo
        self._portfolio_repo = portfolio_repo

    async def get_by_debtor(
        self,
        debtor_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        user_session: UserSession,
        page: int,
        page_size: int,
    ) -> list[ContactsByChannelGroup]:
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        organization_id = await check_portfolio_org_access(
            user_session,
            portfolio,
            PORTFOLIO_COMMUNICATIONS,
            check_access=PortfolioUserAccessService(
                self._portfolio_repo.session
            ).check_access,
        )
        groups = await self._repo.get_by_debtor_grouped_paginated(
            debtor_id, organization_id, portfolio_id, page, page_size
        )
        return [
            ContactsByChannelGroup(
                channel_id=channel_id,
                channel_name=channel_name,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=ceil(total / page_size) if total else 1,
                items=[ContactResponse.model_validate(c) for c in items],
            )
            for channel_id, channel_name, total, items in groups
        ]
