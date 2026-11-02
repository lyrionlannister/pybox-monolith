"""Dirección física asociada a un deudor."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.debtors.enums.address_enums import AddressType


class AddressModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "direcciones"

    address: Mapped[str] = mapped_column(String, nullable=False, name="direccion")
    city: Mapped[str] = mapped_column(String, nullable=False, name="ciudad")
    state: Mapped[str] = mapped_column(String, nullable=False, name="departamento")
    country: Mapped[str] = mapped_column(String, nullable=False, name="pais")
    address_type: Mapped[AddressType] = mapped_column(
        ENUM(
            AddressType,
            name="tipo_direccion_deudor",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AddressType.PRIMARY,
        name="tipo_direccion",
    )
    debtor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=False,
        index=True,
        name="id_deudor",
    )
