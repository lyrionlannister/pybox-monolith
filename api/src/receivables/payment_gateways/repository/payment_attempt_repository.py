"""Acceso a datos de los intentos de cobro contra la pasarela de la organización."""

import uuid

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.payment_gateways.models.payment_attempt_model import (
    CreditPaymentAttemptModel,
)


class CreditPaymentAttemptRepository(
    SoftDeleteRepositoryBase[CreditPaymentAttemptModel]
):
    model_class = CreditPaymentAttemptModel

    async def get_latest_by_payment_id(
        self, payment_id: uuid.UUID, *, for_update: bool = False
    ) -> CreditPaymentAttemptModel | None:
        query = (
            select(CreditPaymentAttemptModel)
            .where(
                CreditPaymentAttemptModel.payment_id == payment_id,
                CreditPaymentAttemptModel.deleted_at.is_(None),
            )
            .order_by(CreditPaymentAttemptModel.attempt_number.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_provider_reference(
        self, provider_reference: str, *, for_update: bool = False
    ) -> CreditPaymentAttemptModel | None:
        query = select(CreditPaymentAttemptModel).where(
            CreditPaymentAttemptModel.provider_reference == provider_reference,
            CreditPaymentAttemptModel.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_by_provider_transaction_id(
        self, provider_transaction_id: str, *, for_update: bool = False
    ) -> CreditPaymentAttemptModel | None:
        query = select(CreditPaymentAttemptModel).where(
            CreditPaymentAttemptModel.provider_transaction_id
            == provider_transaction_id,
            CreditPaymentAttemptModel.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalars().first()
