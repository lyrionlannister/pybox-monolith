"""Acceso a datos de las notificaciones judiciales."""

import uuid
from datetime import datetime
from typing import NamedTuple, Optional, Sequence

from sqlalchemy import func, or_, select, update

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from identity.organizations.models.organization_model import OrganizationModel
from receivables.credits.enums.credit_enums import CreditTypes
from receivables.credits.models.credit_model import CreditModel
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.judicial_notifications.models.judicial_notification_model import (
    JudicialNotificationModel,
)
from receivables.portfolios.models.portfolio_model import PortfolioModel


class JudicialNotificationRow(NamedTuple):
    """Notificación con los datos del crédito y la entidad ya resueltos por join."""

    notification: JudicialNotificationModel
    credit_number: str
    credit_type: CreditTypes
    entity_name: str


class JudicialNotificationRepository(
    SoftDeleteRepositoryBase[JudicialNotificationModel]
):
    model_class = JudicialNotificationModel

    def _debtor_filter(self, debtor_ids: Sequence[uuid.UUID]):
        """El titular ve las notificaciones de sus créditos, sea como deudor o codeudor,
        en cualquiera de sus filas de deudor (una por empresa)."""
        return or_(
            CreditModel.debtor_id.in_(debtor_ids),
            CreditModel.codebtor_id.in_(debtor_ids),
        )

    def _with_credit_and_entity(self):
        return (
            select(
                JudicialNotificationModel,
                CreditModel.credit_number,
                CreditModel.credit_type,
                OrganizationModel.name,
            )
            .join(CreditModel, CreditModel.id == JudicialNotificationModel.credit_id)
            .join(PortfolioModel, PortfolioModel.id == CreditModel.portfolio_id)
            .join(
                OrganizationModel,
                OrganizationModel.id == PortfolioModel.organization_id,
            )
            .where(JudicialNotificationModel.deleted_at.is_(None))
        )

    async def get_inbox_by_debtor_ids(
        self, debtor_ids: Sequence[uuid.UUID]
    ) -> list[JudicialNotificationRow]:
        result = await self.session.execute(
            self._with_credit_and_entity()
            .where(self._debtor_filter(debtor_ids))
            .order_by(JudicialNotificationModel.notified_at.desc())
        )
        return [JudicialNotificationRow(*row) for row in result.all()]

    async def count_unread_by_debtor_ids(self, debtor_ids: Sequence[uuid.UUID]) -> int:
        count = await self.session.scalar(
            select(func.count(JudicialNotificationModel.id))
            .join(CreditModel, CreditModel.id == JudicialNotificationModel.credit_id)
            .where(
                JudicialNotificationModel.deleted_at.is_(None),
                JudicialNotificationModel.is_read.is_(False),
                self._debtor_filter(debtor_ids),
            )
        )
        return count or 0

    async def get_owned_by_debtor(
        self, notification_id: uuid.UUID, debtor_ids: Sequence[uuid.UUID]
    ) -> Optional[JudicialNotificationModel]:
        """Devuelve la notificación solo si pertenece a un crédito del titular indicado.

        Es el filtro que hace cumplir el ownership: si no es suya, el service ve None y
        responde 404 en vez de revelar que existe.
        """
        return await self.session.scalar(
            select(JudicialNotificationModel)
            .join(CreditModel, CreditModel.id == JudicialNotificationModel.credit_id)
            .where(
                JudicialNotificationModel.id == notification_id,
                JudicialNotificationModel.deleted_at.is_(None),
                self._debtor_filter(debtor_ids),
            )
        )

    async def mark_all_read_by_debtor_ids(
        self, debtor_ids: Sequence[uuid.UUID]
    ) -> None:
        credit_ids = select(CreditModel.id).where(self._debtor_filter(debtor_ids))
        await self.session.execute(
            update(JudicialNotificationModel)
            .where(
                JudicialNotificationModel.credit_id.in_(credit_ids),
                JudicialNotificationModel.deleted_at.is_(None),
                JudicialNotificationModel.is_read.is_(False),
            )
            .values(**self._touch(is_read=True))
        )
        await self.session.flush()

    async def get_by_credit_id(
        self, credit_id: uuid.UUID
    ) -> list[JudicialNotificationRow]:
        """Listado del lado de la entidad: lo emitido sobre un crédito."""
        result = await self.session.execute(
            self._with_credit_and_entity()
            .where(JudicialNotificationModel.credit_id == credit_id)
            .order_by(JudicialNotificationModel.notified_at.desc())
        )
        return [JudicialNotificationRow(*row) for row in result.all()]

    async def get_credit_organization_id(
        self, credit_id: uuid.UUID
    ) -> Optional[uuid.UUID]:
        """Entidad dueña del crédito, para el gate de permisos al emitir."""
        return await self.session.scalar(
            select(PortfolioModel.organization_id)
            .join(CreditModel, CreditModel.portfolio_id == PortfolioModel.id)
            .where(CreditModel.id == credit_id, CreditModel.deleted_at.is_(None))
        )

    async def get_credit_recipients(self, credit_id: uuid.UUID) -> list[DebtorModel]:
        """Deudor y codeudor del crédito: exactamente quienes verán la notificación en
        su buzón, según el mismo criterio que `_debtor_filter`."""
        result = await self.session.execute(
            select(DebtorModel)
            .join(
                CreditModel,
                or_(
                    CreditModel.debtor_id == DebtorModel.id,
                    CreditModel.codebtor_id == DebtorModel.id,
                ),
            )
            .where(CreditModel.id == credit_id, DebtorModel.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def get_row_by_id(
        self, notification_id: uuid.UUID
    ) -> Optional[JudicialNotificationRow]:
        """Una notificación con crédito y entidad resueltos, para devolver la
        recién creada."""
        result = await self.session.execute(
            self._with_credit_and_entity().where(
                JudicialNotificationModel.id == notification_id
            )
        )
        row = result.first()
        return JudicialNotificationRow(*row) if row else None

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de las notificaciones judiciales de los créditos de la
        organización."""
        await self.soft_delete_where(
            JudicialNotificationModel.credit_id.in_(
                select(CreditModel.id).where(
                    CreditModel.portfolio_id.in_(
                        select(PortfolioModel.id).where(
                            PortfolioModel.organization_id == organization_id
                        )
                    )
                )
            ),
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Inverso de ``soft_delete_by_organization``: solo lo que cayó con la
        organización."""
        await self.restore_where(
            JudicialNotificationModel.credit_id.in_(
                select(CreditModel.id).where(
                    CreditModel.portfolio_id.in_(
                        select(PortfolioModel.id).where(
                            PortfolioModel.organization_id == organization_id
                        )
                    )
                )
            ),
            deleted_at=deleted_at,
        )
