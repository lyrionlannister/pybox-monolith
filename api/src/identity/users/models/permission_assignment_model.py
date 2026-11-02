"""Permiso granular otorgado/denegado a un usuario en un scope específico."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from identity.users.enums.user_enums import PermissionEffect, UserScope


class PermissionAssignmentModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "permisos_asignados"
    __table_args__ = (
        # Único parcial (solo entre asignaciones vivas): con soft-delete, un permiso
        # revocado no debe bloquear volver a otorgar el mismo permiso más tarde.
        Index(
            "uq_permiso_usuario_scope",
            "id_usuario",
            "id_permiso",
            "alcance",
            "id_organizacion",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="id_usuario",
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("permisos.id"),
        nullable=False,
        index=True,
        name="id_permiso",
    )
    scope: Mapped[UserScope] = mapped_column(
        ENUM(
            UserScope,
            name="alcance_usuario",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="alcance",
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        index=True,
        name="id_organizacion",
    )
    effect: Mapped[PermissionEffect] = mapped_column(
        ENUM(
            PermissionEffect,
            name="efecto_permiso",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PermissionEffect.GRANT,
        name="efecto",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
