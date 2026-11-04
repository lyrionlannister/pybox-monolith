"""Control de campañas IVR en vuelo: pausar, reanudar, cancelar y ajustar ritmo.

El estado local (`ejecuciones_ivr`) es una copia rápida de consulta, no la
fuente de verdad: si alguien opera desde la consola de Helena en vez de
Punvox, los eventos `CAMPAIGN_*` (ver `ivr_event_service._update_execution_status`)
la corrigen igual. Por eso cada acción de escritura aquí actualiza el estado
local de forma **optimista** tras el éxito en Helena, y el webhook la reafirma
o la corrige después.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

import httpx
from fastapi import HTTPException, status

from core.config.logger import logger
from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.ivr.client.helena_client import HelenaClient
from messaging.ivr.enums.ivr_enums import (
    TERMINAL_EXECUTION_STATUSES,
    IvrExecutionStatus,
)
from messaging.ivr.models.ivr_execution_model import IvrExecutionModel
from messaging.ivr.repository.ivr_execution_repository import IvrExecutionRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)


class IvrExecutionService:
    def __init__(
        self,
        execution_repo: IvrExecutionRepository,
        campaign_repo: CampaignRepository,
        portfolio_repo: PortfolioRepository,
        helena_client: HelenaClient,
    ) -> None:
        self._executions = execution_repo
        self._campaigns = campaign_repo
        self._portfolios = portfolio_repo
        self._helena = helena_client

    # ── Autorización ─────────────────────────────────────────────────────────

    async def _authorize_execution(
        self, bulk_id: str, user_session: UserSession
    ) -> IvrExecutionModel:
        execution = await self._executions.get_by_bulk_id(bulk_id)
        if execution is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ejecución no encontrada")

        campaign = await self._campaigns.get_by_id(execution.campaign_id)
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
        return execution

    async def _authorize_campaign(
        self, campaign_id: uuid.UUID, user_session: UserSession
    ) -> None:
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

    # ── Lectura ───────────────────────────────────────────────────────────────

    async def list_for_campaign(
        self, campaign_id: uuid.UUID, user_session: UserSession
    ) -> Sequence[IvrExecutionModel]:
        await self._authorize_campaign(campaign_id, user_session)
        return await self._executions.list_by_campaign(campaign_id)

    async def get_live_status(
        self, bulk_id: str, user_session: UserSession
    ) -> tuple[IvrExecutionModel, dict | None]:
        execution = await self._authorize_execution(bulk_id, user_session)
        try:
            helena_status = await self._helena.queue_status(bulk_id=bulk_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # El estado local sigue siendo útil aunque Helena no responda ahora.
            logger.warning(
                "[ivr_execution] queue_status falló bulk=%s: %s", bulk_id, exc
            )
            helena_status = None
        return execution, helena_status

    # ── Escritura ─────────────────────────────────────────────────────────────

    async def pause(self, bulk_id: str, user_session: UserSession) -> IvrExecutionModel:
        execution = await self._authorize_execution(bulk_id, user_session)
        self._require_not_terminal(execution, "pausar")

        await self._call_helena(
            self._helena.pause_queue(bulk_id=bulk_id),
            bulk_id,
            "pausar",
        )
        execution.status = IvrExecutionStatus.PAUSED
        return await self._executions.update(execution)

    async def resume(
        self, bulk_id: str, user_session: UserSession
    ) -> IvrExecutionModel:
        execution = await self._authorize_execution(bulk_id, user_session)
        self._require_not_terminal(execution, "reanudar")

        await self._call_helena(
            self._helena.resume_queue(bulk_id=bulk_id),
            bulk_id,
            "reanudar",
        )
        execution.status = IvrExecutionStatus.RUNNING
        return await self._executions.update(execution)

    async def cancel(
        self, bulk_id: str, user_session: UserSession
    ) -> IvrExecutionModel:
        """Irreversible en Helena: no hay operación inversa a `cancel`."""
        execution = await self._authorize_execution(bulk_id, user_session)
        self._require_not_terminal(execution, "cancelar")

        await self._call_helena(
            self._helena.cancel_queue(bulk_id=bulk_id, reason="Cancelado desde Punvox"),
            bulk_id,
            "cancelar",
        )
        execution.status = IvrExecutionStatus.CANCELLED
        execution.finished_at = datetime.now(timezone.utc)
        return await self._executions.update(execution)

    async def set_allocation(
        self,
        bulk_id: str,
        calls_per_second: int | None,
        max_concurrent: int | None,
        user_session: UserSession,
    ) -> IvrExecutionModel:
        execution = await self._authorize_execution(bulk_id, user_session)
        self._require_not_terminal(execution, "ajustar el ritmo de")

        if calls_per_second is None and max_concurrent is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Indica al menos un valor para ajustar"
            )

        await self._call_helena(
            self._helena.set_allocation(bulk_id, calls_per_second, max_concurrent),
            bulk_id,
            "ajustar el ritmo de",
        )
        if calls_per_second is not None:
            execution.calls_per_second = calls_per_second
        if max_concurrent is not None:
            execution.max_concurrent = max_concurrent
        return await self._executions.update(execution)

    # ── Internos ──────────────────────────────────────────────────────────────

    def _require_not_terminal(self, execution: IvrExecutionModel, action: str) -> None:
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"No se puede {action} un bulk en estado {execution.status.value}",
            )

    async def _call_helena(self, coro, bulk_id: str, action: str):
        try:
            return await coro
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300] if exc.response is not None else ""
            logger.error(
                "[ivr_execution] Helena rechazó %s | bulk=%s status=%s body=%s",
                action,
                bulk_id,
                exc.response.status_code if exc.response is not None else "?",
                detail,
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Helena rechazó la solicitud de {action}: {detail or exc}",
            ) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "[ivr_execution] error al %s | bulk=%s error=%s", action, bulk_id, exc
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"No se pudo comunicar con Helena para {action} el bulk.",
            ) from exc
