"""Parser del CSV/XLSX de carga masiva de portafolio (deudores + créditos)."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

import polars as pl

from app_platform.countries.enums.country_enums import (
    DOCUMENT_TYPE_BY_CODE,
    UserDocumentType,
)
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.credits.enums.credit_enums import CREDIT_TYPE_ALIASES, CreditTypes
from receivables.debtors.enums.address_enums import AddressType
from receivables.debtors.enums.debtor_enums import DebtorType
from receivables.portfolios.constants.portfolio_csv_constants import (
    DATE_FORMATS,
    NULL_STRINGS,
    REQUIRED_COLUMNS,
)
from receivables.portfolios.schemas.portfolio_file_schemas import (
    AddressRowData,
    ContactMethodRowData,
    CreditAdjustmentRowData,
    CreditRowData,
    DebtorRowData,
    PaymentRowData,
    PortfolioFileData,
    PortfolioRowData,
    UVRQuoteRowData,
)


class PortfolioFileParser:
    @staticmethod
    def _as_utf8(file_bytes: bytes) -> bytes:
        """
        Los CSV exportados desde Excel en Latinoamerica suelen venir en
        Windows-1252/Latin-1 (tildes y enie rompen UTF-8 estricto). polars no
        detecta encoding automaticamente, asi que se prueba UTF-8 primero y se
        cae a cp1252 (superset de latin-1) para no perder los caracteres.
        """
        try:
            file_bytes.decode("utf-8")
            return file_bytes
        except UnicodeDecodeError:
            return file_bytes.decode("cp1252", errors="replace").encode("utf-8")

    def parse(self, file_bytes: bytes, filename: str = "") -> PortfolioFileData:
        if not file_bytes:
            raise ValueError("El archivo está vacío")

        is_xlsx = filename.lower().endswith(".xlsx") or file_bytes[:4] == b"PK\x03\x04"
        if is_xlsx:
            df = pl.read_excel(BytesIO(file_bytes))
            # pylint infiere mal el retorno de pl.read_excel (stubs con
            # @overload de polars) y marca esto como código inalcanzable; sí
            # se ejecuta.
            df = df.select(  # pylint: disable=unreachable
                [pl.col(c).cast(pl.String, strict=False) for c in df.columns]
            )
        else:
            df = pl.read_csv(
                BytesIO(self._as_utf8(file_bytes)),
                infer_schema_length=0,  # all columns as strings to avoid type coercion
                ignore_errors=True,
                truncate_ragged_lines=True,
            )
        self._validate_columns(set(df.columns))

        rows: list[PortfolioRowData] = []
        total_skipped = 0

        for raw in df.to_dicts():
            row = self._build_row(raw)
            if row is None:
                total_skipped += 1
                continue
            rows.append(row)

        return PortfolioFileData(rows=rows, total_skipped=total_skipped)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_columns(self, columns: set[str]) -> None:
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(
                "El archivo no tiene las columnas requeridas: "
                f"{', '.join(sorted(missing))}"
            )

    # ------------------------------------------------------------------
    # Row builder — returns None to signal skip
    # ------------------------------------------------------------------

    def _build_row(self, raw: dict[str, Any]) -> PortfolioRowData | None:
        document_number = self._normalize_str(raw.get("Numero de documento"))
        credit_number = self._normalize_str(raw.get("Numero de credito"))

        if not document_number or not credit_number:
            return None

        debtor = self._build_debtor(raw, document_number)
        codebtor = self._build_codebtor(raw)
        primary_address = self._build_address(raw, AddressType.PRIMARY)
        secondary_address = self._build_secondary_address(raw)
        debtor_contacts = self._build_contacts(raw, "Telefono", "Correo Electronico")
        codebtor_contacts = (
            self._build_contacts(
                raw, "Telefono codeudor", "Correo Electronico codeudor"
            )
            if codebtor
            else []
        )
        credit = self._build_credit(raw, credit_number)
        payment = self._build_payment(raw)
        uvr_quote = self._build_uvr_quote(raw)
        credit_adjustment = self._build_credit_adjustment(raw)

        return PortfolioRowData(
            debtor=debtor,
            codebtor=codebtor,
            primary_address=primary_address,
            secondary_address=secondary_address,
            debtor_contacts=debtor_contacts,
            codebtor_contacts=codebtor_contacts,
            credit=credit,
            payment=payment,
            uvr_quote=uvr_quote,
            credit_adjustment=credit_adjustment,
        )

    # ------------------------------------------------------------------
    # Entity builders
    # ------------------------------------------------------------------

    def _build_debtor(self, raw: dict[str, Any], document_number: str) -> DebtorRowData:
        return DebtorRowData(
            document_number=document_number,
            full_name=self._normalize_str(raw.get("Nombre del titular")) or "",
            document_type=self._map_document_type(raw.get("Tipo documento")),
            debtor_type=DebtorType.DEBTOR,
        )

    def _build_codebtor(self, raw: dict[str, Any]) -> DebtorRowData | None:
        name = self._normalize_str(raw.get("Nombre del Codeudor"))
        if not name:
            return None
        doc_number = self._normalize_str(raw.get("Numero de documento codeudor"))
        if not doc_number:
            return None
        return DebtorRowData(
            document_number=doc_number,
            full_name=name,
            document_type=UserDocumentType.CC,
            debtor_type=DebtorType.CO_DEBTOR,
        )

    def _build_address(
        self, raw: dict[str, Any], address_type: AddressType
    ) -> AddressRowData:
        if address_type == AddressType.PRIMARY:
            return AddressRowData(
                address=self._normalize_str(raw.get("Direccion")) or "",
                city=self._normalize_str(raw.get("Ciudad")) or "",
                state=self._normalize_str(raw.get("Departamento")) or "",
                country="Colombia",
                address_type=AddressType.PRIMARY,
            )
        return AddressRowData(
            address=self._normalize_str(raw.get("Direccion 2")) or "",
            city=self._normalize_str(raw.get("Ciudad 2")) or "",
            state=self._normalize_str(raw.get("Departamento 2")) or "",
            country="Colombia",
            address_type=AddressType.SECONDARY,
        )

    def _build_secondary_address(self, raw: dict[str, Any]) -> AddressRowData | None:
        city2 = self._normalize_str(raw.get("Ciudad 2"))
        if not city2:
            return None
        return self._build_address(raw, AddressType.SECONDARY)

    def _build_contacts(
        self,
        raw: dict[str, Any],
        phone_col: str,
        email_col: str,
    ) -> list[ContactMethodRowData]:
        contacts: list[ContactMethodRowData] = []
        phone = self._normalize_phone(raw.get(phone_col))
        email = self._normalize_str(raw.get(email_col))
        if phone:
            contacts.append(ContactMethodRowData(ContactMethodType.PHONE, phone))
        if email:
            contacts.append(ContactMethodRowData(ContactMethodType.EMAIL, email))
        return contacts

    def _build_credit(self, raw: dict[str, Any], credit_number: str) -> CreditRowData:
        disbursed_date = self._parse_date(raw.get("Fecha Desembolso"))
        court_date = self._parse_date(raw.get("Fecha de corte"))
        return CreditRowData(
            credit_number=credit_number,
            credit_date=disbursed_date,
            disbursed_date=disbursed_date,
            credit_type=self._map_credit_type(raw.get("Tipo de producto")),
            agreed_interest_rate=self._to_decimal(raw.get("Tasa de interes pactada")),
            charged_effective_annual_rate=self._to_decimal_or_none(
                raw.get("Tasa de interes cobrada")
            ),
            balance_disbursed=self._to_decimal(raw.get("Saldo Desembolso")),
            court_date=court_date,
            initial_term=self._to_int(raw.get("plazo inicial")),
            total_credit_balance=self._to_decimal(raw.get("saldo total del credito")),
            overdue_principal_balance=self._to_decimal(
                raw.get("Saldo Capital en mora")
            ),
            current_interest=self._to_decimal(raw.get("Intereses Corrientes")),
            overdue_interest=self._to_decimal(raw.get("Intereses Mora")),
            other_concepts=self._to_decimal(raw.get("Otros Conceptos")),
            overdue_installments=self._to_int(raw.get("Cuotas en mora")),
            days_overdue_at_cutoff=self._to_int(raw.get("Dias en mora al corte")),
            amortization_system=self._normalize_str(raw.get("Sistema de amortizacion")),
            pending_installments=self._to_int(raw.get("numero de cuotas pendientes")),
            insurance_total=self._to_decimal(raw.get("Seguros")),
            commission_accum=self._to_decimal(raw.get("Comision")),
            platform_fee_accum=self._to_decimal(raw.get("Plataforma")),
            vat_accum=self._to_decimal(raw.get("IVA")),
            subproduct=self._normalize_str(raw.get("SUBPRODUCTO")),
            uvr_last_quote=self._to_decimal_or_none(raw.get("Cotizacion de UVR")),
            condonations_accum=self._to_decimal(
                raw.get("Condonaciones y/o descuentos")
            ),
        )

    def _build_payment(self, raw: dict[str, Any]) -> PaymentRowData | None:
        payment_date = self._parse_date(raw.get("Fecha del pago"))
        if not payment_date:
            return None
        limit_date = self._parse_date(raw.get("Fecha limite de pago")) or payment_date
        return PaymentRowData(
            payment_date=payment_date,
            limit_pay_date=limit_date,
            payment_amount=self._to_decimal(raw.get("total")),
            installment_number=self._to_int_or_none(
                raw.get("Numero de la cuota que se cancela")
            ),
            principal_payment=self._to_decimal(raw.get("abono a capital")),
            current_interest_amount=self._to_decimal(raw.get("interes corriente")),
            overdue_interest_amount=self._to_decimal(raw.get("interes mora")),
            life_insurance_charge=self._to_decimal(raw.get("Seguro de vida")),
            vehicle_insurance_charge=self._to_decimal(raw.get("seguro de vehiculo")),
            other_charges=self._to_decimal(raw.get("otros cargos")),
            vat=self._to_decimal(raw.get("IVA")),
            commission_amount=self._to_decimal(raw.get("Comision")),
            platform_fee=self._to_decimal(raw.get("Plataforma")),
        )

    def _build_uvr_quote(self, raw: dict[str, Any]) -> UVRQuoteRowData | None:
        value = self._to_decimal_or_none(raw.get("Cotizacion de UVR"))
        if value is None:
            return None
        quote_date = self._parse_date(raw.get("Fecha de corte"))
        if not quote_date:
            return None
        return UVRQuoteRowData(quote_value=value, quote_date=quote_date)

    def _build_credit_adjustment(
        self, raw: dict[str, Any]
    ) -> CreditAdjustmentRowData | None:
        amount = self._to_decimal_or_none(raw.get("Condonaciones y/o descuentos"))
        if amount is None:
            return None
        applied_date = self._parse_date(raw.get("Fecha de corte")) or datetime.now()
        return CreditAdjustmentRowData(
            adjustment_amount=amount,
            applied_date=applied_date,
        )

    # ------------------------------------------------------------------
    # Mappers
    # ------------------------------------------------------------------

    def _map_document_type(self, value: Any) -> UserDocumentType:
        raw = self._normalize_str(value)
        if raw:
            return DOCUMENT_TYPE_BY_CODE.get(raw.upper(), UserDocumentType.CC)
        return UserDocumentType.CC

    def _map_credit_type(self, value: Any) -> CreditTypes:
        raw = self._normalize_str(value)
        if raw:
            return CREDIT_TYPE_ALIASES.get(raw.upper(), CreditTypes.OTHER_SERVICE)
        return CreditTypes.OTHER_SERVICE

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    def _normalize_str(self, value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        if s.lower() in NULL_STRINGS:
            return None
        return s

    def _normalize_phone(self, value: Any) -> str | None:
        # Kept as string intentionally to avoid int coercion issues with asyncpg
        return self._normalize_str(value)

    def _to_decimal(self, value: Any, default: Decimal = Decimal("0")) -> Decimal:
        result = self._to_decimal_or_none(value)
        return result if result is not None else default

    def _to_decimal_or_none(self, value: Any) -> Decimal | None:
        s = self._normalize_str(value)
        if s is None:
            return None
        try:
            return Decimal(s.replace(",", ""))
        except InvalidOperation:
            return None

    def _to_int(self, value: Any, default: int = 0) -> int:
        result = self._to_int_or_none(value)
        return result if result is not None else default

    def _to_int_or_none(self, value: Any) -> int | None:
        s = self._normalize_str(value)
        if s is None:
            return None
        try:
            return int(Decimal(s.replace(",", "")))
        except InvalidOperation, ValueError:
            return None

    def _parse_date(self, value: Any) -> datetime | None:
        s = self._normalize_str(value)
        if s is None:
            return None
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None
