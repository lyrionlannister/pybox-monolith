"""Código de verificación (OTP) emitido a un usuario por email o SMS."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from identity.auth.enums.notification_enums import VerificationChannel


class VerificationCodeModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "codigos_verificacion"
    __table_args__ = (
        Index(
            "ix_codigos_verificacion_usuario_canal_consumido",
            "id_usuario",
            "canal",
            "consumido_en",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="id_usuario",
    )
    channel: Mapped[VerificationChannel] = mapped_column(
        ENUM(
            VerificationChannel,
            name="canal_verificacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="canal",
    )
    # HMAC-SHA256 en hex (ver `hash_verification_code`), nunca el OTP en claro.
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, name="codigo"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="expira_en"
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="consumido_en"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), name="creado_en"
    )
