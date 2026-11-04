"""Tests unitarios de `SegmentService`: construcción/CRUD de un segmento y las dos
ramas de `execute` (preview vs audit). `DmlService` se mockea (unittest.mock) porque
la ejecución dinámica de queries pertenece a `app_platform.schema_manager` -- lo que
importa acá es que `SegmentService` arme bien la llamada y trate distinto un preview
(no persiste nada) de un audit (persiste `SegmentExecutionModel` y guarda el archivo).
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app_platform.schema_manager.services.dml_service import DmlService
from core.security.constants.permissions import (
    PORTFOLIO_CLIENTS,
    PORTFOLIO_COMMUNICATIONS,
)
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry, UserSession
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.repository.segment_execution_repository import (
    SegmentExecutionRepository,
)
from receivables.segments.repository.segment_repository import SegmentRepository
from receivables.segments.schemas.segment_schemas import (
    SegmentCreateRequest,
    SegmentExecuteRequest,
    SegmentQueryConfig,
    SegmentUpdateRequest,
)
from receivables.segments.services.segment_service import SegmentService
from tests.receivables.conftest import build_organization, build_portfolio


def build_service(db_session, dml_mock=None) -> SegmentService:
    return SegmentService(
        segment_repo=SegmentRepository(db_session),
        execution_repo=SegmentExecutionRepository(db_session),
        dml_service=dml_mock or AsyncMock(spec=DmlService),
        portfolio_repo=PortfolioRepository(db_session),
    )


def org_session(
    make_user_session_factory,
    org_id: uuid.UUID,
    *,
    role: UserRole = UserRole.ADMIN,
    permissions: frozenset[str] = frozenset({PORTFOLIO_COMMUNICATIONS}),
) -> UserSession:
    return make_user_session_factory(
        role=role,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                verification_status=VerificationStatus.APPROVED,
                permissions=permissions,
            )
        },
    )


def no_access_session(make_user_session_factory) -> UserSession:
    return make_user_session_factory(
        role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
    )


def query_config(**overrides) -> SegmentQueryConfig:
    defaults = dict(tables=[{"name": "deudores", "columns": ["nombre_completo"]}])
    defaults.update(overrides)
    return SegmentQueryConfig.model_validate(defaults)


@pytest.fixture
async def org_and_portfolio(db_session):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    return org, portfolio


class TestCreate:
    async def test_creates_segment_with_given_criteria(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)

        result = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Mora 30+", filter_criteria=query_config()),
            session,
        )

        assert result.id is not None
        assert result.name == "Mora 30+"
        assert result.portfolio_id == portfolio.id
        assert result.filter_criteria["tables"][0]["name"] == "deudores"

    async def test_create_from_an_unrelated_org_raises_404(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        _, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = no_access_session(make_user_session_factory)

        with pytest.raises(HTTPException) as exc_info:
            await service.create(
                portfolio.id,
                SegmentCreateRequest(name="X", filter_criteria=query_config()),
                session,
            )
        assert exc_info.value.status_code == 404

    async def test_create_unknown_portfolio_raises_404(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = no_access_session(make_user_session_factory)

        with pytest.raises(HTTPException) as exc_info:
            await service.create(
                uuid.uuid4(),
                SegmentCreateRequest(name="X", filter_criteria=query_config()),
                session,
            )
        assert exc_info.value.status_code == 404


class TestListing:
    async def test_list_by_org_paginates(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        for i in range(3):
            await service.create(
                portfolio.id,
                SegmentCreateRequest(name=f"Seg {i}", filter_criteria=query_config()),
                session,
            )

        items, total = await service.list_by_org(
            portfolio.id, page=1, page_size=2, user_session=session
        )
        assert total == 3
        assert len(items) == 2

    async def test_list_all_by_org_is_cached(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        """Segunda llamada no debe volver a golpear el repo -- cache-aside vía
        `cache_service.get_or_set` (Redis fake del conftest raíz)."""
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Seg", filter_criteria=query_config()),
            session,
        )

        first = await service.list_all_by_org(portfolio.id, session)
        assert len(first) == 1

        # Crear un segundo segmento directo por repo (sin pasar por `create`, que
        # busteo el cache) -- si `list_all_by_org` sigue sirviendo desde cache, no debe
        # verlo.
        segment_repo = SegmentRepository(db_session)
        from receivables.segments.models.segment_model import SegmentModel

        await segment_repo.add(
            SegmentModel(
                name="Directo",
                filter_criteria={"tables": []},
                portfolio_id=portfolio.id,
            )
        )

        second = await service.list_all_by_org(portfolio.id, session)
        assert len(second) == 1

    async def test_create_busts_list_cache(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)

        await service.list_all_by_org(portfolio.id, session)
        await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Nuevo", filter_criteria=query_config()),
            session,
        )

        result = await service.list_all_by_org(portfolio.id, session)
        assert len(result) == 1


class TestGetUpdateDelete:
    async def test_get_wrong_portfolio_raises_404(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        other_portfolio = build_portfolio(org.id)
        db_session.add(other_portfolio)
        await db_session.flush()
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Seg", filter_criteria=query_config()),
            session,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.get(segment.id, other_portfolio.id, session)
        assert exc_info.value.status_code == 404

    async def test_update_changes_fields(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Original", filter_criteria=query_config()),
            session,
        )

        updated = await service.update(
            segment.id,
            portfolio.id,
            SegmentUpdateRequest(name="Renombrado", description="nueva desc"),
            session,
        )

        assert updated.name == "Renombrado"
        assert updated.description == "nueva desc"

    async def test_delete_removes_segment(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Borrar", filter_criteria=query_config()),
            session,
        )

        await service.delete(segment.id, portfolio.id, session)

        with pytest.raises(HTTPException) as exc_info:
            await service.get(segment.id, portfolio.id, session)
        assert exc_info.value.status_code == 404


class TestExecute:
    def _ok_result(self, rows: list[dict]) -> dict:
        columns = list(rows[0].keys()) if rows else []
        return {
            "success": True,
            "data": json.dumps(rows),
            "columns": columns,
            "rows": len(rows),
            "error": "",
        }

    async def test_preview_mode_does_not_persist_execution(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = self._ok_result(
            [{"nombre_completo": "Ana"}]
        )
        service = build_service(db_session, dml_mock)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Preview", filter_criteria=query_config()),
            session,
        )

        result = await service.execute(
            segment.id,
            portfolio.id,
            SegmentExecuteRequest(mode="preview"),
            uuid.uuid4(),
            session,
        )

        assert result["success"] is True
        assert result["rows"] == 1
        assert result["file_name"] is None
        assert result["document_id"] is None
        executions = await service.list_executions(segment.id, portfolio.id, session)
        assert len(executions) == 0

    async def test_audit_mode_persists_execution_and_file(
        self,
        db_session,
        make_user_session_factory,
        org_and_portfolio,
        real_admin_user_id,
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = self._ok_result(
            [{"nombre_completo": "Ana"}, {"nombre_completo": "Luis"}]
        )
        service = build_service(db_session, dml_mock)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Audit", filter_criteria=query_config()),
            session,
        )

        result = await service.execute(
            segment.id,
            portfolio.id,
            SegmentExecuteRequest(mode="audit"),
            real_admin_user_id,
            session,
        )

        assert result["rows"] == 2
        assert result["file_name"] is not None
        assert result["document_id"] is not None

        executions = await service.list_executions(segment.id, portfolio.id, session)
        assert len(executions) == 1
        assert executions[0].mode == "audit"
        assert executions[0].rows == 2
        assert executions[0].executed_by == real_admin_user_id

    async def test_dml_failure_raises_500(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = {
            "success": False,
            "error": "columna inexistente",
        }
        service = build_service(db_session, dml_mock)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Falla", filter_criteria=query_config()),
            session,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.execute(
                segment.id,
                portfolio.id,
                SegmentExecuteRequest(mode="preview"),
                uuid.uuid4(),
                session,
            )
        assert exc_info.value.status_code == 500

    async def test_invalid_query_config_raises_422_with_dml_message(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = {
            "success": False,
            "error": "Una de las columnas configuradas no existe en su tabla.",
            "status_code": 422,
        }
        service = build_service(db_session, dml_mock)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Config mala", filter_criteria=query_config()),
            session,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.execute(
                segment.id,
                portfolio.id,
                SegmentExecuteRequest(mode="preview"),
                uuid.uuid4(),
                session,
            )
        assert exc_info.value.status_code == 422
        assert (
            exc_info.value.detail
            == "Una de las columnas configuradas no existe en su tabla."
        )

    async def _execute_and_get_dml_kwargs(
        self, db_session, org_and_portfolio, make_user_session_factory, **session_kwargs
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = self._ok_result([])
        service = build_service(db_session, dml_mock)
        creator = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Documentos", filter_criteria=query_config()),
            creator,
        )
        session = (
            org_session(make_user_session_factory, org.id, **session_kwargs)
            if session_kwargs
            else creator
        )
        await service.execute(
            segment.id,
            portfolio.id,
            SegmentExecuteRequest(mode="preview"),
            uuid.uuid4(),
            session,
        )
        _, kwargs = dml_mock.execute_query.call_args
        return kwargs

    async def test_document_is_decrypted_with_clients_permission(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        kwargs = await self._execute_and_get_dml_kwargs(
            db_session,
            org_and_portfolio,
            make_user_session_factory,
            permissions=frozenset({PORTFOLIO_COMMUNICATIONS, PORTFOLIO_CLIENTS}),
        )
        assert kwargs["decrypt_sensitive"] is True

    async def test_document_stays_encrypted_with_communications_only(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        # Ejecutar un segmento solo exige comunicaciones: sin `portfolio.clients` el
        # usuario no debe poder leer documentos que DebtorService no le mostraría.
        kwargs = await self._execute_and_get_dml_kwargs(
            db_session, org_and_portfolio, make_user_session_factory
        )
        assert kwargs["decrypt_sensitive"] is False

    async def test_document_is_decrypted_for_global_session(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        _, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = self._ok_result([])
        service = build_service(db_session, dml_mock)
        session = make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Global", filter_criteria=query_config()),
            session,
        )
        await service.execute(
            segment.id,
            portfolio.id,
            SegmentExecuteRequest(mode="preview"),
            uuid.uuid4(),
            session,
        )
        _, kwargs = dml_mock.execute_query.call_args
        assert kwargs["decrypt_sensitive"] is True

    async def test_execute_passes_portfolio_scoping_to_dml(
        self, db_session, make_user_session_factory, org_and_portfolio
    ):
        org, portfolio = org_and_portfolio
        dml_mock = AsyncMock(spec=DmlService)
        dml_mock.execute_query.return_value = self._ok_result([])
        service = build_service(db_session, dml_mock)
        session = org_session(make_user_session_factory, org.id)
        segment = await service.create(
            portfolio.id,
            SegmentCreateRequest(name="Scoped", filter_criteria=query_config()),
            session,
        )

        await service.execute(
            segment.id,
            portfolio.id,
            SegmentExecuteRequest(mode="preview", limit=50),
            uuid.uuid4(),
            session,
        )

        _, kwargs = dml_mock.execute_query.call_args
        assert kwargs["portfolio_ids"] == [portfolio.id]
        assert kwargs["organization_ids"] == [org.id]
        assert kwargs["limit"] == 50
