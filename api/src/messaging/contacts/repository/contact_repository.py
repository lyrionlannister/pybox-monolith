"""Acceso a datos de los contactos (envíos) y su agregación para billing/reportes."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select, update

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.channels.enums.channel_enums import ChannelName
from messaging.channels.models.channel_model import ChannelModel
from messaging.contacts.enums.contact_enums import ContactStatus, ProviderType
from messaging.contacts.models.contact_model import ContactModel


@dataclass
class CampaignUsageRow:
    campaign_id: uuid.UUID
    campaign_name: str
    channel_id: uuid.UUID
    channel_name: str
    currency: str
    quantity: int
    subtotal: Decimal


class ContactRepository(SoftDeleteRepositoryBase[ContactModel]):
    model_class = ContactModel

    async def get_billing_usage(
        self, organization_id: uuid.UUID, period_start: datetime, period_end: datetime
    ) -> list[CampaignUsageRow]:
        """
        Desglose de consumo facturable por campaña dentro del periodo
        [period_start, period_end). Solo cuenta contactos efectivamente
        enviados (sent_at no nulo) con precio registrado; el costo se suma
        a partir del snapshot de precio de cada envío individual, ya que
        el precio del canal puede haber cambiado durante el periodo.
        """
        stmt = (
            select(
                ContactModel.campaign_id,
                CampaignModel.name,
                ContactModel.snapshot_channel_id,
                ChannelModel.name,
                ContactModel.snapshot_currency,
                func.count(ContactModel.id),
                func.sum(ContactModel.snapshot_unit_price),
            )
            .join(CampaignModel, CampaignModel.id == ContactModel.campaign_id)
            .join(ChannelModel, ChannelModel.id == ContactModel.snapshot_channel_id)
            .where(
                ContactModel.organization_id == organization_id,
                ContactModel.sent_at.is_not(None),
                ContactModel.sent_at >= period_start,
                ContactModel.sent_at < period_end,
                ContactModel.snapshot_unit_price.is_not(None),
            )
            .group_by(
                ContactModel.campaign_id,
                CampaignModel.name,
                ContactModel.snapshot_channel_id,
                ChannelModel.name,
                ContactModel.snapshot_currency,
            )
            .order_by(CampaignModel.name)
        )
        result = await self.session.execute(stmt)
        return [
            CampaignUsageRow(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                channel_id=channel_id,
                channel_name=(
                    channel_name.value
                    if hasattr(channel_name, "value")
                    else channel_name
                ),
                currency=currency or "USD",
                quantity=quantity,
                subtotal=subtotal or Decimal("0"),
            )
            for (
                campaign_id,
                campaign_name,
                channel_id,
                channel_name,
                currency,
                quantity,
                subtotal,
            ) in result.all()
        ]

    async def get_monthly_sends_by_campaign(
        self, organization_id: uuid.UUID, campaign_id: uuid.UUID, period_start: datetime
    ) -> list[tuple[datetime, int]]:
        """Conteo de envios efectivos (sent_at no nulo) agrupado por mes
        desde period_start."""
        month = func.date_trunc("month", ContactModel.sent_at)
        stmt = (
            select(month, func.count(ContactModel.id))
            .where(
                ContactModel.organization_id == organization_id,
                ContactModel.campaign_id == campaign_id,
                ContactModel.sent_at.is_not(None),
                ContactModel.sent_at >= period_start,
            )
            .group_by(month)
            .order_by(month)
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def get_by_debtor(
        self,
        debtor_id: uuid.UUID,
        organization_id: uuid.UUID,
        portfolio_id: uuid.UUID | None = None,
    ) -> Sequence[ContactModel]:
        stmt = (
            select(ContactModel)
            .where(
                ContactModel.debtor_id == debtor_id,
                ContactModel.organization_id == organization_id,
            )
            .order_by(ContactModel.sent_at.desc().nullslast(), ContactModel.id.desc())
        )
        if portfolio_id is not None:
            stmt = stmt.where(ContactModel.portfolio_id == portfolio_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_debtor_grouped_paginated(
        self,
        debtor_id: uuid.UUID,
        organization_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> list[tuple[uuid.UUID | None, str, int, Sequence[ContactModel]]]:
        """Envíos del deudor en el portafolio, agrupados por canal; cada
        canal pagina de forma independiente."""
        base_filters = (
            ContactModel.debtor_id == debtor_id,
            ContactModel.organization_id == organization_id,
            ContactModel.portfolio_id == portfolio_id,
        )

        channels_stmt = (
            select(
                ContactModel.snapshot_channel_id,
                ChannelModel.name,
                func.count(ContactModel.id),
            )
            .outerjoin(
                ChannelModel, ChannelModel.id == ContactModel.snapshot_channel_id
            )
            .where(*base_filters)
            .group_by(ContactModel.snapshot_channel_id, ChannelModel.name)
            .order_by(func.count(ContactModel.id).desc())
        )
        channels_result = await self.session.execute(channels_stmt)

        offset = (page - 1) * page_size
        groups: list[tuple[uuid.UUID | None, str, int, Sequence[ContactModel]]] = []
        for channel_id, channel_name, total in channels_result.all():
            channel_filter = (
                ContactModel.snapshot_channel_id.is_(None)
                if channel_id is None
                else ContactModel.snapshot_channel_id == channel_id
            )
            items_stmt = (
                select(ContactModel)
                .where(*base_filters, channel_filter)
                .order_by(
                    ContactModel.sent_at.desc().nullslast(), ContactModel.id.desc()
                )
                .offset(offset)
                .limit(page_size)
            )
            items_result = await self.session.execute(items_stmt)
            name = (
                channel_name.value
                if hasattr(channel_name, "value")
                else (channel_name or "Sin canal")
            )
            groups.append((channel_id, name, total, items_result.scalars().all()))
        return groups

    async def get_latest_by_recipient_and_org(
        self, recipient: str, organization_id: uuid.UUID
    ) -> ContactModel | None:
        """Último envío hecho a ese destinatario dentro de la organización — usado para
        resolver `debtor_id` por teléfono (best-effort) en flujos de WhatsApp."""
        result = await self.session.execute(
            select(ContactModel)
            .where(
                ContactModel.recipient == recipient,
                ContactModel.organization_id == organization_id,
                ContactModel.debtor_id.is_not(None),
            )
            .order_by(ContactModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_id: str) -> ContactModel | None:
        result = await self.session.execute(
            select(ContactModel).where(ContactModel.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_sending_ids(self) -> Sequence[tuple[str, ChannelName]]:
        stmt = (
            select(ContactModel.sending_id, ChannelModel.name)
            .join(ChannelModel, ChannelModel.id == ContactModel.snapshot_channel_id)
            .where(
                ContactModel.provider == ProviderType.NRS360,
                ContactModel.sending_id.is_not(None),
                ContactModel.status == ContactStatus.SENT,
            )
            .distinct()
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def get_by_sending_and_recipient(
        self, sending_id: str, recipient: str
    ) -> ContactModel | None:
        """Contacto de un envío concreto por destinatario.

        Es la correlación del canal IVR: los eventos de Helena traen `bulkId`
        (= `sending_id`) y `phone` (= `recipient`), pero no la campaña.
        """
        result = await self.session.execute(
            select(ContactModel)
            .where(
                ContactModel.sending_id == sending_id,
                ContactModel.recipient == recipient,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_sending_id(self, sending_id: str) -> Sequence[ContactModel]:
        result = await self.session.execute(
            select(ContactModel).where(ContactModel.sending_id == sending_id)
        )
        return result.scalars().all()

    async def mark_failed_if_sent_bulk(self, contact_ids: Sequence[uuid.UUID]) -> None:
        """Pasa a FAILED, en un solo UPDATE, los contactos dados que sigan en SENT.

        Usado por `IvrStaleService` para cerrar de una vez los contactos ligados a
        interacciones IVR huérfanas, en vez de un SELECT + UPDATE por fila. Los
        contactos que ya cambiaron de estado (p. ej. el webhook llegó justo antes
        del cron) no se tocan, igual que el chequeo `contact.status == SENT` que
        reemplaza.
        """
        if not contact_ids:
            return
        await self.session.execute(
            update(ContactModel)
            .where(
                ContactModel.id.in_(contact_ids),
                ContactModel.status == ContactStatus.SENT,
            )
            .values(**self._touch(status=ContactStatus.FAILED))
        )

    async def get_send_status_counts(
        self, organization_id: uuid.UUID, portfolio_id: uuid.UUID | None = None
    ) -> list[tuple[str, int]]:
        """Conteo de contactos por status; solo devuelve los statuses con
        al menos un registro."""
        filters = [ContactModel.organization_id == organization_id]
        if portfolio_id is not None:
            filters.append(ContactModel.portfolio_id == portfolio_id)
        stmt = (
            select(ContactModel.status, func.count(ContactModel.id))
            .where(*filters)
            .group_by(ContactModel.status)
            .order_by(func.count(ContactModel.id).desc())
        )
        result = await self.session.execute(stmt)
        return [(str(s), c) for s, c in result.all()]

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de los contactos de la organización con el
        sello de la organización."""
        await self.soft_delete_where(
            ContactModel.organization_id == organization_id, deleted_at=deleted_at
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Inverso de ``soft_delete_by_organization``: solo lo que cayó
        con la organización."""
        await self.restore_where(
            ContactModel.organization_id == organization_id, deleted_at=deleted_at
        )
