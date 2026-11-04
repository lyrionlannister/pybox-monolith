"""Consultas del monitor de llamadas y autorización de acceso.

Cada campaña pertenece a un portafolio, y ese portafolio a una organización.
Sin esta comprobación cualquier usuario autenticado podría abrir el stream de
las llamadas de otra organización, así que el chequeo va tanto en el snapshot
como en el stream y en el listado.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.ivr.enums.ivr_enums import IvrCallStatus
from messaging.ivr.repository.ivr_interaction_repository import IvrInteractionRepository
from messaging.ivr.schemas.ivr_monitor_schemas import (
    IvrCallListResponse,
    IvrCallSchema,
    IvrCampaignStatsSchema,
    IvrSnapshotSchema,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)

#: Ventana durante la cual una llamada ya terminada sigue apareciendo en el
#: snapshot, para que al recargar no desaparezcan de golpe los resultados que
#: el usuario acaba de ver pasar.
_RECENTLY_ENDED_SECONDS = 60


class IvrMonitorService:
    def __init__(
        self,
        interaction_repo: IvrInteractionRepository,
        campaign_repo: CampaignRepository,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._interactions = interaction_repo
        self._campaigns = campaign_repo
        self._portfolios = portfolio_repo

    async def authorize_campaign(
        self, campaign_id: uuid.UUID, user_session: UserSession
    ) -> CampaignModel:
        campaign = await self._campaigns.get_by_id(campaign_id)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaña no encontrada")
        portfolio = await self._portfolios.get_by_id(campaign.portfolio_id)
        await check_portfolio_org_access(
            user_session,
            portfolio,
            PORTFOLIO_COMMUNICATIONS,
            check_access=PortfolioUserAccessService(
                self._portfolios.session
            ).check_access,
        )
        return campaign

    async def get_snapshot(
        self, campaign_id: uuid.UUID, user_session: UserSession
    ) -> IvrSnapshotSchema:
        await self.authorize_campaign(campaign_id, user_session)
        return await self.build_snapshot(campaign_id)

    async def build_snapshot(self, campaign_id: uuid.UUID) -> IvrSnapshotSchema:
        """Snapshot sin comprobar permisos (ya validados por quien llama)."""
        ended_since = datetime.now(timezone.utc) - timedelta(
            seconds=_RECENTLY_ENDED_SECONDS
        )
        rows = await self._interactions.get_active_for_campaign(
            campaign_id, ended_since
        )
        stats = await self._interactions.get_campaign_stats(campaign_id)
        return IvrSnapshotSchema(
            active_calls=[IvrCallSchema.from_model(row) for row in rows],
            stats=IvrCampaignStatsSchema(**stats),
            generated_at=datetime.now(timezone.utc),
        )

    async def get_stats(self, campaign_id: uuid.UUID) -> IvrCampaignStatsSchema:
        return IvrCampaignStatsSchema(
            **await self._interactions.get_campaign_stats(campaign_id)
        )

    async def list_calls(
        self,
        campaign_id: uuid.UUID,
        user_session: UserSession,
        page: int,
        page_size: int,
        call_status: IvrCallStatus | None = None,
        phone: str | None = None,
        outcome_key: str | None = None,
    ) -> IvrCallListResponse:
        await self.authorize_campaign(campaign_id, user_session)
        rows, total = await self._interactions.list_for_campaign(
            campaign_id, page, page_size, call_status, phone, outcome_key
        )
        return IvrCallListResponse(
            items=[IvrCallSchema.from_model(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
