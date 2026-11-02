"""Acceso a datos de las interacciones (llamadas) IVR reportadas por Helena."""

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import func, or_, select, update

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from messaging.ivr.enums.ivr_enums import TERMINAL_CALL_STATUSES, IvrCallStatus
from messaging.ivr.models.ivr_interaction_model import IvrInteractionModel


class IvrInteractionRepository(SoftDeleteRepositoryBase[IvrInteractionModel]):
    model_class = IvrInteractionModel

    async def get_by_interaction_id(
        self, interaction_id: str
    ) -> IvrInteractionModel | None:
        result = await self.session.execute(
            select(IvrInteractionModel).where(
                IvrInteractionModel.interaction_id == interaction_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_bulk_id(self, bulk_id: str) -> Sequence[IvrInteractionModel]:
        result = await self.session.execute(
            select(IvrInteractionModel).where(IvrInteractionModel.bulk_id == bulk_id)
        )
        return result.scalars().all()

    async def get_latest_attempt_for_contact(
        self, contact_id: uuid.UUID
    ) -> IvrInteractionModel | None:
        """Interacción cerrada con el mayor número de intento de ese contacto.

        Con remarcación, el estado que le corresponde al contacto es el del
        último intento, no el del primero que cierre.
        """
        result = await self.session.execute(
            select(IvrInteractionModel)
            .where(
                IvrInteractionModel.contact_id == contact_id,
                IvrInteractionModel.status.in_(tuple(TERMINAL_CALL_STATUSES)),
            )
            .order_by(IvrInteractionModel.attempt_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_by_status_for_bulk(self, bulk_id: str) -> dict[IvrCallStatus, int]:
        result = await self.session.execute(
            select(IvrInteractionModel.status, func.count(IvrInteractionModel.id))
            .where(IvrInteractionModel.bulk_id == bulk_id)
            .group_by(IvrInteractionModel.status)
        )
        # dict(result.all()) confunde al type checker sobre el tipo de Row; se
        # deja la comprehension explícita a propósito.
        # pylint: disable-next=unnecessary-comprehension
        return {status: count for status, count in result.all()}

    async def count_unique_phones_for_bulk(self, bulk_id: str) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(IvrInteractionModel.phone))).where(
                IvrInteractionModel.bulk_id == bulk_id
            )
        )
        return int(result.scalar_one() or 0)

    async def find_stale_open(
        self, older_than: datetime, limit: int = 500
    ) -> Sequence[IvrInteractionModel]:
        """Interacciones sin evento terminal creadas antes de `older_than`.

        Red de seguridad para webhooks que nunca llegaron (API caída, fallo de
        red agotando el único reintento de Helena).
        """
        result = await self.session.execute(
            select(IvrInteractionModel)
            .where(
                IvrInteractionModel.status.notin_(tuple(TERMINAL_CALL_STATUSES)),
                IvrInteractionModel.created_at < older_than,
            )
            .order_by(IvrInteractionModel.created_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def close_stale_bulk(
        self, ids: Sequence[uuid.UUID], last_event: str, ended_at: datetime
    ) -> None:
        """Cierra en un solo UPDATE las interacciones dadas (ver `find_stale_open`).

        Evita un UPDATE por fila cuando el cron encuentra varias interacciones
        huérfanas en la misma corrida. `ended_at` solo se aplica si la fila no
        traía uno ya (mismo criterio que el cierre fila por fila que reemplaza).
        """
        if not ids:
            return
        await self.session.execute(
            update(IvrInteractionModel)
            .where(IvrInteractionModel.id.in_(ids))
            .values(
                **self._touch(
                    status=IvrCallStatus.FAILED,
                    ended_at=func.coalesce(IvrInteractionModel.ended_at, ended_at),
                    last_event=last_event,
                )
            )
        )

    async def get_active_for_campaign(
        self, campaign_id: uuid.UUID, ended_since: datetime, limit: int = 200
    ) -> Sequence[IvrInteractionModel]:
        """Llamadas en curso, más las que terminaron hace poco.

        Las recién terminadas se incluyen para que al recargar el monitor a
        mitad de campaña no desaparezcan de golpe los resultados que el usuario
        acaba de ver pasar.
        """
        result = await self.session.execute(
            select(IvrInteractionModel)
            .where(
                IvrInteractionModel.campaign_id == campaign_id,
                or_(
                    IvrInteractionModel.status.notin_(tuple(TERMINAL_CALL_STATUSES)),
                    IvrInteractionModel.ended_at >= ended_since,
                ),
            )
            .order_by(IvrInteractionModel.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_campaign_stats(self, campaign_id: uuid.UUID) -> dict[str, int]:
        """Contadores de la campaña en una sola pasada.

        Los de AMD, pulsaciones y transferencias son acumulados (sobre los
        campos persistidos), no derivados del estado actual: una llamada que
        fue HUMAN y terminó COMPLETED debe seguir contando como humana.
        """
        terminal = tuple(TERMINAL_CALL_STATUSES)
        has_dtmf = (
            func.coalesce(func.jsonb_array_length(IvrInteractionModel.dtmf_events), 0)
            > 0
        )

        stmt = select(
            func.count(IvrInteractionModel.id),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.status.notin_(terminal)
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.amd_status == "HUMAN"
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.amd_status.in_(("MACHINE", "NOTSURE"))
            ),
            func.count(IvrInteractionModel.id).filter(has_dtmf),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.transferred.is_(True)
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.status == IvrCallStatus.COMPLETED
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.status == IvrCallStatus.FAILED
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.status == IvrCallStatus.NO_ANSWER
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.status == IvrCallStatus.CANCELLED
            ),
        ).where(IvrInteractionModel.campaign_id == campaign_id)

        row = (await self.session.execute(stmt)).one()
        keys = (
            "total_calls",
            "active_calls",
            "human_detections",
            "machine_detections",
            "menu_selections",
            "transfers",
            "completed",
            "failed",
            "no_answer",
            "cancelled",
        )
        return {key: int(value or 0) for key, value in zip(keys, row)}

    async def list_for_campaign(
        self,
        campaign_id: uuid.UUID,
        page: int,
        page_size: int,
        status: IvrCallStatus | None = None,
        phone: str | None = None,
        outcome_key: str | None = None,
    ) -> tuple[Sequence[IvrInteractionModel], int]:
        filters: list[Any] = [IvrInteractionModel.campaign_id == campaign_id]
        if status is not None:
            filters.append(IvrInteractionModel.status == status)
        if phone:
            filters.append(IvrInteractionModel.phone.ilike(f"%{phone}%"))
        if outcome_key:
            filters.append(IvrInteractionModel.outcome_key == outcome_key)

        total = (
            await self.session.execute(
                select(func.count(IvrInteractionModel.id)).where(*filters)
            )
        ).scalar_one()

        result = await self.session.execute(
            select(IvrInteractionModel)
            .where(*filters)
            .order_by(IvrInteractionModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), int(total or 0)

    async def group_by_outcome(
        self, campaign_id: uuid.UUID
    ) -> list[tuple[str, str | None, int]]:
        """Distribución de resultados de negocio: (clave, etiqueta, cantidad)."""
        result = await self.session.execute(
            select(
                IvrInteractionModel.outcome_key,
                func.max(IvrInteractionModel.outcome_label),
                func.count(IvrInteractionModel.id),
            )
            .where(
                IvrInteractionModel.campaign_id == campaign_id,
                IvrInteractionModel.outcome_key.is_not(None),
            )
            .group_by(IvrInteractionModel.outcome_key)
            .order_by(func.count(IvrInteractionModel.id).desc())
        )
        return [(key, label, int(count)) for key, label, count in result.all()]

    async def group_by_column(
        self, campaign_id: uuid.UUID, column: Any
    ) -> list[tuple[str | None, int]]:
        """Conteo agrupado por una columna simple (AMD, nodo final, intento…)."""
        result = await self.session.execute(
            select(column, func.count(IvrInteractionModel.id))
            .where(IvrInteractionModel.campaign_id == campaign_id)
            .group_by(column)
            .order_by(func.count(IvrInteractionModel.id).desc())
        )
        return [
            (None if value is None else str(value), int(count))
            for value, count in result.all()
        ]

    async def get_funnel(self, campaign_id: uuid.UUID) -> dict[str, int]:
        """Embudo de la campaña: marcadas -> contestadas -> IVR -> transferidas.

        Cada escalón se cuenta sobre los campos persistidos, no sobre el estado
        actual, para que las llamadas ya cerradas sigan contando en los escalones
        por los que pasaron.
        """
        has_dtmf = (
            func.coalesce(func.jsonb_array_length(IvrInteractionModel.dtmf_events), 0)
            > 0
        )
        has_collect = (
            func.coalesce(
                func.jsonb_array_length(IvrInteractionModel.collected_data), 0
            )
            > 0
        )

        stmt = select(
            func.count(IvrInteractionModel.id),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.dial_status == "ANSWER"
            ),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.amd_status == "HUMAN"
            ),
            func.count(IvrInteractionModel.id).filter(has_dtmf | has_collect),
            func.count(IvrInteractionModel.id).filter(
                IvrInteractionModel.transferred.is_(True)
            ),
        ).where(IvrInteractionModel.campaign_id == campaign_id)

        row = (await self.session.execute(stmt)).one()
        keys = ("dialed", "answered", "human", "interacted", "transferred")
        return {key: int(value or 0) for key, value in zip(keys, row)}

    async def get_duration_summary(self, campaign_id: uuid.UUID) -> dict[str, int]:
        stmt = select(
            func.coalesce(func.sum(IvrInteractionModel.duration_seconds), 0),
            func.coalesce(func.avg(IvrInteractionModel.duration_seconds), 0),
            func.coalesce(func.sum(IvrInteractionModel.billable_seconds), 0),
        ).where(
            IvrInteractionModel.campaign_id == campaign_id,
            IvrInteractionModel.duration_seconds.is_not(None),
        )
        total, average, billable = (await self.session.execute(stmt)).one()
        return {
            "total_seconds": int(total or 0),
            "average_seconds": int(average or 0),
            "billable_seconds": int(billable or 0),
        }

    async def iter_for_export(
        self, campaign_id: uuid.UUID, limit: int = 50_000
    ) -> Sequence[IvrInteractionModel]:
        result = await self.session.execute(
            select(IvrInteractionModel)
            .where(IvrInteractionModel.campaign_id == campaign_id)
            .order_by(IvrInteractionModel.created_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de las interacciones IVR de la organización
        con el sello de la organización."""
        await self.soft_delete_where(
            IvrInteractionModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Inverso de ``soft_delete_by_organization``: solo lo que cayó
        con la organización."""
        await self.restore_where(
            IvrInteractionModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )
