"""Doble cobro: `PaymentCheckoutService.create_transaction` no debe iniciar una
transacción nueva contra la pasarela (cargo real) si ya hay un intento PENDING o
APPROVED para la misma cuota -- doble clic, reintento de red o carrera entre el
checkout manual y el cron de 3RI no deben generar dos cargos."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.security.services.encrypt_service import encrypt_service
from identity.users.enums.user_enums import UserRole, UserScope
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import CardPaymentMethod
from receivables.payment_gateways.models.payment_attempt_model import (
    CreditPaymentAttemptModel,
)
from receivables.payment_gateways.repository.payment_attempt_repository import (
    CreditPaymentAttemptRepository,
)
from receivables.payment_gateways.services.payment_checkout_service import (
    PaymentCheckoutService,
)
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.payments.services.payment_ownership_resolver import (
    PaymentOwnershipResolver,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from tests.receivables.conftest import (
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)


def _self_session(make_user_session_factory, document_number_hash: str):
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
    )


def _make_ownership_resolver(db_session) -> PaymentOwnershipResolver:
    return PaymentOwnershipResolver(
        DebtorRepository(db_session),
        CreditRepository(db_session),
        PaymentRepository(db_session),
        PortfolioRepository(db_session),
    )


@pytest.fixture
async def own_payment(db_session, make_user_session_factory):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    owner_doc = "321654987"
    owner = build_debtor(org.id, document_number_plain=owner_doc)
    db_session.add(owner)
    await db_session.flush()
    credit = build_credit(portfolio.id, owner.id, is_active=True)
    db_session.add(credit)
    await db_session.flush()
    payment = PaymentModel(
        limit_pay_date=datetime.now(timezone.utc),
        payment_amount=100,
        principal_payment=80,
        total_interest_amount=20,
        status=PaymentStatus.PENDING,
        credit_id=credit.id,
    )
    db_session.add(payment)
    await db_session.flush()
    session = _self_session(
        make_user_session_factory, encrypt_service.hash_document(owner_doc)
    )
    return payment, session


class TestPaymentCheckoutDoubleCharge:
    @pytest.mark.parametrize(
        "status",
        [
            ReceivablesPaymentAttemptStatus.PENDING,
            ReceivablesPaymentAttemptStatus.APPROVED,
        ],
    )
    async def test_rejects_new_charge_with_attempt_in_flight(
        self, db_session, own_payment, status
    ):
        payment, session = own_payment
        db_session.add(
            CreditPaymentAttemptModel(
                payment_id=payment.id,
                attempt_number=1,
                provider=ReceivablesGatewayProvider.WOMPI,
                charge_mode=ChargeMode.CHECKOUT,
                status=status,
            )
        )
        await db_session.flush()

        gateway_resolver = AsyncMock()
        gateway = AsyncMock()
        gateway_resolver.get_active_for_organization.return_value = gateway
        service = PaymentCheckoutService(
            _make_ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            gateway_resolver,
            PaymentRepository(db_session),
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
                session, payment.id, card, "debtor@example.com"
            )

        assert exc_info.value.status_code == 409
        gateway.create_transaction.assert_not_awaited()
