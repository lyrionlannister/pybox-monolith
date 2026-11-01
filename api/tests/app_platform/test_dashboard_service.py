"""Unit tests de `DashboardService` con repos mockeados (unittest.mock, sin DB): el
service es puro cálculo/orquestación sobre lo que devuelven los repos, así que un
doble alcanza para cubrir las ramas de negocio (porcentaje con denominador cero,
armado de la serie mensual con huecos) sin levantar datos reales de créditos.
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app_platform.dashboard.services.dashboard_service import DashboardService
from receivables.credits.repository.credit_repository import PortfolioCreditStats


def _make_service(**repo_overrides):
    repos = {
        "credit_repo": AsyncMock(),
        "portfolio_repo": AsyncMock(),
        "campaign_repo": AsyncMock(),
        "contact_repo": AsyncMock(),
    }
    repos.update(repo_overrides)
    return DashboardService(**repos), repos


class TestGetOrganizationStats:
    async def test_percentage_computed_normally(self):
        service, repos = _make_service()
        repos["credit_repo"].get_organization_stats.return_value = PortfolioCreditStats(
            creditos=100,
            titulares=50,
            codeudores=10,
            clientes_unicos=80,
            documentos_unicos=5,
            total_mora=Decimal("12345.6"),
        )
        repos[
            "portfolio_repo"
        ].count_active_inactive_by_organization_id.return_value = (3, 1)

        result = await service.get_organization_stats(uuid.uuid4())

        assert result.portfolios_count == 4
        assert result.portfolios_active_count == 3
        assert result.portfolios_inactive_count == 1
        assert result.credits_count == 100
        assert result.debtors_count == 50
        assert result.unique_debtors_count == 80
        assert result.total_overdue_amount == Decimal("12345.6")
        assert result.debtors_loaded_percentage == 62.5

    async def test_percentage_is_zero_when_no_unique_debtors(self):
        # clientes_unicos=0 dividiría por cero -- debe caer al 0.0 explícito, no
        # reventar con ZeroDivisionError.
        service, repos = _make_service()
        repos["credit_repo"].get_organization_stats.return_value = PortfolioCreditStats(
            creditos=0,
            titulares=0,
            codeudores=0,
            clientes_unicos=0,
            documentos_unicos=0,
            total_mora=0.0,
        )
        repos[
            "portfolio_repo"
        ].count_active_inactive_by_organization_id.return_value = (0, 0)

        result = await service.get_organization_stats(uuid.uuid4())

        assert result.debtors_loaded_percentage == 0.0


class TestListCampaignOptions:
    async def test_maps_campaigns_to_options(self):
        service, repos = _make_service()
        campaign = type("C", (), {"id": uuid.uuid4(), "name": "Campaña Q1"})()
        repos["campaign_repo"].list_by_organization_id.return_value = [campaign]

        result = await service.list_campaign_options(uuid.uuid4())

        assert len(result) == 1
        assert result[0].id == campaign.id
        assert result[0].name == "Campaña Q1"


class TestGetSendStatusCounts:
    async def test_maps_rows_to_items(self):
        service, repos = _make_service()
        repos["contact_repo"].get_send_status_counts.return_value = [
            ("entregado", 10),
            ("fallido", 2),
        ]

        result = await service.get_send_status_counts(uuid.uuid4())

        assert [(i.status, i.count) for i in result.items] == [
            ("entregado", 10),
            ("fallido", 2),
        ]


class TestGetMonthlySends:
    async def test_unknown_campaign_raises_404(self):
        service, repos = _make_service()
        repos["campaign_repo"].get_by_id_and_organization_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await service.get_monthly_sends(uuid.uuid4(), uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_valid_campaign_fills_gaps_with_zero(self):
        service, repos = _make_service()
        campaign_id = uuid.uuid4()
        org_id = uuid.uuid4()
        campaign = type("C", (), {"id": campaign_id, "name": "Campaña Activa"})()
        repos["campaign_repo"].get_by_id_and_organization_id.return_value = campaign

        # Últimos 12 meses: solo devolvemos datos para el mes actual, el resto debe
        # completarse con 0 en la serie.
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        repos["contact_repo"].get_monthly_sends_by_campaign.return_value = [
            (date(now.year, now.month, 1), 42)
        ]

        result = await service.get_monthly_sends(org_id, campaign_id)

        assert result.campaign_id == campaign_id
        assert result.campaign_name == "Campaña Activa"
        assert len(result.points) == 12
        current_period = f"{now.year}-{now.month:02d}"
        current_point = next(p for p in result.points if p.period == current_period)
        assert current_point.count == 42
        # Cualquier otro mes sin datos queda en 0, no ausente de la serie.
        assert all(p.count == 0 for p in result.points if p.period != current_period)
