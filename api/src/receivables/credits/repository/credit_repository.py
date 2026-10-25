"""Acceso a datos de créditos, con las consultas agregadas de cartera."""

import uuid
from datetime import date, datetime, timezone
from typing import NamedTuple, Sequence

from sqlalchemy import case, cast, func, or_, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.types import Date as SADate

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.credits.models.credit_model import CreditModel
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.portfolios.models.portfolio_daily_counter_config_model import (
    PortfolioDailyCounterConfigModel,
)
from receivables.portfolios.models.portfolio_model import PortfolioModel


class PortfolioCreditStats(NamedTuple):
    creditos: int
    titulares: int
    codeudores: int
    clientes_unicos: int
    documentos_unicos: int
    total_mora: float


class CreditRepository(SoftDeleteRepositoryBase[CreditModel]):
    model_class = CreditModel

    async def get_by_ids(self, credit_ids: list[uuid.UUID]) -> list[CreditModel]:
        if not credit_ids:
            return []
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.id.in_(credit_ids),
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_portfolio_stats(
        self, portfolio_id: uuid.UUID
    ) -> PortfolioCreditStats:
        result = await self.session.execute(
            select(
                func.count(CreditModel.id).label("creditos"),
                func.count(func.distinct(CreditModel.debtor_id)).label("titulares"),
                func.count(func.distinct(CreditModel.codebtor_id)).label("codeudores"),
                func.coalesce(func.sum(CreditModel.overdue_principal_balance), 0).label(
                    "total_mora"
                ),
            ).where(
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        row = result.one()

        debtors_q = select(CreditModel.debtor_id.label("id")).where(
            CreditModel.portfolio_id == portfolio_id, CreditModel.deleted_at.is_(None)
        )
        codebtors_q = select(CreditModel.codebtor_id.label("id")).where(
            CreditModel.portfolio_id == portfolio_id,
            CreditModel.deleted_at.is_(None),
            CreditModel.codebtor_id.is_not(None),
        )
        all_ids = union(debtors_q, codebtors_q).subquery()
        clientes_unicos: int = (
            await self.session.scalar(select(func.count()).select_from(all_ids)) or 0
        )

        # Conteo de (tipo_documento, numero_documento) únicos entre titulares +
        # codeudores.
        documentos_unicos: int = await self._count_unique_documents(all_ids)

        return PortfolioCreditStats(
            creditos=row.creditos,
            titulares=row.titulares,
            codeudores=row.codeudores,
            clientes_unicos=clientes_unicos,
            documentos_unicos=documentos_unicos,
            total_mora=float(row.total_mora),
        )

    async def _count_unique_documents(self, debtor_ids_subq) -> int:
        """Cuenta combinaciones únicas (tipo_documento, numero_documento) de los
        deudores referenciados por ``debtor_ids_subq`` (subquery con columna
        ``id``)."""
        docs_subq = (
            select(DebtorModel.document_type, DebtorModel.document_number_hash)
            .where(DebtorModel.id.in_(select(debtor_ids_subq.c.id)))
            .distinct()
            .subquery()
        )
        return (
            await self.session.scalar(select(func.count()).select_from(docs_subq)) or 0
        )

    async def get_organization_stats(
        self, organization_id: uuid.UUID
    ) -> PortfolioCreditStats:
        """Igual que get_portfolio_stats pero agregado a nivel organizacion (todos
        sus portafolios)."""
        result = await self.session.execute(
            select(
                func.count(CreditModel.id).label("creditos"),
                func.count(func.distinct(CreditModel.debtor_id)).label("titulares"),
                func.count(func.distinct(CreditModel.codebtor_id)).label("codeudores"),
                func.coalesce(func.sum(CreditModel.overdue_principal_balance), 0).label(
                    "total_mora"
                ),
            )
            .join(PortfolioModel, PortfolioModel.id == CreditModel.portfolio_id)
            .where(
                PortfolioModel.organization_id == organization_id,
                PortfolioModel.deleted_at.is_(None),
                CreditModel.deleted_at.is_(None),
            )
        )
        row = result.one()

        debtors_q = (
            select(CreditModel.debtor_id.label("id"))
            .join(PortfolioModel, PortfolioModel.id == CreditModel.portfolio_id)
            .where(
                PortfolioModel.organization_id == organization_id,
                PortfolioModel.deleted_at.is_(None),
                CreditModel.deleted_at.is_(None),
            )
        )
        codebtors_q = (
            select(CreditModel.codebtor_id.label("id"))
            .join(PortfolioModel, PortfolioModel.id == CreditModel.portfolio_id)
            .where(
                PortfolioModel.organization_id == organization_id,
                PortfolioModel.deleted_at.is_(None),
                CreditModel.deleted_at.is_(None),
                CreditModel.codebtor_id.is_not(None),
            )
        )
        all_ids = union(debtors_q, codebtors_q).subquery()
        clientes_unicos: int = (
            await self.session.scalar(select(func.count()).select_from(all_ids)) or 0
        )

        documentos_unicos: int = await self._count_unique_documents(all_ids)

        return PortfolioCreditStats(
            creditos=row.creditos,
            titulares=row.titulares,
            codeudores=row.codeudores,
            clientes_unicos=clientes_unicos,
            documentos_unicos=documentos_unicos,
            total_mora=float(row.total_mora),
        )

    async def get_by_credit_number(
        self, credit_number: str, portfolio_id: uuid.UUID
    ) -> CreditModel | None:
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.credit_number == credit_number,
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def bulk_upsert_by_credit_number(
        self, credits: list[dict]
    ) -> dict[str, uuid.UUID]:
        """Un solo `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` para varios créditos
        a la vez (Fase 4 de la auditoría), en vez de un SELECT+INSERT/UPDATE por cada
        uno. ``credits``: dicts con los campos de `CreditRowData` (nombres de atributo)
        más `portfolio_id`/`debtor_id`/`codebtor_id` ya resueltos. Devuelve
        ``{credit_number: id}``. `discounts_accum`/`is_active` quedan fuera del SET de
        conflicto a propósito -- igual que el upsert fila por fila, que tampoco los
        toca -- para que conserven su valor/default en vez de resetearse en cada carga.
        `deleted_at` se fuerza a `None` en conflicto: revive un `credit_number` que
        `update_csv` había soft-borrado antes de recargar, en vez de dejarlo
        actualizado-pero-eliminado. El conflict target es `(id_portafolio,
        numero_credito)` -- el número lo asigna cada empresa por su cuenta, así que
        dos portafolios pueden reusarlo sin colisionar; `id_portafolio` por eso
        también queda fuera del SET, nunca se reasigna un crédito de un conflicto."""
        if not credits:
            return {}

        table = self.model_class.__table__
        column_by_attr = {
            "credit_date": "fecha_credito",
            "disbursed_date": "fecha_desembolso",
            "credit_type": "tipo_credito",
            "agreed_interest_rate": "tasa_interes_pactada",
            "charged_effective_annual_rate": "tasa_efectiva_anual_cobrada",
            "balance_disbursed": "saldo_desembolsado",
            "court_date": "fecha_corte",
            "initial_term": "plazo_inicial",
            "total_credit_balance": "saldo_total_credito",
            "overdue_principal_balance": "saldo_capital_mora",
            "current_interest": "interes_corriente",
            "overdue_interest": "interes_mora",
            "other_concepts": "otros_conceptos",
            "overdue_installments": "cuotas_en_mora",
            "days_overdue_at_cutoff": "dias_mora_al_corte",
            "amortization_system": "sistema_amortizacion",
            "pending_installments": "cuotas_pendientes",
            "insurance_total": "seguros_totales",
            "commission_accum": "comision_acumulada",
            "platform_fee_accum": "fee_plataforma_acumulado",
            "vat_accum": "iva_acumulado",
            "subproduct": "subproducto",
            "uvr_last_quote": "uvr_ultima_cotizacion",
            "condonations_accum": "condonaciones_acumuladas",
            "portfolio_id": "id_portafolio",
            "debtor_id": "id_deudor",
            "codebtor_id": "id_codeudor",
        }
        values = [
            {
                "numero_credito": c["credit_number"],
                **{column_by_attr[k]: v for k, v in c.items() if k != "credit_number"},
            }
            for c in credits
        ]
        update_columns = [
            col for col in column_by_attr.values() if col != "id_portafolio"
        ]
        stmt = pg_insert(table).values(values)
        set_clause = {col: getattr(stmt.excluded, col) for col in update_columns}
        set_clause["eliminado_en"] = None
        set_clause["fecha_actualizacion"] = datetime.now(timezone.utc)
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.id_portafolio, table.c.numero_credito],
            set_=set_clause,
        ).returning(table.c.id, table.c.numero_credito)

        result = await self.session.execute(stmt)
        return {row.numero_credito: row.id for row in result}

    async def get_by_credit_numbers(
        self, credit_numbers: list[str], portfolio_id: uuid.UUID
    ) -> list[CreditModel]:
        """Versión en lote de `get_by_credit_number`, para precargar en 1 query los
        créditos que va a necesitar la carga de plan de cuotas por CSV, en vez de un
        SELECT por fila (Fase 4 de la auditoría)."""
        if not credit_numbers:
            return []
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.credit_number.in_(credit_numbers),
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_portfolio_id(self, portfolio_id: uuid.UUID) -> list[CreditModel]:
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_debtor_id(self, debtor_id: uuid.UUID) -> list[CreditModel]:
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.debtor_id == debtor_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_debtor_ids(self, debtor_ids: list[uuid.UUID]) -> list[CreditModel]:
        if not debtor_ids:
            return []
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.debtor_id.in_(debtor_ids),
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_debtor_and_portfolio(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID
    ) -> list[CreditModel]:
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.debtor_id == debtor_id,
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_codebtor_id(self, codebtor_id: uuid.UUID) -> list[CreditModel]:
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.codebtor_id == codebtor_id,
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_codebtor_ids(
        self, codebtor_ids: list[uuid.UUID]
    ) -> list[CreditModel]:
        if not codebtor_ids:
            return []
        result = await self.session.execute(
            select(CreditModel).where(
                CreditModel.codebtor_id.in_(codebtor_ids),
                CreditModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_codebtor_ids(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """Codeudores de los creditos donde ``debtor_id`` es titular, dentro del
        portafolio."""
        result = await self.session.execute(
            select(CreditModel.codebtor_id)
            .where(
                CreditModel.debtor_id == debtor_id,
                CreditModel.codebtor_id.is_not(None),
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
            .distinct()
        )
        return {cid for cid in result.scalars().all() if cid}

    async def debtor_belongs_to_portfolio(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID
    ) -> bool:
        """True si el deudor participa (como titular o codeudor) en algun credito
        del portafolio."""
        result = await self.session.execute(
            select(CreditModel.id)
            .where(
                or_(
                    CreditModel.debtor_id == debtor_id,
                    CreditModel.codebtor_id == debtor_id,
                ),
                CreditModel.portfolio_id == portfolio_id,
                CreditModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        return result.scalar() is not None

    async def bulk_advance_overdue_days(
        self, country_code: str, tz_str: str, today: date, now: datetime
    ) -> int:
        """Suma un día de mora a los créditos vencidos de los portafolios con contador
        diario habilitado en ``country_code``, cuyo ``court_date`` (en la zona del país)
        todavía no se actualizó hoy."""
        enabled_portfolios = (
            select(PortfolioDailyCounterConfigModel.portfolio_id)
            .join(
                PortfolioModel,
                PortfolioModel.id == PortfolioDailyCounterConfigModel.portfolio_id,
            )
            .where(
                PortfolioDailyCounterConfigModel.enabled.is_(True),
                PortfolioModel.country == country_code,
            )
        )

        mora_condition = or_(
            CreditModel.overdue_principal_balance > 0,
            CreditModel.overdue_installments > 0,
            CreditModel.overdue_interest > 0,
            CreditModel.days_overdue_at_cutoff > 0,
        )

        local_court_date = func.timezone(tz_str, CreditModel.court_date).cast(SADate)

        not_updated_today = or_(
            CreditModel.court_date.is_(None),
            local_court_date < today,
        )

        days_delta = case(
            (CreditModel.court_date.is_(None), 1),
            else_=func.greatest(
                cast(today, SADate) - local_court_date,
                0,
            ),
        )

        result = await self.session.execute(
            update(CreditModel)
            .where(
                CreditModel.portfolio_id.in_(enabled_portfolios),
                mora_condition,
                not_updated_today,
            )
            .values(
                days_overdue_at_cutoff=CreditModel.days_overdue_at_cutoff + days_delta,
                court_date=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount  # type: ignore[union-attr]

    async def get_latest_by_debtor_ids(
        self, debtor_ids: list[uuid.UUID]
    ) -> list[CreditModel]:
        """Un deudor puede tener varios creditos: retorna el desembolsado mas
        reciente por deudor."""
        if not debtor_ids:
            return []
        result = await self.session.execute(
            select(CreditModel)
            .where(
                CreditModel.debtor_id.in_(debtor_ids), CreditModel.deleted_at.is_(None)
            )
            .distinct(CreditModel.debtor_id)
            .order_by(CreditModel.debtor_id, CreditModel.disbursed_date.desc())
        )
        return list(result.scalars().all())

    async def soft_delete_by_portfolios(
        self, portfolio_ids: Sequence[uuid.UUID], deleted_at: datetime
    ) -> None:
        """Baja en cascada de los créditos vivos de esos portafolios (mismo sello que el
        portafolio, para poder restaurarlos juntos sin resucitar créditos dados de baja
        antes por otra vía, p. ej. la recarga del CSV en modo update)."""
        if portfolio_ids:
            await self.soft_delete_where(
                CreditModel.portfolio_id.in_(portfolio_ids), deleted_at=deleted_at
            )

    async def restore_by_portfolios(
        self, portfolio_ids: Sequence[uuid.UUID], deleted_at: datetime
    ) -> None:
        if portfolio_ids:
            await self.restore_where(
                CreditModel.portfolio_id.in_(portfolio_ids), deleted_at=deleted_at
            )
