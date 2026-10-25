"""`PaymentCheckoutService` con Daviplata (ePayco): el cobro queda `PENDING` con un
`OtpChallenge` y se cierra con `confirm_daviplata_otp`. El gateway se mockea; intento
y pago son reales contra la DB de test -- mismo criterio que
`test_payment_checkout_card_pse_polling.py`."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    DaviplataPaymentMethod,
    DeviceInfo,
    GatewayTransaction,
    OtpChallenge,
)
from receivables.payment_gateways.repository.payment_attempt_repository import (
    CreditPaymentAttemptRepository,
)
from receivables.payment_gateways.services.payment_checkout_service import (
    PaymentCheckoutService,
)
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.repository.payment_repository import PaymentRepository
from tests.receivables.conftest import add_organization, build_debtor
from tests.receivables.test_payment_checkout_card_pse_polling import (
    _ownership_resolver,
    _self_session,
    _setup_payment,
)

_DAVIPLATA = DaviplataPaymentMethod(
    user_legal_id_type="CC",
    user_legal_id="123456789",
    full_name="Ana Pérez",
    address="Calle 1 # 2-3",
    city="Bogotá",
)
_DEVICE = DeviceInfo(
    device_session_id="dev-1", cookie="dev-1", user_agent="pytest", ip_address="1.2.3.4"
)


def _epayco_gateway() -> AsyncMock:
    gateway = AsyncMock()
    gateway.name = "EPAYCO"
    gateway.get_acceptance_tokens.return_value = AcceptanceTokens(
        acceptance_token="",
        acceptance_permalink="",
        personal_data_token="",
        personal_data_permalink="",
    )
    gateway.create_transaction.return_value = GatewayTransaction(
        id="30612544",
        status="PENDING",
        amount_in_cents=1_500_000,
        currency="COP",
        reference="30612544",
        payment_method_type="DAVIPLATA",
        raw={
            "data": {"transaction": {"refPayco": 30612544, "idSessionToken": "tok-1"}}
        },
        otp_challenge=OtpChallenge(transaction_id="30612544", id_session_token="tok-1"),
    )
    return gateway


def _service(db_session, gateway) -> PaymentCheckoutService:
    gateway_resolver = AsyncMock()
    gateway_resolver.get_active_for_organization.return_value = gateway
    return PaymentCheckoutService(
        _ownership_resolver(db_session),
        CreditPaymentAttemptRepository(db_session),
        gateway_resolver,
        PaymentRepository(db_session),
    )


class TestDaviplataOtp:
    async def test_create_surfaces_otp_and_forwards_device_info(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        gateway = _epayco_gateway()
        service = _service(db_session, gateway)
        session = _self_session(make_user_session_factory, debtor.document_number_hash)

        attempt, _challenge, _redirect, otp = await service.create_transaction(
            session, payment.id, _DAVIPLATA, "debtor@example.com", device_info=_DEVICE
        )

        assert attempt.status == ReceivablesPaymentAttemptStatus.PENDING
        assert otp is not None
        assert gateway.create_transaction.await_args.kwargs["device_info"] is _DEVICE

    async def test_confirm_otp_approves_attempt_and_payment(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        gateway = _epayco_gateway()
        gateway.confirm_daviplata_otp.return_value = GatewayTransaction(
            id="30612544",
            status="APPROVED",
            amount_in_cents=1_500_000,
            currency="COP",
            reference="30612544",
            payment_method_type="DAVIPLATA",
            raw={"data": {"status": "Aceptada", "value": 15000}},
        )
        service = _service(db_session, gateway)
        session = _self_session(make_user_session_factory, debtor.document_number_hash)
        attempt, *_ = await service.create_transaction(
            session, payment.id, _DAVIPLATA, "debtor@example.com"
        )

        confirmed = await service.confirm_daviplata_otp(
            session, payment.id, attempt.id, "123456"
        )

        gateway.confirm_daviplata_otp.assert_awaited_once_with(
            "30612544", "tok-1", "123456"
        )
        assert confirmed.status == ReceivablesPaymentAttemptStatus.APPROVED
        refreshed = await PaymentRepository(db_session).get_by_id(payment.id)
        assert refreshed.status == PaymentStatus.PAID

    async def test_confirm_on_attempt_without_otp_raises_400(
        self, db_session, make_user_session_factory
    ):
        _org, debtor, payment = await _setup_payment(db_session)
        gateway = _epayco_gateway()
        gateway.create_transaction.return_value = GatewayTransaction(
            id="30612545",
            status="PENDING",
            amount_in_cents=1_500_000,
            currency="COP",
            reference="30612545",
            payment_method_type="PSE",
            raw={"data": {"ref_payco": 30612545}},
        )
        service = _service(db_session, gateway)
        session = _self_session(make_user_session_factory, debtor.document_number_hash)
        attempt, *_ = await service.create_transaction(
            session, payment.id, _DAVIPLATA, "debtor@example.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_daviplata_otp(
                session, payment.id, attempt.id, "123456"
            )
        assert exc_info.value.status_code == 400
        gateway.confirm_daviplata_otp.assert_not_awaited()

    async def test_confirm_on_others_payment_raises_404(
        self, db_session, make_user_session_factory
    ):
        from core.security.services.encrypt_service import encrypt_service

        _org, debtor, payment = await _setup_payment(db_session)
        gateway = _epayco_gateway()
        service = _service(db_session, gateway)
        owner = _self_session(make_user_session_factory, debtor.document_number_hash)
        attempt, *_ = await service.create_transaction(
            owner, payment.id, _DAVIPLATA, "debtor@example.com"
        )
        requester_doc = "999888777"
        db_session.add(
            build_debtor(
                (await add_organization(db_session)).id,
                document_number_plain=requester_doc,
            )
        )
        await db_session.flush()
        stranger = _self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.confirm_daviplata_otp(
                stranger, payment.id, attempt.id, "1234"
            )
        assert exc_info.value.status_code == 404
        gateway.confirm_daviplata_otp.assert_not_awaited()
