"""Endpoints de autenticación: registro, login, tokens y recuperación de cuenta."""

import uuid

from fastapi import Depends, HTTPException, Request, Response, status

from core.config.api_router import APIRouter
from core.security.constants.cookie_constants import REFRESH_TOKEN_COOKIE
from core.security.dependencies import CurrentSession
from core.security.rate_limit import rate_limit
from core.security.utils.cookie_utils import clear_auth_cookies, set_auth_cookies
from identity.auth.dependencies import AuthServiceDep, TokenPayload
from identity.auth.schemas.auth_schemas import (
    AuthResponse,
    ChangePasswordSchema,
    ForgotPasswordLookupResponse,
    ForgotPasswordLookupSchema,
    ForgotPasswordSendCodeSchema,
    ForgotPasswordVerifyCodeSchema,
    ProviderAuth,
    ProviderLogin,
    RefreshRequest,
    ResetPasswordSchema,
    UserCreate,
    UserLogin,
)
from identity.users.dependencies import UserServiceDep
from identity.users.enums.user_enums import UserRole, UserScope

router = APIRouter(prefix="/auth", tags=["Autenticación"])

# Límite por IP: un código OTP de 6 dígitos o un password son vulnerables a fuerza
# bruta sin fricción.
_auth_rate_limit = Depends(rate_limit("auth", max_attempts=20, window_seconds=60))
_forgot_password_rate_limit = Depends(
    rate_limit("forgot-password", max_attempts=8, window_seconds=300)
)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar administrador de organización",
    dependencies=[_auth_rate_limit],
)
async def register_admin(
    body: UserCreate, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.register_and_authenticate(
        body, UserRole.ADMIN, UserScope.ORGANIZATION
    )
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/register/user",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar usuario deudor",
    dependencies=[_auth_rate_limit],
)
async def register_user(
    body: UserCreate, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.register_and_authenticate(
        body, UserRole.USER, UserScope.SELF
    )
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Iniciar sesión con correo y contraseña",
    dependencies=[_auth_rate_limit],
)
async def login(
    body: UserLogin, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.authenticate_user(body)
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/oauth",
    response_model=AuthResponse,
    summary="Registrar administrador con proveedor OAuth",
    dependencies=[_auth_rate_limit],
)
async def oauth_register_admin(
    body: ProviderLogin, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.authenticate_provider_user(
        body, UserRole.ADMIN, UserScope.ORGANIZATION
    )
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/oauth/user",
    response_model=AuthResponse,
    summary="Registrar usuario deudor con proveedor OAuth",
    dependencies=[_auth_rate_limit],
)
async def oauth_register_user(
    body: ProviderLogin, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.authenticate_provider_user(
        body, UserRole.USER, UserScope.SELF
    )
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/oauth/login",
    response_model=AuthResponse,
    summary="Iniciar sesión con proveedor OAuth existente",
    dependencies=[_auth_rate_limit],
)
async def oauth_existing_login(
    body: ProviderAuth, response: Response, service: AuthServiceDep
) -> AuthResponse:
    result = await service.authenticate_existing_provider_user(body)
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post(
    "/refresh", response_model=AuthResponse, summary="Renovar tokens de acceso"
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    body: RefreshRequest | None = None,
) -> AuthResponse:
    refresh_token = (body.refresh_token if body else None) or request.cookies.get(
        REFRESH_TOKEN_COOKIE
    )
    if not refresh_token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "No se encontró un refresh token."
        )
    result = await service.refresh_tokens(refresh_token)
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return result


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Cerrar sesión")
async def logout(
    payload: TokenPayload, response: Response, service: AuthServiceDep
) -> dict:
    await service.logout(uuid.UUID(str(payload["sub"])))
    clear_auth_cookies(response)
    return {"message": "Sesión cerrada."}


@router.post(
    "/logout/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Cerrar sesión de otro usuario (admin)",
)
async def force_logout(
    user_id: uuid.UUID,
    session: CurrentSession,
    service: AuthServiceDep,
    user_service: UserServiceDep,
) -> dict:
    """Cierra la sesión de otro usuario; exige el mismo permiso que gestionarlo, para
    que un admin de una organización no pueda desconectar usuarios de otra."""
    if session.user_id == user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Usa /auth/logout para cerrar tu propia sesión.",
        )
    await user_service.assert_can_manage_user(session, user_id)
    await service.logout(user_id)
    return {"message": "Sesión cerrada."}


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cambiar contraseña",
)
async def change_password(
    body: ChangePasswordSchema, session: CurrentSession, service: AuthServiceDep
) -> None:
    try:
        await service.change_password(
            session.user_id, body.current_password, body.new_password
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post(
    "/forgot-password/lookup",
    response_model=ForgotPasswordLookupResponse,
    summary="Paso 1 — Buscar cuenta por documento",
    dependencies=[_forgot_password_rate_limit],
)
async def forgot_password_lookup(
    body: ForgotPasswordLookupSchema, service: AuthServiceDep
) -> ForgotPasswordLookupResponse:
    result = await service.lookup_user_for_reset(
        body.document_type, body.document_number
    )
    return ForgotPasswordLookupResponse(**result)


@router.post(
    "/forgot-password/send-code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Paso 2 — Enviar código al canal elegido",
    dependencies=[_forgot_password_rate_limit],
)
async def forgot_password_send_code(
    body: ForgotPasswordSendCodeSchema, service: AuthServiceDep
) -> None:
    try:
        await service.send_reset_code(
            body.document_type, body.document_number, body.channel
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


@router.post(
    "/forgot-password/verify-code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Paso 3 — Validar código sin consumirlo",
    dependencies=[_forgot_password_rate_limit],
)
async def forgot_password_verify_code(
    body: ForgotPasswordVerifyCodeSchema, service: AuthServiceDep
) -> None:
    try:
        await service.verify_reset_code(
            body.document_type, body.document_number, body.code, body.channel
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Paso 4 — Nueva contraseña (consume el código)",
    dependencies=[_forgot_password_rate_limit],
)
async def reset_password(body: ResetPasswordSchema, service: AuthServiceDep) -> None:
    try:
        await service.reset_password(
            body.document_type,
            body.document_number,
            body.code,
            body.channel,
            body.new_password,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
