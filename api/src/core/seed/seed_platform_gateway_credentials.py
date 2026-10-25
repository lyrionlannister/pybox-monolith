"""Crea las credenciales de pasarela de pago de la plataforma desde el entorno."""

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.provider_credentials.enums.provider_credential_enums import (
    PlatformGatewayProvider,
)
from billing.provider_credentials.models.provider_credential_model import (
    PlatformGatewayCredentialModel,
)
from core.config.logger import logger
from core.security.services.encrypt_service import encrypt_service


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip()


async def seed_platform_gateway_credentials(session: AsyncSession) -> None:
    """Credenciales de la(s) cuenta(s) PROPIA(S) de PYBOX en una pasarela, para cobrar
    la suscripción/consumo a las organizaciones. No confundir con
    `receivables.payment_gateways`, que es la pasarela de CADA organización para
    cobrarle a sus propios deudores — esa tabla no lleva seed (nace vacía, se llena
    cuando una empresa configura su propia cuenta)."""
    existing = {
        (row[0], row[1])
        for row in (
            await session.execute(
                select(
                    PlatformGatewayCredentialModel.country_code,
                    PlatformGatewayCredentialModel.provider,
                )
            )
        ).all()
    }

    seeded = 0

    # MercadoPago MX: por país (no global), con lookup_key = application_id para que
    # el webhook resuelva la cuenta antes de verificar la firma. secretos =
    # access_token + webhook_secret; no secretos (van al frontend / se buscan por
    # igualdad) = public_key + application_id.
    if ("MX", PlatformGatewayProvider.MERCADOPAGO) not in existing:
        mp_access = _env("MP_ACCESS_TOKEN_MX")
        mp_secret = _env("MP_WEBHOOK_SECRET_MX")
        mp_public = _env("MP_PUBLIC_KEY_MX")
        mp_app_id = _env("MP_APPLICATION_ID_MX")
        if mp_access and mp_secret and mp_app_id:
            session.add(
                PlatformGatewayCredentialModel(
                    country_code="MX",
                    provider=PlatformGatewayProvider.MERCADOPAGO,
                    secrets={
                        "access_token": encrypt_service.encrypt_to_str(mp_access),
                        "webhook_secret": encrypt_service.encrypt_to_str(mp_secret),
                    },
                    public_config={
                        "public_key": mp_public,
                        "application_id": mp_app_id,
                    },
                    lookup_key=mp_app_id,
                )
            )
            seeded += 1
        else:
            logger.warning(
                "[seed] platform_gateway_credential_skipped | "
                "provider=mercadopago MX (env incompleto)"
            )

    logger.info("[seed] platform_gateway_credentials_seeded | nuevos=%d", seeded)
