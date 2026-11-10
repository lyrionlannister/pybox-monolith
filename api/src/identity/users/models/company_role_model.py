"""Rol nombrado que una organización define con un subconjunto del catálogo."""

from sqlalchemy import Boolean, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CompanyRoleModel(
    IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "roles_empresa"
    __table_args__ = (
        # Único parcial (solo entre roles vivos): con soft-delete, un rol borrado no
        # debe bloquear crear otro con el mismo nombre más tarde.
        Index(
            "uq_rol_empresa_organizacion_nombre",
            "id_organizacion",
            "nombre",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
        # Habilita la FK compuesta de UserCompanyRoleModel/CompanyRolePermissionModel
        # (id_organizacion + id_rol_empresa -> roles_empresa.id_organizacion + .id):
        # sin esta unicidad sobre el par, Postgres no puede exigir que el rol
        # asignado pertenezca a la MISMA organización que lo referencia (ver
        # db-schema-design, ítem 8 — FK sin scope de tenant).
        UniqueConstraint(
            "id", "id_organizacion", name="uq_roles_empresa_id_organizacion"
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, name="nombre")
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, name="descripcion"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
