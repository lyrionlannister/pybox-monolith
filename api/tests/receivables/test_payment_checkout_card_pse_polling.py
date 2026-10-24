"""`PaymentCheckoutService`: tarjeta con reto 3DS, listado de bancos PSE, y el polling
de `refresh_attempt_status` (usado por el frontend mientras el deudor resuelve el reto
3DS). El gateway se mockea (nunca pega HTTP real a Wompi); intento/pago son reales
contra la DB de test -- mismo criterio que `test_wompi_webhook_service.py`."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    BrowserInfo,
    CardPaymentMethod,
    ThreeDsChallenge,
    GatewayFinancialInstitution,
    GatewayTransaction,
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


async def _setup_payment(db_session):
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
    return org, debtor, payment


def _self_session(make_user_session_factory, document_number_hash: str):
    from identity.users.enums.user_enums import UserRole, UserScope

    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
    )


class TestCardThreeDsChallenge:
    async def test_card_payment_with_pending_challenge_is_surfaced(
        self, db_session, make_user_session_factory
    ):
        org, debtor, payment = await _setup_payment(db_session)
        gateway = AsyncMock()
        gateway.name = "WOMPI"
        gateway.get_acceptance_tokens.return_value = AcceptanceTokens(
            acceptance_token="acc_tok",
            acceptance_permalink="https://x/acc",
            personal_data_token="pd_tok",
            personal_data_permalink="https://x/pd",
        )
        gateway.create_transaction.return_value = GatewayTransaction(
            id="txn-card-1",
            status="PENDING",
            amount_in_cents=1_500_000,
            currency="COP",
            reference="PAG-ref",
            payment_method_type="CARD",
            raw={"id": "txn-card-1", "status": "PENDING"},
            three_ds_challenge=ThreeDsChallenge(
                current_step="CHALLENGE",
                current_step_status="PENDING",
                challenge_html="<iframe></iframe>",
            ),
        )
        gateway_resolver = AsyncMock()
        gateway_resolver.get_active_for_organization.return_value = gateway

        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            gateway_resolver,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        card = CardPaymentMethod(
            number="4242424242424242",
            cvc="123",
            exp_month="12",
            exp_year="29",
            card_holder="Test",
        )
        browser_info = BrowserInfo(
            browser_color_depth="24",
            browser_screen_height="1050",
            browser_screen_width="1680",
            browser_language="es-CO",
            browser_user_agent="pytest",
            browser_tz="300",
        )
        (
            attempt,
            challenge,
            redirect_action,
            otp_challenge,
        ) = await service.create_transaction(
            session, payment.id, card, "debtor@example.com", browser_info=browser_info
        )
        assert redirect_action is None
        assert otp_challenge is None

        assert attempt.status == ReceivablesPaymentAttemptStatus.PENDING
        assert attempt.charge_mode == ChargeMode.CHECKOUT
        assert challenge is not None
        assert challenge.current_step_status == "PENDING"
        assert challenge.challenge_html == "<iframe></iframe>"
        gateway.create_transaction.assert_awaited_once()
        assert (
            gateway.create_transaction.await_args.kwargs["browser_info"] is browser_info
        )


class TestListPseInstitutions:
    async def test_lists_institutions_for_own_payment(
        self, db_session, make_user_session_factory
    ):
        org, debtor, payment = await _setup_payment(db_session)
        gateway = AsyncMock()
        gateway.list_pse_financial_institutions.return_value = [
            GatewayFinancialInstitution(
                financial_institution_code="1", financial_institution_name="Banco Uno"
            ),
        ]
        gateway_resolver = AsyncMock()
        gateway_resolver.get_active_for_organization.return_value = gateway

        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            gateway_resolver,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        institutions = await service.list_pse_institutions(session, payment.id)
        assert [i.financial_institution_name for i in institutions] == ["Banco Uno"]

    async def test_listing_on_others_payment_raises_404(
        self, db_session, make_user_session_factory
    ):
        from core.security.services.encrypt_service import encrypt_service

        _org, _owner, payment = await _setup_payment(db_session)
        requester_doc = "999888777"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            AsyncMock(),
            PaymentRepository(db_session),
        )
        session = _self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.list_pse_institutions(session, payment.id)
        assert exc_info.value.status_code == 404


class TestRefreshAttemptStatus:
    async def _add_attempt(
        self, db_session, payment, **overrides
    ) -> CreditPaymentAttemptModel:
        defaults = dict(
            payment_id=payment.id,
            attempt_number=1,
            provider=ReceivablesGatewayProvider.WOMPI,
            charge_mode=ChargeMode.CHECKOUT,
            provider_reference="PAG-ref",
            provider_transaction_id="txn-1",
            expected_amount_cents=1_500_000,
            status=ReceivablesPaymentAttemptStatus.PENDING,
        )
        defaults.update(overrides)
        attempt = CreditPaymentAttemptModel(**defaults)
        db_session.add(attempt)
        await db_session.flush()
        return attempt

    async def test_pending_transitions_to_approved_and_marks_payment_paid(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        attempt = await self._add_attempt(db_session, payment)

        gateway = AsyncMock()
        gateway.get_transaction.return_value = GatewayTransaction(
            id="txn-1",
            status="APPROVED",
            amount_in_cents=1_500_000,
            currency="COP",
            reference="PAG-ref",
            payment_method_type="CARD",
            raw={"id": "txn-1", "status": "APPROVED"},
        )
        gateway_resolver = AsyncMock()
        gateway_resolver.get_active_for_organization.return_value = gateway

        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            gateway_resolver,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        result = await service.refresh_attempt_status(session, payment.id, attempt.id)
        assert result.status == ReceivablesPaymentAttemptStatus.APPROVED
        await db_session.refresh(payment)
        assert payment.status == PaymentStatus.PAID

    async def test_already_final_status_does_not_requery_gateway(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        attempt = await self._add_attempt(
            db_session, payment, status=ReceivablesPaymentAttemptStatus.APPROVED
        )

        gateway_resolver = AsyncMock()
        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            gateway_resolver,
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        result = await service.refresh_attempt_status(session, payment.id, attempt.id)
        assert result.status == ReceivablesPaymentAttemptStatus.APPROVED
        gateway_resolver.get_active_for_organization.assert_not_awaited()

    async def test_attempt_of_another_payment_raises_404(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        _org2, _debtor2, other_payment = await _setup_payment(db_session)
        foreign_attempt = await self._add_attempt(db_session, other_payment)

        service = PaymentCheckoutService(
            _ownership_resolver(db_session),
            CreditPaymentAttemptRepository(db_session),
            AsyncMock(),
            PaymentRepository(db_session),
        )
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.refresh_attempt_status(
                session, payment.id, foreign_attempt.id
            )
        assert exc_info.value.status_code == 404
