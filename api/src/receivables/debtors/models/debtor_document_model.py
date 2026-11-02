"""Documento del repositorio documental de un deudor."""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.debtors.enums.debtor_document_enums import DebtorDocumentCategory


class DebtorDocumentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Documento del repositorio documental de un deudor.

    Tabla de unión por relación (solución (c) del catálogo de asociaciones
    polimórficas): reemplaza al par `documentos.ambito='DEUDOR' +
    documentos.id_dueno`, que no podía tener FK real porque `id_dueno` apuntaba a
    cinco tablas distintas. Acá las dos FK son reales y unidireccionales —
    `deudores` y `documentos` no apuntan de vuelta, así que no hay ciclo y no hace
    falta `use_alter`.

    `id_documento` es UNIQUE: un archivo pertenece a un solo deudor. Eso también deja la
    relación como 1:1 del lado del documento, que es lo que hacía cierto el viejo
    `id_dueno` único sin poder declararlo.
    """

    __tablename__ = "documentos_deudor"

    debtor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=False,
        index=True,
        name="id_deudor",
    )
    category: Mapped[DebtorDocumentCategory] = mapped_column(
        ENUM(
            DebtorDocumentCategory,
            name="categoria_documento_deudor",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        name="categoria",
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id"),
        nullable=False,
        unique=True,
        name="id_documento",
    )
