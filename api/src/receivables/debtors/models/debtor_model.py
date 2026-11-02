"""Deudor de un crédito, propio de una organización."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.debtors.enums.debtor_enums import DebtorType


class DebtorModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "deudores"
    __table_args__ = (
        # El deudor es de UNA empresa: el mismo documento puede existir en varias
        # empresas como filas distintas e independientes (datos de contacto, direcciones
        # y documentos no se comparten). Único global rompía el aislamiento: la carga de
        # una empresa sobrescribía el nombre del deudor de otra y le exponía sus datos.
        UniqueConstraint(
            "id_organizacion",
            "numero_documento_hash",
            name="uq_deudores_organizacion_documento",
        ),
    )

    full_name: Mapped[str] = mapped_column(
        String, nullable=False, name="nombre_completo"
    )
    debtor_type: Mapped[DebtorType] = mapped_column(
        ENUM(
            DebtorType,
            name="tipo_deudor",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="tipo_deudor",
    )
    document_type: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("tipos_documento.codigo"),
        nullable=False,
        name="tipo_documento",
    )
    document_number: Mapped[str] = mapped_column(
        String, nullable=False, name="numero_documento"
    )
    document_number_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, name="numero_documento_hash"
    )
