"""Acceso a datos de los métodos de pago manuales de una organización."""

import uuid

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.payment_methods.models.payment_method_model import PaymentMethodModel


class PaymentMethodRepository(SoftDeleteRepositoryBase[PaymentMethodModel]):
    model_class = PaymentMethodModel

    async def get_by_organization_id(
        self, organization_id: uuid.UUID
    ) -> list[PaymentMethodModel]:
        result = await self.session.execute(
            select(PaymentMethodModel).where(
                PaymentMethodModel.organization_id == organization_id,
                PaymentMethodModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_active_by_organization_id(
        self, organization_id: uuid.UUID
    ) -> list[PaymentMethodModel]:
        result = await self.session.execute(
            select(PaymentMethodModel).where(
                PaymentMethodModel.organization_id == organization_id,
                PaymentMethodModel.is_active.is_(True),
                PaymentMethodModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_active_by_organization_ids(
        self, organization_ids: list[uuid.UUID]
    ) -> list[PaymentMethodModel]:
        if not organization_ids:
            return []
        result = await self.session.execute(
            select(PaymentMethodModel).where(
                PaymentMethodModel.organization_id.in_(organization_ids),
                PaymentMethodModel.is_active.is_(True),
                PaymentMethodModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())
