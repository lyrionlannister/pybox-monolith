"""Flujo IVR reutilizable diseñado en el frontend."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class IvrFlowModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Flujo IVR reutilizable diseñado en el frontend.

    `config` guarda el `CampaignIvrConfig` ya compilado y listo para enviar a
    Helena (mapa de nodos + entry_node + defaults). `graph` guarda el grafo
    crudo de React Flow para poder reeditarlo en el diseñador sin pérdida.
    """

    __tablename__ = "flujos_ivr"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, name="nombre")

    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="descripcion"
    )

    config: Mapped[dict] = mapped_column(JSONB, nullable=False, name="config")

    graph: Mapped[dict | None] = mapped_column(JSONB, nullable=True, name="grafo")

    redial_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, name="config_remarcado"
    )

    # Variables enviadas a Helena por defecto para todo el bulk (AMD_*, PJSIP_TRUNK, …).
    variables: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, name="variables"
    )

    # Etiquetas de resultado por desenlace, compiladas desde el diseñador:
    outcomes: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, name="resultados"
    )

    # Ritmo de marcación y caller ID por defecto para los bulks de este flujo
    calls_per_second: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="llamadas_por_segundo"
    )

    max_concurrent: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="maximo_concurrentes"
    )

    caller_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True, name="id_llamante"
    )

    # Política de contacto de Helena (horario permitido de marcación). Se guarda
    # solo el id: las ventanas horarias las administra Helena, no Pybox.
    contact_policy_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, name="id_politica_contacto"
    )
