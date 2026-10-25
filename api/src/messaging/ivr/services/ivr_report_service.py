"""Reporte de resultados de una campaña IVR."""

from __future__ import annotations

import csv
import io
import uuid

from messaging.ivr.models.ivr_interaction_model import IvrInteractionModel
from messaging.ivr.repository.ivr_interaction_repository import IvrInteractionRepository
from messaging.ivr.schemas.ivr_report_schemas import (
    IvrBreakdownRow,
    IvrCampaignReportSchema,
    IvrDurationSchema,
    IvrFunnelSchema,
    IvrOutcomeRow,
)

_EXPORT_COLUMNS = [
    "interaction_id",
    "telefono",
    "cliente",
    "documento",
    "estado",
    "resultado",
    "clave_resultado",
    "amd",
    "marcacion",
    "nodo_final",
    "razon_final",
    "transferida",
    "intento",
    "duracion_segundos",
    "iniciada_en",
    "contestada_en",
    "finalizada_en",
]


class IvrReportService:
    def __init__(self, interaction_repo: IvrInteractionRepository) -> None:
        self._interactions = interaction_repo

    async def build(self, campaign_id: uuid.UUID) -> IvrCampaignReportSchema:
        outcome_rows = await self._interactions.group_by_outcome(campaign_id)
        typified = sum(count for _, _, count in outcome_rows)

        stats = await self._interactions.get_campaign_stats(campaign_id)
        funnel = await self._interactions.get_funnel(campaign_id)
        duration = await self._interactions.get_duration_summary(campaign_id)

        by_amd = await self._interactions.group_by_column(
            campaign_id, IvrInteractionModel.amd_status
        )
        by_end_node = await self._interactions.group_by_column(
            campaign_id, IvrInteractionModel.ivr_end_node_id
        )
        by_attempt = await self._interactions.group_by_column(
            campaign_id, IvrInteractionModel.attempt_number
        )

        return IvrCampaignReportSchema(
            campaign_id=str(campaign_id),
            total_calls=stats["total_calls"],
            typified_calls=typified,
            outcomes=[
                IvrOutcomeRow(
                    key=key,
                    label=label,
                    count=count,
                    # El porcentaje se calcula sobre lo tipificado, no sobre el
                    # total: mezclar ambos haría que los porcentajes no sumen 100
                    # cuando hay llamadas sin resultado resuelto.
                    percentage=round(count * 100 / typified, 2) if typified else 0.0,
                )
                for key, label, count in outcome_rows
            ],
            by_amd=[
                IvrBreakdownRow(value=value, count=count) for value, count in by_amd
            ],
            by_end_node=[
                IvrBreakdownRow(value=value, count=count)
                for value, count in by_end_node
            ],
            by_attempt=[
                IvrBreakdownRow(value=value, count=count) for value, count in by_attempt
            ],
            funnel=IvrFunnelSchema(**funnel),
            duration=IvrDurationSchema(**duration),
        )

    async def export_csv(self, campaign_id: uuid.UUID) -> str:
        rows = await self._interactions.iter_for_export(campaign_id)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_EXPORT_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.interaction_id,
                    row.phone,
                    _csv_safe(row.customer_name),
                    _csv_safe(row.customer_document),
                    str(row.status),
                    _csv_safe(row.outcome_label),
                    row.outcome_key or "",
                    row.amd_status or "",
                    row.dial_status or "",
                    row.ivr_end_node_id or "",
                    _csv_safe(row.ivr_end_reason),
                    "si" if row.transferred else "no",
                    row.attempt_number,
                    row.duration_seconds if row.duration_seconds is not None else "",
                    _iso(row.started_at),
                    _iso(row.answered_at),
                    _iso(row.ended_at),
                ]
            )
        return buffer.getvalue()


def _iso(value) -> str:
    return value.isoformat() if value is not None else ""


def _csv_safe(value: str | None) -> str:
    """Antepone `'` a texto libre que empiece en =+-@: evita que Excel/Sheets lo
    interprete como fórmula al abrir el CSV (CWE-1236)."""
    text = value or ""
    return f"'{text}" if text and text[0] in "=+-@" else text
