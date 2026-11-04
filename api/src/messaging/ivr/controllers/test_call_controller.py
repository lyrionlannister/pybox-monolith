"""Endpoint de prueba para enviar una llamada IVR única a través de Helena."""

from typing import Any

import httpx
from fastapi import HTTPException, status

from core.config.api_router import APIRouter
from core.config.logger import logger
from core.security.dependencies import CurrentSession
from core.database.redis import redis_client
from identity.organizations.dependencies import OrgServiceDep
from messaging.ivr.dependencies import HelenaClientDep, IvrFlowServiceDep
from messaging.ivr.schemas.test_call_schemas import IvrTestCallRequest

router = APIRouter(prefix="/ivr/test-call", tags=["IVR - Prueba"])

TEST_CALLS_PER_HOUR = 20


@router.post("/", summary="Enviar una llamada de prueba de un flujo IVR")
async def send_test_call(
    body: IvrTestCallRequest,
    session: CurrentSession,
    client: HelenaClientDep,
    flow_service: IvrFlowServiceDep,
    org_service: OrgServiceDep,
) -> dict[str, Any]:
    """Marca un único número con el flujo del diseñador.

    La cuenta de Helena es compartida por toda la plataforma, así que se exige lo
    mismo que para editar el flujo (permiso de comunicaciones y acceso al
    portafolio), organización verificada y un tope de llamadas por usuario."""
    organization_id = await flow_service.authorize_portfolio(session, body.portfolio_id)
    await org_service.ensure_verified(organization_id)
    calls = await redis_client.increment(f"ivr-test-call:{session.user_id}", 3600)
    if calls > TEST_CALLS_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Alcanzaste el límite de llamadas de prueba por hora.",
        )

    payload: dict[str, Any] = {
        "phone": body.phone.strip(),
        "campaignId": "TEST",
        "ivrConfig": body.config,
    }
    if body.variables:
        payload["variables"] = body.variables
    if body.customer_name:
        payload["customerName"] = body.customer_name
    if body.customer_document:
        payload["customerDocument"] = body.customer_document
    if body.redial_config:
        payload["redialConfig"] = body.redial_config

    try:
        return await client.send_unique(payload)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response is not None else ""
        logger.error(
            "[ivr] test_call_http_error | status=%s body=%s",
            exc.response.status_code if exc.response is not None else "?",
            detail,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Helena rechazó la llamada de prueba."
        ) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Cualquier falla no-HTTP de Helena (timeout, conexión) también debe
        # volver como 502 y no como 500 sin manejar.
        logger.error("[ivr] test_call_error | error=%s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "No se pudo enviar la llamada de prueba."
        ) from exc
