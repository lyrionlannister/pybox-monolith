"""Emisión y verificación de JWT de acceso/refresh para la sesión de usuario."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from core.config.logger import logger
from core.tools.config_tools import get_or_throw
from identity.auth.enums.auth_enums import AuthProvider
from identity.users.models.user_model import UserModel


class AuthTokenService:
    ACCESS_TOKEN_EXPIRE_MINUTES = 60
    REFRESH_TOKEN_EXPIRE_DAYS = 7
    ALGORITHM = "HS256"
    # Claim `typ`: access y refresh comparten secreto y algoritmo, así que sin él un
    # refresh token (7 días) también pasaría como access token.
    ACCESS_TOKEN_TYPE = "access"
    REFRESH_TOKEN_TYPE = "refresh"

    def __init__(self, secret_key: str | None = None, redis=None):
        self.secret_key = secret_key or get_or_throw("AUTH_TOKEN_SECRET")
        self._redis = redis

    @property
    def redis(self):
        if self._redis is None:
            # Import perezoso: instanciar el módulo evalúa RedisConfig y exige
            # REDIS_HOST/PORT/PASSWORD ya en el import. Los métodos de tokens
            # que no tocan Redis (generate/verify_access_token) deben poder
            # usarse sin esas variables configuradas.
            from core.database.redis import (  # pylint: disable=import-outside-toplevel
                redis_client,
            )

            self._redis = redis_client
        return self._redis

    def generate_access_token(
        self, user: UserModel, auth_provider: AuthProvider
    ) -> str:
        logger.debug(
            "[token] generate_access | user_id=%s provider=%s",
            user.id,
            auth_provider.value,
        )
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": str(user.id),
                "typ": self.ACCESS_TOKEN_TYPE,
                "email": str(user.email),
                "auth_provider": auth_provider.value,
                "iat": now,
                "exp": now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES),
            },
            self.secret_key,
            algorithm=self.ALGORITHM,
        )
        return token

    async def generate_refresh_token(self, user_id: uuid.UUID) -> str:
        jti = secrets.token_urlsafe(32)
        token = jwt.encode(
            {
                "sub": str(user_id),
                "typ": self.REFRESH_TOKEN_TYPE,
                "jti": jti,
                "exp": datetime.now(timezone.utc)
                + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS),
            },
            self.secret_key,
            algorithm=self.ALGORITHM,
        )
        await self.redis.set(
            f"refresh:{user_id}", jti, self.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
        )
        return token

    def _decode(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.ALGORITHM])
        except jwt.ExpiredSignatureError as e:
            logger.debug("[token] verify_%s | result=expired", expected_type)
            raise ValueError("El token expiró.") from e
        except jwt.InvalidTokenError as e:
            logger.debug(
                "[token] verify_%s | result=invalid error=%s",
                expected_type,
                type(e).__name__,
            )
            raise ValueError("El token no es válido.") from e
        if payload.get("typ") != expected_type or not payload.get("sub"):
            logger.debug("[token] verify_%s | result=wrong_type", expected_type)
            raise ValueError("El token no es válido.")
        return payload

    def verify_access_token(self, token: str) -> dict[str, Any]:
        payload = self._decode(token, self.ACCESS_TOKEN_TYPE)
        logger.debug("[token] verify_access | result=ok user_id=%s", payload.get("sub"))
        return payload

    def verify_refresh_token_jwt(self, token: str) -> dict[str, Any]:
        """Decodifica un refresh token; exige `typ=refresh` y `jti`."""
        payload = self._decode(token, self.REFRESH_TOKEN_TYPE)
        if not payload.get("jti"):
            raise ValueError("El token no es válido.")
        return payload

    async def verify_refresh_token(self, user_id: uuid.UUID, jti: str) -> bool:
        stored = await self.redis.get(f"refresh:{user_id}")
        return stored == jti

    async def revoke_refresh_token(self, user_id: uuid.UUID) -> None:
        await self.redis.delete(f"refresh:{user_id}")

    def verify_token(self, token: str) -> dict[str, Any]:
        return self.verify_access_token(token)
