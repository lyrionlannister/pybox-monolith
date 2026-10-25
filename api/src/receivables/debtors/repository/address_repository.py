"""Acceso a datos de las direcciones de un deudor."""

import uuid
from datetime import datetime

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.debtors.models.address_model import AddressModel
from receivables.debtors.models.debtor_model import DebtorModel


class AddressRepository(SoftDeleteRepositoryBase[AddressModel]):
    model_class = AddressModel

    async def get_by_debtor_id(self, debtor_id: uuid.UUID) -> list[AddressModel]:
        result = await self.session.execute(
            select(AddressModel).where(
                AddressModel.debtor_id == debtor_id,
                AddressModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_debtor_ids(
        self, debtor_ids: list[uuid.UUID]
    ) -> list[AddressModel]:
        if not debtor_ids:
            return []
        result = await self.session.execute(
            select(AddressModel).where(
                AddressModel.debtor_id.in_(debtor_ids),
                AddressModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de las direcciones de los deudores de la organización con
        el sello de la organización."""
        await self.soft_delete_where(
            AddressModel.debtor_id.in_(
                select(DebtorModel.id).where(
                    DebtorModel.organization_id == organization_id
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
            AddressModel.debtor_id.in_(
                select(DebtorModel.id).where(
                    DebtorModel.organization_id == organization_id
                )
            ),
            deleted_at=deleted_at,
        )
