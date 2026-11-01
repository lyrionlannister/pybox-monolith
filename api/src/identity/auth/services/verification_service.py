"""Base común de generación/verificación de OTP, compartida por email y SMS."""

import secrets
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.config.logger import logger
from core.database.redis import redis_client
from core.tools.config_tools import get_or_throw
from identity.auth.enums.notification_enums import VerificationChannel
from identity.auth.exceptions import (
    CodeAlreadyUsedException,
    CodeExpiredException,
    CodeNotFoundException,
)
from identity.auth.models.verification_code_model import VerificationCodeModel
from identity.auth.repository.verification_code_repository import (
    VerificationCodeRepository,
)

EXPIRATION_MINUTES = 5
# Único defensa contra fuerza bruta propia del código (el rate-limit de IP en el
# controller es compartido entre los 4 pasos de forgot-password, no por código): tras
# este número de intentos fallidos con el MISMO código vigente, se invalida como si
# hubiera expirado, obligando a pedir uno nuevo.
MAX_FAILED_ATTEMPTS = 5


class VerificationService(ABC):
    channel: VerificationChannel

    def __init__(self, session: AsyncSession) -> None:
        self._repo = VerificationCodeRepository(session)
        self._session = session

    def _generate_code(self) -> str:
        return str(secrets.randbelow(1_000_000)).zfill(6)

    def _attempts_key(self, user_id: uuid.UUID) -> str:
        return f"otp-attempts:{self.channel.value}:{user_id}"

    async def _assert_not_locked_out(self, user_id: uuid.UUID) -> None:
        raw = await redis_client.get(self._attempts_key(user_id))
        if raw is not None and int(raw) >= MAX_FAILED_ATTEMPTS:
            logger.warning(
                "[verification] locked_out | user_id=%s channel=%s",
                user_id,
                self.channel.value,
            )
            raise CodeExpiredException(
                "Demasiados intentos fallidos. Solicita un código nuevo."
            )

    async def _register_failed_attempt(self, user_id: uuid.UUID) -> None:
        await redis_client.increment(
            self._attempts_key(user_id), EXPIRATION_MINUTES * 60
        )

    async def send_code(self, user) -> None:
        logger.info(
            "[verification] send_code_start | user_id=%s channel=%s",
            user.id,
            self.channel.value,
        )
        code = self._generate_code()
        record = VerificationCodeModel(
            user_id=user.id,
            channel=self.channel,
            code=code,
            expires_at=datetime.now() + timedelta(minutes=EXPIRATION_MINUTES),
        )
        await self._repo.add(record)
        logger.info(
            "[verification] code_record_created | user_id=%s channel=%s expires_at=%s",
            user.id,
            self.channel.value,
            record.expires_at,
        )

        if get_or_throw("ENV") == "development":
            logger.info(
                "[verification] code_sent_dev | user_id=%s channel=%s code=%s",
                user.id,
                self.channel.value,
                code,
            )
            return

        logger.info(
            "[verification] dispatch_start | user_id=%s channel=%s",
            user.id,
            self.channel.value,
        )
        sent = await self._dispatch(user, code)
        logger.info(
            "[verification] dispatch_result | user_id=%s channel=%s sent=%s",
            user.id,
            self.channel.value,
            sent,
        )
        if not sent:
            logger.error(
                "[verification] dispatch_failed | user_id=%s channel=%s",
                user.id,
                self.channel.value,
            )
            raise RuntimeError(
                f"No fue posible enviar el código por {self.channel.value}"
            )

    async def verify_code(self, user_id: uuid.UUID, code: str) -> None:
        await self._assert_not_locked_out(user_id)
        try:
            record = await self._repo.verify_with_exceptions(
                user_id, code, self.channel
            )
            await self._repo.mark_consumed(record)
        except (
            CodeNotFoundException,
            CodeExpiredException,
            CodeAlreadyUsedException,
        ) as exc:
            if isinstance(exc, CodeNotFoundException):
                await self._register_failed_attempt(user_id)
            logger.warning(
                "[verification] verify_failed | user_id=%s channel=%s error=%s",
                user_id,
                self.channel.value,
                type(exc).__name__,
            )
            raise
        await redis_client.delete(self._attempts_key(user_id))

    async def peek_code(self, user_id: uuid.UUID, code: str) -> None:
        """Valida el código sin consumirlo."""
        await self._assert_not_locked_out(user_id)
        try:
            await self._repo.verify_with_exceptions(user_id, code, self.channel)
        except (
            CodeNotFoundException,
            CodeExpiredException,
            CodeAlreadyUsedException,
        ) as exc:
            if isinstance(exc, CodeNotFoundException):
                await self._register_failed_attempt(user_id)
            logger.warning(
                "[verification] peek_failed | user_id=%s channel=%s error=%s",
                user_id,
                self.channel.value,
                type(exc).__name__,
            )
            raise

    @abstractmethod
    async def _dispatch(self, user, code: str) -> bool:
        """Envía el código al destino según el canal."""
