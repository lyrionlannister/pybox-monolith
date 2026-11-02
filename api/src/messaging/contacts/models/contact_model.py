"""Registro de un envío individual (contacto) y su estado de entrega."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.contacts.enums.contact_enums import ContactStatus, ProviderType


class ContactModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "contactos"

    # Filtros de rango de fecha por organización (facturación por periodo,
    # ContactRepository.get_billing_usage/get_monthly_sends_by_campaign) y
    # ORDER BY sent_at en listados por deudor -- sin este índice compuesto, el
    # índice simple de id_organizacion no alcanza sobre una tabla sin tope de
    # crecimiento (una fila por mensaje enviado).
    __table_args__ = (
        Index("ix_contactos_organizacion_enviado_en", "id_organizacion", "enviado_en"),
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        name="contenido",
    )

    recipient: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        name="destinatario",
    )

    status: Mapped[ContactStatus] = mapped_column(
        Enum(ContactStatus),
        nullable=False,
        default=ContactStatus.PENDING,
        name="estado",
    )

    debtor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=True,
        index=True,
        name="id_deudor",
    )

    debtor_document: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        name="documento_deudor",
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        name="enviado_en",
    )

    provider: Mapped[ProviderType | None] = mapped_column(
        Enum(
            ProviderType,
            name="tipo_proveedor_envio",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
        name="proveedor",
    )

    # Id individual del mensaje en 360NRS (result[].id), usado para matchear el webhook.
    external_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        name="id_externo",
    )

    # Id del lote/envío en 360NRS (sendingId), usado para reconciliar vía
    # reports-by-sending.
    sending_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        name="id_envio",
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        name="error",
    )

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=True,
        index=True,
        name="id_campania",
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        index=True,
        name="id_organizacion",
    )

    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=True,
        index=True,
        name="id_portafolio",
    )

    # Snapshot del canal usado al momento del envío, igual criterio que
    # InvoiceItemModel.channel_id: si el canal cambia o se borra después, este registro
    # histórico de envío no debe cambiar ni romperse. Deliberadamente sin FK.
    snapshot_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=True,
        name="snapshot_canal_id",
    )

    snapshot_currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        name="snapshot_moneda",
    )

    snapshot_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=14, scale=6),
        nullable=True,
        name="snapshot_precio_unitario",
    )
