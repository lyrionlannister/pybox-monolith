"""Tests unitarios de `StatementService`: generación de extracto (consolidado vs
puntual), filtro de créditos inactivos, y los dos lados de lectura (organización y
portal del titular). Contra repos reales atados a `db_session`; el PDF se genera de
verdad (`build_statement_pdf`, cubierto aparte en `test_statement_pdf_builder.py`) y
se guarda en el storage real de test (`_object_storage`, ver tests/conftest.py)."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app_platform.countries.repository.country_repository import CountryRepository
from core.security.constants.permissions import PORTFOLIO_CLIENTS
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from identity.users.schemas.user_session_schema import OrgSessionEntry, UserSession
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.statements.repository.statement_repository import StatementRepository
from receivables.statements.services.statement_service import StatementService
from tests.factories import unique_email
from tests.receivables.conftest import (
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)


def build_service(db_session) -> StatementService:
    return StatementService(
        session=db_session,
        statement_repo=StatementRepository(db_session),
        debtor_repo=DebtorRepository(db_session),
        portfolio_repo=PortfolioRepository(db_session),
        credit_repo=CreditRepository(db_session),
        payment_repo=PaymentRepository(db_session),
        organization_repo=OrganizationRepository(db_session),
    )


async def _real_user_id(db_session) -> uuid.UUID:
    """`StatementService.generate` guarda el PDF vía `document_service.store_generated`
    con `uploaded_by=session.user_id`, que tiene FK a `usuarios` -- un `user_id`
    aleatorio de `make_user_session_factory` (no persistido) revienta el INSERT con
    ForeignKeyViolationError. Se crea un usuario real mínimo para usar como dueño."""
    from identity.users.models.user_model import UserModel

    user = UserModel(firstname="Test", lastname="User", email=unique_email())
    db_session.add(user)
    await db_session.flush()
    return user.id


async def org_session(
    db_session,
    make_user_session_factory,
    org_id: uuid.UUID,
    *,
    role: UserRole = UserRole.ADMIN,
) -> UserSession:
    return make_user_session_factory(
        user_id=await _real_user_id(db_session),
        role=role,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                verification_status=VerificationStatus.APPROVED,
                permissions=frozenset({PORTFOLIO_CLIENTS}),
            )
        },
    )


async def no_access_session(db_session, make_user_session_factory) -> UserSession:
    return make_user_session_factory(
        user_id=await _real_user_id(db_session),
        role=UserRole.USER,
        scope=UserScope.ORGANIZATION,
        orgs={},
    )


async def self_session(
    db_session, make_user_session_factory, document_number_hash: str
) -> UserSession:
    return make_user_session_factory(
        user_id=await _real_user_id(db_session),
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
        # _require_self_debtors (ver statement_service.py) exige identidad
        # verificada además de ser deudor conocido: sin esto, el acceso se corta
        # antes de llegar a la lógica de pertenencia que prueban estos tests.
        identity_verification_status=IdentityVerificationStatus.APPROVED,
    )


@pytest.fixture
async def org_portfolio_debtor(db_session):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id, country="CO")
    db_session.add(portfolio)
    await db_session.flush()
    doc_number = "900123456"
    debtor = build_debtor(org.id, document_number_plain=doc_number)
    db_session.add(debtor)
    await db_session.flush()
    return org, portfolio, debtor, doc_number


async def _add_payment(db_session, credit_id: uuid.UUID, **overrides) -> PaymentModel:
    defaults = dict(
        limit_pay_date=datetime.now(timezone.utc),
        payment_date=datetime.now(timezone.utc),
        payment_amount=100,
        principal_payment=80,
        total_interest_amount=20,
        status=PaymentStatus.PAID,
        credit_id=credit_id,
    )
    defaults.update(overrides)
    payment = PaymentModel(**defaults)
    db_session.add(payment)
    await db_session.flush()
    return payment


class TestGenerateConsolidated:
    async def test_generates_statement_for_all_active_credits(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit1 = build_credit(portfolio.id, debtor.id, is_active=True)
        credit2 = build_credit(portfolio.id, debtor.id, is_active=True)
        inactive = build_credit(portfolio.id, debtor.id, is_active=False)
        db_session.add_all([credit1, credit2, inactive])
        await db_session.flush()
        await _add_payment(db_session, credit1.id)

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        result = await service.generate(debtor.id, portfolio.id, None, session)

        assert result.debtor_id == debtor.id
        assert result.credit_id is None
        assert result.credit_number is None
        assert result.document_id is not None

    async def test_no_active_credits_raises_422(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=False)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor.id, portfolio.id, None, session)
        assert exc_info.value.status_code == 422

    async def test_debtor_with_no_credits_in_portfolio_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        """Un deudor sin ningún crédito (ni activo ni inactivo) en este portafolio no
        tiene relación alguna con él -- `_require_debtor` ahora lo trata igual que un
        deudor de otro tenant (404), no como "sin créditos activos" (422, reservado a
        cuando SÍ hay créditos en el portafolio pero ninguno activo -- ver el test de
        arriba)."""
        org, portfolio, debtor, _ = org_portfolio_debtor
        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor.id, portfolio.id, None, session)
        assert exc_info.value.status_code == 404


class TestGenerateSingleCredit:
    async def test_generates_statement_for_specific_credit(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        result = await service.generate(debtor.id, portfolio.id, credit.id, session)

        assert result.credit_id == credit.id
        assert result.credit_number == credit.credit_number

    async def test_inactive_credit_id_raises_422(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=False)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor.id, portfolio.id, credit.id, session)
        assert exc_info.value.status_code == 422

    async def test_credit_from_other_portfolio_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        other_portfolio = build_portfolio(org.id)
        db_session.add(other_portfolio)
        await db_session.flush()
        credit = build_credit(other_portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor.id, portfolio.id, credit.id, session)
        assert exc_info.value.status_code == 404

    async def test_unknown_debtor_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, _, _ = org_portfolio_debtor
        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(uuid.uuid4(), portfolio.id, None, session)
        assert exc_info.value.status_code == 404

    async def test_from_an_unrelated_org_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        _, portfolio, debtor, _ = org_portfolio_debtor
        service = build_service(db_session)
        session = await no_access_session(db_session, make_user_session_factory)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor.id, portfolio.id, None, session)
        assert exc_info.value.status_code == 404


class TestCrossPortfolioIdor:
    """Regresión: `_require_debtor` debe rechazar (404) un `debtor_id` real que no
    tiene ningún crédito en el `portfolio_id` pedido, aunque la sesión SÍ tenga
    acceso legítimo a ese portafolio -- igual patrón que el IDOR ya cubierto en
    `test_debtor_service.py::TestCrossPortfolioIdor`. Antes del fix, `generate`
    dejaba pasar el `debtor_id` (existe globalmente) y solo fallaba después con un
    422 de "sin créditos activos", confirmando por el código de error que el deudor
    existe en algún otro portafolio del sistema."""

    async def test_generate_cross_portfolio_debtor_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, _, _ = org_portfolio_debtor
        other_org = build_organization()
        db_session.add(other_org)
        await db_session.flush()
        other_portfolio = build_portfolio(other_org.id)
        db_session.add(other_portfolio)
        await db_session.flush()
        debtor_elsewhere = build_debtor(other_org.id)
        db_session.add(debtor_elsewhere)
        await db_session.flush()
        credit = build_credit(other_portfolio.id, debtor_elsewhere.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.generate(debtor_elsewhere.id, portfolio.id, None, session)
        assert exc_info.value.status_code == 404

    async def test_list_for_org_cross_portfolio_debtor_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, _, _ = org_portfolio_debtor
        other_org = build_organization()
        db_session.add(other_org)
        await db_session.flush()
        other_portfolio = build_portfolio(other_org.id)
        db_session.add(other_portfolio)
        await db_session.flush()
        debtor_elsewhere = build_debtor(other_org.id)
        db_session.add(debtor_elsewhere)
        await db_session.flush()
        credit = build_credit(other_portfolio.id, debtor_elsewhere.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_for_org(debtor_elsewhere.id, portfolio.id, session)
        assert exc_info.value.status_code == 404


class TestListAndContentForOrg:
    async def test_list_for_org_returns_generated_statements(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)
        await service.generate(debtor.id, portfolio.id, None, session)

        result = await service.list_for_org(debtor.id, portfolio.id, session)

        assert result.total == 1
        assert result.items[0].organization_name == org.name

    async def test_get_content_for_org_wrong_debtor_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)
        statement = await service.generate(debtor.id, portfolio.id, None, session)

        other_debtor = build_debtor(org.id)
        db_session.add(other_debtor)
        await db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            await service.get_content_for_org(
                statement.id, other_debtor.id, portfolio.id, session
            )
        assert exc_info.value.status_code == 404

    async def test_get_content_for_org_returns_pdf_response(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, _ = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        service = build_service(db_session)
        session = await org_session(db_session, make_user_session_factory, org.id)
        statement = await service.generate(debtor.id, portfolio.id, None, session)

        response = await service.get_content_for_org(
            statement.id, debtor.id, portfolio.id, session
        )

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/pdf"


class TestSelfService:
    async def test_list_mine_resolves_debtor_by_document(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, doc_number = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        service = build_service(db_session)
        org_sess = await org_session(db_session, make_user_session_factory, org.id)
        await service.generate(debtor.id, portfolio.id, None, org_sess)

        doc_hash = encrypt_service.hash_document(doc_number)
        session = await self_session(db_session, make_user_session_factory, doc_hash)

        result = await service.list_mine(session)

        assert result.total == 1

    async def test_list_mine_without_matching_debtor_raises_404(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = await self_session(
            db_session,
            make_user_session_factory,
            encrypt_service.hash_document("000000000"),
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.list_mine(session)
        assert exc_info.value.status_code == 404

    async def test_get_content_mine_wrong_owner_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_debtor
    ):
        org, portfolio, debtor, doc_number = org_portfolio_debtor
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        service = build_service(db_session)
        org_sess = await org_session(db_session, make_user_session_factory, org.id)
        statement = await service.generate(debtor.id, portfolio.id, None, org_sess)

        other_hash = encrypt_service.hash_document("111111111")
        other_debtor = build_debtor(org.id, document_number_plain="111111111")
        db_session.add(other_debtor)
        await db_session.flush()
        session = await self_session(db_session, make_user_session_factory, other_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_content_mine(statement.id, session)
        assert exc_info.value.status_code == 404
