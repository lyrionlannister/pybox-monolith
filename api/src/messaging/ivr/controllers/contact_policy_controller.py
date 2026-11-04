"""Proxy de lectura hacia las políticas de contacto de Helena (IVR)."""

from typing import Any

import httpx
from fastapi import HTTPException, status

from core.config.api_router import APIRouter
from core.config.logger import logger
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import require_org_or_global
from messaging.ivr.dependencies import HelenaClientDep

router = APIRouter(prefix="/ivr/contact-policies", tags=["IVR - Políticas de contacto"])


@router.get("/", summary="Listar las políticas de contacto de Helena")
async def list_contact_policies(
    session: CurrentSession,
    client: HelenaClientDep,
) -> Any:
    """Proxy de solo lectura hacia `GET /contact-policies` de Helena.

    Las políticas (ventanas horarias, festivos, excepciones) las administra
    Helena; Pybox solo necesita listarlas para que el diseñador elija cuál
    aplicar al flujo, y guarda el id elegido en `flujos_ivr`.
    """
    require_org_or_global(session)
    try:
        return await client.list_contact_policies()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300] if exc.response is not None else ""
        logger.error("[ivr] contact_policies_http_error | body=%s", detail)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Helena rechazó la consulta de políticas.",
        ) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Cualquier falla no-HTTP de Helena (timeout, conexión) también debe
        # volver como 502 y no como 500 sin manejar.
        logger.error("[ivr] contact_policies_error | error=%s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "No se pudieron consultar las políticas de contacto.",
        ) from exc
