"""Acceso a datos de las cuotas de pago de un crédito."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.payments.models.payment_model import PaymentModel


class PaymentRepository(SoftDeleteRepositoryBase[PaymentModel]):
    model_class = PaymentModel

    async def get_by_credit_id(self, credit_id: uuid.UUID) -> list[PaymentModel]:
        result = await self.session.execute(
            select(PaymentModel)
            .where(
                PaymentModel.credit_id == credit_id,
                PaymentModel.deleted_at.is_(None),
            )
            .order_by(PaymentModel.limit_pay_date)
        )
        return list(result.scalars().all())

    async def get_by_credit_ids(
        self, credit_ids: list[uuid.UUID]
    ) -> list[PaymentModel]:
        if not credit_ids:
            return []
        result = await self.session.execute(
            select(PaymentModel)
            .where(
                PaymentModel.credit_id.in_(credit_ids),
                PaymentModel.deleted_at.is_(None),
            )
            .order_by(PaymentModel.limit_pay_date)
        )
        return list(result.scalars().all())

    async def get_next_due_by_credit_ids(
        self, credit_ids: list[uuid.UUID]
    ) -> list[PaymentModel]:
        """Un crédito tiene muchas cuotas: retorna, por crédito, la más próxima a
        vencer que aún no se ha pagado (fecha límite en el futuro)."""
        if not credit_ids:
            return []
        result = await self.session.execute(
            select(PaymentModel)
            .where(
                PaymentModel.credit_id.in_(credit_ids),
                PaymentModel.deleted_at.is_(None),
                PaymentModel.payment_date.is_(None),
                PaymentModel.limit_pay_date >= datetime.now(timezone.utc),
            )
            .distinct(PaymentModel.credit_id)
            .order_by(PaymentModel.credit_id, PaymentModel.limit_pay_date.asc())
        )
        return list(result.scalars().all())

    async def get_oldest_overdue_by_credit_ids(
        self, credit_ids: list[uuid.UUID]
    ) -> list[PaymentModel]:
        """Por crédito, la cuota vencida (fecha límite ya pasada) más antigua sin
        pagar."""
        if not credit_ids:
            return []
        result = await self.session.execute(
            select(PaymentModel)
            .where(
                PaymentModel.credit_id.in_(credit_ids),
                PaymentModel.deleted_at.is_(None),
                PaymentModel.payment_date.is_(None),
                PaymentModel.limit_pay_date < datetime.now(timezone.utc),
            )
            .distinct(PaymentModel.credit_id)
            .order_by(PaymentModel.credit_id, PaymentModel.limit_pay_date.asc())
        )
        return list(result.scalars().all())

    async def get_by_credit_and_installment(
        self, credit_id: uuid.UUID, installment_number: int
    ) -> PaymentModel | None:
        """Usado por la carga de plan de cuotas (installment_csv_service) para
        decidir si una fila del CSV actualiza una cuota ya cargada o crea una
        nueva."""
        result = await self.session.execute(
            select(PaymentModel).where(
                PaymentModel.credit_id == credit_id,
                PaymentModel.installment_number == installment_number,
                PaymentModel.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_pending_by_credit_id(
        self, credit_id: uuid.UUID
    ) -> list[PaymentModel]:
        """Cuotas de un crédito sin pagar todavía. Usado al procesar un pago total del
        crédito en la carga de plan de cuotas, para cerrarlas todas de una vez."""
        result = await self.session.execute(
            select(PaymentModel).where(
                PaymentModel.credit_id == credit_id,
                PaymentModel.deleted_at.is_(None),
                PaymentModel.payment_date.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_last_unpaid_by_credit_ids(
        self, credit_ids: list[uuid.UUID]
    ) -> list[PaymentModel]:
        """Por crédito, la última cuota del cronograma que sigue sin pagar (vencida
        o no)."""
        if not credit_ids:
            return []
        result = await self.session.execute(
            select(PaymentModel)
            .where(
                PaymentModel.credit_id.in_(credit_ids),
                PaymentModel.deleted_at.is_(None),
                PaymentModel.payment_date.is_(None),
            )
            .distinct(PaymentModel.credit_id)
            .order_by(PaymentModel.credit_id, PaymentModel.limit_pay_date.desc())
        )
        return list(result.scalars().all())
