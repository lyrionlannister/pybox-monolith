"""Dependencias de FastAPI para SupportService y el filtro de acceso del usuario."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.support.enums.support_enums import (
    SupportCaseType,
    SupportTicketPriority,
    SupportTicketStatus,
)
from app_platform.support.schemas.support_schemas import SupportFilter
from app_platform.support.services.support_service import SupportService
from core.database.database import get_main_session
from core.security.dependencies import CurrentSession
from identity.users.enums.user_enums import UserRole, UserScope

_STAFF_ROLES = {UserRole.ADMIN, UserRole.CUSTOMER_SERVICE}

_STATUS_MAP = {s.value: s for s in SupportTicketStatus}

_PRIORITY_MAP = {p.value: p for p in SupportTicketPriority}

_CASE_TYPE_MAP = {ct.value: ct for ct in SupportCaseType}


def get_support_filter(
    session: CurrentSession,
    include_resolved: bool = Query(False, alias="includeResolved"),
    q: str | None = Query(None, description="Búsqueda en título y notas"),
    status_param: str | None = Query(None, alias="status"),
    priority_param: str | None = Query(None, alias="priority"),
    case_type_param: str | None = Query(None, alias="caseType"),
    assigned_to_param: int | None = Query(None, alias="assignedTo"),
    from_date_param: datetime | None = Query(None, alias="fromDate"),
    to_date_param: datetime | None = Query(None, alias="toDate"),
) -> SupportFilter:
    search = {
        "q": q or None,
        "status_filter": _STATUS_MAP.get(status_param) if status_param else None,
        "priority_filter": (
            _PRIORITY_MAP.get(priority_param) if priority_param else None
        ),
        "case_type_filter": (
            _CASE_TYPE_MAP.get(case_type_param) if case_type_param else None
        ),
        "assigned_to_filter": assigned_to_param,
        "from_date": from_date_param,
        "to_date": to_date_param,
    }

    # Global scope: role is set at session level
    if session.scope == UserScope.GLOBAL:
        is_admin = session.role == UserRole.ADMIN
        return SupportFilter(
            include_resolved=include_resolved,
            can_resolve=session.role in _STAFF_ROLES,
            can_assign=is_admin,
            can_create=True,
            can_escalate=True,
            route_to_global=True,
            **search,
        )

    # Org scope: role is per-org (session.role is None for org users)
    if session.scope == UserScope.ORGANIZATION:
        org_roles = {entry.role for entry in session.orgs.values()}
        org_ids = [uuid.UUID(o) for o in session.orgs]
        if org_roles & _STAFF_ROLES:
            is_admin = UserRole.ADMIN in org_roles
            is_cs = UserRole.CUSTOMER_SERVICE in org_roles
            staff_org_ids = [
                uuid.UUID(o)
                for o, entry in session.orgs.items()
                if entry.role in _STAFF_ROLES
            ]
            mixed_roles = len(staff_org_ids) < len(org_ids)
            return SupportFilter(
                org_ids=org_ids,
                staff_org_ids=staff_org_ids if mixed_roles else None,
                viewer_id=session.user_id if mixed_roles else None,
                include_resolved=include_resolved,
                can_resolve=is_cs,
                can_assign=is_admin or is_cs,
                can_create=True,
                can_escalate=is_cs,
                route_to_global=is_cs,
                **search,
            )
        # Non-staff org user (USER ORG)
        return SupportFilter(
            org_ids=org_ids,
            created_by=session.user_id,
            include_resolved=True,
            can_create=True,
            **search,
        )

    # Self scope (end users / debtors)
    if session.scope == UserScope.SELF:
        return SupportFilter(
            created_by=session.user_id,
            include_resolved=True,
            can_create=True,
            check_portfolio_access=True,
            **search,
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado."
    )


def get_support_service(
    db: Annotated[AsyncSession, Depends(get_main_session)],
) -> SupportService:
    return SupportService(db)


SupportServiceDep = Annotated[SupportService, Depends(get_support_service)]
SupportAccessFilter = Annotated[SupportFilter, Depends(get_support_filter)]
