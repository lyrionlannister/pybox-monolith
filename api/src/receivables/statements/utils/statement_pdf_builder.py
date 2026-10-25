"""Construcción del PDF de extracto de cuenta con reportlab."""

import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass(frozen=True)
class StatementPaymentLine:
    installment_number: int | None
    limit_pay_date: datetime
    payment_date: datetime | None
    payment_amount: Decimal
    principal_payment: Decimal
    total_interest_amount: Decimal
    status_label: str


@dataclass(frozen=True)
class StatementCreditLine:
    credit_number: str
    credit_type_label: str
    disbursed_date: datetime
    total_credit_balance: Decimal
    overdue_principal_balance: Decimal
    days_overdue_at_cutoff: int
    pending_installments: int
    overdue_installments: int
    payments: list[StatementPaymentLine]


def _money(value: Decimal, currency_code: str) -> str:
    return f"{currency_code} {value:,.2f}"


def _date(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


def build_statement_pdf(
    *,
    organization_name: str,
    debtor_name: str,
    debtor_document: str,
    currency_code: str,
    cutoff_date: datetime,
    credits: list[StatementCreditLine],
) -> bytes:
    """Arma el PDF del extracto: un bloque de resumen + historial de pagos por cada
    crédito de `credits`. Con un solo elemento es el extracto de un crédito puntual;
    con varios, el consolidado de todos los créditos activos del deudor."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        title=f"Extracto de cuenta - {debtor_name}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "StatementTitle", parent=styles["Title"], fontSize=16, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "StatementSubtitle", parent=styles["Normal"], fontSize=10, textColor=colors.grey
    )
    section_style = ParagraphStyle(
        "StatementSection",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=14,
        spaceAfter=6,
    )

    story = [
        Paragraph("Extracto de cuenta", title_style),
        Paragraph(organization_name, subtitle_style),
        Spacer(1, 10),
        Paragraph(f"<b>Titular:</b> {debtor_name}", styles["Normal"]),
        Paragraph(f"<b>Documento:</b> {debtor_document}", styles["Normal"]),
        Paragraph(f"<b>Fecha de corte:</b> {_date(cutoff_date)}", styles["Normal"]),
        Spacer(1, 6),
    ]

    for line in credits:
        story.append(
            Paragraph(
                f"Crédito {line.credit_number} — {line.credit_type_label}",
                section_style,
            )
        )

        summary_data = [
            ["Concepto", "Valor"],
            ["Fecha de desembolso", _date(line.disbursed_date)],
            ["Saldo total", _money(line.total_credit_balance, currency_code)],
            [
                "Saldo en mora (capital)",
                _money(line.overdue_principal_balance, currency_code),
            ],
            ["Días de mora al corte", str(line.days_overdue_at_cutoff)],
            ["Cuotas pendientes", str(line.pending_installments)],
            ["Cuotas en mora", str(line.overdue_installments)],
        ]
        summary_table = Table(summary_data, colWidths=[7 * cm, 8 * cm])
        summary_table.setStyle(_summary_table_style())
        story.append(summary_table)
        story.append(Spacer(1, 8))

        if line.payments:
            payments_data = [
                [
                    "Cuota",
                    "Fecha límite",
                    "Fecha de pago",
                    "Monto",
                    "Capital",
                    "Interés",
                    "Estado",
                ]
            ] + [
                [
                    (
                        str(p.installment_number)
                        if p.installment_number is not None
                        else "-"
                    ),
                    _date(p.limit_pay_date),
                    _date(p.payment_date),
                    _money(p.payment_amount, currency_code),
                    _money(p.principal_payment, currency_code),
                    _money(p.total_interest_amount, currency_code),
                    p.status_label,
                ]
                for p in line.payments
            ]
            payments_table = Table(payments_data, repeatRows=1)
            payments_table.setStyle(_payments_table_style())
            story.append(payments_table)

        story.append(Spacer(1, 16))

    doc.build(story)
    return buffer.getvalue()


def _summary_table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#f9fafb")],
            ),
        ]
    )


def _payments_table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (3, 1), (5, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#f9fafb")],
            ),
        ]
    )
