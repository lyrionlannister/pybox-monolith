"""Schemas de tickets de soporte: creación, mensajes, filtros y respuesta."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, field_validator

from app_platform.support.enums.support_enums import (
    IdentityTopic,
    IncidentTopic,
    PaymentTopic,
    RequirementTopic,
    SupportCaseType,
    SupportTicketEventType,
    SupportTicketPriority,
    SupportTicketStatus,
)
from core.base.schema_base import BaseSchema


@dataclass
class SupportFilter:
    # Access control
    org_ids: list[uuid.UUID] | None = None
    created_by: uuid.UUID | None = None
    # Usuario staff (admin/CS) en unas organizaciones y miembro raso en otras: sus
    # capacidades de staff solo valen en `staff_org_ids`; en el resto solo ve sus
    # propios tickets (`viewer_id`). None = sin esa restricción.
    staff_org_ids: list[uuid.UUID] | None = None
    viewer_id: uuid.UUID | None = None
    include_resolved: bool = False
    can_resolve: bool = False
    can_assign: bool = False
    can_create: bool = False
    can_escalate: bool = False
    route_to_global: bool = False
    check_portfolio_access: bool = False
    # Search / filters
    q: str | None = None
    status_filter: SupportTicketStatus | None = None
    priority_filter: SupportTicketPriority | None = None
    case_type_filter: SupportCaseType | None = None
    assigned_to_filter: uuid.UUID | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None


# Un topic pertenece a exactamente uno de los dos enums — determina el case_type,
# ya no hace falta (ni se confía en) que el cliente lo mande por separado.
_TOPIC_CASE_TYPE: dict[str, SupportCaseType] = {
    **{t.value: SupportCaseType.REQUIREMENT for t in RequirementTopic},
    **{t.value: SupportCaseType.INCIDENT for t in IncidentTopic},
    **{t.value: SupportCaseType.REQUIREMENT for t in PaymentTopic},
    **{t.value: SupportCaseType.REQUIREMENT for t in IdentityTopic},
}


class TicketCategorySchema(BaseSchema):
    label: str = Field(description="Nombre de la categoría")
    topic: str = Field(
        description=(
            "Identificador estable de la categoría (RequirementTopic o IncidentTopic)"
        )
    )
    case_type: SupportCaseType = Field(
        description="Tipo de caso derivado del topic: incident o requirement"
    )
    description: str = Field(description="Descripción de la categoría")
    icon: str = Field(description="Nombre del icono")


class CreateTicketSchema(BaseSchema):
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="ID de la organización (obligatorio para scope ORG y SELF)",
    )
    title: str = Field(description="Título del ticket")
    topic: str = Field(
        description=(
            "Categoría del ticket — determina el case_type, "
            "ver RequirementTopic/IncidentTopic"
        )
    )
    notes: str = Field(description="Descripción detallada del caso")
    priority: SupportTicketPriority = Field(
        default=SupportTicketPriority.MEDIUM, description="Prioridad del ticket"
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        if v not in _TOPIC_CASE_TYPE:
            raise ValueError(f"Categoría de ticket inválida: {v!r}")
        return v

    @property
    def case_type(self) -> SupportCaseType:
        return _TOPIC_CASE_TYPE[self.topic]


class TicketOrgSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID de la organización")
    name: str = Field(description="Nombre de la organización")


class ResolveTicketSchema(BaseSchema):
    approved: bool = Field(
        description="True si la resolución fue aprobada por el cliente"
    )
    notes: str = Field(description="Notas de cierre")


class UpdateTicketStatusSchema(BaseSchema):
    status: SupportTicketStatus = Field(description="Nuevo estado del ticket")


class UpdateTicketPrioritySchema(BaseSchema):
    priority: SupportTicketPriority = Field(description="Nueva prioridad del ticket")


class AssignTicketSchema(BaseSchema):
    user_id: uuid.UUID = Field(description="ID del agente al que se asigna el ticket")


class SupportTicketSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID único del ticket")
    ticket_number: int = Field(description="Número secuencial del ticket")
    case_type: SupportCaseType = Field(description="Tipo de caso")
    topic: str | None = Field(
        default=None,
        description=(
            "Categoría del ticket (RequirementTopic o IncidentTopic); "
            "null en tickets antiguos sin migrar"
        ),
    )
    status: SupportTicketStatus = Field(description="Estado actual del ticket")
    priority: SupportTicketPriority = Field(description="Prioridad del ticket")
    organization_id: uuid.UUID | None = Field(description="ID de la organización")
    organization_name: str = Field(default="", description="Nombre de la organización")
    created_by: uuid.UUID = Field(description="ID del usuario que creó el ticket")
    assigned_to: uuid.UUID | None = Field(description="ID del agente asignado")
    title: str | None = Field(description="Título del ticket")
    notes: str | None = Field(description="Notas o descripción")
    resolved_at: datetime | None = Field(description="Fecha de resolución")
    closed_at: datetime | None = Field(default=None, description="Fecha de cierre")
    created_at: datetime = Field(description="Fecha de creación")


class TicketAttachmentSchema(BaseSchema):
    name: str = Field(description="Nombre del archivo")
    url: str = Field(description="URL de descarga")
    size: int = Field(description="Tamaño en bytes")


class OrgDocSchema(BaseSchema):
    label: str = Field(description="Etiqueta del documento")
    url: str | None = Field(description="URL del documento")


class OrgDocsSchema(BaseSchema):
    org_name: str = Field(description="Nombre de la organización")
    documents: list[OrgDocSchema] = Field(
        description="Lista de documentos de verificación"
    )


class CreateMessageSchema(BaseSchema):
    body: str = Field(
        description="Contenido del mensaje", min_length=1, max_length=4000
    )
    is_internal: bool = Field(
        default=False, description="True si el mensaje es solo para agentes"
    )


class TicketMessageSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID del mensaje")
    ticket_id: uuid.UUID = Field(description="ID del ticket")
    sender_id: uuid.UUID = Field(description="ID del remitente")
    body: str = Field(description="Contenido del mensaje")
    is_internal: bool = Field(description="Mensaje interno de agente")
    created_at: datetime = Field(description="Fecha de envío")


class TicketEventSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID del evento")
    ticket_id: uuid.UUID = Field(description="ID del ticket")
    user_id: uuid.UUID = Field(description="ID del usuario que realizó la acción")
    user_name: str = Field(description="Nombre del usuario que realizó la acción")
    event_type: SupportTicketEventType = Field(description="Tipo de evento")
    from_value: str | None = Field(description="Valor anterior")
    to_value: str | None = Field(description="Valor nuevo")
    created_at: datetime = Field(description="Fecha del evento")


class TicketMetricsSchema(BaseSchema):
    total: int = Field(description="Total de tickets")
    open: int = Field(description="Tickets abiertos o nuevos")
    in_progress: int = Field(description="Tickets en proceso")
    pending: int = Field(description="Tickets pendientes (cliente o tercero)")
    resolved: int = Field(description="Tickets resueltos")
    closed: int = Field(description="Tickets cerrados")
    created_today: int = Field(description="Tickets creados hoy")
    resolved_today: int = Field(description="Tickets resueltos hoy")
    avg_resolution_hours: float | None = Field(
        description="Tiempo promedio de resolución en horas"
    )
    by_priority: dict[str, int] = Field(description="Tickets por prioridad")
