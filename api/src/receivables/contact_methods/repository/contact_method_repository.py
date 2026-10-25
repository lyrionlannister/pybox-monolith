"""Acceso a datos de los métodos de contacto de un deudor."""

import uuid
from datetime import datetime

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.models.contact_method_model import ContactMethodModel
from receivables.debtors.models.debtor_model import DebtorModel


class ContactMethodRepository(SoftDeleteRepositoryBase[ContactMethodModel]):
    model_class = ContactMethodModel

    async def get_by_debtor_id(self, debtor_id: uuid.UUID) -> list[ContactMethodModel]:
        result = await self.session.execute(
            select(ContactMethodModel).where(
                ContactMethodModel.debtor_id == debtor_id,
                ContactMethodModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_debtor_ids(
        self, debtor_ids: list[uuid.UUID]
    ) -> list[ContactMethodModel]:
        if not debtor_ids:
            return []
        result = await self.session.execute(
            select(ContactMethodModel).where(
                ContactMethodModel.debtor_id.in_(debtor_ids),
                ContactMethodModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_values_by_debtors(
        self, debtor_ids: list[uuid.UUID], contact_type: ContactMethodType
    ) -> dict[uuid.UUID, str]:
        """Resuelve, para cada deudor, un valor de contacto del tipo indicado.

        Devuelve ``{debtor_id: valor_contacto}`` tomando el primer valor no vacío por
        deudor (orden estable por id). Deudores sin contacto de ese tipo quedan fuera.
        """
        if not debtor_ids:
            return {}
        result = await self.session.execute(
            select(ContactMethodModel)
            .where(
                ContactMethodModel.debtor_id.in_(debtor_ids),
                ContactMethodModel.contact_type == contact_type,
                ContactMethodModel.deleted_at.is_(None),
            )
            .order_by(ContactMethodModel.debtor_id, ContactMethodModel.id)
        )
        values: dict[uuid.UUID, str] = {}
        for cm in result.scalars().all():
            value = (cm.contact_value or "").strip()
            if value and cm.debtor_id not in values:
                values[cm.debtor_id] = value
        return values

    async def get_all_values_by_debtors(
        self, debtor_ids: list[uuid.UUID], contact_type: ContactMethodType
    ) -> dict[uuid.UUID, list[str]]:
        """Resuelve, para cada deudor, **todos** los valores de contacto del tipo
        indicado.

        Devuelve ``{debtor_id: [valores...]}`` con los valores no vacíos deduplicados
        por deudor (orden estable por id). Se usa cuando la mensajería debe contactar
        tanto el dato importado por la org como el autogestionado/verificado por el
        titular. Deudores sin contacto quedan fuera.
        """
        if not debtor_ids:
            return {}
        result = await self.session.execute(
            select(ContactMethodModel)
            .where(
                ContactMethodModel.debtor_id.in_(debtor_ids),
                ContactMethodModel.contact_type == contact_type,
                ContactMethodModel.deleted_at.is_(None),
            )
            .order_by(ContactMethodModel.debtor_id, ContactMethodModel.id)
        )
        values: dict[uuid.UUID, list[str]] = {}
        for cm in result.scalars().all():
            value = (cm.contact_value or "").strip()
            if not value:
                continue
            bucket = values.setdefault(cm.debtor_id, [])
            if value not in bucket:
                bucket.append(value)
        return values

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de los métodos de contacto de los deudores de la
        organización con el sello de la organización."""
        await self.soft_delete_where(
            ContactMethodModel.debtor_id.in_(
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
            ContactMethodModel.debtor_id.in_(
                select(DebtorModel.id).where(
                    DebtorModel.organization_id == organization_id
                )
            ),
            deleted_at=deleted_at,
        )
