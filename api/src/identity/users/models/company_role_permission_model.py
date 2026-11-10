"""Permiso del catálogo incluido en un rol de empresa."""

import uuid

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CompanyRolePermissionModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "roles_empresa_permisos"
    __table_args__ = (
        # Único parcial (solo entre asignaciones vivas): con soft-delete, quitar un
        # permiso de un rol no debe bloquear volver a agregarlo más tarde.
        Index(
            "uq_rol_empresa_permiso",
            "id_rol_empresa",
            "id_permiso",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
    )

    company_role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles_empresa.id"),
        nullable=False,
        index=True,
        name="id_rol_empresa",
    )
    # Sin ON DELETE CASCADE/SET NULL explícito: el default de Postgres es RESTRICT,
    # así que un permiso del catálogo referenciado por un rol nunca se borra
    # físicamente. Desactivarlo (`PermissionModel.is_active=False`) lo apaga en
    # todos los roles que lo usan sin romper esta FK (ver addendum Bloque B).
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("permisos.id"),
        nullable=False,
        index=True,
        name="id_permiso",
    )
