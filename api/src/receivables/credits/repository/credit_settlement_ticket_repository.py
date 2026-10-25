"""Acceso a datos del vínculo entre ticket de soporte y crédito a dar de baja."""

import uuid

from sqlalchemy import select

from app_platform.support.enums.support_enums import SupportTicketStatus
from app_platform.support.models.support_ticket_model import SupportTicketModel
from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.credits.models.credit_settlement_ticket_model import (
    CreditSettlementTicketModel,
)


class CreditSettlementTicketRepository(
    SoftDeleteRepositoryBase[CreditSettlementTicketModel]
):
    model_class = CreditSettlementTicketModel

    async def get_by_ticket_id(
        self, ticket_id: uuid.UUID
    ) -> CreditSettlementTicketModel | None:
        result = await self.session.execute(
            select(CreditSettlementTicketModel).where(
                CreditSettlementTicketModel.ticket_id == ticket_id
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_credit_id(
        self, credit_id: uuid.UUID
    ) -> CreditSettlementTicketModel | None:
        """Vínculo de baja cuyo ticket sigue abierto (ni resuelto ni cerrado). Se usa
        para bloquear solicitudes de baja duplicadas sobre el mismo crédito."""
        result = await self.session.execute(
            select(CreditSettlementTicketModel)
            .join(
                SupportTicketModel,
                SupportTicketModel.id == CreditSettlementTicketModel.ticket_id,
            )
            .where(
                CreditSettlementTicketModel.credit_id == credit_id,
                SupportTicketModel.status.not_in(
                    [SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED]
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_credit_ids(
        self, credit_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Igual que `get_active_by_credit_id`, en batch: créditos con un vínculo de
        baja cuyo ticket sigue abierto."""
        if not credit_ids:
            return set()
        result = await self.session.execute(
            select(CreditSettlementTicketModel.credit_id)
            .join(
                SupportTicketModel,
                SupportTicketModel.id == CreditSettlementTicketModel.ticket_id,
            )
            .where(
                CreditSettlementTicketModel.credit_id.in_(credit_ids),
                SupportTicketModel.status.not_in(
                    [SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED]
                ),
            )
        )
        return set(result.scalars().all())
