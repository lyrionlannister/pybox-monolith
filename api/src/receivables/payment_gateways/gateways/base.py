"""Protocol común de las pasarelas de cobro de receivables (Wompi, Bold, ...)."""

from dataclasses import dataclass
from typing import Any, Protocol, Union


@dataclass(frozen=True)
class AcceptanceTokens:
    """Tokens firmados por la pasarela con vigencia corta (ver skill `wompi-gateway`,
    Paso 3) — se piden antes de CADA cobro, nunca se cachean a largo plazo. El
    `permalink` de cada uno se le debe mostrar al deudor para que confirme que los leyó
    antes de pagar (requisito legal, Ley 1581 Habeas Data, no solo de UI)."""

    acceptance_token: str
    acceptance_permalink: str
    personal_data_token: str
    personal_data_permalink: str


@dataclass(frozen=True)
class CardPaymentMethod:
    """Datos crudos de la tarjeta -- `WompiGateway.create_transaction` la tokeniza
    server-to-server (mismo mecanismo ya usado por `PaymentSourceService`, con la
    `public_key` de la organización ya descifrada en el backend) antes de cobrar.
    Ningún frontend necesita la `public_key` ni el widget de Wompi para esto."""

    number: str
    cvc: str
    exp_month: str
    exp_year: str
    card_holder: str
    installments: int = 1


@dataclass(frozen=True)
class PsePaymentMethod:
    """PSE no tiene fuente de pago reutilizable en Wompi — solo aplica a un cobro
    `CHECKOUT` puntual, nunca a `AUTOMATIC_3RI`. Los 4 campos finales son ignorados por
    Wompi (ya pide documento/identidad dentro del propio método) pero obligatorios
    para PayU/ePayco, que exigen `buyer`/`payer` completos -- ver `PayUGateway`/
    `EpaycoGateway`."""

    user_type: int  # 0 = persona natural, 1 = persona juridica
    user_legal_id_type: str
    user_legal_id: str
    financial_institution_code: str
    payment_description: str
    full_name: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None


@dataclass(frozen=True)
class NequiPaymentMethod:
    """Los campos opcionales son ignorados por Wompi (solo pide `phone_number`) pero
    obligatorios para PayU, que exige `buyer`/`payer` completos -- ver `PayUGateway`."""

    phone_number: str
    full_name: str | None = None
    user_legal_id: str | None = None
    user_legal_id_type: str | None = None
    address: str | None = None
    city: str | None = None
    payment_description: str | None = None


@dataclass(frozen=True)
class BancolombiaTransferPaymentMethod:
    """Tampoco tiene fuente de pago reutilizable en Wompi — mismo alcance que PSE, solo
    `CHECKOUT`. Los campos opcionales son ignorados por Wompi/Bold pero obligatorios
    para PayU -- ver `PayUGateway`."""

    payment_description: str
    full_name: str | None = None
    phone: str | None = None
    user_legal_id: str | None = None
    user_legal_id_type: str | None = None
    address: str | None = None
    city: str | None = None


@dataclass(frozen=True)
class DaviplataPaymentMethod:
    """Único método de ePayco en este Protocol (Wompi/Bold/PayU no tienen Daviplata) --
    ver `EpaycoGateway.confirm_daviplata_otp`."""

    user_legal_id_type: str
    user_legal_id: str
    full_name: str
    address: str
    city: str
    phone: str | None = None


PaymentMethodInput = Union[
    CardPaymentMethod,
    PsePaymentMethod,
    NequiPaymentMethod,
    BancolombiaTransferPaymentMethod,
    DaviplataPaymentMethod,
]


@dataclass(frozen=True)
class DeviceInfo:
    """Antifraude exigido por PayU (`deviceSessionId`/`ipAddress`/`cookie`/
    `userAgent`, ver `PayUGateway._submit_transaction`) -- ePayco solo usa
    `ip_address` (ver `EpaycoGateway.create_transaction`). Wompi/Bold no lo piden."""

    device_session_id: str
    cookie: str
    user_agent: str
    ip_address: str


@dataclass(frozen=True)
class BrowserInfo:
    """Fingerprint del navegador exigido por Wompi para 3D Secure v2 (challenge_v2) en
    transacciones CARD -- ver skill `wompi-gateway`, Paso 6. Nombres en snake_case
    porque viajan tal cual dentro de `customer_data.browser_info` del body de
    `POST /transactions`."""

    browser_color_depth: str
    browser_screen_height: str
    browser_screen_width: str
    browser_language: str
    browser_user_agent: str
    browser_tz: str


@dataclass(frozen=True)
class ThreeDsChallenge:
    """Reto 3DS pendiente de resolver (ver `WompiGateway._to_transaction`). El HTML del
    iframe ya llega decodificado (la API de Wompi lo entrega escapado)."""

    current_step: str
    current_step_status: str
    challenge_html: str


@dataclass(frozen=True)
class RedirectAction:
    """Algunas pasarelas (Bold: PSE, Botón Bancolombia, 3DS de tarjeta) no resuelven el
    cobro en la misma llamada -- el deudor debe salir de la app, confirmar en el banco o
    en el challenge 3DS, y volver por `callback_url`. Wompi nunca llena este campo
    (su reto 3DS se resuelve con `ThreeDsChallenge`, embebido, sin salir de la app)."""

    redirect_url: str
    redirect_method: str


@dataclass(frozen=True)
class OtpChallenge:
    """Daviplata (ePayco) no se resuelve por redirección ni por notificación push
    esperada en silencio -- el deudor recibe un OTP en su app y hay que volver a
    pedírselo y confirmarlo con `EpaycoGateway.confirm_daviplata_otp`."""

    transaction_id: str
    id_session_token: str


@dataclass(frozen=True)
class GatewayTransaction:
    """Transacción ya normalizada al vocabulario propio (`raw` conserva la respuesta
    completa del proveedor para auditoría/debug). Antes `WompiTransaction` -- se
    generalizó al agregar Bold como segundo adaptador real."""

    id: str
    status: str
    amount_in_cents: int
    currency: str
    reference: str
    payment_method_type: str
    raw: dict[str, Any]
    three_ds_challenge: ThreeDsChallenge | None = None
    redirect_action: RedirectAction | None = None
    otp_challenge: OtpChallenge | None = None


@dataclass(frozen=True)
class GatewayPaymentSource:
    """Antes `WompiPaymentSource` -- generalizado al agregar Bold (que nunca la
    produce, ver `ReceivablesPaymentGateway.supports_saved_payment_sources`)."""

    id: str
    status: str
    type: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class GatewayFinancialInstitution:
    """Banco disponible para pagar por PSE. Antes `WompiFinancialInstitution` --
    generalizado porque Bold también expone un listado de bancos PSE propio
    (`GET /v1/payment/pse/banks`)."""

    financial_institution_code: str
    financial_institution_name: str


class ReceivablesPaymentGateway(Protocol):
    """Protocolo propio de `receivables` (NO el `PaymentGateway` de `billing/gateways/`
    — ver discusión de arquitectura: mismo patrón, interfaces deliberadamente separadas
    porque resuelven credenciales por clave distinta y tienen obligaciones de
    cumplimiento distintas). Una instancia ya trae las credenciales de UNA organización
    resueltas (ver `resolver.py`).

    No todas las pasarelas ofrecen las mismas capacidades (Bold no tiene fuente de
    pago reutilizable ni cobro automático 3RI, a diferencia de Wompi) -- los métodos
    `supports_*` son la forma explícita de declarar esa diferencia. Un adaptador sin
    una capacidad igual debe implementar los métodos que dependen de ella (no puede
    omitirlos, el Protocol los exige), pero levanta `NotImplementedError` ahí: el
    llamador SIEMPRE debe chequear el `supports_*` correspondiente antes de
    invocarlos."""

    name: str

    async def get_acceptance_tokens(self) -> AcceptanceTokens:
        """Tokens de aceptación de términos/habeas data (ver `AcceptanceTokens`). Una
        pasarela sin este concepto (Bold: la aceptación queda dentro de su propia
        página de cobro alojada) devuelve tokens vacíos en vez de levantar -- se piden
        siempre, para cualquier pasarela, antes de cada cobro (ver
        `PaymentCheckoutService.create_transaction`)."""
        ...

    async def create_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: PaymentMethodInput | None,
        acceptance_token: str,
        accept_personal_auth: str,
        customer_email: str,
        payment_source_id: str | None = None,
        browser_info: BrowserInfo | None = None,
        device_info: DeviceInfo | None = None,
    ) -> GatewayTransaction:
        """`payment_method` es obligatorio salvo cuando se cobra contra una fuente de
        pago guardada (`payment_source_id` presente, ver Paso 5.3 de la skill de
        Wompi) — en ese caso Wompi ignora `payment_method` y este se pasa en `None`.
        `payment_source_id` no aplica a pasarelas sin `supports_saved_payment_sources`.
        `browser_info` se exige para CARD (3DS) y no aplica a los demás métodos.
        `device_info` lo exige PayU (antifraude) y ePayco (solo la IP); Wompi/Bold lo
        ignoran."""
        ...

    async def tokenize_card(
        self, number: str, cvc: str, exp_month: str, exp_year: str, card_holder: str
    ) -> str:
        """Solo tiene sentido cuando `supports_saved_payment_sources()` es `True` (el
        dato tokenizado se usa para `create_payment_source`, no para
        `create_transaction` -- Wompi tokeniza la tarjeta igual en un cobro puntual,
        pero eso lo hace el propio adaptador internamente, no pasa por este
        método)."""
        ...

    async def tokenize_nequi(self, phone_number: str) -> str:
        """Mismo alcance que `tokenize_card`: solo para guardar una fuente
        reutilizable."""
        ...

    async def create_payment_source(
        self,
        type: str,
        token: str,
        customer_email: str,
        acceptance_token: str,
        accept_personal_auth: str,
    ) -> GatewayPaymentSource:
        """Solo disponible cuando `supports_saved_payment_sources()` es `True`."""
        ...

    async def list_pse_financial_institutions(
        self,
    ) -> list[GatewayFinancialInstitution]: ...

    async def get_transaction(self, transaction_id: str) -> GatewayTransaction: ...

    async def confirm_daviplata_otp(
        self, transaction_id: str, id_session_token: str, otp: str
    ) -> GatewayTransaction:
        """Solo ePayco tiene Daviplata (ver `OtpChallenge`); las demás pasarelas
        levantan `NotImplementedError`."""
        ...

    def verify_webhook_signature(self, event_body: dict[str, Any]) -> bool: ...

    def supports_automatic_charge(self) -> bool:
        """Si esta organización tiene la activación de fraude de Wompi para cobro 3RI
        (skill `wompi-gateway`, Paso 6) — condición necesaria pero no suficiente: la
        fuente de pago también debe cumplir `three_ds_enrolled` y ser Mastercard. Bold
        no tiene este concepto en su API: siempre `False`."""
        ...

    def supports_saved_payment_sources(self) -> bool:
        """Si esta pasarela puede guardar un medio de pago reutilizable
        (`tokenize_card`/`tokenize_nequi`/`create_payment_source`). Es condición
        necesaria -- no suficiente -- para `supports_automatic_charge`: toda pasarela
        con cobro automático necesariamente soporta fuentes guardadas, pero no al
        revés (Wompi soporta fuentes guardadas incluso para organizaciones sin la
        activación de fraude de 3RI)."""
        ...
