"""Acceso a datos de los códigos de verificación (OTP) y su ciclo de vida."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from core.security.services.encrypt_service import encrypt_service
from identity.auth.enums.notification_enums import VerificationChannel
from identity.auth.exceptions import (
    CodeAlreadyUsedException,
    CodeExpiredException,
    CodeNotFoundException,
)
from identity.auth.models.verification_code_model import VerificationCodeModel


def hash_verification_code(user_id: uuid.UUID, code: str) -> str:
    """HMAC del código ligado al usuario: la tabla nunca guarda el OTP en claro (un
    volcado de la base no debe servir para resetear contraseñas o pasar el MFA)."""
    return encrypt_service.hash_document(f"otp:{user_id}:{code}")


class VerificationCodeRepository(SoftDeleteRepositoryBase[VerificationCodeModel]):
    model_class = VerificationCodeModel

    async def get_active_by_user_and_channel(
        self, user_id: uuid.UUID, code: str, channel: VerificationChannel
    ) -> VerificationCodeModel | None:
        result = await self.session.execute(
            select(VerificationCodeModel).where(
                VerificationCodeModel.user_id == user_id,
                VerificationCodeModel.code == hash_verification_code(user_id, code),
                VerificationCodeModel.channel == channel,
                VerificationCodeModel.consumed_at.is_(None),
                VerificationCodeModel.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()

    async def verify_with_exceptions(
        self, user_id: uuid.UUID, code: str, channel: VerificationChannel
    ) -> VerificationCodeModel:
        result = await self.session.execute(
            select(VerificationCodeModel).where(
                VerificationCodeModel.user_id == user_id,
                VerificationCodeModel.code == hash_verification_code(user_id, code),
                VerificationCodeModel.channel == channel,
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            raise CodeNotFoundException("Código de verificación no encontrado")
        if record.consumed_at is not None:
            raise CodeAlreadyUsedException("El código de verificación ya fue utilizado")
        if record.expires_at <= datetime.now(timezone.utc):
            raise CodeExpiredException("El código de verificación ha expirado")

        return record

    async def mark_consumed(
        self, record: VerificationCodeModel
    ) -> VerificationCodeModel:
        record.consumed_at = datetime.now(timezone.utc)
        return await self.update(record)
