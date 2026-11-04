"""`PaymentCheckoutService.resolve_by_reference`: Bold/PayU reenvían NUESTRA
`provider_reference` en la URL de retorno, pero ePayco solo conoce su propio
`ref_payco` (`provider_transaction_id`) -- este método debe resolver cualquiera de
los dos, sin que el llamador sepa de antemano cuál aplica."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
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
    add_organization,
    build_credit,
    build_debtor,
    build_portfolio,
)


def _ownership_resolver(db_session) -> PaymentOwnershipResolver:
    return PaymentOwnershipResolver(
        DebtorRepository(db_session),
        CreditRepository(db_session),
        PaymentRepository(db_session),
        PortfolioRepository(db_session),
    )


async def _setup_attempt(
    db_session, *, provider_reference: str, provider_transaction_id: str
):
    org = await add_organization(db_session)
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    debtor = build_debtor(org.id)
    db_session.add(debtor)
    await db_session.flush()
    credit = build_credit(portfolio.id, debtor.id, is_active=True)
    db_session.add(credit)
    await db_session.flush()
    payment = PaymentModel(
        limit_pay_date=datetime.now(timezone.utc),
        payment_amount=Decimal("15000.00"),
        principal_payment=Decimal("12000.00"),
        total_interest_amount=Decimal("3000.00"),
        status=PaymentStatus.PENDING,
        credit_id=credit.id,
    )
    db_session.add(payment)
    await db_session.flush()
    attempt = CreditPaymentAttemptModel(
        payment_id=payment.id,
        attempt_number=1,
        provider=ReceivablesGatewayProvider.EPAYCO,
        charge_mode=ChargeMode.CHECKOUT,
        provider_reference=provider_reference,
        provider_transaction_id=provider_transaction_id,
        expected_amount_cents=1_500_000,
        status=ReceivablesPaymentAttemptStatus.PENDING,
    )
    db_session.add(attempt)
    await db_session.flush()
    return debtor, attempt


def _self_session(make_user_session_factory, document_number_hash: str):
    from identity.users.enums.user_enums import (
        IdentityVerificationStatus,
        UserRole,
        UserScope,
    )

    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
        identity_verification_status=IdentityVerificationStatus.APPROVED,
    )


class TestResolveByReference:
    async def test_resolves_by_provider_reference(
        self, db_session, make_user_session_factory
    ):
        debtor, attempt = await _setup_attempt(
            db_session, provider_reference="PAG-1", provider_transaction_id="999999"
        )
        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            None,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        resolved = await service.resolve_by_reference(session, "PAG-1")
        assert resolved.id == attempt.id

    async def test_falls_back_to_provider_transaction_id(
        self, db_session, make_user_session_factory
    ):
        """ePayco: la URL de retorno solo trae `ref_payco`, no nuestra referencia."""
        debtor, attempt = await _setup_attempt(
            db_session, provider_reference="PAG-2", provider_transaction_id="26292245"
        )
        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            None,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        resolved = await service.resolve_by_reference(session, "26292245")
        assert resolved.id == attempt.id

    async def test_unknown_reference_raises_404(
        self, db_session, make_user_session_factory
    ):
        debtor, _attempt = await _setup_attempt(
            db_session, provider_reference="PAG-3", provider_transaction_id="123"
        )
        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            None,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.resolve_by_reference(session, "does-not-exist")
        assert exc_info.value.status_code == 404
