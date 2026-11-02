"""Relación país-tipo de documento y el alcance en que aplica."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app_platform.countries.enums.country_enums import DocumentScope
from core.base.created_at_mixin import CreatedAtMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CountryDocumentTypeModel(CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Relación país ↔ tipo de documento con su alcance. Reemplaza a los dicts
    DOCUMENTS_BY_NATIONALITY (scope=PERSON), ORG_FISCAL_DOCUMENT_BY_NATIONALITY
    (scope=ORG_FISCAL) y ORG_MERCANTILE_DOCUMENT_BY_NATIONALITY (scope=ORG_MERCANTILE).
    Es la fuente que responde 'qué documentos aplican a este país' y valida el alta."""

    __tablename__ = "paises_tipos_documento"

    country_code: Mapped[str] = mapped_column(
        String(2), ForeignKey("paises.codigo"), primary_key=True, name="codigo_pais"
    )
    document_code: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("tipos_documento.codigo"),
        primary_key=True,
        name="codigo_documento",
    )
    scope: Mapped[DocumentScope] = mapped_column(
        ENUM(
            DocumentScope,
            name="alcance_documento",
            values_callable=lambda e: [m.value for m in e],
        ),
        primary_key=True,
        name="alcance",
    )
