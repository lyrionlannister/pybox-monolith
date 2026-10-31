"""Schemas de respuesta del dashboard de organización."""

import uuid
from decimal import Decimal

from pydantic import Field

from core.base.schema_base import BaseSchema


class OrganizationStatsResponse(BaseSchema):
    portfolios_count: int = Field(description="Total de portafolios de la organización")
    portfolios_active_count: int = Field(description="Portafolios activos")
    portfolios_inactive_count: int = Field(description="Portafolios inactivos")
    credits_count: int = Field(description="Total de créditos en todos los portafolios")
    debtors_count: int = Field(
        description="Total de deudores titulares únicos (cédulas cargadas)"
    )
    unique_debtors_count: int = Field(
        description="Total de clientes únicos (titulares + co-deudores sin duplicados)"
    )
    total_overdue_amount: Decimal = Field(
        description=(
            "Suma del saldo capital en mora en todos los portafolios de la organización"
        )
    )
    debtors_loaded_percentage: float = Field(
        description=(
            "Porcentaje que representan los titulares sobre el total de "
            "clientes únicos (titulares + co-deudores)"
        )
    )


class DashboardCampaignOption(BaseSchema):
    id: uuid.UUID = Field(description="ID de la campaña")
    name: str = Field(description="Nombre de la campaña")


class MonthlySendsPoint(BaseSchema):
    period: str = Field(description="Periodo en formato YYYY-MM")
    count: int = Field(description="Cantidad de envíos efectivos en el periodo")


class MonthlySendsResponse(BaseSchema):
    campaign_id: uuid.UUID = Field(description="ID de la campaña consultada")
    campaign_name: str = Field(description="Nombre de la campaña consultada")
    points: list[MonthlySendsPoint] = Field(description="Serie de los últimos 12 meses")


class SendStatusCountItem(BaseSchema):
    status: str = Field(description="Valor del status (ContactStatus)")
    count: int = Field(description="Cantidad de contactos en este status")


class SendStatusCountsResponse(BaseSchema):
    items: list[SendStatusCountItem] = Field(
        description="Statuses con al menos un contacto, ordenados por volumen desc"
    )
