"""Ciclo de vida de los tickets de soporte: alta, mensajes, resolución y adjuntos."""

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.services.document_service import DocumentService
from app_platform.notifications.services.notification_service import NotificationService
from app_platform.support.enums.support_enums import (
    IdentityTopic,
    IncidentTopic,
    PaymentTopic,
    RequirementTopic,
    SupportCaseType,
    SupportTicketEventType,
    SupportTicketPriority,
    SupportTicketStatus,
    TicketDocumentCategory,
)
from app_platform.support.models.support_ticket_event_model import (
    SupportTicketEventModel,
)
from app_platform.support.models.support_ticket_message_model import (
    SupportTicketMessageModel,
)
from app_platform.support.models.support_ticket_model import SupportTicketModel
from app_platform.support.models.ticket_document_model import TicketDocumentModel
from app_platform.support.repository.support_event_repository import (
    SupportEventRepository,
)
from app_platform.support.repository.support_message_repository import (
    SupportMessageRepository,
)
from app_platform.support.repository.support_ticket_repository import (
    SupportTicketRepository,
)
from app_platform.support.repository.ticket_document_repository import (
    TICKET_DOCUMENT_STORAGE_DOMAIN,
    TicketDocumentRepository,
)
from app_platform.support.schemas.support_schemas import (
    AssignTicketSchema,
    CreateMessageSchema,
    CreateTicketSchema,
    OrgDocSchema,
    OrgDocsSchema,
    ResolveTicketSchema,
    SupportFilter,
    SupportTicketSchema,
    TicketAttachmentSchema,
    TicketCategorySchema,
    TicketEventSchema,
    TicketMessageSchema,
    TicketMetricsSchema,
    TicketOrgSchema,
    UpdateTicketPrioritySchema,
    UpdateTicketStatusSchema,
)
from core.database.redis import redis_client
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import IdentityVerificationStatus
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import UserSession, session_key
from receivables.credits.services.credit_settlement_resolution_service import (
    CreditSettlementResolutionService,
)
from receivables.payments.services.payment_resolution_service import (
    PaymentResolutionService,
)
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)


class SupportService:
    def __init__(self, session: AsyncSession) -> None:
        self._ticket_repo = SupportTicketRepository(session)
        self._message_repo = SupportMessageRepository(session)
        self._event_repo = SupportEventRepository(session)
        self._org_repo = OrganizationRepository(session)
        self._membership_repo = OrganizationMembershipRepository(session)
        self._portfolio_access_repo = PortfolioUserAccessRepository(session)
        self._payment_resolution = PaymentResolutionService(session)
        self._credit_settlement_resolution = CreditSettlementResolutionService(session)
        self._notification_service = NotificationService(session)
        self._document_service = DocumentService(session)
        self._user_repo = UserRepository(session)
        # Los adjuntos cuelgan del ticket vía `documentos_ticket`: el filtro por
        # ticket lo hace este repo, no una columna polimórfica de `documentos`.
        self._ticket_document_repo = TicketDocumentRepository(session)

    async def create_org_verification_ticket(
        self, org_id: uuid.UUID, created_by: uuid.UUID
    ) -> SupportTicketModel:
        org = await self._org_repo.get_by_id(org_id)
        org_name = org.name if org else "empresa"
        ticket = await self._ticket_repo.add(
            SupportTicketModel(
                case_type=SupportCaseType.REQUIREMENT,
                status=SupportTicketStatus.OPEN,
                organization_id=org_id,
                created_by=created_by,
                title=f"Validación de Documentos {org_name}",
                notes=(
                    f"Ticket creado automáticamente al registrar empresa: "
                    f"{org_name}. Se debe realizar la verificación documental."
                ),
                system_topic=RequirementTopic.DOCUMENT_VALIDATION.value,
            )
        )
        await self._auto_assign(ticket)
        return ticket

    async def create_identity_verification_ticket(
        self, user_id: uuid.UUID, user_name: str, file: UploadFile
    ) -> SupportTicketModel:
        """Ticket de validación de identidad de un titular (scope SELF), con su
        documento de identidad como adjunto (mismo mecanismo que cualquier adjunto de
        ticket — ver `_store_attachments`). Sin `organization_id`: la identidad de una
        persona no es un concern de una organización puntual, la resuelve cualquier
        Atención al Cliente GLOBAL (`prefer_global=True` en `_auto_assign`), igual que
        `ensure_whatsapp_number_ticket`."""
        ticket = await self._ticket_repo.add(
            SupportTicketModel(
                case_type=SupportCaseType.REQUIREMENT,
                status=SupportTicketStatus.OPEN,
                organization_id=None,
                created_by=user_id,
                title=f"Validación de identidad — {user_name}",
                notes=(
                    "Ticket creado automáticamente al subir el documento de "
                    f"identidad de {user_name}."
                ),
                system_topic=IdentityTopic.IDENTITY_VALIDATION.value,
            )
        )
        await self._store_attachments(
            ticket, [file], TicketDocumentCategory.TICKET_ATTACHMENT, user_id
        )
        await self._emit_event(ticket, user_id, SupportTicketEventType.CREATED)
        await self._auto_assign(ticket, prefer_global=True)
        return ticket

    async def ensure_whatsapp_number_ticket(
        self, org_id: uuid.UUID, created_by: uuid.UUID
    ) -> SupportTicketModel:
        """Idempotente: si ya hay un ticket abierto de este tema para la org, lo
        reutiliza en vez de crear uno duplicado cada vez que se intenta registrar
        una campaña de WhatsApp sin número configurado."""
        existing = await self._ticket_repo.get_open_by_org_and_topic(
            org_id, RequirementTopic.WHATSAPP_NUMBER_REQUEST.value
        )
        if existing is not None:
            return existing

        org = await self._org_repo.get_by_id(org_id)
        org_name = org.name if org else "empresa"
        ticket = await self._ticket_repo.add(
            SupportTicketModel(
                case_type=SupportCaseType.REQUIREMENT,
                status=SupportTicketStatus.OPEN,
                organization_id=org_id,
                created_by=created_by,
                title=f"Número de WhatsApp para {org_name}",
                notes=(
                    f"Ticket creado automáticamente: {org_name} intentó registrar "
                    "una campaña de WhatsApp sin tener un número configurado. "
                    "Provisionar el número en Meta Business Manager y configurarlo "
                    "en la organización (whatsapp-credentials)."
                ),
                system_topic=RequirementTopic.WHATSAPP_NUMBER_REQUEST.value,
            )
        )
        await self._auto_assign(ticket, prefer_global=True)
        return ticket

    async def create_payment_ticket(
        self,
        org_id: uuid.UUID,
        created_by: uuid.UUID,
        topic: PaymentTopic,
        title: str,
        notes: str,
    ) -> SupportTicketModel:
        """Crea un ticket de autogestión de pago (reprogramación / validación) del
        titular y lo asigna al CUSTOMER_SERVICE de la organización dueña del crédito
        reusando la cola por menos-cargado (`_auto_assign`)."""
        ticket = await self._ticket_repo.add(
            SupportTicketModel(
                case_type=SupportCaseType.REQUIREMENT,
                status=SupportTicketStatus.OPEN,
                organization_id=org_id,
                created_by=created_by,
                title=title,
                notes=notes,
                system_topic=topic.value,
            )
        )
        await self._emit_event(ticket, created_by, SupportTicketEventType.CREATED)
        await self._auto_assign(ticket)
        return ticket

    async def get_all_tickets(self, f: SupportFilter) -> list[SupportTicketSchema]:
        tickets = await self._ticket_repo.get_filtered(f)
        org_ids = {t.organization_id for t in tickets if t.organization_id is not None}
        org_names = {
            o.id: o.name for o in await self._org_repo.get_by_ids(list(org_ids))
        }
        return [
            self._ticket_to_schema(t, org_names.get(t.organization_id, ""))
            for t in tickets
        ]

    async def get_ticket(
        self, ticket_number: int, f: SupportFilter
    ) -> SupportTicketSchema:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        return await self._ticket_to_schema_one(ticket)

    async def resolve_ticket(
        self,
        ticket_number: int,
        agent_user_id: uuid.UUID,
        data: ResolveTicketSchema,
        f: SupportFilter,
    ) -> SupportTicketSchema:
        if not f.can_resolve:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para resolver tickets.",
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        if ticket.status == SupportTicketStatus.RESOLVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El ticket ya fue resuelto.",
            )

        prev_status = ticket.status
        ticket.status = SupportTicketStatus.RESOLVED
        ticket.assigned_to = agent_user_id
        ticket.notes = data.notes
        ticket.resolved_at = datetime.now(timezone.utc)

        await self._emit_event(
            ticket,
            agent_user_id,
            SupportTicketEventType.RESOLVED,
            from_value=prev_status.value,
            to_value=SupportTicketStatus.RESOLVED.value,
        )

        if ticket.system_topic == RequirementTopic.DOCUMENT_VALIDATION.value:
            org = await self._org_repo.get_by_id(ticket.organization_id)
            if org is not None:
                org.verification_status = (
                    VerificationStatus.APPROVED
                    if data.approved
                    else VerificationStatus.DENIED
                )
                await self._org_repo.update(org)

            await self._notify_org_verification(
                ticket.organization_id, ticket.created_by, data.approved
            )

        elif ticket.system_topic == PaymentTopic.PAYMENT_RESCHEDULE.value:
            await self._payment_resolution.apply_reschedule_resolution(
                ticket.id, data.approved
            )

        elif ticket.system_topic == PaymentTopic.PAYMENT_VALIDATION.value:
            await self._payment_resolution.apply_validation_resolution(
                ticket.id, data.approved
            )

        elif ticket.system_topic == PaymentTopic.CREDIT_SETTLEMENT.value:
            await self._credit_settlement_resolution.apply_settlement_resolution(
                ticket.id, data.approved
            )

        elif ticket.system_topic == IdentityTopic.IDENTITY_VALIDATION.value:
            await self._resolve_identity_verification(ticket.created_by, data.approved)

        updated = await self._ticket_repo.update(ticket)
        return await self._ticket_to_schema_one(updated)

    def get_categories(self, session: UserSession) -> list[TicketCategorySchema]:
        # Categorías de autogestión de pago: SOLO visibles/creables por el titular
        # (rol USER, scope SELF). Se inician desde el calendario financiero, no desde
        # este formulario genérico (ver guard en create_ticket).
        if session.is_self:
            return [
                TicketCategorySchema(
                    label="Reprogramación de pago",
                    topic=PaymentTopic.PAYMENT_RESCHEDULE.value,
                    case_type=SupportCaseType.REQUIREMENT,
                    description="Solicita mover la fecha de una cuota (hasta 30 días)",
                    icon="calendar-clock",
                ),
                TicketCategorySchema(
                    label="Validación de pago",
                    topic=PaymentTopic.PAYMENT_VALIDATION.value,
                    case_type=SupportCaseType.REQUIREMENT,
                    description="Sube el comprobante de un pago que ya realizaste",
                    icon="receipt",
                ),
                TicketCategorySchema(
                    label="Consulta general",
                    topic=IncidentTopic.GENERAL_INQUIRY.value,
                    case_type=SupportCaseType.INCIDENT,
                    description="Tengo una pregunta sobre el sistema",
                    icon="help-circle",
                ),
            ]

        # No incluye "Solicitud de número de WhatsApp": ese ticket lo crea el sistema
        # automáticamente (ensure_whatsapp_number_ticket), no es una categoría que un
        # usuario elija a mano en este formulario.
        return [
            TicketCategorySchema(
                label="Reportar un error",
                topic=IncidentTopic.BUG_REPORT.value,
                case_type=SupportCaseType.INCIDENT,
                description="Algo no funciona como se espera",
                icon="bug",
            ),
            TicketCategorySchema(
                label="Nueva funcionalidad",
                topic=RequirementTopic.NEW_FEATURE.value,
                case_type=SupportCaseType.REQUIREMENT,
                description="Propón una mejora o característica nueva",
                icon="sparkles",
            ),
            TicketCategorySchema(
                label="Problema de acceso",
                topic=IncidentTopic.ACCESS_ISSUE.value,
                case_type=SupportCaseType.INCIDENT,
                description="No puedo acceder a mi cuenta o a un módulo",
                icon="lock-keyhole",
            ),
            TicketCategorySchema(
                label="Consulta general",
                topic=IncidentTopic.GENERAL_INQUIRY.value,
                case_type=SupportCaseType.INCIDENT,
                description="Tengo una pregunta sobre el sistema",
                icon="help-circle",
            ),
            TicketCategorySchema(
                label="Validación de documentos",
                topic=RequirementTopic.DOCUMENT_VALIDATION.value,
                case_type=SupportCaseType.REQUIREMENT,
                description="Verificación documental de empresa",
                icon="file-check",
            ),
            TicketCategorySchema(
                label="Otro",
                topic=IncidentTopic.OTHER.value,
                case_type=SupportCaseType.INCIDENT,
                description="Mi situación no encaja en las categorías anteriores",
                icon="more-horizontal",
            ),
        ]

    async def get_ticket_orgs(self, session: UserSession) -> list[TicketOrgSchema]:
        if session.is_self:
            org_ids = await self._portfolio_access_repo.get_distinct_org_ids_by_user(
                session.user_id
            )
            orgs = await self._org_repo.get_by_ids(list(org_ids))
            return [TicketOrgSchema(id=org.id, name=org.name) for org in orgs]
        if session.orgs:
            return [
                TicketOrgSchema(id=uuid.UUID(org_id), name=entry.org_name)
                for org_id, entry in session.orgs.items()
            ]
        # Global scope (ADMIN GLOBAL / CS GLOBAL): return all orgs
        orgs = await self._org_repo.get_all()
        return [TicketOrgSchema(id=org.id, name=org.name) for org in orgs]

    async def create_ticket(
        self, user_id: uuid.UUID, data: CreateTicketSchema, f: SupportFilter
    ) -> SupportTicketSchema:
        if not f.can_create:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para crear tickets.",
            )

        # Las solicitudes de pago requieren un pago concreto (y comprobante/fecha); se
        # crean desde el calendario financiero, no por este formulario genérico.
        if data.topic in {t.value for t in PaymentTopic}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Las solicitudes de pago se crean desde el calendario financiero."
                ),
            )

        # org_ids=None → GLOBAL scope: organización es opcional
        if f.org_ids is not None and data.organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La entidad es obligatoria.",
            )

        if data.organization_id is not None:
            if f.check_portfolio_access:
                accesses = await self._portfolio_access_repo.get_active_by_user_and_org(
                    user_id, data.organization_id
                )
                if not accesses:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="No tienes acceso a esta entidad.",
                    )
            elif f.org_ids is not None and data.organization_id not in f.org_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes acceso a esta entidad.",
                )

        # El topic elegido por el usuario se guarda tal cual — ya no hace falta
        # inferir nada de case_type. Solo "document_validation" dispara el efecto
        # secundario de verificación al resolver (ver resolve_ticket/get_org_docs);
        # cualquier otro topic (incluido "new_feature") es puramente
        # informativo/de categorización.
        ticket = SupportTicketModel(
            case_type=data.case_type,
            system_topic=data.topic,
            status=SupportTicketStatus.OPEN,
            priority=data.priority,
            organization_id=data.organization_id,
            created_by=user_id,
            title=data.title,
            notes=data.notes,
        )
        ticket = await self._ticket_repo.add(ticket)
        await self._emit_event(ticket, user_id, SupportTicketEventType.CREATED)
        await self._auto_assign(ticket, prefer_global=f.route_to_global)

        return await self._ticket_to_schema_one(ticket)

    async def escalate_ticket(
        self, ticket_number: int, f: SupportFilter
    ) -> SupportTicketSchema:
        if not f.can_escalate:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para escalar tickets.",
            )

        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        if ticket.status == SupportTicketStatus.RESOLVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede escalar un ticket resuelto.",
            )

        old_agent = ticket.assigned_to
        await self._auto_assign(ticket, prefer_global=True)
        if ticket.assigned_to and ticket.assigned_to != old_agent:
            await self._emit_event(
                ticket,
                ticket.assigned_to,
                SupportTicketEventType.ESCALATED,
                to_value=str(ticket.assigned_to),
            )
        return await self._ticket_to_schema_one(ticket)

    async def get_org_docs(self, ticket_number: int, f: SupportFilter) -> OrgDocsSchema:
        if not (f.can_resolve or f.can_assign):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado."
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        if ticket.system_topic != RequirementTopic.DOCUMENT_VALIDATION.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este ticket no es de verificación.",
            )
        org = await self._org_repo.get_by_id(ticket.organization_id)
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada."
            )

        def _url(document_id: uuid.UUID | None) -> str | None:
            if document_id is None:
                return None
            # La ruta se movió al controller de organizaciones: el documento fiscal/
            # mercantil/representante cuelga de `entidades`, no de una tabla
            # polimórfica.
            return f"/organizations/{org.id}/documents/{document_id}/content"

        return OrgDocsSchema(
            org_name=org.name,
            documents=[
                OrgDocSchema(
                    label="Documento fiscal", url=_url(org.fiscal_document_id)
                ),
                OrgDocSchema(
                    label="Documento mercantil", url=_url(org.mercantile_document_id)
                ),
                OrgDocSchema(
                    label="Documento representante",
                    url=_url(org.representative_document_id),
                ),
            ],
        )

    _TERMINAL_STATUSES = {SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED}

    async def update_ticket_status(
        self,
        ticket_number: int,
        user_id: uuid.UUID,
        data: UpdateTicketStatusSchema,
        f: SupportFilter,
    ) -> SupportTicketSchema:
        if not f.can_assign:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para mover tickets.",
            )
        if data.status in self._TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usa el endpoint de cierre para resolver o cerrar tickets.",
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        if ticket.status in self._TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede mover un ticket resuelto o cerrado.",
            )
        prev = ticket.status
        ticket.status = data.status
        updated = await self._ticket_repo.update(ticket)
        await self._emit_event(
            ticket,
            user_id,
            SupportTicketEventType.STATUS_CHANGED,
            from_value=prev.value,
            to_value=data.status.value,
        )
        return await self._ticket_to_schema_one(updated)

    async def update_ticket_priority(
        self,
        ticket_number: int,
        user_id: uuid.UUID,
        data: UpdateTicketPrioritySchema,
        f: SupportFilter,
    ) -> SupportTicketSchema:
        if not f.can_assign:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para cambiar la prioridad.",
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        prev = ticket.priority
        ticket.priority = data.priority
        updated = await self._ticket_repo.update(ticket)
        await self._emit_event(
            ticket,
            user_id,
            SupportTicketEventType.PRIORITY_CHANGED,
            from_value=prev.value,
            to_value=data.priority.value,
        )
        return await self._ticket_to_schema_one(updated)

    async def assign_ticket(
        self,
        ticket_number: int,
        actor_id: uuid.UUID,
        data: AssignTicketSchema,
        f: SupportFilter,
    ) -> SupportTicketSchema:
        if not f.can_assign:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para asignar tickets.",
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        if ticket.status in self._TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede reasignar un ticket resuelto o cerrado.",
            )

        event_type = (
            SupportTicketEventType.REASSIGNED
            if ticket.assigned_to
            else SupportTicketEventType.ASSIGNED
        )
        prev_agent = str(ticket.assigned_to) if ticket.assigned_to else None
        ticket.assigned_to = data.user_id
        ticket.status = SupportTicketStatus.IN_PROGRESS
        updated = await self._ticket_repo.update(ticket)
        await self._emit_event(
            ticket,
            actor_id,
            event_type,
            from_value=prev_agent,
            to_value=str(data.user_id),
        )

        await self._notification_service.create_notification(
            user_id=data.user_id,
            title="Ticket asignado",
            body=f"Se te asignó el ticket de soporte #{ticket.ticket_number}.",
            category="support",
            notif_type="info",
            link=f"/cs/tickets/{ticket.ticket_number}",
        )
        return SupportTicketSchema.model_validate(updated)

    # ------------------------------------------------------------------
    # Events (audit log)
    # ------------------------------------------------------------------

    async def list_events(
        self, ticket_number: int, f: SupportFilter
    ) -> list[TicketEventSchema]:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        events = await self._event_repo.get_by_ticket_id(ticket.id)
        return [
            TicketEventSchema(
                id=event.id,
                ticket_id=event.ticket_id,
                user_id=event.user_id,
                user_name=user_name,
                event_type=event.event_type,
                from_value=event.from_value,
                to_value=event.to_value,
                created_at=event.created_at,
            )
            for event, user_name in events
        ]

    async def get_metrics(self, f: SupportFilter) -> TicketMetricsSchema:
        tickets = await self._ticket_repo.get_metrics_data(
            org_ids=f.org_ids, created_by=f.created_by
        )
        today = datetime.now(timezone.utc).date()

        by_priority: dict[str, int] = {p.value: 0 for p in SupportTicketPriority}

        open_count = in_progress = pending = resolved = closed = 0
        created_today = resolved_today = 0
        resolution_hours: list[float] = []

        for t in tickets:
            s = t.status
            if s in (SupportTicketStatus.NEW, SupportTicketStatus.OPEN):
                open_count += 1
            elif s == SupportTicketStatus.IN_PROGRESS:
                in_progress += 1
            elif s in (
                SupportTicketStatus.PENDING_CLIENT,
                SupportTicketStatus.PENDING_THIRD,
            ):
                pending += 1
            elif s == SupportTicketStatus.RESOLVED:
                resolved += 1
                if t.resolved_at and t.resolved_at.date() == today:
                    resolved_today += 1
                if t.resolved_at and t.created_at:
                    delta = (t.resolved_at - t.created_at).total_seconds() / 3600
                    resolution_hours.append(delta)
            elif s == SupportTicketStatus.CLOSED:
                closed += 1

            if t.created_at.date() == today:
                created_today += 1

            prio_key = t.priority.value
            by_priority[prio_key] = by_priority.get(prio_key, 0) + 1

        avg = (
            round(sum(resolution_hours) / len(resolution_hours), 1)
            if resolution_hours
            else None
        )

        return TicketMetricsSchema(
            total=len(tickets),
            open=open_count,
            in_progress=in_progress,
            pending=pending,
            resolved=resolved,
            closed=closed,
            created_today=created_today,
            resolved_today=resolved_today,
            avg_resolution_hours=avg,
            by_priority=by_priority,
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def list_messages(
        self, ticket_number: int, f: SupportFilter
    ) -> list[TicketMessageSchema]:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        messages = await self._message_repo.get_by_ticket_id(ticket.id)
        is_staff = f.can_resolve or f.can_assign
        return [
            TicketMessageSchema.model_validate(m)
            for m in messages
            if is_staff or not m.is_internal
        ]

    async def create_message(
        self,
        ticket_number: int,
        sender_id: uuid.UUID,
        data: CreateMessageSchema,
        f: SupportFilter,
    ) -> TicketMessageSchema:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        if ticket.status in self._TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede enviar mensajes en un ticket cerrado.",
            )
        if data.is_internal and not (f.can_resolve or f.can_assign):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo los agentes pueden enviar mensajes internos.",
            )

        message = await self._message_repo.add(
            SupportTicketMessageModel(
                ticket_id=ticket.id,
                sender_id=sender_id,
                body=data.body,
                is_internal=data.is_internal,
            )
        )

        await self._notify_new_message(ticket, sender_id, data.is_internal)
        return TicketMessageSchema.model_validate(message)

    async def _notify_new_message(
        self, ticket: SupportTicketModel, sender_id: uuid.UUID, is_internal: bool
    ) -> None:
        recipients: set[uuid.UUID] = set()
        if ticket.assigned_to and ticket.assigned_to != sender_id:
            recipients.add(ticket.assigned_to)
        if not is_internal and ticket.created_by != sender_id:
            recipients.add(ticket.created_by)

        for uid in recipients:
            await self._notification_service.create_notification(
                user_id=uid,
                title="Nuevo mensaje en ticket",
                body=f"Mensaje en ticket #{ticket.ticket_number}.",
                category="support_message",
                notif_type="info",
                link=f"/cs/tickets/{ticket.ticket_number}",
                details={"ticket_number": ticket.ticket_number},
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        ticket: SupportTicketModel,
        user_id: uuid.UUID,
        event_type: SupportTicketEventType,
        from_value: str | None = None,
        to_value: str | None = None,
    ) -> None:
        await self._event_repo.add(
            SupportTicketEventModel(
                ticket_id=ticket.id,
                user_id=user_id,
                event_type=event_type,
                from_value=from_value,
                to_value=to_value,
            )
        )

    async def _get_ticket_or_404(self, ticket_number: int) -> SupportTicketModel:
        ticket = await self._ticket_repo.get_by_ticket_number(ticket_number)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado."
            )
        return ticket

    def _assert_ticket_access(
        self,
        ticket: SupportTicketModel,
        f: "SupportFilter",
        *,
        check_creator: bool = False,
    ) -> None:
        # 404 genérico, no 403: un 403 distinto de "no encontrado" deja distinguir
        # por fuerza bruta qué `ticket_number` existen en el sistema (secuencial).
        if f.org_ids is not None and ticket.organization_id not in f.org_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado."
            )
        if (
            check_creator
            and f.created_by is not None
            and ticket.created_by != f.created_by
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado."
            )

    _ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".doc", ".pdf"}
    _MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    _CONTENT_TYPE_BY_EXT = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".doc": "application/msword",
        ".pdf": "application/pdf",
    }

    @staticmethod
    def _safe_filename(name: str | None) -> str:
        if not name:
            return "attachment"
        safe = re.sub(r"[^\w.\-]", "_", name)
        return safe[:120]

    def _to_attachment_schema(
        self, ticket: SupportTicketModel, document: DocumentModel
    ) -> TicketAttachmentSchema:
        return TicketAttachmentSchema(
            name=document.original_name,
            url=f"/cs/tickets/{ticket.ticket_number}/documents/{document.id}/content",
            size=document.size_bytes or 0,
        )

    async def _store_attachments(
        self,
        ticket: SupportTicketModel,
        files: list[UploadFile],
        category: TicketDocumentCategory,
        uploaded_by: uuid.UUID | None,
    ) -> list[TicketAttachmentSchema]:
        result = []
        for upload in files:
            ext = os.path.splitext(upload.filename or "")[1].lower()
            if ext not in self._ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Tipo de archivo no permitido: {ext}",
                )
            content = await self._read_within_limit(upload)
            safe_name = self._safe_filename(upload.filename)
            # store_generated() está pensado para artefactos que genera la propia
            # API, no para subidas de usuario — pero acá es seguro: el content-type
            # no sale del header que manda el cliente, sale de la whitelist de
            # extensión de arriba.
            document = await self._document_service.store_generated(
                content=content,
                filename=safe_name,
                content_type=self._CONTENT_TYPE_BY_EXT.get(
                    ext, "application/octet-stream"
                ),
                domain=TICKET_DOCUMENT_STORAGE_DOMAIN,
                owner_id=str(ticket.id),
                uploaded_by=uploaded_by,
                organization_id=ticket.organization_id,
            )
            # El enlace al ticket es una fila propia con FK real, en la misma
            # sesión: si falla, la unidad de trabajo hace rollback de las dos.
            await self._ticket_document_repo.add(
                TicketDocumentModel(
                    ticket_id=ticket.id,
                    category=category,
                    document_id=document.id,
                )
            )
            result.append(self._to_attachment_schema(ticket, document))
        return result

    async def _read_within_limit(self, upload: UploadFile) -> bytes:
        """Lee el archivo en chunks y corta apenas se supera el máximo, en vez de
        bufferear todo el contenido en memoria antes de poder rechazarlo."""
        if upload.size is not None and upload.size > self._MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="El archivo excede el tamaño máximo de 10 MB.",
            )
        chunks = bytearray()
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > self._MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="El archivo excede el tamaño máximo de 10 MB.",
                )
        return bytes(chunks)

    async def upload_attachments(
        self, ticket_number: int, files: list[UploadFile], f: SupportFilter
    ) -> list[TicketAttachmentSchema]:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        return await self._store_attachments(
            ticket, files, TicketDocumentCategory.TICKET_ATTACHMENT, f.created_by
        )

    async def upload_closure_attachments(
        self, ticket_number: int, files: list[UploadFile], f: SupportFilter
    ) -> list[TicketAttachmentSchema]:
        if not f.can_resolve:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para adjuntar evidencias de cierre.",
            )
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f)
        return await self._store_attachments(
            ticket, files, TicketDocumentCategory.TICKET_CLOSURE, f.created_by
        )

    async def list_closure_attachments(
        self, ticket_number: int, f: SupportFilter
    ) -> list[TicketAttachmentSchema]:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        rows = await self._ticket_document_repo.list_by_ticket(
            ticket.id, TicketDocumentCategory.TICKET_CLOSURE
        )
        return [self._to_attachment_schema(ticket, document) for _, document in rows]

    async def list_attachments(
        self, ticket_number: int, f: SupportFilter
    ) -> list[TicketAttachmentSchema]:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        rows = await self._ticket_document_repo.list_by_ticket(
            ticket.id, TicketDocumentCategory.TICKET_ATTACHMENT
        )
        return [self._to_attachment_schema(ticket, document) for _, document in rows]

    async def get_ticket_document_content(
        self, ticket_number: int, document_id: uuid.UUID, f: SupportFilter
    ) -> Response:
        ticket = await self._get_ticket_or_404(ticket_number)
        self._assert_ticket_access(ticket, f, check_creator=True)
        # El adjunto tiene que colgar de ESE ticket: si no, 404 sin confirmar
        # existencia.
        row = await self._ticket_document_repo.get_owned(ticket.id, document_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado."
            )
        return await self._document_service.to_content_response(row[1])

    async def _auto_assign(
        self, ticket: SupportTicketModel, *, prefer_global: bool = False
    ) -> None:
        if prefer_global:
            agent_id = await self._ticket_repo.find_least_loaded_cs_global()
        else:
            agent_id = await self._ticket_repo.find_least_loaded_cs_org(
                ticket.organization_id
            )
            if agent_id is None:
                agent_id = await self._ticket_repo.find_least_loaded_cs_global()

        if agent_id is None:
            return

        ticket.assigned_to = agent_id
        ticket.status = SupportTicketStatus.IN_PROGRESS
        await self._ticket_repo.update(ticket)
        await self._notification_service.create_notification(
            user_id=agent_id,
            title="Nuevo ticket asignado",
            body=f"Se te asignó un ticket de soporte #{ticket.ticket_number}.",
            category="support",
            notif_type="info",
            link=f"/cs/tickets/{ticket.ticket_number}",
        )

    def _ticket_to_schema(
        self, ticket: SupportTicketModel, org_name: str = ""
    ) -> SupportTicketSchema:
        schema = SupportTicketSchema.model_validate(ticket)
        return schema.model_copy(
            update={"organization_name": org_name, "topic": ticket.system_topic}
        )

    async def _ticket_to_schema_one(
        self, ticket: SupportTicketModel
    ) -> SupportTicketSchema:
        org_name = ""
        if ticket.organization_id is not None:
            org = await self._org_repo.get_by_id(ticket.organization_id)
            org_name = org.name if org else ""
        return self._ticket_to_schema(ticket, org_name)

    async def _notify_org_verification(
        self, org_id: uuid.UUID, ticket_created_by: uuid.UUID, approved: bool
    ) -> None:
        memberships = await self._membership_repo.get_by_organization_id(org_id)
        rep = next((m for m in memberships if m.is_legal_representative), None)

        recipient_ids: set[uuid.UUID] = {ticket_created_by}
        if rep is not None:
            recipient_ids.add(rep.user_id)

        title = "Empresa verificada" if approved else "Verificación rechazada"
        body = (
            "Los documentos de tu empresa han sido aprobados."
            if approved
            else "Los documentos de tu empresa fueron rechazados. Revisa los detalles."
        )

        for user_id in recipient_ids:
            await self._notification_service.create_notification(
                user_id=user_id,
                title=title,
                body=body,
                category="org_verification",
            )

    async def _resolve_identity_verification(
        self, user_id: uuid.UUID, approved: bool
    ) -> None:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            return
        user.identity_verification_status = (
            IdentityVerificationStatus.APPROVED
            if approved
            else IdentityVerificationStatus.DENIED
        )
        await self._user_repo.update(user)

        # La sesión (si sigue activa en Redis) se parchea en el momento para que el
        # titular vea el nuevo estado sin tener que volver a iniciar sesión — a
        # diferencia de get_user_session(), esto no reconstruye toda la sesión (roles,
        # membresías, ...) solo para actualizar un campo.
        cached = await redis_client.get_json(session_key(user_id), UserSession)
        if cached is not None:
            cached.identity_verification_status = user.identity_verification_status
            await redis_client.set_json(session_key(user_id), cached)

        title = (
            "Identidad verificada"
            if approved
            else "Verificación de identidad rechazada"
        )
        body = (
            "Tu identidad fue verificada. Ya puedes ver tu información crediticia."
            if approved
            else (
                "No pudimos verificar tu identidad con el documento enviado. "
                "Contacta a soporte."
            )
        )
        await self._notification_service.create_notification(
            user_id=user_id,
            title=title,
            body=body,
            category="identity_verification",
        )
