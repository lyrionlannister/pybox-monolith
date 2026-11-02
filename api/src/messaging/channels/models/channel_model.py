"""Canal de mensajería (SMS, email, WhatsApp, llamada) y su precio unitario."""

from decimal import Decimal

from sqlalchemy import Enum, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.channels.enums.channel_enums import ChannelName, Currency


class ChannelModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "canales"
    __table_args__ = (
        # Único parcial (solo entre canales vivos): con soft-delete, un canal borrado
        # no debe bloquear crear uno nuevo con el mismo nombre.
        Index(
            "uq_canales_nombre",
            "nombre",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
    )

    name: Mapped[ChannelName] = mapped_column(
        Enum(ChannelName), nullable=False, name="nombre"
    )

    currency: Mapped[Currency] = mapped_column(
        Enum(Currency), nullable=False, default=Currency.COP, name="moneda"
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2), nullable=False, name="precio_unitario"
    )

    description: Mapped[str] = mapped_column(
        String(255), nullable=False, name="descripcion"
    )

    label: Mapped[str] = mapped_column(String(50), nullable=False, name="etiqueta")
