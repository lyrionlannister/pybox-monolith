"""Credenciales de WhatsApp Business Cloud API de una organización."""

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class WhatsAppOrgCredentialsModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "whatsapp_credenciales_organizacion"
    __table_args__ = (
        UniqueConstraint(
            "id_organizacion", name="uq_whatsapp_credenciales_organizacion"
        ),
    )

    phone_number_id: Mapped[str] = mapped_column(
        String(50), nullable=False, name="id_numero_telefono"
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="nombre_visible"
    )

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
