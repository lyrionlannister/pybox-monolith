"""Ticket de soporte de una organización o usuario global."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app_platform.support.enums.support_enums import (
    SupportCaseType,
    SupportTicketPriority,
    SupportTicketStatus,
)
from core.base.audit_model import BaseModel


class SupportTicketModel(BaseModel):
    __tablename__ = "soporte_tickets"

    ticket_number: Mapped[int] = mapped_column(
        Integer, Identity(start=1), unique=True, nullable=False, name="numero_ticket"
    )
    case_type: Mapped[SupportCaseType] = mapped_column(
        ENUM(
            SupportCaseType,
            name="tipo_caso_soporte",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="tipo_caso",
    )
    # Distingue el propósito de un ticket generado por el sistema (más específico que
    # case_type) cuando resolverlo debe disparar un efecto secundario concreto —
    # ej. "org_verification" marca verification_status al resolver. Null en tickets
    # creados manualmente por un usuario (no tienen efecto secundario al resolver).
    system_topic: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="tema_sistema"
    )
    status: Mapped[SupportTicketStatus] = mapped_column(
        ENUM(
            SupportTicketStatus,
            name="estado_ticket_soporte",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SupportTicketStatus.OPEN,
        name="estado",
        index=True,
    )
    priority: Mapped[SupportTicketPriority] = mapped_column(
        ENUM(
            SupportTicketPriority,
            name="prioridad_ticket_soporte",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SupportTicketPriority.MEDIUM,
        name="prioridad",
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        name="id_entidad",
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="creado_por",
        index=True,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        name="asignado_a",
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, name="titulo")
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True, name="notas")
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="resuelto_en"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="cerrado_en"
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        name="cerrado_por",
        index=True,
    )
