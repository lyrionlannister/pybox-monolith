"""Helpers de datos compartidos entre módulos de test. No son fixtures (no
dependen de `client`/`db_session`) para poder importarse desde cualquier lado
sin acoplar un test file a otro."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.redis import redis_client
from identity.users.models.user_model import UserModel
from identity.users.schemas.user_session_schema import mfa_verified_key

STRONG_PASSWORD = "Str0ng!Passw0rd"


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def unique_document_number() -> str:
    return str(uuid.uuid4().int)[:9]


def unique_phone() -> str:
    return f"+57{uuid.uuid4().int % 10**10:010d}"


def register_payload(**overrides) -> dict:
    payload = {
        "firstname": "Ana",
        "lastname": "Test",
        "email": unique_email(),
        "password": STRONG_PASSWORD,
        "phone_number": unique_phone(),
        "nationality": "CO",
        "document_type": "CC",
        "document_number": unique_document_number(),
    }
    payload.update(overrides)
    return payload


async def get_user_by_email(db_session: AsyncSession, email: str) -> UserModel:
    result = await db_session.execute(
        select(UserModel).where(UserModel.email == email.lower())
    )
    return result.scalar_one()


async def mark_mfa_verified(user_id: uuid.UUID) -> None:
    """Simula haber pasado el desafío MFA del login vigente (lo que hace
    `OnboardingService.verify_otp` al validar el código). Todo usuario nuevo nace con
    `mfa_habilitado=True`: un test que registra un usuario real y espera acceso
    inmediato a endpoints de negocio (`CurrentSession`) necesita esto, igual que en
    producción necesitaría completar el paso de OTP tras el login."""
    await redis_client.set(mfa_verified_key(user_id), "1", 3600)


# OTP fijo en tests (ver fixture `deterministic_otp` en conftest): la tabla solo
# guarda el HMAC del código, así que los tests no pueden leerlo de la base.
TEST_OTP_CODE = "246810"
