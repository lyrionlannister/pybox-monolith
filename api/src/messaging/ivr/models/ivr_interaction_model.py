"""Una interacción (llamada) reportada por Helena."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import BaseModel
from messaging.ivr.enums.ivr_enums import IvrCallStatus


class IvrInteractionModel(BaseModel):
    """Una interacción (llamada) reportada por Helena.

    Con remarcación activa hay varias interacciones por destinatario, agrupadas
    por `root_interaction_id`; por eso no se puede guardar el resultado en
    `contactos` (que es 1:1 con el destinatario del envío) ni en su enum de
    estado, que tiene forma de eventos de 360NRS.

    La correlación con la campaña se resuelve por `(bulk_id, phone)` contra
    `contactos.(id_envio, destinatario)`: el `interaction` del webhook no trae
    `campaignId` ni `organizationId`, solo `bulkId`.
    """

    __tablename__ = "interacciones_ivr"

    __table_args__ = (
        Index("ix_interacciones_ivr_campania_estado", "id_campania", "estado"),
        Index("ix_interacciones_ivr_envio_telefono", "id_envio", "telefono"),
    )

    # ── Identidad en Helena ───────────────────────────────────────────────────

    interaction_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, name="id_interaccion"
    )

    bulk_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, name="id_envio"
    )

    root_interaction_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, name="id_interaccion_raiz"
    )

    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, name="numero_intento"
    )

    # ── Correlación con el modelo de Pybox ───────────────────────────────────

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("contactos.id"),
        nullable=True,
        index=True,
        name="id_contacto",
    )

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=True,
        index=True,
        name="id_campania",
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        index=True,
        name="id_organizacion",
    )

    debtor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("deudores.id"), nullable=True, name="id_deudor"
    )

    # ── Datos del destinatario ────────────────────────────────────────────────

    phone: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, name="telefono"
    )

    customer_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="nombre_cliente"
    )

    customer_document: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="documento_cliente"
    )

    # ── Resultado de la llamada ───────────────────────────────────────────────

    status: Mapped[IvrCallStatus] = mapped_column(
        Enum(IvrCallStatus),
        nullable=False,
        default=IvrCallStatus.QUEUED,
        name="estado",
    )

    amd_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, name="estado_amd"
    )

    amd_cause: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="causa_amd"
    )

    dial_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="estado_marcacion"
    )

    ivr_end_node_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="nodo_final_ivr"
    )

    ivr_end_reason: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="razon_final_ivr"
    )

    transferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="transferido"
    )

    # Resultado de negocio resuelto contra `flujos_ivr.outcomes` al cerrar la
    # llamada. `key` es el desenlace técnico; `label` la etiqueta del diseñador.
    outcome_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, name="clave_resultado"
    )

    outcome_label: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="etiqueta_resultado"
    )

    transfer_dial_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="estado_transferencia"
    )

    duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="duracion_segundos"
    )

    billable_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="segundos_facturables"
    )

    # ── Interacción con el IVR ────────────────────────────────────────────────

    dtmf_events: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, name="eventos_dtmf"
    )

    collected_data: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, name="datos_capturados"
    )

    # ── Marcas de tiempo del ciclo de la llamada ──────────────────────────────

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="iniciada_en"
    )

    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="contestada_en"
    )

    transfer_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="transferencia_iniciada_en"
    )

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="finalizada_en"
    )

    # ── Trazabilidad ──────────────────────────────────────────────────────────

    last_event: Mapped[str | None] = mapped_column(
        String(60), nullable=True, name="ultimo_evento"
    )

    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, name="payload_crudo"
    )
