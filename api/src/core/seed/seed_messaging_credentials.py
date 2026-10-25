"""Crea las credenciales de mensajería globales a partir de variables de entorno."""

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.logger import logger
from core.security.services.encrypt_service import encrypt_service
from messaging.provider_credentials.enums.provider_credential_enums import (
    MessagingCredentialProvider,
)
from messaging.provider_credentials.models.provider_credential_model import (
    MessagingProviderCredentialModel,
)


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip()


# Credenciales GLOBALES (country_code=None) sembradas desde las env vars actuales.
# Cada spec: (provider, {clave_secreta: env_var}, {clave_publica: env_var}).
_SPECS: list[tuple[MessagingCredentialProvider, dict[str, str], dict[str, str]]] = [
    (
        MessagingCredentialProvider.NRS360_SMS,
        {"token": "NRS360_SMS_TOKEN"},
        {"sender": "NRS360_SMS_SENDER"},
    ),
    (
        MessagingCredentialProvider.NRS360_EMAIL,
        {"token": "NRS360_EMAIL_TOKEN"},
        {"sender": "NRS360_EMAIL_SENDER", "sender_name": "NRS360_EMAIL_SENDER_NAME"},
    ),
    (
        MessagingCredentialProvider.WHATSAPP_CLOUD,
        {
            "access_token": "WHATSAPP_CLOUD_ACCESS_TOKEN",
            "app_secret": "WHATSAPP_CLOUD_APP_SECRET",
        },
        {"waba_id": "WHATSAPP_CLOUD_WABA_ID"},
    ),
]


async def seed_messaging_credentials(session: AsyncSession) -> None:
    existing = {
        (row[0], row[1])
        for row in (
            await session.execute(
                select(
                    MessagingProviderCredentialModel.country_code,
                    MessagingProviderCredentialModel.provider,
                )
            )
        ).all()
    }

    seeded = 0
    for provider, secret_env, public_env in _SPECS:
        if (None, provider) in existing:
            continue
        secret_values = {key: _env(var) for key, var in secret_env.items()}
        # Env parcialmente configurado no debe crear una credencial inválida; se omite
        # y el envío por ese proveedor caerá al fallback de env.
        if any(not value for value in secret_values.values()):
            logger.warning(
                "[seed] messaging_credential_skipped | provider=%s "
                "(secreto faltante en env)",
                provider.value,
            )
            continue
        session.add(
            MessagingProviderCredentialModel(
                country_code=None,
                provider=provider,
                secrets={
                    key: encrypt_service.encrypt_to_str(value)
                    for key, value in secret_values.items()
                },
                public_config={key: _env(var) for key, var in public_env.items()},
            )
        )
        seeded += 1

    logger.info("[seed] messaging_credentials_seeded | nuevos=%d", seeded)
