"""Asignación de un rol de empresa a un usuario."""

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class UserCompanyRoleModel(
    IdMixin, TenantMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "usuarios_roles_empresa"
    __table_args__ = (
        # Único parcial (solo entre asignaciones vivas): con soft-delete, revocar un
        # rol no debe bloquear volver a asignarlo más tarde.
        Index(
            "uq_usuario_rol_empresa",
            "id_usuario",
            "id_rol_empresa",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
        # FK compuesta contra (roles_empresa.id, roles_empresa.id_organizacion): un
        # usuario nunca puede quedar asignado a un rol de OTRA organización, reforzado
        # a nivel de constraint y no solo por el chequeo del Service (db-schema-design,
        # ítem 8).
        ForeignKeyConstraint(
            ["id_rol_empresa", "id_organizacion"],
            ["roles_empresa.id", "roles_empresa.id_organizacion"],
            name="fk_usuarios_roles_empresa_rol_organizacion",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        index=True,
        name="id_usuario",
    )
    company_role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        nullable=False,
        index=True,
        name="id_rol_empresa",
    )
