"""Resultado agregado del cierre real de una ejecución de campaña."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CampaignResultModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "resultados_campanias"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=False,
        index=True,
        name="id_campania",
    )

    campaign_time_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("programacion_campanias.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        name="id_programacion",
    )

    total_sent: Mapped[int] = mapped_column(Integer, default=0, name="total_enviados")

    success_count: Mapped[int] = mapped_column(Integer, default=0, name="exitosos")

    failure_count: Mapped[int] = mapped_column(Integer, default=0, name="con_errores")

    unique_customers: Mapped[int] = mapped_column(
        Integer, default=0, name="clientes_unicos"
    )

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), name="fecha_envio"
    )

    # Id del envío de 360NRS (sendingId) reconciliado. Null para el
    # resultado agregado inicial post-envío.
    sending_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, name="id_envio"
    )
