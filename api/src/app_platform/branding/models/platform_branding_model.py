"""Configuración de marca global de la plataforma (fila única)."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class PlatformBrandingModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Fila única de configuración de marca de toda la plataforma (hoy solo el logo
    que se muestra a los usuarios sin organización). `singleton_key` + su CHECK
    garantizan la fila única a nivel de base de datos -- no "el service se encarga de
    que solo haya una".
    """

    __tablename__ = "configuracion_plataforma"
    __table_args__ = (
        CheckConstraint(
            "clave_singleton = 1", name="ck_configuracion_plataforma_singleton"
        ),
    )

    singleton_key: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, unique=True, default=1, name="clave_singleton"
    )

    # Simple, no compuesta: a diferencia de entidades.id_documento_* (que protegen que
    # el documento sea de la MISMA organización), acá no hay tenant que aislar -- el
    # dueño es la plataforma entera. use_alter por el mismo ciclo de FK que
    # usuarios.id_documento_foto_perfil / entidades.id_documento_logo.
    logo_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id", use_alter=True),
        nullable=True,
        name="id_documento_logo",
    )
