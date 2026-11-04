"""Dependencias de FastAPI para resolver la sesión (cookie/SSE/WebSocket) y el MFA."""

import time
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, WebSocket, status
from pydantic import ValidationError as PydanticValidationError

from core.config.redis_config import RedisConfig
from core.database.redis import redis_client
from core.security.constants.cookie_constants import ACCESS_TOKEN_COOKIE
from core.security.services.auth_token_service import AuthTokenService
from core.security.utils.service_key_verifier import verify_n8n_service_key
from core.tools.config_tools import get_or_throw
from identity.auth.dependencies import TokenPayload
from identity.users.schemas.user_session_schema import (
    UserSession,
    mfa_verified_key,
    session_key,
)

_sse_token_service = AuthTokenService()


def _resolve_stream_token(connection: Request | WebSocket) -> str:
    """El token de acceso de un stream (SSE/WebSocket) sale SOLO de la cookie httpOnly.

    Aceptarlo también por query string (`?token=`) lo dejaría en logs de acceso,
    proxies e historial del navegador; `EventSource` y `WebSocket` adjuntan la cookie
    solos."""
    token = connection.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido."
        )
    return token


def _subject_to_uuid(payload: TokenPayload) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido."
        ) from e


async def _load_session(user_id: uuid.UUID) -> UserSession:
    key = session_key(user_id)
    try:
        session = await redis_client.get_json(key, UserSession)
    except PydanticValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tu sesión no es válida. Inicia sesión nuevamente.",
        ) from e
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión expirada. Inicia sesión nuevamente.",
        )
    await redis_client.expire(key, RedisConfig.DEFAULT_TTL)
    return session


async def _require_mfa_verified(session: UserSession) -> UserSession:
    """Exige que el segundo factor ya se haya superado en el login vigente.

    El token/cookie de acceso se emite completo desde el login (ver
    `AuthService._build_response`): sin este chequeo, el MFA solo bloquea la UI de
    React y cualquiera con la contraseña correcta tiene acceso completo a la API
    saltándose el segundo factor. `mfa_verified_key` lo setea
    `OnboardingService.verify_otp` al validar el código, y `_build_response` lo borra
    en cada login nuevo (no en refresh) para que un login nuevo siempre lo vuelva a
    exigir."""
    if session.mfa_enabled and not await redis_client.get(
        mfa_verified_key(session.user_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verificación de dos pasos pendiente.",
        )
    return session


async def get_session(payload: TokenPayload) -> UserSession:
    session = await _load_session(_subject_to_uuid(payload))
    return await _require_mfa_verified(session)


async def get_pending_mfa_session(payload: TokenPayload) -> UserSession:
    """Igual que `get_session` pero sin exigir el segundo factor.

    La usan exclusivamente los endpoints de onboarding (incluidos request/verify-otp):
    son justo los que deben quedar accesibles mientras el MFA sigue pendiente, ya sea
    porque el usuario todavía está completando su registro o porque está resolviendo
    el propio desafío de MFA."""
    return await _load_session(_subject_to_uuid(payload))


async def get_sse_session(request: Request) -> UserSession:
    resolved_token = _resolve_stream_token(request)
    try:
        payload = _sse_token_service.verify_token(resolved_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido."
        ) from e
    session = await _load_session(_subject_to_uuid(payload))
    return await _require_mfa_verified(session)


WS_SESSION_RECHECK_SECONDS = 60


def _allowed_ws_origins() -> set[str]:
    return {o.strip() for o in get_or_throw("CORS_ORIGINS").split(",") if o.strip()}


async def get_ws_session(websocket: WebSocket) -> UserSession:
    """Autentica un WebSocket por la cookie de acceso.

    Los WebSockets no pasan por CORS: sin validar `Origin`, una página de otro
    origen (p. ej. un subdominio hermano) podría abrir el socket con la cookie de
    la víctima. Un cliente sin `Origin` no es un navegador y no corre ese riesgo."""
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in _allowed_ws_origins():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Origen no permitido."
        )
    resolved_token = _resolve_stream_token(websocket)
    try:
        payload = _sse_token_service.verify_token(resolved_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido."
        ) from e
    session = await _load_session(_subject_to_uuid(payload))
    return await _require_mfa_verified(session)


class WsSessionGuard:
    """Revalida periódicamente la sesión de un WebSocket abierto: sin esto, un
    logout, una desactivación o la pérdida de acceso a la organización no cortaban
    el socket ya conectado. Devuelve la sesión vigente (con permisos actualizados)
    o lanza HTTPException si ya no es válida."""

    def __init__(self, session: UserSession) -> None:
        self.session = session
        self._checked_at = time.monotonic()

    async def current(self) -> UserSession:
        if time.monotonic() - self._checked_at >= WS_SESSION_RECHECK_SECONDS:
            refreshed = await _load_session(self.session.user_id)
            self.session = await _require_mfa_verified(refreshed)
            self._checked_at = time.monotonic()
        return self.session


async def require_n8n_service_key(
    x_service_key: Annotated[str | None, Header()] = None,
) -> None:
    """Gate de ruta para los endpoints internos que consume n8n (sin sesión de
    usuario)."""
    if not verify_n8n_service_key(x_service_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service key"
        )


CurrentSession = Annotated[UserSession, Depends(get_session)]
PendingMfaSession = Annotated[UserSession, Depends(get_pending_mfa_session)]
SSESession = Annotated[UserSession, Depends(get_sse_session)]
