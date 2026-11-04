"""Endpoints del propio usuario: perfil, preferencias, foto y disponibilidad."""

import uuid
from typing import Annotated

from fastapi import File, HTTPException, Query, Response, UploadFile, status

from core.config.api_router import APIRouter
from core.security.constants.permissions import ORG_USERS
from core.security.dependencies import CurrentSession, PendingMfaSession
from core.security.policies.security_policies import (
    require_admin_or_org,
    require_global_admin,
)
from identity.users.dependencies import UserServiceDep
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_preferences_schema import UserToursSchema
from identity.users.schemas.user_schemas import (
    AdminUserDetailSchema,
    AdminUserSummarySchema,
    ChatAvailableUserSchema,
    ProfilePhotoSchema,
    UpdateUserSchema,
)
from identity.users.schemas.user_session_schema import UserSession

router = APIRouter(prefix="/users", tags=["Usuarios"])


@router.get(
    "/me", response_model=UserSession, summary="Obtener sesión del usuario autenticado"
)
async def me(session: PendingMfaSession) -> UserSession:
    """Devuelve la sesión vigente en Redis, sin reconstruirla.

    Admite MFA pendiente (lo consulta `MfaGuard` para decidir si mostrar el
    desafío). Si la sesión no existe responde 401: reconstruirla aquí revivía
    sesiones cerradas por logout o revocación con un token aún vigente; el
    cliente recupera una sesión invalidada vía `/auth/refresh`."""
    return session


@router.get(
    "/me/preferences/tours",
    response_model=UserToursSchema,
    summary="Obtener tours descartados por el usuario",
)
async def get_tour_preferences(
    session: PendingMfaSession, service: UserServiceDep
) -> UserToursSchema:
    dismissed = await service.get_dismissed_tours(session.user_id)
    return UserToursSchema(dismissed_tours=dismissed)


@router.post(
    "/me/preferences/tours/{tour_key}/dismiss",
    response_model=UserToursSchema,
    summary="Descartar un tour de la interfaz",
)
async def dismiss_tour(
    tour_key: str, session: PendingMfaSession, service: UserServiceDep
) -> UserToursSchema:
    dismissed = await service.dismiss_tour(session.user_id, tour_key)
    return UserToursSchema(dismissed_tours=dismissed)


@router.post(
    "/me/preferences/tours/{tour_key}/restore",
    response_model=UserToursSchema,
    summary="Volver a mostrar un tour de la interfaz",
)
async def restore_tour(
    tour_key: str, session: PendingMfaSession, service: UserServiceDep
) -> UserToursSchema:
    dismissed = await service.restore_tour(session.user_id, tour_key)
    return UserToursSchema(dismissed_tours=dismissed)


@router.post(
    "/me/preferences/tours/restore",
    response_model=UserToursSchema,
    summary="Volver a mostrar todos los tours de la interfaz",
)
async def restore_all_tours(
    session: PendingMfaSession, service: UserServiceDep
) -> UserToursSchema:
    dismissed = await service.restore_all_tours(session.user_id)
    return UserToursSchema(dismissed_tours=dismissed)


@router.put(
    "/me/profile-photo",
    response_model=ProfilePhotoSchema,
    summary="Actualizar la foto de perfil",
    description="Sube la imagen (JPG, PNG o WebP) y reemplaza la anterior.",
)
async def update_profile_photo(
    session: CurrentSession,
    service: UserServiceDep,
    file: Annotated[UploadFile, File(description="Imagen a subir")],
) -> ProfilePhotoSchema:
    return await service.update_profile_photo(session.user_id, file)


@router.get(
    "/{user_id}/profile-photo/content",
    summary="Descargar la foto de perfil de un usuario",
    description=(
        "Cualquier sesión autenticada puede ver el avatar de otro usuario "
        "(chats, fichas, tickets). La API trae la imagen del almacén y la "
        "entrega."
    ),
    response_class=Response,
)
async def get_profile_photo_content(
    user_id: uuid.UUID,
    _: CurrentSession,
    service: UserServiceDep,
) -> Response:
    return await service.get_profile_photo_content(user_id)


@router.get(
    "/available-for-chat",
    response_model=list[ChatAvailableUserSchema],
    summary="Listar usuarios disponibles para chat",
)
async def get_available_for_chat(session: CurrentSession, service: UserServiceDep):
    return await service.get_available_for_chat(session)


@router.get(
    "",
    response_model=list[AdminUserSummarySchema],
    summary="Listar usuarios",
    description=(
        "Lista los usuarios accesibles según el rol del solicitante. Soporta "
        "filtro por organización."
    ),
)
async def list_users(
    session: CurrentSession,
    service: UserServiceDep,
    org_id: str | None = Query(None),
    include_deleted: bool = Query(False, alias="includeDeleted"),
):
    # include_deleted es la papelera de Admin Global: si quien pide no lo es, el flag
    # se ignora en silencio en vez de devolver 403 — no vale la pena romper el listado
    # normal de alguien que no tiene el poder, solo no le damos el dato extra.
    show_deleted = include_deleted and session.is_global

    if session.is_global:
        org_ids = [uuid.UUID(org_id)] if org_id else None
        return await service.get_accessible_users(
            org_ids=org_ids, include_deleted=show_deleted
        )

    if session.scope != UserScope.ORGANIZATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado."
        )

    if org_id:
        require_admin_or_org(ORG_USERS, session, org_id)
        org_ids = [uuid.UUID(org_id)]
    else:
        allowed_org_ids = [
            oid
            for oid, entry in session.orgs.items()
            if entry.role == UserRole.ADMIN or ORG_USERS in entry.permissions
        ]
        if not allowed_org_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado."
            )
        org_ids = [uuid.UUID(oid) for oid in allowed_org_ids]

    return await service.get_accessible_users(
        org_ids=org_ids, include_deleted=show_deleted
    )


@router.get(
    "/{user_id}",
    response_model=AdminUserDetailSchema,
    summary="Obtener detalle de usuario",
)
async def get_user(
    user_id: uuid.UUID, session: CurrentSession, service: UserServiceDep
):
    return await service.get_user_detail(session, user_id)


@router.patch(
    "/{user_id}",
    response_model=AdminUserDetailSchema,
    summary="Actualizar datos de usuario",
)
async def update_user(
    user_id: uuid.UUID,
    data: UpdateUserSchema,
    session: CurrentSession,
    service: UserServiceDep,
):
    return await service.update_user(session, user_id, data)


@router.delete(
    "/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar usuario"
)
async def delete_user(
    user_id: uuid.UUID, session: CurrentSession, service: UserServiceDep
):
    if session.user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminarte a ti mismo.",
        )
    await service.soft_delete_user(session, user_id)


@router.post(
    "/{user_id}/restore",
    status_code=status.HTTP_200_OK,
    summary="Restaurar usuario",
    description=(
        "Deshace la baja lógica del usuario, sus membresías y las "
        "organizaciones de las que era único admin. Solo administradores "
        "globales."
    ),
)
async def restore_user(
    user_id: uuid.UUID, session: CurrentSession, service: UserServiceDep
) -> None:
    require_global_admin(session)
    await service.restore_user(user_id)
