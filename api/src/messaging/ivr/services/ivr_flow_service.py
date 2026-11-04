"""Alta, edición y consulta de flujos IVR reutilizables."""

import uuid

from fastapi import HTTPException, status

from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.ivr.models.ivr_flow_model import IvrFlowModel
from messaging.ivr.repository.ivr_flow_repository import IvrFlowRepository
from messaging.ivr.schemas.ivr_flow_schemas import (
    IvrFlowCreateRequest,
    IvrFlowUpdateRequest,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)


class IvrFlowService:
    def __init__(
        self,
        repo: IvrFlowRepository,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._repo = repo
        self._portfolio_repo = portfolio_repo

    async def _check_portfolio_access(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ) -> uuid.UUID:
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        return await check_portfolio_org_access(
            user_session,
            portfolio,
            PORTFOLIO_COMMUNICATIONS,
            check_access=PortfolioUserAccessService(
                self._portfolio_repo.session
            ).check_access,
        )

    async def authorize_portfolio(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ) -> uuid.UUID:
        """Mismo chequeo que el resto de operaciones de flujos (permiso de
        comunicaciones + acceso al portafolio); devuelve la organización dueña."""
        return await self._check_portfolio_access(user_session, portfolio_id)

    async def list_by_portfolio(
        self, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> list[IvrFlowModel]:
        await self._check_portfolio_access(user_session, portfolio_id)
        return await self._repo.list_by_portfolio(portfolio_id)

    async def get_by_id(
        self, flow_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> IvrFlowModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        flow = await self._repo.get_by_id_and_portfolio(flow_id, portfolio_id)
        if flow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Flujo IVR no encontrado")
        return flow

    async def create(
        self,
        portfolio_id: uuid.UUID,
        data: IvrFlowCreateRequest,
        user_session: UserSession,
    ) -> IvrFlowModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        flow = IvrFlowModel(
            portfolio_id=portfolio_id,
            name=data.name,
            description=data.description,
            config=data.config,
            graph=data.graph,
            redial_config=data.redial_config,
            variables=data.variables,
            outcomes=data.outcomes,
            calls_per_second=data.calls_per_second,
            max_concurrent=data.max_concurrent,
            caller_id=data.caller_id,
            contact_policy_id=data.contact_policy_id,
        )
        return await self._repo.add(flow)

    async def update(
        self,
        flow_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: IvrFlowUpdateRequest,
        user_session: UserSession,
    ) -> IvrFlowModel:
        flow = await self.get_by_id(flow_id, portfolio_id, user_session)
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(flow, key, value)
        return await self._repo.update(flow)

    async def delete(
        self, flow_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> None:
        flow = await self.get_by_id(flow_id, portfolio_id, user_session)
        await self._repo.delete(flow)
