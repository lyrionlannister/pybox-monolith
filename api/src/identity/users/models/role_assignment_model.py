"""Rol de un usuario en un scope (global u organización)."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from identity.users.enums.user_enums import VALID_ROLE_SCOPE, UserRole, UserScope

_CHECK_SQL = " OR ".join(
    f"(rol = '{r.value}' AND alcance = '{s.value}')" for r, s in VALID_ROLE_SCOPE
)


class RoleAssignmentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "roles_asignados"
    __table_args__ = (
        # Único parcial (solo entre asignaciones vivas): con soft-delete, un rol
        # revocado no debe bloquear volver a asignar el mismo rol más tarde.
        Index(
            "uq_rol_usuario_org",
            "id_usuario",
            "rol",
            "id_organizacion",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
        CheckConstraint(_CHECK_SQL, name="ck_rol_alcance_valido"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="id_usuario",
    )
    role: Mapped[UserRole] = mapped_column(
        ENUM(
            UserRole, name="rol_usuario", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        name="rol",
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

    @validates("role", "scope")
    def validate_role_scope(
        self, key: str, value: UserRole | UserScope
    ) -> UserRole | UserScope:
        role = value if key == "role" else self.role
        scope = value if key == "scope" else self.scope
        if (
            role is not None
            and scope is not None
            and (role, scope) not in VALID_ROLE_SCOPE
        ):
            raise ValueError(f"Combinación inválida: {role} + {scope}")
        return value
