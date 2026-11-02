"""Catálogo de códigos de tipo de documento (persona y organización)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class DocumentTypeModel(CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Catálogo de códigos de documento (persona + organización). Un código es
    único: el alcance (persona / fiscal / mercantil) y a qué país aplica se define
    en `paises_tipos_documento`, porque un mismo código (NIT, RFC, CUIT…) puede
    servir como documento de persona y como documento fiscal de organización."""

    __tablename__ = "tipos_documento"

    code: Mapped[str] = mapped_column(String(40), primary_key=True, name="codigo")
    label: Mapped[str] = mapped_column(String(150), nullable=False, name="etiqueta")
