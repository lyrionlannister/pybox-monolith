"""Ejecución guardada (auditoría) de un segmento de cartera."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import BaseModel


class SegmentExecutionModel(BaseModel):
    """Ejecución de un segmento en modo auditoría.

    El CSV resultante vive en `documentos`. Antes se guardaba su id dentro de la columna
    de texto `ruta_archivo` (un "keyless entry": un id de otra tabla en un VARCHAR, sin
    FK que lo respalde). Ahora es `id_documento`, una FK real y UNIQUE contra
    `documentos.id` -- mismo patrón ya aplicado en `ReportExecutionModel`.
    """

    __tablename__ = "ejecuciones_segmentos"

    segment_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("segmentos.id"),
        nullable=False,
        index=True,
        name="id_segmento",
    )
    mode: Mapped[str] = mapped_column(String, nullable=False, name="modo")
    file_name: Mapped[str | None] = mapped_column(
        String, nullable=True, name="nombre_archivo"
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id"),
        nullable=True,
        unique=True,
        index=True,
        name="id_documento",
    )
    rows: Mapped[int] = mapped_column(Integer, nullable=False, name="filas")
    columns: Mapped[list] = mapped_column(JSONB, nullable=False, name="columnas")
    executed_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="ejecutado_por",
        index=True,
    )
