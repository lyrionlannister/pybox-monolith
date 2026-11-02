"""Membresía de un usuario en una organización."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class OrganizationMembershipModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "membresias_organizacion"
    __table_args__ = (
        # Único parcial (solo entre membresías vivas): con soft-delete, una membresía
        # revocada no debe bloquear volver a invitar al mismo usuario más tarde.
        Index(
            "uq_membresia_usuario_entidad",
            "id_usuario",
            "id_entidad",
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
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=False,
        name="id_entidad",
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        name="creado_por",
        nullable=False,
        index=True,
    )
    is_legal_representative: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, name="es_representante_legal"
    )

    user = relationship(
        "UserModel", foreign_keys=[user_id], back_populates="memberships"
    )
    organization = relationship("OrganizationModel", back_populates="memberships")
    creator = relationship(
        "UserModel", foreign_keys=[created_by], back_populates="created_memberships"
    )
