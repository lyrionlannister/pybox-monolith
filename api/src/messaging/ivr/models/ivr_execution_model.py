"""Un bulk de llamadas IVR despachado a Helena."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import BaseModel
from messaging.ivr.enums.ivr_enums import IvrExecutionStatus


class IvrExecutionModel(BaseModel):
    """Un bulk de llamadas despachado a Helena.

    Una campaña puede generar varias filas: cada disparo del cron es un bulk
    distinto (`bulkId` propio), y un envío grande se trocea en varios bulks de
    hasta `BATCH_SIZE` destinatarios (`batch_sender.py`). Esta tabla es lo que
    le permite al monitor y a los controles de pausa/cancelación saber "cuál es
    el bulk activo de esta campaña" sin inferirlo de `contactos`.
    """

    __tablename__ = "ejecuciones_ivr"

    bulk_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, name="id_envio"
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=False,
        index=True,
        name="id_campania",
    )

    # `ondelete=SET NULL`, mismo criterio que `CampaignResultModel`: si se borra
    # la programación que disparó el envío, la ejecución sigue existiendo.
    campaign_time_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("programacion_campanias.id", ondelete="SET NULL"),
        nullable=True,
        name="id_programacion",
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=False,
        index=True,
        name="id_organizacion",
    )

    status: Mapped[IvrExecutionStatus] = mapped_column(
        Enum(IvrExecutionStatus),
        nullable=False,
        default=IvrExecutionStatus.RUNNING,
        name="estado",
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, name="cantidad")

    calls_per_second: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="llamadas_por_segundo"
    )

    max_concurrent: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="maximo_concurrentes"
    )

    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="despachado_en"
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="finalizado_en"
    )
