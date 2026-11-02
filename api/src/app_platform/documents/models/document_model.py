"""Metadatos de un archivo guardado en el almacén de objetos."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class DocumentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Metadatos de un archivo guardado en el almacén de objetos.

    Los bytes viven en el almacén; acá vive solo lo que describe al ARCHIVO.
    `object_key` es interno: no se expone al cliente, que solo maneja el `id`. Por eso
    no hay ninguna ruta manipulable desde el front y el path traversal deja de ser una
    categoría de bug posible.

    De quién es el documento NO se guarda acá. Antes había un par
    (`ambito`, `id_dueno`) + `categoria`: una asociación polimórfica clásica (Karwin,
    *SQL Antipatterns*) — `id_dueno` no podía tener FK porque apuntaba a cinco tablas
    distintas, y la integridad quedaba "garantizada por el service". Se reemplazó por la
    solución (c) del catálogo: una tabla de unión por relación
    (`documentos_deudor`, `documentos_ticket`, `documentos_portafolio`,
    `documentos_notificacion_judicial`), cada una con FK real a su dueño y a
    `documentos`. Los casos 1:1 (fiscal/mercantil/representante de una entidad, foto de
    perfil, extracto, ejecución de reporte) ya apuntan a `documentos.id` desde su propia
    tabla y no necesitan unión.
    """

    __tablename__ = "documentos"
    __table_args__ = (
        # Habilita la FK compuesta de OrganizationModel (entidades.id_documento_fiscal/
        # mercantil/representante -> documentos.id + documentos.id_organizacion): sin
        # esta unicidad sobre el par, Postgres no puede exigir que el documento apuntado
        # pertenezca a la MISMA organización que lo referencia (ver db-schema-design,
        # ítem 3 — atributo derivado sin invariante protegida).
        UniqueConstraint(
            "id", "id_organizacion", name="uq_documentos_id_id_organizacion"
        ),
    )

    # ── Ubicación en el almacén ──────────────────────────────────────────────
    object_key: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True, name="clave_objeto"
    )

    # ── Aislamiento entre entidades ──────────────────────────────────────────
    # Entidad acreedora dueña del documento, cuando aplica. Es el filtro de aislamiento
    # entre organizaciones; en documentos del titular va nulo.
    #
    # use_alter: `entidades` apunta de vuelta a `documentos` (fiscal, mercantil,
    # representante) y `usuarios` también (foto de perfil), así que hay un ciclo de
    # FK y no existe un orden de CREATE TABLE que lo satisfaga. Marcando este lado,
    # SQLAlchemy lo saca del grafo de dependencias y puede volver a ordenar las tablas.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id", use_alter=True),
        nullable=True,
        index=True,
        name="id_organizacion",
    )

    # ── Datos del archivo ────────────────────────────────────────────────────
    original_name: Mapped[str] = mapped_column(
        String(255), nullable=False, name="nombre_original"
    )
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, name="tipo_contenido"
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, name="tamano_bytes"
    )
    # SHA-256 del contenido. La API ve pasar los bytes, así que puede calcularlo:
    # sirve para detectar duplicados y para probar la integridad de un documento
    # con valor legal.
    checksum: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, name="suma_verificacion"
    )
    # ETag que reporta el almacén, para reconciliar contra él si hiciera falta.
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True, name="etag")

    # use_alter por el mismo ciclo que `organization_id`:
    # usuarios.id_documento_foto_perfil apunta a esta tabla.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id", use_alter=True),
        nullable=True,
        name="subido_por",
        index=True,
    )
