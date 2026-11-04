"""IDOR: `PaymentCheckoutService`/`PaymentSourceService` no pueden iniciar un cobro ni
tokenizar/listar/revocar un medio de pago sobre una cuota o fuente que no es del deudor
autenticado -- misma cadena de pertenencia que `PaymentSelfServiceService`
(`PaymentOwnershipResolver` compartido, ver `test_payment_selfservice_service.py`). El
`gateway_resolver` se mockea porque el IDOR se corta ANTES de resolver credenciales o
hacer cualquier llamada HTTP a Wompi."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.security.services.encrypt_service import encrypt_service
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payment_gateways.enums.payment_gateway_enums import (
    PaymentSourceStatus,
    PaymentSourceType,
    ReceivablesGatewayProvider,
)
from receivables.payment_gateways.gateways.base import CardPaymentMethod
from receivables.payment_gateways.models.payment_source_model import (
    DebtorPaymentSourceModel,
)
from receivables.payment_gateways.repository.payment_attempt_repository import (
    CreditPaymentAttemptRepository,
)
from receivables.payment_gateways.repository.payment_source_repository import (
    DebtorPaymentSourceRepository,
)
from receivables.payment_gateways.services.payment_checkout_service import (
    PaymentCheckoutService,
)
from receivables.payment_gateways.services.payment_source_service import (
    PaymentSourceService,
)
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.payments.services.payment_ownership_resolver import (
    PaymentOwnershipResolver,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from tests.receivables.conftest import (
    add_organization,
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)


def self_session(make_user_session_factory, document_number_hash: str):
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
        identity_verification_status=IdentityVerificationStatus.APPROVED,
    )


async def _add_payment(db_session, credit_id: uuid.UUID, **overrides) -> PaymentModel:
    defaults = dict(
        limit_pay_date=datetime.now(timezone.utc),
        payment_amount=100,
        principal_payment=80,
        total_interest_amount=20,
        status=PaymentStatus.PENDING,
        credit_id=credit_id,
    )
    defaults.update(overrides)
    payment = PaymentModel(**defaults)
    db_session.add(payment)
    await db_session.flush()
    return payment


def make_ownership_resolver(db_session) -> PaymentOwnershipResolver:
    return PaymentOwnershipResolver(
        DebtorRepository(db_session),
        CreditRepository(db_session),
        PaymentRepository(db_session),
        PortfolioRepository(db_session),
    )


@pytest.fixture
async def payment_of_another_debtor(db_session):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    owner = build_debtor(org.id)
    db_session.add(owner)
    await db_session.flush()
    credit = build_credit(portfolio.id, owner.id, is_active=True)
    db_session.add(credit)
    await db_session.flush()
    return await _add_payment(db_session, credit.id)


class TestPaymentCheckoutServiceIdor:
    async def test_create_transaction_on_others_payment_raises_404(
        self, db_session, make_user_session_factory, payment_of_another_debtor
    ):
        requester_doc = "111222333"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = PaymentCheckoutService(
            make_ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            AsyncMock(),
            PaymentRepository(db_session),
        )
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )
        card = CardPaymentMethod(
            number="4242424242424242",
            cvc="123",
            exp_month="12",
            exp_year="29",
            card_holder="Test",
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_transaction(
                session, payment_of_another_debtor.id, card, "debtor@example.com"
            )
        assert exc_info.value.status_code == 404


class TestPaymentSourceServiceIdor:
    async def test_list_sources_on_others_payment_raises_404(
        self, db_session, make_user_session_factory, payment_of_another_debtor
    ):
        requester_doc = "444555666"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = PaymentSourceService(
            make_ownership_resolver(db_session),
            DebtorPaymentSourceRepository(db_session),
            AsyncMock(),
        )
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.list_active(session, payment_of_another_debtor.id)
        assert exc_info.value.status_code == 404

    async def test_revoke_source_of_another_debtor_raises_404(
        self, db_session, make_user_session_factory
    ):
        """Aunque el `payment_id` sea propio, revocar una fuente cuyo `debtor_id` no
        coincide con el deudor resuelto debe fallar -- no basta con "conoce un
        payment_id válido", la fuente en sí debe ser del mismo deudor."""
        org = await add_organization(db_session)
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        owner_doc = "777888999"
        owner = build_debtor(org.id, document_number_plain=owner_doc)
        db_session.add(owner)
        await db_session.flush()
        credit = build_credit(portfolio.id, owner.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        own_payment = await _add_payment(db_session, credit.id)

        other_debtor = build_debtor(org.id)
        db_session.add(other_debtor)
        await db_session.flush()

        foreign_source = DebtorPaymentSourceModel(
            debtor_id=other_debtor.id,
            provider=ReceivablesGatewayProvider.WOMPI,
            type=PaymentSourceType.CARD,
            provider_source_id="src_foreign",
            status=PaymentSourceStatus.AVAILABLE,
        )
        db_session.add(foreign_source)
        await db_session.flush()

        service = PaymentSourceService(
            make_ownership_resolver(db_session),
            DebtorPaymentSourceRepository(db_session),
            AsyncMock(),
        )
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(owner_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.revoke(session, own_payment.id, foreign_source.id)
        assert exc_info.value.status_code == 404
