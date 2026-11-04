"""Acceso a datos de tickets de soporte, con los filtros de acceso por scope."""

import uuid
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import and_, func, or_, select

from app_platform.support.enums.support_enums import SupportTicketStatus
from app_platform.support.models.support_ticket_model import SupportTicketModel
from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel

if TYPE_CHECKING:
    from app_platform.support.schemas.support_schemas import SupportFilter

_TERMINAL = (SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED)


class SupportTicketRepository(SoftDeleteRepositoryBase[SupportTicketModel]):
    model_class = SupportTicketModel

    async def get_by_ticket_number(
        self, ticket_number: int
    ) -> SupportTicketModel | None:
        result = await self.session.execute(
            select(SupportTicketModel).where(
                SupportTicketModel.ticket_number == ticket_number
            )
        )
        return result.scalar_one_or_none()

    async def get_filtered(self, f: "SupportFilter") -> Sequence[SupportTicketModel]:
        conditions = []

        # Access control
        if not f.include_resolved:
            conditions.append(SupportTicketModel.status.notin_(_TERMINAL))
        if f.org_ids is not None:
            conditions.append(SupportTicketModel.organization_id.in_(f.org_ids))
        if f.created_by is not None:
            conditions.append(SupportTicketModel.created_by == f.created_by)
        if f.staff_org_ids is not None:
            conditions.append(
                or_(
                    SupportTicketModel.organization_id.in_(f.staff_org_ids),
                    SupportTicketModel.created_by == f.viewer_id,
                )
            )

        # Search filters
        if f.q:
            term = f"%{f.q}%"
            conditions.append(
                or_(
                    SupportTicketModel.title.ilike(term),
                    SupportTicketModel.notes.ilike(term),
                )
            )
        if f.status_filter is not None:
            conditions.append(SupportTicketModel.status == f.status_filter)
        if f.priority_filter is not None:
            conditions.append(SupportTicketModel.priority == f.priority_filter)
        if f.case_type_filter is not None:
            conditions.append(SupportTicketModel.case_type == f.case_type_filter)
        if f.assigned_to_filter is not None:
            conditions.append(SupportTicketModel.assigned_to == f.assigned_to_filter)
        if f.from_date is not None:
            conditions.append(SupportTicketModel.created_at >= f.from_date)
        if f.to_date is not None:
            conditions.append(SupportTicketModel.created_at <= f.to_date)

        result = await self.session.execute(
            select(SupportTicketModel)
            .where(*conditions)
            .order_by(SupportTicketModel.created_at.desc())
        )
        return result.scalars().all()

    async def get_open_by_org_and_topic(
        self, org_id: uuid.UUID, topic: str
    ) -> SupportTicketModel | None:
        result = await self.session.execute(
            select(SupportTicketModel)
            .where(
                SupportTicketModel.organization_id == org_id,
                SupportTicketModel.system_topic == topic,
                SupportTicketModel.status.notin_(_TERMINAL),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_metrics_data(
        self,
        org_ids: list[uuid.UUID] | None = None,
        created_by: uuid.UUID | None = None,
        staff_org_ids: list[uuid.UUID] | None = None,
        viewer_id: uuid.UUID | None = None,
    ) -> Sequence[SupportTicketModel]:
        conditions = []
        if org_ids is not None:
            conditions.append(SupportTicketModel.organization_id.in_(org_ids))
        if created_by is not None:
            conditions.append(SupportTicketModel.created_by == created_by)
        if staff_org_ids is not None:
            conditions.append(
                or_(
                    SupportTicketModel.organization_id.in_(staff_org_ids),
                    SupportTicketModel.created_by == viewer_id,
                )
            )
        result = await self.session.execute(
            select(SupportTicketModel).where(*conditions)
        )
        return result.scalars().all()

    async def find_least_loaded_cs_org(self, org_id: uuid.UUID) -> int | None:
        stmt = (
            select(RoleAssignmentModel.user_id)
            .outerjoin(
                SupportTicketModel,
                and_(
                    SupportTicketModel.assigned_to == RoleAssignmentModel.user_id,
                    SupportTicketModel.status.notin_(_TERMINAL),
                ),
            )
            .where(
                RoleAssignmentModel.role == UserRole.CUSTOMER_SERVICE,
                RoleAssignmentModel.scope == UserScope.ORGANIZATION,
                RoleAssignmentModel.organization_id == org_id,
            )
            .group_by(RoleAssignmentModel.user_id)
            .order_by(func.count(SupportTicketModel.id).asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_least_loaded_cs_global(self) -> int | None:
        stmt = (
            select(RoleAssignmentModel.user_id)
            .outerjoin(
                SupportTicketModel,
                and_(
                    SupportTicketModel.assigned_to == RoleAssignmentModel.user_id,
                    SupportTicketModel.status.notin_(_TERMINAL),
                ),
            )
            .where(
                RoleAssignmentModel.role == UserRole.CUSTOMER_SERVICE,
                RoleAssignmentModel.scope == UserScope.GLOBAL,
            )
            .group_by(RoleAssignmentModel.user_id)
            .order_by(func.count(SupportTicketModel.id).asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
