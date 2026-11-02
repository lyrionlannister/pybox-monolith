"""Relación entre un documento y la notificación judicial a la que pertenece."""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class JudicialNotificationDocumentModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Adjunto de una notificación judicial.

    Tabla de unión por relación, misma solución que `documentos_deudor`: reemplaza
    al par `documentos.ambito='NOTIFICACION_JUDICIAL' + documentos.id_dueno`. Las
    dos FK son reales y unidireccionales, así que no hay ciclo y no hace falta
    `use_alter`.

    Sin columna `categoria`: el viejo enum global tenía un único valor para este ámbito
    (`ADJUNTO_NOTIFICACION_JUDICIAL`), así que la columna no distinguía nada — la propia
    tabla ya dice qué es el documento.
    """

    __tablename__ = "documentos_notificacion_judicial"

    judicial_notification_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("notificaciones_judiciales.id"),
        nullable=False,
        index=True,
        name="id_notificacion_judicial",
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id"),
        nullable=False,
        unique=True,
        name="id_documento",
    )
