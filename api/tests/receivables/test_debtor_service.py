"""Regresión del IDOR crítico: `DebtorService._require_debtor` debe rechazar (404)
cualquier `debtor_id` que no tenga ningún crédito (titular o codeudor) en el
`portfolio_id` solicitado, aunque el llamante SÍ tenga acceso legítimo a ese
portafolio. Antes del fix (`credit_repo.debtor_belongs_to_portfolio`), cualquier
usuario con acceso a SU portafolio podía leer/modificar deudores de OTRAS
organizaciones con solo adivinar/enumerar un `debtor_id` ajeno.

Se prueba contra repositorios reales atados a `db_session` (sin mocks): lo que
importa es el comportamiento end-to-end de la query, no la implementación interna.
"""

import uuid

import pytest
from fastapi import HTTPException

from app_platform.documents.repository.document_repository import DocumentRepository
from core.security.constants.permissions import PORTFOLIO_CLIENTS
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry, UserSession
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.address_repository import AddressRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.debtors.schemas.debtor_schemas import (
    CreateAddressRequest,
    CreateContactMethodRequest,
)
from receivables.debtors.services.debtor_service import DebtorService
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from tests.receivables.conftest import (
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)


def build_service(db_session) -> DebtorService:
    return DebtorService(
        session=db_session,
        debtor_repo=DebtorRepository(db_session),
        address_repo=AddressRepository(db_session),
        contact_repo=ContactMethodRepository(db_session),
        portfolio_repo=PortfolioRepository(db_session),
        credit_repo=CreditRepository(db_session),
        payment_repo=PaymentRepository(db_session),
        document_repo=DocumentRepository(db_session),
    )


def org_session(
    make_user_session_factory, org_id: uuid.UUID, *, role: UserRole = UserRole.USER
) -> UserSession:
    """Sesión org-scoped con permiso `portfolio.clients` sobre `org_id` -- el mínimo
    necesario para pasar `_check_portfolio_access` de un portafolio de esa org."""
    return make_user_session_factory(
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


def non_global_session(make_user_session_factory) -> UserSession:
    """Cualquier sesión con `is_global=False` -- para los casos 400 de portfolioId faltante."""
    return make_user_session_factory(
        role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
    )


@pytest.fixture
async def two_orgs(db_session):
    """Dos organizaciones, cada una con su propio portafolio -- reproduce el escenario
    real del IDOR: un deudor con crédito solo en el portafolio de la organización 1."""
    org1 = build_organization()
    org2 = build_organization()
    db_session.add_all([org1, org2])
    await db_session.flush()

    portfolio_a = build_portfolio(org1.id)
    portfolio_b = build_portfolio(org2.id)
    db_session.add_all([portfolio_a, portfolio_b])
    await db_session.flush()

    return org1, org2, portfolio_a, portfolio_b


@pytest.fixture
async def debtor_only_in_portfolio_a(db_session, two_orgs):
    """Deudor titular de un crédito EXCLUSIVAMENTE en el portafolio A (org 1) -- no
    tiene ningún crédito (ni como titular ni como codeudor) en el portafolio B."""
    org1, _, portfolio_a, _ = two_orgs
    debtor = build_debtor(org1.id)
    db_session.add(debtor)
    await db_session.flush()
    credit = build_credit(portfolio_a.id, debtor.id)
    db_session.add(credit)
    await db_session.flush()
    return debtor


class TestCrossPortfolioIdor:
    """Caso 1 y 2: 6 métodos independientes, cada uno con su propio 404 -- un
    refactor que copie el patrón sin `_require_debtor(..., portfolio_id)` reabriría
    el IDOR en ese endpoint puntual sin que los demás lo detecten."""

    async def test_get_debtor_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor(
                debtor_only_in_portfolio_a.id, session, portfolio_id=portfolio_b.id
            )
        assert exc_info.value.status_code == 404

    async def test_get_debtor_credits_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor_credits(
                debtor_only_in_portfolio_a.id, portfolio_b.id, session
            )
        assert exc_info.value.status_code == 404

    async def test_get_debtor_credits_with_installments_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor_credits_with_installments(
                debtor_only_in_portfolio_a.id, portfolio_b.id, session
            )
        assert exc_info.value.status_code == 404

    async def test_get_debtor_documents_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor_documents(
                debtor_only_in_portfolio_a.id, portfolio_b.id, session
            )
        assert exc_info.value.status_code == 404

    async def test_get_debtor_document_content_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor_document_content(
                debtor_only_in_portfolio_a.id, uuid.uuid4(), portfolio_b.id, session
            )
        assert exc_info.value.status_code == 404

    async def test_create_address_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)
        data = CreateAddressRequest(
            address="Calle 1", city="Bogota", state="Bogota", country="CO"
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_address(
                debtor_only_in_portfolio_a.id,
                data,
                session,
                portfolio_id=portfolio_b.id,
            )
        assert exc_info.value.status_code == 404

    async def test_create_contact_method_cross_portfolio_returns_404(
        self,
        db_session,
        make_user_session_factory,
        two_orgs,
        debtor_only_in_portfolio_a,
    ):
        _, org2, _, portfolio_b = two_orgs
        service = build_service(db_session)
        session = org_session(make_user_session_factory, org2.id)
        data = CreateContactMethodRequest(
            contact_type=ContactMethodType.EMAIL, contact_value="x@example.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_contact_method(
                debtor_only_in_portfolio_a.id,
                data,
                session,
                portfolio_id=portfolio_b.id,
            )
        assert exc_info.value.status_code == 404


class TestCodebtorResolvesInPortfolio:
    """Caso 3: `debtor_belongs_to_portfolio` mira titular O codeudor -- un deudor que
    solo es codeudor de un crédito del portafolio SÍ debe resolver (200), no 404."""

    async def test_get_debtor_as_codebtor_resolves(
        self, db_session, make_user_session_factory, two_orgs
    ):
        org1, _, portfolio_a, _ = two_orgs
        titular = build_debtor(org1.id)
        codebtor = build_debtor(org1.id)
        db_session.add_all([titular, codebtor])
        await db_session.flush()
        credit = build_credit(portfolio_a.id, titular.id, codebtor_id=codebtor.id)
        db_session.add(credit)
        await db_session.flush()

        service = build_service(db_session)
        session = org_session(make_user_session_factory, org1.id)

        result = await service.get_debtor(
            codebtor.id, session, portfolio_id=portfolio_a.id
        )
        assert result.id == codebtor.id


class TestMissingPortfolioIdRequiresGlobal:
    """Caso 4: sin `portfolioId` y sin scope GLOBAL -> 400 (no 403, no 404) en los
    cuatro puntos de entrada que aceptan `portfolio_id` opcional."""

    async def test_get_debtor_without_portfolio_id_returns_400(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = non_global_session(make_user_session_factory)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_debtor(uuid.uuid4(), session, portfolio_id=None)
        assert exc_info.value.status_code == 400

    async def test_list_debtors_without_portfolio_id_returns_400(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = non_global_session(make_user_session_factory)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_debtors(session, page=1, page_size=10, portfolio_id=None)
        assert exc_info.value.status_code == 400

    async def test_create_address_without_portfolio_id_returns_400(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = non_global_session(make_user_session_factory)
        data = CreateAddressRequest(
            address="Calle 1", city="Bogota", state="Bogota", country="CO"
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_address(uuid.uuid4(), data, session, portfolio_id=None)
        assert exc_info.value.status_code == 400

    async def test_create_contact_method_without_portfolio_id_returns_400(
        self, db_session, make_user_session_factory
    ):
        service = build_service(db_session)
        session = non_global_session(make_user_session_factory)
        data = CreateContactMethodRequest(
            contact_type=ContactMethodType.EMAIL, contact_value="x@example.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_contact_method(
                uuid.uuid4(), data, session, portfolio_id=None
            )
        assert exc_info.value.status_code == 400


class TestRelatedContactsScopedToPortfolio:
    """Caso 5: `get_related_contacts` solo debe traer codeudores de créditos EN el
    portafolio pedido, aunque el mismo titular tenga otro crédito (con otro
    codeudor) en un portafolio distinto de la misma organización."""

    async def test_only_returns_codebtors_of_requested_portfolio(
        self, db_session, make_user_session_factory, two_orgs
    ):
        org1, _, portfolio_a, _ = two_orgs
        portfolio_a2 = build_portfolio(org1.id)
        db_session.add(portfolio_a2)
        await db_session.flush()

        titular = build_debtor(org1.id)
        codebtor_in_a = build_debtor(org1.id)
        codebtor_in_a2 = build_debtor(org1.id)
        db_session.add_all([titular, codebtor_in_a, codebtor_in_a2])
        await db_session.flush()

        db_session.add_all(
            [
                build_credit(portfolio_a.id, titular.id, codebtor_id=codebtor_in_a.id),
                build_credit(
                    portfolio_a2.id, titular.id, codebtor_id=codebtor_in_a2.id
                ),
            ]
        )
        await db_session.flush()

        service = build_service(db_session)
        session = org_session(make_user_session_factory, org1.id)

        result = await service.get_related_contacts(titular.id, portfolio_a.id, session)

        assert result.debtor.id == titular.id
        codebtor_ids = {c.id for c in result.codebtors}
        assert codebtor_ids == {codebtor_in_a.id}


class TestPhonePrefixScopedByPortfolio:
    """Un deudor con créditos en portafolios de países distintos (misma empresa) debe
    resolver el indicativo telefónico del portafolio de la operación en curso, no el
    del crédito más reciente en cualquier portafolio."""

    async def test_uses_the_requested_portfolio_country_not_the_most_recent_credit(
        self, db_session, make_user_session_factory
    ):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio_co = build_portfolio(org.id, country="CO")
        portfolio_mx = build_portfolio(org.id, country="MX")
        db_session.add_all([portfolio_co, portfolio_mx])
        await db_session.flush()

        debtor = build_debtor(org.id)
        db_session.add(debtor)
        await db_session.flush()
        # El crédito en CO es el más "reciente" en orden de inserción -- si el fix
        # no filtrara por portfolio_id, tomaría su indicativo (57) aunque la
        # operación en curso sea sobre el portafolio MX.
        db_session.add_all(
            [
                build_credit(portfolio_co.id, debtor.id),
                build_credit(portfolio_mx.id, debtor.id),
            ]
        )
        await db_session.flush()

        service = build_service(db_session)
        session = org_session(make_user_session_factory, org.id)
        data = CreateContactMethodRequest(
            contact_type=ContactMethodType.PHONE, contact_value="3001234567"
        )

        result = await service.create_contact_method(
            debtor.id, data, session, portfolio_id=portfolio_mx.id
        )

        assert result.contact_value.startswith("52")
        assert not result.contact_value.startswith("57")
