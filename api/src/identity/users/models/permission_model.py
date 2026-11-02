"""Catálogo de permisos granulares configurables del sistema."""

from sqlalchemy import Boolean, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class PermissionModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "permisos"

    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, name="nombre"
    )
    label: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="etiqueta"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, name="descripcion"
    )
    max_level_access: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, name="nivel_acceso_maximo"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
