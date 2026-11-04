"""Policies de autorización: quién puede ver/gestionar qué según scope y ownership."""

import uuid
from typing import Awaitable, Callable, Protocol

from fastapi import HTTPException, status

from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import IdentityVerificationStatus, UserRole
from identity.users.schemas.user_session_schema import UserSession

# Tupla (document_type, document_number_hash) usada para filtrar queries de deudores.
# El segundo valor ya es el hash (get_by_document espera hash, no el número en claro).
SelfIdentity = tuple[str, str]


class _OwnedByOrganization(Protocol):
    organization_id: uuid.UUID


class _VerifiableOrganization(Protocol):
    verification_status: VerificationStatus


def require_global(session: UserSession) -> None:
    if not session.is_global:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo usuarios globales pueden realizar esta acción",
        )


def require_global_admin(session: UserSession) -> None:
    if not session.is_global or session.role != UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Acceso restringido a administradores globales"
        )


def require_org_or_global(session: UserSession) -> None:
    if not session.is_global and not session.orgs:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso")


def require_org_admin(session: UserSession, org_id: str) -> None:
    if session.is_global:
        return
    org_entry = session.orgs.get(org_id)
    if org_entry is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta organización")
    if org_entry.role != UserRole.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo administradores pueden realizar esta acción",
        )


def require_permission(perm: str, session: UserSession, org_id: str) -> None:
    if session.is_global:
        return
    ctx = session.orgs.get(org_id)
    if not ctx:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta organización")
    if perm not in ctx.permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "No tienes permisos para esta acción"
        )


def has_permission(perm: str, session: UserSession, org_id: str) -> bool:
    """Versión booleana de `require_permission` (mismo criterio) para decidir qué
    datos mostrar en una operación que el usuario ya está autorizado a hacer, sin
    cortarla."""
    if session.is_global:
        return True
    ctx = session.orgs.get(org_id)
    return ctx is not None and perm in ctx.permissions


def require_admin_or_org(perm: str, session: UserSession, org_id: str) -> None:
    """Permite el acceso si el usuario es global, admin de la organización, o tiene
    el permiso indicado."""
    if session.is_global:
        return
    org_entry = session.orgs.get(org_id)
    if org_entry is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta organización")
    if org_entry.role == UserRole.ADMIN:
        return
    if perm not in org_entry.permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "No tienes permisos para esta acción"
        )


def require_org_visibility(
    session: UserSession, org_id: str, detail: str = "Recurso no encontrado"
) -> None:
    """404 (no 403) para quien no pertenece a la organización dueña del recurso.

    Un 403 distinto de "no existe" deja enumerar qué IDs de otro tenant existen. Va
    ANTES de los chequeos de rol/permiso: esos sí dan 403, pero solo a quien ya es
    miembro."""
    if session.is_global:
        return
    if org_id not in session.orgs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)


def require_org_access(session: UserSession, org_id: str) -> None:
    if session.is_global:
        return
    if org_id not in session.orgs:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta organización")


def require_verified_org(org: _VerifiableOrganization | None) -> None:
    """Una organizacion pending/denied no deberia poder crear ni modificar
    portafolios."""
    if org is None or org.verification_status != VerificationStatus.APPROVED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "La organización debe estar verificada para gestionar portafolios",
        )


def require_self(session: UserSession) -> None:
    """Solo usuarios con scope SELF (el titular/deudor) pueden ejecutar la acción."""
    if not session.is_self:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo el titular puede realizar esta acción"
        )


def require_verified_identity(session: UserSession) -> None:
    """El titular SELF debe tener su identidad aprobada por Atención al Cliente.

    Conocer el tipo+número de documento de alguien no es secreto, así que ser deudor
    conocido no basta para operar sobre sus obligaciones (pagos, acuerdos,
    documentos)."""
    if session.identity_verification_status != IdentityVerificationStatus.APPROVED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verificación de identidad pendiente. Sube tu documento de "
            "identidad para acceder a tu información crediticia.",
        )


def get_self_identity(session: UserSession) -> SelfIdentity:
    if not session.document_type or not session.document_number_hash:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Completa tu documento de identidad para continuar",
        )
    return session.document_type, session.document_number_hash


async def check_portfolio_org_access(
    user_session: UserSession,
    portfolio: _OwnedByOrganization | None,
    permission: str,
) -> uuid.UUID:
    """Valida que el portafolio exista y que el usuario tenga el permiso indicado
    sobre la organización dueña. Usado por los módulos que operan "dentro" de un
    portafolio (campañas, plantillas, segmentos) para no duplicar esta lógica.
    """
    if portfolio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado")
    if not user_session.is_global:
        require_org_visibility(
            user_session, str(portfolio.organization_id), "Portafolio no encontrado"
        )
        require_permission(permission, user_session, str(portfolio.organization_id))
    return portfolio.organization_id


async def require_portfolio_access(
    session: UserSession,
    org_id: str,
    portfolio_id: uuid.UUID,
    check_access: Callable[[uuid.UUID, uuid.UUID, str], Awaitable[bool]],
) -> None:
    if session.is_global:
        return
    org_entry = session.orgs.get(org_id)
    if org_entry is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a esta organización")
    if org_entry.role == UserRole.ADMIN:
        return
    allowed = await check_access(session.user_id, portfolio_id, org_id)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin acceso a este portafolio")
