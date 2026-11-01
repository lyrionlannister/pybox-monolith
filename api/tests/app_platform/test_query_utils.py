"""Unit tests puros (sin DB) para el query-builder dinámico de segmentos/reportes.

`query_utils.py` es el módulo crítico de sanitización: todo identificador que termina
en SQL crudo (columnas, tablas, alias) pasa por acá antes de interpolarse en el
string de la query. Estos tests cubren la construcción de condiciones para los
filtros comunes (igualdad, IN, BETWEEN, LIKE/contiene) y que un identificador
inválido se rechaza antes de llegar a componerse en SQL.
"""

from decimal import Decimal

import pytest
from cryptography.exceptions import InvalidTag

from app_platform.schema_manager.utils.query_utils import (
    build_sql_condition,
    build_table_alias_map,
    build_tenant_scope_condition,
    build_where_clauses,
    decrypt_sensitive_value,
    encrypted_group_outputs,
    encrypted_output_columns,
    is_aggregate_mode,
    normalize_aggregate_specs,
    normalize_operator,
    resolve_alias,
    resolve_full_table_name,
    sanitize_identifier,
    sanitize_table_name,
    serialize_value,
    sql_literal,
)
from core.security.services.encrypt_service import encrypt_service


class TestSanitizeIdentifier:
    def test_valid_identifier_passes_through(self):
        assert sanitize_identifier("nombre_columna", label="column") == "nombre_columna"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Falta indicar"):
            sanitize_identifier("", label="column")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="Falta indicar"):
            sanitize_identifier(None, label="column")

    @pytest.mark.parametrize(
        "bad",
        [
            "not a valid ident!",
            "1starts_with_digit",
            "drop table x; --",
            "col-with-dash",
            "col;DROP TABLE usuarios",
            "col.with.dots",
        ],
    )
    def test_invalid_identifier_rejected(self, bad):
        with pytest.raises(ValueError, match="Valor inválido"):
            sanitize_identifier(bad, label="column")


class TestSanitizeTableName:
    def test_without_schema_defaults_to_public(self):
        assert sanitize_table_name("creditos") == ("public", "creditos")

    def test_with_schema(self):
        assert sanitize_table_name("reportes.creditos") == ("reportes", "creditos")

    def test_invalid_table_rejected(self):
        with pytest.raises(ValueError):
            sanitize_table_name("creditos; DROP TABLE usuarios")

    def test_invalid_schema_rejected(self):
        with pytest.raises(ValueError):
            sanitize_table_name("bad schema!.creditos")


class TestEncryptedOutputColumns:
    def test_single_table_uses_bare_column_name(self):
        assert encrypted_output_columns([{"name": "deudores"}], prefixed=False) == {
            "numero_documento"
        }

    def test_join_uses_alias_prefixed_name_too(self):
        outputs = encrypted_output_columns(
            [{"name": "deudores", "alias": "d"}, {"name": "creditos"}], prefixed=True
        )
        assert outputs == {"numero_documento", "d_numero_documento"}

    def test_tables_without_encrypted_columns_yield_nothing(self):
        assert (
            encrypted_output_columns(
                [{"name": "creditos"}, {"name": "pagos"}], prefixed=True
            )
            == set()
        )

    def test_group_by_output_alias_of_encrypted_column(self):
        alias_map = {"d": "public.deudores", "c": "public.creditos"}
        group_by = [
            {
                "table_alias": "d",
                "column": "numero_documento",
                "output_alias": "documento",
            },
            {
                "table_alias": "d",
                "column": "nombre_completo",
                "output_alias": "nombre_completo",
            },
            {"table_alias": "c", "column": "numero_documento", "output_alias": "otro"},
        ]
        assert encrypted_group_outputs(alias_map, group_by) == {"documento"}


class TestDecryptSensitiveValue:
    def test_decrypts_a_token(self):
        token = encrypt_service.encrypt_to_str("6168564922")
        assert decrypt_sensitive_value(token) == "6168564922"

    def test_plain_text_passes_through(self):
        assert decrypt_sensitive_value("6168564922") == "6168564922"

    def test_non_string_passes_through(self):
        assert decrypt_sensitive_value(None) is None
        assert decrypt_sensitive_value(42) == 42

    def test_corrupted_token_raises(self):
        with pytest.raises((ValueError, InvalidTag)):
            decrypt_sensitive_value("v1:no-es:un-token:valido")


class TestSqlLiteral:
    def test_none_is_null(self):
        assert sql_literal(None) == "NULL"

    def test_bool(self):
        assert sql_literal(True) == "TRUE"
        assert sql_literal(False) == "FALSE"

    def test_number(self):
        assert sql_literal(42) == "42"
        assert sql_literal(3.5) == "3.5"

    def test_string_escapes_quotes(self):
        assert sql_literal("O'Brien") == "'O''Brien'"


class TestBuildSqlCondition:
    def test_equality(self):
        assert build_sql_condition("t.col", "=", "CO") == "t.col = 'CO'"

    def test_not_equal_uses_diamond(self):
        assert build_sql_condition("t.col", "!=", 1) == "t.col <> 1"

    def test_in_operator(self):
        cond = build_sql_condition("t.col", "in", ["CO", "MX"])
        assert cond == "t.col IN ('CO', 'MX')"

    def test_in_operator_single_value_wraps_in_list(self):
        assert build_sql_condition("t.col", "in", "CO") == "t.col IN ('CO')"

    def test_in_operator_empty_list_raises(self):
        with pytest.raises(ValueError, match="operador IN"):
            build_sql_condition("t.col", "in", [])

    def test_not_in_operator(self):
        assert build_sql_condition("t.col", "not_in", ["CO"]) == "t.col NOT IN ('CO')"

    def test_between_date_range(self):
        cond = build_sql_condition("t.fecha", "between", ["2024-01-01", "2024-12-31"])
        assert cond == "t.fecha BETWEEN '2024-01-01' AND '2024-12-31'"

    def test_between_requires_exactly_two_values(self):
        with pytest.raises(ValueError, match="dos valores"):
            build_sql_condition("t.fecha", "between", ["2024-01-01"])

    def test_like_contains(self):
        assert (
            build_sql_condition("t.nombre", "like", "%Colombia%")
            == "t.nombre LIKE '%Colombia%'"
        )

    def test_ilike_contains_case_insensitive(self):
        assert (
            build_sql_condition("t.nombre", "ilike", "%colombia%")
            == "t.nombre ILIKE '%colombia%'"
        )

    def test_is_null(self):
        assert build_sql_condition("t.col", "is_null", None) == "t.col IS NULL"

    def test_is_not_null(self):
        assert build_sql_condition("t.col", "is_not_null", None) == "t.col IS NOT NULL"

    def test_greater_than(self):
        assert build_sql_condition("t.monto", ">", 1000) == "t.monto > 1000"


class TestNormalizeOperator:
    def test_aliases_normalize(self):
        assert normalize_operator("eq") == "="
        assert normalize_operator("notIn") == "not_in"
        assert normalize_operator(" GTE ") == ">="

    def test_default_is_equals(self):
        assert normalize_operator("") == "="
        assert normalize_operator(None) == "="


class TestBuildWhereClauses:
    def test_empty_filters_returns_empty_string(self):
        assert build_where_clauses([], "t") == ""

    def test_single_equality_filter(self):
        clause = build_where_clauses(
            [{"column": "codigo", "op": "=", "value": "CO"}], "t"
        )
        assert clause == "t.codigo = 'CO'"

    def test_multiple_filters_joined_with_and(self):
        clause = build_where_clauses(
            [
                {"column": "codigo", "op": "=", "value": "CO"},
                {"column": "activo", "op": "=", "value": True},
            ],
            "t",
        )
        assert clause == "t.codigo = 'CO' AND t.activo = TRUE"

    def test_in_filter(self):
        clause = build_where_clauses(
            [{"column": "codigo", "op": "in", "value": ["CO", "MX"]}], "t"
        )
        assert clause == "t.codigo IN ('CO', 'MX')"

    def test_numeric_looking_string_stays_quoted(self):
        # Regresión: "6168564922" se volvía int vía json.loads y `varchar = bigint` reventaba.
        clause = build_where_clauses(
            [{"column": "numero_documento", "op": "=", "value": "6168564922"}], "t"
        )
        assert clause == "t.numero_documento = '6168564922'"

    def test_json_list_string_is_still_parsed_for_in(self):
        clause = build_where_clauses(
            [{"column": "codigo", "op": "in", "value": '["CO", "MX"]'}], "t"
        )
        assert clause == "t.codigo IN ('CO', 'MX')"

    def test_debtor_document_filter_uses_hash_column(self):
        # numero_documento va cifrado con nonce aleatorio: solo se puede buscar por el hash.
        clause = build_where_clauses(
            [{"column": "numero_documento", "op": "=", "value": "6168564922"}],
            "d",
            "public.deudores",
        )
        assert (
            clause
            == f"d.numero_documento_hash = '{encrypt_service.hash_document('6168564922')}'"
        )

    def test_debtor_document_filter_in_hashes_every_value(self):
        clause = build_where_clauses(
            [{"column": "numero_documento", "op": "in", "value": ["111", " 222 "]}],
            "d",
            "public.deudores",
        )
        expected = ", ".join(
            f"'{encrypt_service.hash_document(v)}'" for v in ("111", "222")
        )
        assert clause == f"d.numero_documento_hash IN ({expected})"

    def test_debtor_document_filter_rejects_pattern_operators(self):
        with pytest.raises(ValueError, match="solo se puede filtrar por igualdad"):
            build_where_clauses(
                [{"column": "numero_documento", "op": "like", "value": "616%"}],
                "d",
                "public.deudores",
            )

    def test_debtor_document_filter_rejects_empty_value(self):
        with pytest.raises(ValueError, match="requiere un valor"):
            build_where_clauses(
                [{"column": "numero_documento", "op": "=", "value": ""}],
                "d",
                "public.deudores",
            )

    def test_same_column_name_on_other_table_is_not_rewritten(self):
        clause = build_where_clauses(
            [{"column": "numero_documento", "op": "=", "value": "123"}],
            "c",
            "public.contactos",
        )
        assert clause == "c.numero_documento = '123'"

    def test_between_filter_date_range(self):
        clause = build_where_clauses(
            [
                {
                    "column": "fecha",
                    "op": "between",
                    "value": ["2024-01-01", "2024-12-31"],
                }
            ],
            "t",
        )
        assert clause == "t.fecha BETWEEN '2024-01-01' AND '2024-12-31'"

    def test_contains_filter_via_ilike(self):
        clause = build_where_clauses(
            [{"column": "nombre", "op": "ilike", "value": "%bogo%"}], "t"
        )
        assert clause == "t.nombre ILIKE '%bogo%'"

    def test_invalid_column_rejected(self):
        with pytest.raises(ValueError):
            build_where_clauses([{"column": "bad col!", "op": "=", "value": 1}], "t")

    def test_invalid_operator_rejected(self):
        with pytest.raises(ValueError, match="Operador inválido"):
            build_where_clauses(
                [{"column": "codigo", "op": "; DROP TABLE x", "value": 1}], "t"
            )


class TestBuildTenantScopeCondition:
    def test_allowlisted_table_builds_condition(self):
        cond = build_tenant_scope_condition("public.creditos", "c", [], [])
        assert "c.id_portafolio IN (NULL)" in cond

    def test_allowlisted_table_with_ids(self):
        import uuid

        pid = uuid.uuid4()
        cond = build_tenant_scope_condition("public.creditos", "c", [pid], [])
        assert str(pid) in cond

    def test_table_outside_allowlist_rejected(self):
        with pytest.raises(ValueError, match="no está habilitada"):
            build_tenant_scope_condition("public.usuarios", "u", [], [])

    def test_table_outside_allowlist_rejected_even_for_valid_table_name(self):
        # `paises` es una tabla real del esquema pero no está en TENANT_SCOPED_TABLES:
        # reportes/segmentos no pueden apuntarle.
        with pytest.raises(ValueError):
            build_tenant_scope_condition("public.paises", "p", [], [])


class TestBuildTableAliasMap:
    def test_default_alias_is_table_name(self):
        alias_map = build_table_alias_map([{"name": "creditos"}])
        assert alias_map == {"creditos": "public.creditos"}

    def test_explicit_alias(self):
        alias_map = build_table_alias_map([{"name": "creditos", "alias": "c"}])
        assert alias_map == {"c": "public.creditos"}

    def test_duplicate_alias_rejected(self):
        with pytest.raises(ValueError, match="está repetido"):
            build_table_alias_map(
                [{"name": "creditos", "alias": "x"}, {"name": "deudores", "alias": "x"}]
            )

    def test_self_join_with_distinct_aliases_does_not_collide(self):
        """Dos entradas de la MISMA tabla con alias distintos no deben pisarse --
        antes, indexar por nombre de tabla colapsaba la segunda sobre la primera."""
        alias_map = build_table_alias_map(
            [
                {"name": "creditos", "alias": "c1"},
                {"name": "creditos", "alias": "c2"},
            ]
        )
        assert alias_map == {"c1": "public.creditos", "c2": "public.creditos"}


class TestResolveAlias:
    def test_single_table_no_ref_needed(self):
        tables = [{"name": "creditos"}]
        assert resolve_alias(tables, None) == "creditos"

    def test_multiple_tables_requires_ref(self):
        tables = [{"name": "creditos"}, {"name": "deudores"}]
        with pytest.raises(ValueError, match="varias tablas"):
            resolve_alias(tables, None)

    def test_resolve_by_alias(self):
        tables = [
            {"name": "creditos", "alias": "c"},
            {"name": "deudores", "alias": "d"},
        ]
        assert resolve_alias(tables, "d") == "d"

    def test_unknown_reference_rejected(self):
        tables = [{"name": "creditos"}]
        with pytest.raises(ValueError, match="tabla desconocida"):
            resolve_alias(tables, "does_not_exist")

    def test_self_join_resolves_by_explicit_alias(self):
        tables = [
            {"name": "creditos", "alias": "c1"},
            {"name": "creditos", "alias": "c2"},
        ]
        assert resolve_alias(tables, "c1") == "c1"
        assert resolve_alias(tables, "c2") == "c2"

    def test_self_join_bare_table_name_raises_clear_error(self):
        tables = [
            {"name": "creditos", "alias": "c1"},
            {"name": "creditos", "alias": "c2"},
        ]
        with pytest.raises(ValueError, match="self-join"):
            resolve_alias(tables, "creditos")


class TestResolveFullTableName:
    def test_single_table(self):
        tables = [{"name": "creditos"}]
        assert resolve_full_table_name(tables, None) == "public.creditos"

    def test_by_alias(self):
        tables = [{"name": "creditos", "alias": "c"}]
        assert resolve_full_table_name(tables, "c") == "public.creditos"

    def test_self_join_resolves_by_explicit_alias(self):
        tables = [
            {"name": "creditos", "alias": "c1"},
            {"name": "creditos", "alias": "c2"},
        ]
        assert resolve_full_table_name(tables, "c1") == "public.creditos"
        assert resolve_full_table_name(tables, "c2") == "public.creditos"

    def test_self_join_bare_table_name_raises_clear_error(self):
        tables = [
            {"name": "creditos", "alias": "c1"},
            {"name": "creditos", "alias": "c2"},
        ]
        with pytest.raises(ValueError, match="self-join"):
            resolve_full_table_name(tables, "creditos")


class TestIsAggregateMode:
    def test_explicit_aggregate_mode(self):
        assert is_aggregate_mode("aggregate", [], [], [], []) is True

    def test_detail_mode_without_group_by_is_not_aggregate(self):
        assert is_aggregate_mode("detail", [], [], [], []) is False

    def test_group_by_implies_aggregate(self):
        assert is_aggregate_mode("detail", [{"column": "x"}], [], [], []) is True


class TestNormalizeAggregateSpecs:
    def test_count_star(self):
        tables = [{"name": "creditos", "alias": "c"}]
        result = normalize_aggregate_specs(
            tables, [], [{"function": "count", "column": "*"}], [], []
        )
        assert result["aggregations"][0]["sql_expression"] == "COUNT(*)"

    def test_sum_column_on_table(self):
        tables = [{"name": "creditos", "alias": "c"}]
        result = normalize_aggregate_specs(
            tables, [], [{"function": "sum", "column": "monto"}], [], []
        )
        assert result["aggregations"][0]["sql_expression"] == "SUM(c.monto)"

    def test_star_with_non_count_function_rejected(self):
        tables = [{"name": "creditos", "alias": "c"}]
        with pytest.raises(ValueError, match="Solo COUNT"):
            normalize_aggregate_specs(
                tables, [], [{"function": "sum", "column": "*"}], [], []
            )

    def test_no_aggregations_rejected(self):
        tables = [{"name": "creditos", "alias": "c"}]
        with pytest.raises(ValueError, match="al menos una agregación"):
            normalize_aggregate_specs(tables, [], [], [], [])

    def test_having_references_unknown_metric_rejected(self):
        tables = [{"name": "creditos", "alias": "c"}]
        with pytest.raises(ValueError, match="del HAVING no existe"):
            normalize_aggregate_specs(
                tables,
                [],
                [{"function": "count", "column": "*"}],
                [{"metric": "nope", "op": ">", "value": 1}],
                [],
            )

    def test_order_by_must_reference_group_or_metric_alias(self):
        tables = [{"name": "creditos", "alias": "c"}]
        with pytest.raises(ValueError, match="campo de ordenamiento"):
            normalize_aggregate_specs(
                tables,
                [],
                [{"function": "count", "column": "*"}],
                [],
                [{"field": "not_an_alias", "direction": "asc"}],
            )

    def test_duplicated_output_alias_rejected(self):
        tables = [{"name": "creditos", "alias": "c"}]
        with pytest.raises(ValueError, match="Alias de salida repetido"):
            normalize_aggregate_specs(
                tables,
                [{"column": "estado", "alias": "same"}],
                [{"function": "count", "column": "*", "alias": "same"}],
                [],
                [],
            )


class TestSerializeValue:
    def test_decimal_becomes_string_not_float(self):
        """float(Decimal("0.1")) pierde precision -- str no."""
        assert serialize_value(Decimal("12345.6789012345")) == "12345.6789012345"

    def test_passthrough_for_other_types(self):
        assert serialize_value("texto") == "texto"
        assert serialize_value(42) == 42
        assert serialize_value(None) is None
