"""Ejecución guardada (auditoría) de un reporte de cartera."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class ReportExecutionModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Ejecución de un reporte en modo auditoría.

    El CSV resultante vive en `documentos`. Antes se guardaba su id dentro de la columna
    de texto `ruta_archivo` (un "keyless entry": un id de otra tabla en un VARCHAR, sin
    FK que lo respalde). Ahora es `id_documento`, una FK real y UNIQUE contra
    `documentos.id`: no hace falta una tabla de unión porque la relación es 1:1 y esta
    tabla ya es la dueña natural del archivo.
    """

    __tablename__ = "ejecuciones_reportes"

    report_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("reportes.id"),
        nullable=False,
        index=True,
        name="id_reporte",
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
