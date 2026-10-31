"""Estructuras de una fila del archivo de portafolio (CSV/XLSX) ya normalizada.

Son el contrato entre `utils/portfolio_file_parser.py`, que las produce, y
`services/portfolio_csv_service.py`, que las persiste. Van como dataclasses y no
como `BaseSchema` porque nunca cruzan la frontera HTTP: no necesitan alias camelCase
ni validación de Pydantic, igual que `CsvProcessResult` en `portfolio_csv_schemas`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app_platform.countries.enums.country_enums import UserDocumentType
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.credits.enums.credit_enums import CreditTypes
from receivables.debtors.enums.address_enums import AddressType
from receivables.debtors.enums.debtor_enums import DebtorType


@dataclass(frozen=True)
class DebtorRowData:
    document_number: str
    full_name: str
    document_type: UserDocumentType
    debtor_type: DebtorType


@dataclass(frozen=True)
class AddressRowData:
    address: str
    city: str
    state: str
    country: str
    address_type: AddressType


@dataclass(frozen=True)
class ContactMethodRowData:
    contact_type: ContactMethodType
    contact_value: str


@dataclass(frozen=True)
class CreditRowData:
    credit_number: str
    credit_date: datetime | None
    disbursed_date: datetime | None
    credit_type: CreditTypes
    agreed_interest_rate: Decimal
    charged_effective_annual_rate: Decimal | None
    balance_disbursed: Decimal
    court_date: datetime | None
    initial_term: int
    total_credit_balance: Decimal
    overdue_principal_balance: Decimal
    current_interest: Decimal
    overdue_interest: Decimal
    other_concepts: Decimal
    overdue_installments: int
    days_overdue_at_cutoff: int
    amortization_system: str | None
    pending_installments: int
    insurance_total: Decimal
    commission_accum: Decimal
    platform_fee_accum: Decimal
    vat_accum: Decimal
    subproduct: str | None
    uvr_last_quote: Decimal | None
    condonations_accum: Decimal


@dataclass(frozen=True)
class PaymentRowData:
    payment_date: datetime
    limit_pay_date: datetime
    payment_amount: Decimal
    installment_number: int | None
    principal_payment: Decimal
    current_interest_amount: Decimal
    overdue_interest_amount: Decimal
    life_insurance_charge: Decimal
    vehicle_insurance_charge: Decimal
    other_charges: Decimal
    vat: Decimal
    commission_amount: Decimal
    platform_fee: Decimal


@dataclass(frozen=True)
class UVRQuoteRowData:
    quote_value: Decimal
    quote_date: datetime


@dataclass(frozen=True)
class CreditAdjustmentRowData:
    adjustment_amount: Decimal
    applied_date: datetime
    adjustment_type: str = "CONDONACION"


@dataclass(frozen=True)
class PortfolioRowData:
    debtor: DebtorRowData
    codebtor: DebtorRowData | None
    primary_address: AddressRowData
    secondary_address: AddressRowData | None
    debtor_contacts: list[ContactMethodRowData]
    codebtor_contacts: list[ContactMethodRowData]
    credit: CreditRowData
    payment: PaymentRowData | None
    uvr_quote: UVRQuoteRowData | None
    credit_adjustment: CreditAdjustmentRowData | None


@dataclass(frozen=True)
class PortfolioFileData:
    rows: list[PortfolioRowData]
    total_skipped: int


# ──────────────────────────────────────────────────────────────────────────
# Plan de cuotas — carga independiente del importador de portafolio de arriba.
# No reutiliza PaymentRowData/PortfolioRowData a propósito: son estructuras del
# flujo existente y esta es una carga separada (ver
# PortfolioCsvService.upload_installments_csv).
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InstallmentRowData:
    credit_number: str
    installment_number: int | None
    is_full_settlement: bool
    limit_pay_date: datetime
    payment_date: datetime | None  # None = cuota pendiente, aún no pagada
    payment_amount: Decimal
    principal_payment: Decimal
    current_interest_amount: Decimal
    overdue_interest_amount: Decimal
    life_insurance_charge: Decimal
    vehicle_insurance_charge: Decimal
    other_charges: Decimal
    vat: Decimal
    commission_amount: Decimal
    platform_fee: Decimal


@dataclass(frozen=True)
class InstallmentFileData:
    rows: list[InstallmentRowData]
    total_skipped: int
