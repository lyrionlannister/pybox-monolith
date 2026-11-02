"""Registro de un extracto de cuenta generado para un deudor."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class StatementModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Registro de un extracto generado para un deudor.

    Los bytes del PDF viven en `documentos` (vía DocumentService); acá solo se guarda
    de qué se generó el extracto, para poder listarlo sin depender de la categoría del
    documento. `credit_id` nulo significa extracto consolidado (todos los créditos
    activos del deudor en ese portafolio); con valor, extracto de un crédito puntual.

    `organization_id` (de `TenantMixin`) está denormalizado desde el portafolio: aísla
    por organización sin tener que resolverlo en cada consulta, mismo criterio que
    `DocumentModel.organization_id`.
    """

    __tablename__ = "extractos"

    debtor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=False,
        index=True,
        name="id_deudor",
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )
    credit_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=True,
        index=True,
        name="id_credito",
    )
    cutoff_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="fecha_corte"
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id"),
        nullable=False,
        unique=True,
        name="id_documento",
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        name="generado_por",
        index=True,
    )
