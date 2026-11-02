"""Definición de un reporte de cartera (criterio dinámico de consulta)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class ReportModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "reportes"

    name: Mapped[str] = mapped_column(String, nullable=False, name="nombre")
    description: Mapped[str | None] = mapped_column(
        String, nullable=True, name="descripcion"
    )
    report_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, name="configuracion_reporte"
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        index=True,
        name="id_entidad",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, name="es_global"
    )
    category: Mapped[str | None] = mapped_column(
        String, nullable=True, name="categoria"
    )
