"""Extensión de una plantilla para el canal WhatsApp (metadatos, no el contenido)."""

import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.whatsapp.enums.whatsapp_enums import WhatsAppTemplateCategory


class WhatsAppTemplateDataModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Extensión 1:1 de `plantillas` (TemplateModel) para el canal WHATSAPP.

    No es un espejo de la plantilla: el contenido real (componentes, variables) vive en
    Meta y se consulta en vivo. Aquí solo se guarda lo mínimo para poder crearla,
    referenciarla al enviar y mostrar su estado de aprobación.
    """

    __tablename__ = "datos_plantilla_whatsapp"
    __table_args__ = (
        UniqueConstraint("id_plantilla", name="uq_datos_plantilla_whatsapp_plantilla"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plantillas.id"),
        nullable=False,
        index=True,
        name="id_plantilla",
    )

    meta_template_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="id_plantilla_meta"
    )

    meta_name: Mapped[str] = mapped_column(
        String(255), nullable=False, name="nombre_meta"
    )

    language: Mapped[str] = mapped_column(String(10), nullable=False, name="idioma")

    category: Mapped[WhatsAppTemplateCategory] = mapped_column(
        Enum(WhatsAppTemplateCategory), nullable=False, name="categoria"
    )

    # String libre, no enum: Meta controla ese vocabulario (PENDING/APPROVED/REJECTED/
    # PAUSED/DISABLED/IN_APPEAL...) y puede agregar valores sin previo aviso.
    meta_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", name="estado_meta"
    )
