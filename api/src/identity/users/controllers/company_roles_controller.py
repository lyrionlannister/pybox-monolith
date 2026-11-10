"""Endpoints de roles de empresa: alta, edición y asignación a usuarios."""

import uuid

from fastapi import status

from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession
from identity.users.dependencies import CompanyRoleServiceDep
from identity.users.schemas.company_role_schemas import (
    CompanyRoleCreate,
    CompanyRoleResponse,
    CompanyRoleUpdate,
)

router = APIRouter(
    prefix="/organizations/{org_id}/company-roles", tags=["Roles de empresa"]
)


@router.get("", response_model=list[CompanyRoleResponse], summary="Listar roles")
async def list_roles(
    org_id: uuid.UUID, session: CurrentSession, service: CompanyRoleServiceDep
):
    return await service.list_roles(session, org_id)


@router.post(
    "",
    response_model=CompanyRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear rol de empresa",
)
async def create_role(
    org_id: uuid.UUID,
    data: CompanyRoleCreate,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    return await service.create_role(session, org_id, data)


@router.patch(
    "/{role_id}",
    response_model=CompanyRoleResponse,
    summary="Actualizar rol de empresa",
)
async def update_role(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    data: CompanyRoleUpdate,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    return await service.update_role(session, org_id, role_id, data)


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar rol de empresa",
)
async def delete_role(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    await service.delete_role(session, org_id, role_id)


@router.get(
    "/{role_id}/users",
    response_model=list[uuid.UUID],
    summary="Listar usuarios asignados a un rol de empresa",
)
async def list_role_users(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    return await service.list_assigned_user_ids(session, org_id, role_id)


@router.post(
    "/{role_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Asignar rol de empresa a un usuario",
)
async def assign_user(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    user_id: uuid.UUID,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    await service.assign_user(session, org_id, role_id, user_id)


@router.delete(
    "/{role_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revocar rol de empresa a un usuario",
)
async def unassign_user(
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    user_id: uuid.UUID,
    session: CurrentSession,
    service: CompanyRoleServiceDep,
):
    await service.unassign_user(session, org_id, role_id, user_id)
