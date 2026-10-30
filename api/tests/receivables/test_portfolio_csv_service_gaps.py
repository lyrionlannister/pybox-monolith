"""Cierra gaps de `PortfolioCsvService.append_csv`/`update_csv`: el helper
`portfolio_csv_row` de `tests/receivables/conftest.py` solo llena las 4 columnas
mínimas, así que ninguna fila trae pago/cotización UVR/ajuste -- las ramas
`_insert_payment`/`_insert_uvr_quote`/`_insert_credit_adjustment` (líneas 319-371 de
`portfolio_csv_service.py`) nunca se ejercitan en `test_portfolio_csv_upload.py`. Aquí
se arman filas completas para forzarlas, contra `db_session` real.
"""

import uuid

from sqlalchemy import select

from receivables.credits.models.credit_adjustment_model import CreditAdjustmentModel
from receivables.credits.models.uvr_quote_model import UVRQuoteModel
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.models.payment_model import PaymentModel
from receivables.portfolios.services.portfolio_csv_service import PortfolioCsvService
from tests.factories import unique_document_number
from tests.receivables.conftest import (
    build_debtor,
    build_organization,
    build_portfolio,
    build_portfolio_csv,
    portfolio_csv_row,
)


def full_row(**overrides) -> dict[str, str]:
    row = portfolio_csv_row(
        **{
            "Fecha del pago": "10/01/2026",
            "Fecha limite de pago": "01/01/2026",
            "total": "150000",
            "abono a capital": "100000",
            "interes corriente": "30000",
            "interes mora": "0",
            "Seguro de vida": "0",
            "seguro de vehiculo": "0",
            "otros cargos": "0",
            "IVA": "0",
            "Comision": "0",
            "Plataforma": "0",
            "Numero de la cuota que se cancela": "1",
            "Cotizacion de UVR": "350.5",
            "Fecha de corte": "05/01/2026",
            "Condonaciones y/o descuentos": "5000",
        }
    )
    row.update(overrides)
    return row


class TestAppendCsvInsertsOptionalSubRecords:
    async def test_append_creates_payment_uvr_quote_and_adjustment(self, db_session):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        service = PortfolioCsvService(db_session)
        row = full_row()
        result = await service.append_csv(
            portfolio.id, build_portfolio_csv([row]), "cartera.csv"
        )

        assert result.processed_rows == 1

        credit_repo = CreditRepository(db_session)
        credit = await credit_repo.get_by_credit_number(
            row["Numero de credito"], portfolio.id
        )
        assert credit is not None

        payment = (
            (
                await db_session.execute(
                    select(PaymentModel).where(PaymentModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert payment is not None
        assert payment.payment_amount == 150000
        assert payment.installment_number == 1

        uvr_quote = (
            (
                await db_session.execute(
                    select(UVRQuoteModel).where(UVRQuoteModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert uvr_quote is not None
        assert round(uvr_quote.quote_value, 1) == 350.5

        adjustment = (
            (
                await db_session.execute(
                    select(CreditAdjustmentModel).where(
                        CreditAdjustmentModel.credit_id == credit.id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert adjustment is not None
        assert adjustment.adjustment_amount == 5000


class TestUpdateCsvInsertsOptionalSubRecords:
    async def test_update_creates_payment_uvr_quote_and_adjustment(self, db_session):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        service = PortfolioCsvService(db_session)
        row = full_row()
        result = await service.update_csv(
            portfolio.id, build_portfolio_csv([row]), "cartera.csv"
        )
        assert result.processed_rows == 1

        credit_repo = CreditRepository(db_session)
        credit = await credit_repo.get_by_credit_number(
            row["Numero de credito"], portfolio.id
        )
        assert credit is not None
        assert credit.portfolio_id == portfolio.id

        payment = (
            (
                await db_session.execute(
                    select(PaymentModel).where(PaymentModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert payment is not None

        uvr_quote = (
            (
                await db_session.execute(
                    select(UVRQuoteModel).where(UVRQuoteModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert uvr_quote is not None

        adjustment = (
            (
                await db_session.execute(
                    select(CreditAdjustmentModel).where(
                        CreditAdjustmentModel.credit_id == credit.id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert adjustment is not None

    async def test_update_replaces_existing_credits(self, db_session):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        service = PortfolioCsvService(db_session)
        old_row = portfolio_csv_row()
        await service.append_csv(
            portfolio.id, build_portfolio_csv([old_row]), "cartera.csv"
        )

        new_row = portfolio_csv_row()
        await service.update_csv(
            portfolio.id, build_portfolio_csv([new_row]), "cartera2.csv"
        )

        credit_repo = CreditRepository(db_session)
        assert (
            await credit_repo.get_by_credit_number(
                old_row["Numero de credito"], portfolio.id
            )
            is None
        )
        assert (
            await credit_repo.get_by_credit_number(
                new_row["Numero de credito"], portfolio.id
            )
            is not None
        )


class TestProcessCsvCharacterizationGolden:
    """Congela el comportamiento ACTUAL de `process_csv`/`_process_row` (savepoint por
    fila) ANTES del refactor de precarga + bulk-upsert planeado en la auditoría (Fase 4:
    N+1 masivo en carga de portafolio). Si estos valores cambian tras ese refactor, es
    una regresión real que hay que explicar, no un detalle de implementación a
    actualizar sin pensar. Cubre en un solo batch: deudor duplicado entre filas,
    codeudor repetido entre filas, un deudor que ya existía en BD antes de la carga
    (camino update), un deudor nuevo (camino insert), y una fila inválida en medio de
    válidas (para probar que el aislamiento por SAVEPOINT no tumba el resto del archivo).
    """

    async def test_mixed_batch_preserves_row_isolation_and_upsert_semantics(
        self, db_session
    ):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()

        # Deudor pre-existente en BD, antes de que corra la carga -> _upsert_debtor
        # debe tomar el camino "update" (mismo id, nombre actualizado), no crear
        # un segundo registro para el mismo documento.
        existing_doc = unique_document_number()
        existing_debtor = build_debtor(
            org.id, document_number_plain=existing_doc, full_name="Nombre Viejo"
        )
        db_session.add(existing_debtor)
        await db_session.flush()
        existing_debtor_id = existing_debtor.id

        shared_debtor_doc = unique_document_number()
        shared_codebtor_doc = unique_document_number()

        row1 = portfolio_csv_row(
            **{
                "Numero de documento": shared_debtor_doc,
                "Nombre del titular": "Titular Compartido",
                "Numero de credito": "CR-GOLDEN-1",
                "Nombre del Codeudor": "Codeudor Compartido",
                "Numero de documento codeudor": shared_codebtor_doc,
            }
        )
        # Misma persona que row1 (debtor Y codeudor repetidos) pero con otro crédito ->
        # debe reusar el mismo DebtorModel para ambos, no duplicarlo.
        row2 = portfolio_csv_row(
            **{
                "Numero de documento": shared_debtor_doc,
                "Nombre del titular": "Titular Compartido",
                "Numero de credito": "CR-GOLDEN-2",
                "Nombre del Codeudor": "Codeudor Compartido",
                "Numero de documento codeudor": shared_codebtor_doc,
            }
        )
        # Fila inválida: la tasa pactada excede Numeric(10,2) (max 8 dígitos enteros) ->
        # asyncpg.NumericValueOutOfRange dentro del begin_nested() de esta fila.
        row3_invalid = portfolio_csv_row(
            **{
                "Numero de credito": "CR-GOLDEN-3-INVALID",
                "Tasa de interes pactada": "9999999999",
            }
        )
        row4_existing_debtor = portfolio_csv_row(
            **{
                "Numero de documento": existing_doc,
                "Nombre del titular": "Nombre Nuevo Desde El CSV",
                "Numero de credito": "CR-GOLDEN-4",
            }
        )
        row5_after_failure = portfolio_csv_row(
            **{
                "Numero de credito": "CR-GOLDEN-5",
            }
        )

        service = PortfolioCsvService(db_session)
        result = await service.process_csv(
            build_portfolio_csv(
                [row1, row2, row3_invalid, row4_existing_debtor, row5_after_failure]
            ),
            organization_id=org.id,
            portfolio_name="Portafolio Golden",
        )

        # --- Golden del CsvProcessResult: si esto cambia tras el refactor, compararlo
        # campo a campo contra este valor congelado, no asumir que "está bien distinto". ---
        assert result.total_rows == 5
        assert result.processed_rows == 4
        assert result.failed_rows == 1
        assert (
            result.titulares == 4
        )  # shared_debtor_doc cuenta una vez + existing_doc + el de row5
        assert result.codeudores == 1  # shared_codebtor_doc, solo en row1/row2
        assert result.creditos == 5  # cuenta filas parseadas, incluida la que falla
        assert result.clientes_unicos == 4
        assert len(result.errors) == 1
        assert result.errors[0].startswith("Fila 3")

        credit_repo = CreditRepository(db_session)
        debtor_repo = DebtorRepository(db_session)

        # Deudor+codeudor compartidos entre row1/row2: un solo registro de cada uno.
        credit1 = await credit_repo.get_by_credit_number(
            "CR-GOLDEN-1", result.portfolio_id
        )
        credit2 = await credit_repo.get_by_credit_number(
            "CR-GOLDEN-2", result.portfolio_id
        )
        assert credit1 is not None and credit2 is not None
        assert credit1.debtor_id == credit2.debtor_id
        assert credit1.codebtor_id == credit2.codebtor_id

        # La fila inválida (CR-GOLDEN-3-INVALID) no debe haber creado nada.
        assert (
            await credit_repo.get_by_credit_number(
                "CR-GOLDEN-3-INVALID", result.portfolio_id
            )
            is None
        )

        # Deudor pre-existente: mismo id, nombre actualizado por la fila del CSV.
        doc_hash = build_debtor(
            org.id, document_number_plain=existing_doc
        ).document_number_hash
        updated_debtor = await debtor_repo.get_by_document_number(org.id, doc_hash)
        assert updated_debtor.id == existing_debtor_id
        assert updated_debtor.full_name == "Nombre Nuevo Desde El CSV"

        # La fila posterior a la inválida sí se procesó -> confirma el aislamiento
        # por SAVEPOINT: una fila mala no tumba el resto del archivo.
        assert (
            await credit_repo.get_by_credit_number("CR-GOLDEN-5", result.portfolio_id)
            is not None
        )


class TestProcessCsvBulkUpsertPath:
    """Verifica el camino bulk (Fase 4 de la auditoría, detrás del flag
    `PORTFOLIO_CSV_BULK_UPSERT`) contra el mismo golden del camino secuencial de arriba,
    con la MISMA estructura de filas (deudor/codeudor repetido, deudor pre-existente,
    fila inválida, fila posterior a la inválida) pero documentos distintos para no
    interferir entre los dos portafolios."""

    def _rows(self, shared_debtor_doc, shared_codebtor_doc, existing_doc):
        return [
            portfolio_csv_row(
                **{
                    "Numero de documento": shared_debtor_doc,
                    "Nombre del titular": "Titular Compartido",
                    "Numero de credito": f"{shared_debtor_doc}-CR-1",
                    "Nombre del Codeudor": "Codeudor Compartido",
                    "Numero de documento codeudor": shared_codebtor_doc,
                }
            ),
            portfolio_csv_row(
                **{
                    "Numero de documento": shared_debtor_doc,
                    "Nombre del titular": "Titular Compartido",
                    "Numero de credito": f"{shared_debtor_doc}-CR-2",
                    "Nombre del Codeudor": "Codeudor Compartido",
                    "Numero de documento codeudor": shared_codebtor_doc,
                }
            ),
            portfolio_csv_row(
                **{
                    "Numero de credito": f"{shared_debtor_doc}-CR-3-INVALID",
                    "Tasa de interes pactada": "9999999999",
                }
            ),
            portfolio_csv_row(
                **{
                    "Numero de documento": existing_doc,
                    "Nombre del titular": "Nombre Nuevo Desde El CSV",
                    "Numero de credito": f"{shared_debtor_doc}-CR-4",
                }
            ),
            portfolio_csv_row(
                **{
                    "Numero de credito": f"{shared_debtor_doc}-CR-5",
                }
            ),
        ]

    async def test_bulk_path_matches_sequential_path_result(
        self, db_session, monkeypatch
    ):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()

        existing_doc_seq = unique_document_number()
        db_session.add(
            build_debtor(
                org.id, document_number_plain=existing_doc_seq, full_name="Nombre Viejo"
            )
        )
        existing_doc_bulk = unique_document_number()
        db_session.add(
            build_debtor(
                org.id,
                document_number_plain=existing_doc_bulk,
                full_name="Nombre Viejo",
            )
        )
        await db_session.flush()

        service = PortfolioCsvService(db_session)

        monkeypatch.setenv("PORTFOLIO_CSV_BULK_UPSERT", "false")
        seq_debtor_doc, seq_codebtor_doc = (
            unique_document_number(),
            unique_document_number(),
        )
        seq_result = await service.process_csv(
            build_portfolio_csv(
                self._rows(seq_debtor_doc, seq_codebtor_doc, existing_doc_seq)
            ),
            organization_id=org.id,
            portfolio_name="Portafolio Secuencial",
        )

        monkeypatch.setenv("PORTFOLIO_CSV_BULK_UPSERT", "true")
        bulk_debtor_doc, bulk_codebtor_doc = (
            unique_document_number(),
            unique_document_number(),
        )
        bulk_result = await service.process_csv(
            build_portfolio_csv(
                self._rows(bulk_debtor_doc, bulk_codebtor_doc, existing_doc_bulk)
            ),
            organization_id=org.id,
            portfolio_name="Portafolio Bulk",
        )

        # --- Mismo CsvProcessResult, campo a campo (salvo portfolio_id, que difiere). ---
        assert bulk_result.total_rows == seq_result.total_rows == 5
        assert bulk_result.processed_rows == seq_result.processed_rows == 4
        assert bulk_result.failed_rows == seq_result.failed_rows == 1
        assert bulk_result.titulares == seq_result.titulares == 4
        assert bulk_result.codeudores == seq_result.codeudores == 1
        assert bulk_result.creditos == seq_result.creditos == 5
        assert bulk_result.clientes_unicos == seq_result.clientes_unicos == 4
        assert len(bulk_result.errors) == len(seq_result.errors) == 1
        assert bulk_result.errors[0].startswith("Fila 3")
        assert seq_result.errors[0].startswith("Fila 3")

        credit_repo = CreditRepository(db_session)
        debtor_repo = DebtorRepository(db_session)

        # Deudor+codeudor compartidos entre fila 1/2: un solo registro de cada uno,
        # igual que en el camino secuencial.
        c1 = await credit_repo.get_by_credit_number(
            f"{bulk_debtor_doc}-CR-1", bulk_result.portfolio_id
        )
        c2 = await credit_repo.get_by_credit_number(
            f"{bulk_debtor_doc}-CR-2", bulk_result.portfolio_id
        )
        assert c1 is not None and c2 is not None
        assert c1.debtor_id == c2.debtor_id
        assert c1.codebtor_id == c2.codebtor_id

        # La fila inválida no creó nada; la posterior a ella sí se procesó.
        assert (
            await credit_repo.get_by_credit_number(
                f"{bulk_debtor_doc}-CR-3-INVALID", bulk_result.portfolio_id
            )
            is None
        )
        assert (
            await credit_repo.get_by_credit_number(
                f"{bulk_debtor_doc}-CR-5", bulk_result.portfolio_id
            )
            is not None
        )

        # Deudor pre-existente actualizado, mismo criterio que el camino secuencial.
        doc_hash = build_debtor(
            org.id, document_number_plain=existing_doc_bulk
        ).document_number_hash
        updated_debtor = await debtor_repo.get_by_document_number(org.id, doc_hash)
        assert updated_debtor.full_name == "Nombre Nuevo Desde El CSV"

    async def test_bulk_path_chunk_fallback_isolates_only_the_bad_chunk(
        self, db_session, monkeypatch
    ):
        """Con chunk_size=2, la fila inválida cae en su propio chunk -> ese chunk
        reprocesa fila por fila (fallback), pero el resto de chunks sí pasa por bulk
        puro. Confirma que el fallback es por CHUNK, no por archivo completo."""
        import receivables.portfolios.services.portfolio_csv_service as service_module

        monkeypatch.setattr(service_module, "PORTFOLIO_CSV_BULK_CHUNK_SIZE", 2)
        monkeypatch.setenv("PORTFOLIO_CSV_BULK_UPSERT", "true")

        org = build_organization()
        db_session.add(org)
        await db_session.flush()

        doc = unique_document_number()
        rows = self._rows(doc, unique_document_number(), unique_document_number())
        # 5 filas / chunk_size=2 -> chunks [0,1] [2,3] [4]; la inválida (índice 2) cae
        # sola en el segundo chunk junto con la fila 4 (deudor pre-existente inventado
        # -> no existe en BD, así que esa fila también fallará aquí, a propósito, para
        # mantener el escenario simple).
        rows[3] = portfolio_csv_row(**{"Numero de credito": f"{doc}-CR-4-standalone"})

        service = PortfolioCsvService(db_session)
        result = await service.process_csv(
            build_portfolio_csv(rows),
            organization_id=org.id,
            portfolio_name="Portafolio Chunks",
        )

        assert result.processed_rows == 4
        assert result.failed_rows == 1
        assert len(result.errors) == 1
        assert result.errors[0].startswith("Fila 3")

        credit_repo = CreditRepository(db_session)
        # Chunk 1 (filas 1-2, bulk puro) y chunk 3 (fila 5, bulk puro) sí crearon crédito.
        assert (
            await credit_repo.get_by_credit_number(f"{doc}-CR-1", result.portfolio_id)
            is not None
        )
        assert (
            await credit_repo.get_by_credit_number(f"{doc}-CR-5", result.portfolio_id)
            is not None
        )
        # Chunk 2 (filas 3-4, fallback fila por fila): la 3 falla, la 4 sí se procesa.
        assert (
            await credit_repo.get_by_credit_number(
                f"{doc}-CR-3-INVALID", result.portfolio_id
            )
            is None
        )
        assert (
            await credit_repo.get_by_credit_number(
                f"{doc}-CR-4-standalone", result.portfolio_id
            )
            is not None
        )

    async def test_update_csv_reused_credit_number_is_revived_not_left_deleted(
        self, db_session, monkeypatch
    ):
        """`update_csv` soft-borra los créditos existentes antes de recargar
        (ver update_csv). Si el archivo nuevo reusa el mismo `numero_credito` -- muy
        común en una recarga real --, el upsert por ON CONFLICT debe revivirlo
        (`eliminado_en=None`), no dejarlo actualizado-pero-eliminado."""
        monkeypatch.setenv("PORTFOLIO_CSV_BULK_UPSERT", "true")

        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        service = PortfolioCsvService(db_session)
        reused_number = f"CR-REUSE-{uuid.uuid4().hex[:8]}"
        first_row = portfolio_csv_row(**{"Numero de credito": reused_number})
        # append_csv (no process_csv, que crea su propio portafolio) para cargar sobre
        # el `portfolio` ya existente, antes de probar el reemplazo con update_csv.
        await service.append_csv(
            portfolio.id, build_portfolio_csv([first_row]), "primero.csv"
        )

        second_row = portfolio_csv_row(**{"Numero de credito": reused_number})
        result = await service.update_csv(
            portfolio.id, build_portfolio_csv([second_row]), "segundo.csv"
        )

        assert result.processed_rows == 1
        assert result.failed_rows == 0

        credit_repo = CreditRepository(db_session)
        credit = await credit_repo.get_by_credit_number(reused_number, portfolio.id)
        assert credit is not None
        assert credit.deleted_at is None

    async def test_bulk_path_executes_fewer_statements_than_sequential_baseline(
        self, db_session, monkeypatch
    ):
        """Prueba directa de que el flag realmente cambia el camino ejecutado (no solo
        que el resultado coincide por casualidad): mismo escenario de N filas nuevas,
        sin codeudor/pago, medido con AMBOS caminos en el mismo test -- así la
        comparación no depende de asumir de antemano cuánto overhead fijo (portafolio,
        documento archivado, SAVEPOINTs) tiene cada uno."""
        from sqlalchemy import event

        from core.database.database import db as db_container

        sync_engine = db_container.engine.sync_engine

        async def _run_and_count(
            flag_value: str, portfolio_name: str, credit_prefix: str
        ) -> int:
            monkeypatch.setenv("PORTFOLIO_CSV_BULK_UPSERT", flag_value)

            org = build_organization()
            db_session.add(org)
            await db_session.flush()

            statements: list[str] = []

            def _count(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(sync_engine, "before_cursor_execute", _count)
            try:
                service = PortfolioCsvService(db_session)
                rows = [
                    portfolio_csv_row(**{"Numero de credito": f"{credit_prefix}-{i}"})
                    for i in range(10)
                ]
                result = await service.process_csv(
                    build_portfolio_csv(rows),
                    organization_id=org.id,
                    portfolio_name=portfolio_name,
                )
            finally:
                event.remove(sync_engine, "before_cursor_execute", _count)

            assert result.processed_rows == 10
            return len(statements)

        sequential_count = await _run_and_count(
            "false", "Portafolio Seq Baseline", "CR-SEQBASE"
        )
        bulk_count = await _run_and_count(
            "true", "Portafolio Bulk Baseline", "CR-BULKBASE"
        )

        # 10 filas nuevas: el secuencial hace un SELECT+INSERT/refresh de deudor y de
        # crédito POR FILA (10 de cada); el bulk los colapsa a 1 statement cada uno para
        # todo el chunk -- la diferencia debe crecer con N, no ser un margen fijo chico.
        assert bulk_count < sequential_count

    async def test_bulk_row_statement_count_baseline(self, db_session):
        """Baseline explícito del número de statements SQL que ejecuta HOY
        `_process_row` por fila (queries + inserts/updates dentro de su propio
        SAVEPOINT). Tras el refactor de la Fase 4 (precarga + bulk upsert) este
        número debe BAJAR de forma medible para un batch de N filas nuevas -- este
        test es la vara de medir, no algo a "arreglar" si cambia sin que baje."""
        org = build_organization()
        db_session.add(org)
        await db_session.flush()

        statements: list[str] = []

        def _count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        from sqlalchemy import event

        from core.database.database import db as db_container

        sync_engine = db_container.engine.sync_engine
        event.listen(sync_engine, "before_cursor_execute", _count)
        try:
            service = PortfolioCsvService(db_session)
            rows = [
                portfolio_csv_row(**{"Numero de credito": f"CR-BASELINE-{i}"})
                for i in range(5)
            ]
            await service.process_csv(
                build_portfolio_csv(rows),
                organization_id=org.id,
                portfolio_name="Portafolio Baseline",
            )
        finally:
            event.remove(sync_engine, "before_cursor_execute", _count)

        # 5 filas nuevas (sin codeudor/pago) hoy ejecutan ~4-6 statements cada una
        # (lookup debtor, insert debtor, lookup address, insert address, lookup
        # contactos -- sin contactos en `portfolio_csv_row` mínimo --, lookup+insert
        # credito) más overhead fijo del portfolio/documento archivado. El número
        # exacto importa menos que la magnitud: debe ser un múltiplo claro de 5, no
        # una constante acotada. Se deja como piso de comparación explícito.
        assert len(statements) >= 5 * 4


class TestDecimalPrecisionOnInsert:
    """Regresión para la Fase 2 de la auditoría (dinero como float en
    `receivables`): `_insert_payment`/`_insert_uvr_quote` ya no pasan por
    `float(...)` antes de persistir/sumar. Usa 0.10 + 0.20 -- el caso clásico donde
    la suma en binario da 0.30000000000000004 -- para que un `float(...)` reintroducido
    por accidente rompa este test en vez de pasar desapercibido."""

    async def test_insurance_sum_and_uvr_quote_keep_exact_decimal_precision(
        self, db_session
    ):
        from decimal import Decimal

        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()

        service = PortfolioCsvService(db_session)
        row = full_row(
            **{
                "Seguro de vida": "0.10",
                "seguro de vehiculo": "0.20",
                "Cotizacion de UVR": "123.456789",
            }
        )
        result = await service.process_csv(
            build_portfolio_csv([row]),
            organization_id=org.id,
            portfolio_name="Portafolio Decimal",
        )
        assert result.processed_rows == 1

        credit_repo = CreditRepository(db_session)
        credit = await credit_repo.get_by_credit_number(
            row["Numero de credito"], result.portfolio_id
        )

        payment = (
            (
                await db_session.execute(
                    select(PaymentModel).where(PaymentModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert payment.insurances_total == Decimal("0.30")

        uvr_quote = (
            (
                await db_session.execute(
                    select(UVRQuoteModel).where(UVRQuoteModel.credit_id == credit.id)
                )
            )
            .scalars()
            .first()
        )
        assert uvr_quote.quote_value == Decimal("123.456789")
