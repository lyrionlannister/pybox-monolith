"""Acceso a datos de facturas: consulta, listado y transiciones de estado."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select, tuple_, update

from billing.invoices.enums.invoice_enums import InvoiceStatus, PaymentAttemptStatus
from billing.invoices.models.invoice_item_model import InvoiceItemModel
from billing.invoices.models.invoice_model import InvoiceModel
from billing.invoices.models.payment_attempt_model import InvoicePaymentAttemptModel
from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from identity.organizations.models.organization_model import OrganizationModel

_NON_BILLABLE_STATUSES = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)


class InvoiceRepository(SoftDeleteRepositoryBase[InvoiceModel]):
    model_class = InvoiceModel

    async def get_current_by_organization_id(
        self, organization_id: uuid.UUID
    ) -> InvoiceModel | None:
        result = await self.session.execute(
            select(InvoiceModel)
            .where(
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.deleted_at.is_(None),
            )
            .order_by(InvoiceModel.period_year.desc(), InvoiceModel.period_month.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_id_and_organization_id(
        self, id: uuid.UUID, organization_id: uuid.UUID
    ) -> InvoiceModel | None:
        result = await self.session.execute(
            select(InvoiceModel).where(
                InvoiceModel.id == id,
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_open_by_organization_id(
        self, organization_id: uuid.UUID
    ) -> InvoiceModel | None:
        """Factura mas reciente en un estado que requiere atencion
        (no PAID/CANCELLED/DRAFT).
        """
        result = await self.session.execute(
            select(InvoiceModel)
            .where(
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.in_(
                    [
                        InvoiceStatus.ISSUED,
                        InvoiceStatus.PAYMENT_PENDING,
                        InvoiceStatus.OVERDUE,
                        InvoiceStatus.BLOCKED,
                    ]
                ),
            )
            .order_by(InvoiceModel.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_oldest_unpaid_due(
        self, organization_id: uuid.UUID, now: datetime
    ) -> InvoiceModel | None:
        """Factura mas antigua vencida y sin pagar, o None si la organizacion
        esta al dia.

        Recorre todas las facturas y no solo la mas reciente: al emitirse la
        factura del mes siguiente, esta pasa a ser la mas reciente y taparia
        una factura anterior impaga, desbloqueando sola a la organizacion
        cada mes.

        Se filtra por due_at en vez de por el estado OVERDUE porque el cron
        que marca los estados solo corre una vez al dia: una factura puede
        llevar hasta 24 h vencida y seguir en ISSUED. PAYMENT_PENDING
        tambien cuenta como impaga mientras no llegue la confirmacion del
        gateway.
        """
        result = await self.session.execute(
            select(InvoiceModel)
            .where(
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.deleted_at.is_(None),
                or_(
                    InvoiceModel.status == InvoiceStatus.BLOCKED,
                    and_(
                        InvoiceModel.status.in_(
                            [
                                InvoiceStatus.ISSUED,
                                InvoiceStatus.PAYMENT_PENDING,
                                InvoiceStatus.OVERDUE,
                            ]
                        ),
                        InvoiceModel.due_at.is_not(None),
                        InvoiceModel.due_at < now,
                    ),
                ),
            )
            .order_by(InvoiceModel.due_at.asc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_period(
        self, organization_id: uuid.UUID, period_year: int, period_month: int
    ) -> InvoiceModel | None:
        result = await self.session.execute(
            select(InvoiceModel).where(
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.period_year == period_year,
                InvoiceModel.period_month == period_month,
                InvoiceModel.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def list_by_organization_id(
        self, organization_id: uuid.UUID, page: int, limit: int
    ) -> tuple[list[InvoiceModel], int]:
        base_filter = (
            InvoiceModel.organization_id == organization_id,
            InvoiceModel.deleted_at.is_(None),
        )
        total = await self.session.scalar(
            select(func.count()).select_from(InvoiceModel).where(*base_filter)
        )
        result = await self.session.execute(
            select(InvoiceModel)
            .where(*base_filter)
            .order_by(InvoiceModel.period_year.desc(), InvoiceModel.period_month.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_by_id_with_organization_name(
        self, id: uuid.UUID
    ) -> tuple[InvoiceModel, str] | None:
        result = await self.session.execute(
            select(InvoiceModel, OrganizationModel.name)
            .join(
                OrganizationModel, OrganizationModel.id == InvoiceModel.organization_id
            )
            .where(InvoiceModel.id == id, InvoiceModel.deleted_at.is_(None))
        )
        return result.first()

    async def list_all_with_organization_name(
        self, page: int, limit: int, organization_id: uuid.UUID | None = None
    ) -> tuple[list[tuple[InvoiceModel, str]], int]:
        filters = [InvoiceModel.deleted_at.is_(None)]
        if organization_id is not None:
            filters.append(InvoiceModel.organization_id == organization_id)

        total = await self.session.scalar(
            select(func.count()).select_from(InvoiceModel).where(*filters)
        )
        result = await self.session.execute(
            select(InvoiceModel, OrganizationModel.name)
            .join(
                OrganizationModel, OrganizationModel.id == InvoiceModel.organization_id
            )
            .where(*filters)
            .order_by(InvoiceModel.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(result.all()), total or 0

    async def mark_overdue(self, now: datetime) -> None:
        await self.session.execute(
            update(InvoiceModel)
            .where(
                InvoiceModel.status == InvoiceStatus.ISSUED,
                InvoiceModel.due_at.is_not(None),
                InvoiceModel.due_at < now,
            )
            .values(**self._touch(status=InvoiceStatus.OVERDUE))
        )

    async def mark_blocked(self, now: datetime) -> None:
        await self.session.execute(
            update(InvoiceModel)
            .where(
                InvoiceModel.status.in_(
                    [InvoiceStatus.OVERDUE, InvoiceStatus.PAYMENT_PENDING]
                ),
                InvoiceModel.block_at.is_not(None),
                InvoiceModel.block_at < now,
            )
            .values(**self._touch(status=InvoiceStatus.BLOCKED))
        )

    # -- Agregaciones globales (dashboard admin, todas las organizaciones) --------
    # Todas usan subtotal_base_amount (siempre USD) en vez de total_amount, ya que
    # este ultimo esta en billing_currency, que varia segun el pais de cada organizacion
    # y no puede sumarse directamente entre organizaciones de distintos paises.

    async def get_revenue_for_period(
        self, period_year: int, period_month: int
    ) -> Decimal:
        result = await self.session.scalar(
            select(func.coalesce(func.sum(InvoiceModel.subtotal_base_amount), 0)).where(
                InvoiceModel.period_year == period_year,
                InvoiceModel.period_month == period_month,
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.notin_(_NON_BILLABLE_STATUSES),
            )
        )
        return Decimal(result or 0)

    async def get_overdue_amount(self) -> Decimal:
        result = await self.session.scalar(
            select(func.coalesce(func.sum(InvoiceModel.subtotal_base_amount), 0)).where(
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.in_([InvoiceStatus.OVERDUE, InvoiceStatus.BLOCKED]),
            )
        )
        return Decimal(result or 0)

    async def count_billed_organizations(
        self, period_year: int, period_month: int
    ) -> int:
        result = await self.session.scalar(
            select(func.count(func.distinct(InvoiceModel.organization_id))).where(
                InvoiceModel.period_year == period_year,
                InvoiceModel.period_month == period_month,
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.notin_(_NON_BILLABLE_STATUSES),
            )
        )
        return result or 0

    async def get_status_breakdown(
        self, period_year: int, period_month: int
    ) -> list[tuple[InvoiceStatus, int, Decimal]]:
        result = await self.session.execute(
            select(
                InvoiceModel.status,
                func.count(),
                func.coalesce(func.sum(InvoiceModel.subtotal_base_amount), 0),
            )
            .where(
                InvoiceModel.period_year == period_year,
                InvoiceModel.period_month == period_month,
                InvoiceModel.deleted_at.is_(None),
            )
            .group_by(InvoiceModel.status)
        )
        return [
            (status, count, Decimal(total)) for status, count, total in result.all()
        ]

    async def get_monthly_revenue(
        self, since_year: int, since_month: int
    ) -> list[tuple[int, int, Decimal]]:
        result = await self.session.execute(
            select(
                InvoiceModel.period_year,
                InvoiceModel.period_month,
                func.coalesce(func.sum(InvoiceModel.subtotal_base_amount), 0),
            )
            .where(
                tuple_(InvoiceModel.period_year, InvoiceModel.period_month)
                >= (since_year, since_month),
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.notin_(_NON_BILLABLE_STATUSES),
            )
            .group_by(InvoiceModel.period_year, InvoiceModel.period_month)
        )
        return [(year, month, Decimal(total)) for year, month, total in result.all()]

    async def get_revenue_by_channel(
        self, since_year: int, since_month: int
    ) -> list[tuple[str, Decimal]]:
        result = await self.session.execute(
            select(
                InvoiceItemModel.channel_name,
                func.coalesce(func.sum(InvoiceItemModel.subtotal_base), 0),
            )
            .join(InvoiceModel, InvoiceModel.id == InvoiceItemModel.invoice_id)
            .where(
                tuple_(InvoiceModel.period_year, InvoiceModel.period_month)
                >= (since_year, since_month),
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status.notin_(_NON_BILLABLE_STATUSES),
            )
            .group_by(InvoiceItemModel.channel_name)
            .order_by(func.sum(InvoiceItemModel.subtotal_base).desc())
        )
        return [(channel_name, Decimal(total)) for channel_name, total in result.all()]

    async def get_revenue_by_provider(
        self, since_year: int, since_month: int
    ) -> list[tuple[str, Decimal]]:
        """Ingreso (subtotal_base_amount) de facturas pagadas, atribuido a la
        pasarela del intento que las pago.
        """
        result = await self.session.execute(
            select(
                InvoicePaymentAttemptModel.provider,
                func.coalesce(func.sum(InvoiceModel.subtotal_base_amount), 0),
            )
            .join(
                InvoicePaymentAttemptModel,
                InvoicePaymentAttemptModel.invoice_id == InvoiceModel.id,
            )
            .where(
                tuple_(InvoiceModel.period_year, InvoiceModel.period_month)
                >= (since_year, since_month),
                InvoiceModel.deleted_at.is_(None),
                InvoiceModel.status == InvoiceStatus.PAID,
                InvoicePaymentAttemptModel.status == PaymentAttemptStatus.PAID,
                InvoicePaymentAttemptModel.deleted_at.is_(None),
            )
            .group_by(InvoicePaymentAttemptModel.provider)
            .order_by(func.sum(InvoiceModel.subtotal_base_amount).desc())
        )
        return [(provider, Decimal(total)) for provider, total in result.all()]
