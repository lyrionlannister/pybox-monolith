"""Construcción de SQL dinámico: literales, columnas cifradas y agregaciones."""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app_platform.schema_manager.constants.query_constants import (
    ENCRYPTED_COLUMNS,
    HASHED_FILTER_COLUMNS,
    HASHED_FILTER_OPERATORS,
    IDENTIFIER_RE,
    OPERATOR_ALIASES,
    TENANT_SCOPED_TABLES,
    VALID_AGG_FUNCTIONS,
    VALID_HAVING_OPERATORS,
    VALID_WHERE_OPERATORS,
)
from app_platform.schema_manager.utils.relative_dates import resolve_filter_value
from core.security.services.encrypt_service import encrypt_service


def serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        # str, no float: esto sale del resultado del query builder dinamico
        # (DmlService) tal cual a la respuesta JSON -- float perderia precision.
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, UUID):
        return str(value)
    return value


def encrypted_output_columns(
    tables: list[dict[str, Any]], *, prefixed: bool
) -> set[str]:
    """Nombres, en el resultado, de las columnas que vienen de ENCRYPTED_COLUMNS.
    `prefixed` es el modo join (`alias_columna`); con `alias.*` o modo tabla única
    el nombre es el de la columna. Incluir de más es inofensivo:
    `decrypt_sensitive_value` solo toca tokens."""
    outputs: set[str] = set()
    for table in tables:
        schema, table_name = sanitize_table_name(table["name"])
        encrypted = ENCRYPTED_COLUMNS.get(f"{schema}.{table_name}")
        if not encrypted:
            continue
        alias = table.get("alias") or table_name
        for column in encrypted:
            outputs.add(column)
            if prefixed:
                outputs.add(f"{alias}_{column}")
    return outputs


def encrypted_group_outputs(
    alias_map: dict[str, str], group_by: list[dict[str, Any]]
) -> set[str]:
    """Alias de salida de las columnas de agrupación (ya normalizadas) que son
    cifradas."""
    encrypted_by_alias = {
        alias: ENCRYPTED_COLUMNS.get(full_name, set())
        for full_name, alias in alias_map.items()
    }
    return {
        g["output_alias"]
        for g in group_by
        if g["column"] in encrypted_by_alias.get(g["table_alias"], set())
    }


def decrypt_sensitive_value(value: Any) -> Any:
    """Descifra un token de EncryptService; cualquier otro valor (None, texto
    plano de otra tabla) pasa igual. Un token inválido o de otra clave lanza
    ValueError / InvalidTag."""
    if isinstance(value, str) and value.startswith(f"{encrypt_service.VERSION}:"):
        return encrypt_service.decrypt_to_str(value)
    return value


def parse_json_if_string(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except TypeError, ValueError:
            return value
    return value


def parse_json_list_if_string(value: Any) -> Any:
    """Para valores de filtro WHERE: solo desempaqueta strings JSON que sean listas
    (`'["CO","MX"]'` para IN/BETWEEN). Los escalares se quedan como texto, porque
    `json.loads("6168564922")` daría un int y `varchar = 6168564922` no existe en
    Postgres; un literal `'6168564922'` sí se castea solo a la columna."""
    parsed = parse_json_if_string(value)
    return parsed if isinstance(parsed, list) else value


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return f"'{value.isoformat()}'"
    if isinstance(value, Decimal):
        return str(float(value))
    if isinstance(value, bytes):
        escaped = value.decode("utf-8", errors="ignore").replace("'", "''")
        return f"'{escaped}'"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def sanitize_identifier(value: str | None, *, label: str) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        raise ValueError(f"Falta indicar {label}.")
    if not IDENTIFIER_RE.match(identifier):
        raise ValueError(
            f"Valor inválido para {label}: '{value}'. "
            "Solo se permiten letras, números y guion bajo (_), y no puede "
            "empezar por un número."
        )
    return identifier


def sanitize_table_name(full_name: str) -> tuple[str, str]:
    raw = str(full_name or "")
    if "." not in raw:
        return "public", sanitize_identifier(raw, label="la tabla")
    schema, table = raw.split(".", 1)
    return sanitize_identifier(schema, label="el esquema"), sanitize_identifier(
        table, label="la tabla"
    )


def normalize_operator(op: str) -> str:
    normalized = str(op or "=").strip().lower().replace(" ", "_")
    return OPERATOR_ALIASES.get(normalized, normalized)


def ensure_operator_allowed(op: str, *, in_having: bool = False) -> str:
    normalized = normalize_operator(op)
    allowed = VALID_HAVING_OPERATORS if in_having else VALID_WHERE_OPERATORS
    if normalized not in allowed:
        raise ValueError(f"Operador inválido: '{op}'.")
    return normalized


def normalize_sort_direction(direction: str) -> str:
    normalized = str(direction or "asc").strip().lower()
    if normalized not in {"asc", "desc"}:
        raise ValueError(
            f"Dirección de ordenamiento inválida: '{direction}' (usa asc o desc)."
        )
    return normalized


def normalize_aggregate_function(function_name: str | None) -> str:
    normalized = str(function_name or "").strip().lower()
    if normalized not in VALID_AGG_FUNCTIONS:
        raise ValueError(
            f"Función de agregación no soportada: '{function_name}'. Usa "
            "count, sum, avg, min o max."
        )
    return normalized


def build_sql_condition(expression: str, operator: str, value: Any) -> str:
    if operator == "is_null":
        return f"{expression} IS NULL"
    if operator == "is_not_null":
        return f"{expression} IS NOT NULL"
    if operator == "in":
        values = value if isinstance(value, list) else [value]
        if not values:
            raise ValueError("El operador IN requiere al menos un valor.")
        return f"{expression} IN ({', '.join(sql_literal(v) for v in values)})"
    if operator == "not_in":
        values = value if isinstance(value, list) else [value]
        if not values:
            raise ValueError("El operador NOT IN requiere al menos un valor.")
        return f"{expression} NOT IN ({', '.join(sql_literal(v) for v in values)})"
    if operator == "between":
        values = value if isinstance(value, list) else []
        if len(values) != 2:
            raise ValueError("El operador BETWEEN requiere exactamente dos valores.")
        return (
            f"{expression} BETWEEN {sql_literal(values[0])} "
            f"AND {sql_literal(values[1])}"
        )
    if operator == "like":
        return f"{expression} LIKE {sql_literal(value)}"
    if operator == "ilike":
        return f"{expression} ILIKE {sql_literal(value)}"
    sql_op = "<>" if operator == "!=" else operator
    return f"{expression} {sql_op} {sql_literal(value)}"


def build_tenant_scope_condition(
    full_table_name: str,
    alias: str,
    portfolio_ids: list[UUID],
    organization_ids: list[UUID],
) -> str:
    """Acota una tabla de reportes/segmentos a los portafolios/organizaciones permitidos
    del caller. Rechaza cualquier tabla que no esté en TENANT_SCOPED_TABLES: reportes y
    segmentos solo pueden apuntar a las tablas explícitamente habilitadas para eso."""
    template = TENANT_SCOPED_TABLES.get(full_table_name)
    if template is None:
        raise ValueError(
            f"La tabla '{full_table_name}' no está habilitada para reportes/segmentos."
        )
    portfolio_list = ", ".join(sql_literal(pid) for pid in portfolio_ids) or "NULL"
    organization_list = (
        ", ".join(sql_literal(oid) for oid in organization_ids) or "NULL"
    )
    return template.format(
        alias=alias, portfolio_ids=portfolio_list, organization_ids=organization_list
    )


def _hash_filter_value(column: str, op: str, value: Any) -> Any:
    if op in {"is_null", "is_not_null"}:
        return value
    if op not in HASHED_FILTER_OPERATORS:
        raise ValueError(
            f"La columna '{column}' solo se puede filtrar por igualdad o "
            "lista de valores."
        )
    values = value if isinstance(value, list) else [value]
    if not values or any(v is None or not str(v).strip() for v in values):
        raise ValueError(f"El filtro de '{column}' requiere un valor.")
    hashed = [encrypt_service.hash_document(str(v).strip()) for v in values]
    return hashed if isinstance(value, list) else hashed[0]


def build_where_clauses(
    filters: list[dict[str, Any]], alias: str, full_table_name: str | None = None
) -> str:
    """`full_table_name` (`schema.tabla`) permite reescribir las columnas cifradas de
    HASHED_FILTER_COLUMNS a su columna hash; sin él todos los filtros van tal cual."""
    if not filters:
        return ""
    hashed_columns = HASHED_FILTER_COLUMNS.get(full_table_name or "", {})
    clauses = []
    for f in filters:
        column = sanitize_identifier(f["column"], label="la columna del filtro")
        op = ensure_operator_allowed(f.get("op", "="), in_having=False)
        value = resolve_filter_value(parse_json_list_if_string(f.get("value")))
        if column in hashed_columns:
            value = _hash_filter_value(column, op, value)
            column = hashed_columns[column]
        clauses.append(build_sql_condition(f"{alias}.{column}", op, value))
    return " AND ".join(clauses)


def build_table_alias_map(tables: list[dict[str, Any]]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    alias_set: set[str] = set()
    for table in tables:
        schema, table_name = sanitize_table_name(table["name"])
        full_name = f"{schema}.{table_name}"
        alias = table.get("alias") or table_name
        alias = sanitize_identifier(alias, label=f"el alias de la tabla {full_name}")
        if alias in alias_set:
            raise ValueError(
                f"El alias de tabla '{alias}' está repetido: cada tabla debe "
                "tener un alias distinto."
            )
        alias_set.add(alias)
        alias_map[full_name] = alias
    return alias_map


def resolve_alias(tables: list[dict[str, Any]], table_ref: str | None) -> str:
    alias_map = build_table_alias_map(tables)
    if not table_ref:
        if len(alias_map) == 1:
            return next(iter(alias_map.values()))
        raise ValueError(
            "Cuando hay varias tablas hay que indicar a cuál se refiere cada campo."
        )
    ref = str(table_ref).strip()
    if ref in alias_map.values():
        return sanitize_identifier(ref, label="el alias de la tabla")
    schema, table = sanitize_table_name(ref)
    full_name = f"{schema}.{table}"
    if full_name not in alias_map:
        raise ValueError(f"Referencia a una tabla desconocida: '{table_ref}'.")
    return alias_map[full_name]


def resolve_full_table_name(tables: list[dict[str, Any]], table_ref: str | None) -> str:
    alias_map = build_table_alias_map(tables)
    if not table_ref:
        if len(alias_map) == 1:
            return next(iter(alias_map.keys()))
        raise ValueError(
            "Cuando hay varias tablas hay que indicar a cuál se refiere cada campo."
        )
    ref = str(table_ref).strip()
    if ref in alias_map:
        return ref
    for full_name, alias in alias_map.items():
        if alias == ref:
            return full_name
    schema, table = sanitize_table_name(ref)
    full_name = f"{schema}.{table}"
    if full_name not in alias_map:
        raise ValueError(f"Referencia a una tabla desconocida: '{table_ref}'.")
    return full_name


def build_select_parts(
    table: dict[str, Any], alias: str, *, prefixed_alias: bool = False
) -> list[str]:
    columns = table.get("columns") or []
    if not columns:
        return [f"{alias}.*"]
    parts = []
    for raw_col in columns:
        col = sanitize_identifier(raw_col, label="la columna")
        parts.append(
            f"{alias}.{col} AS {alias}_{col}" if prefixed_alias else f"{alias}.{col}"
        )
    return parts


def default_group_alias(alias_value: str | None, column: str) -> str:
    if alias_value:
        return sanitize_identifier(alias_value, label="el alias de agrupación")
    return sanitize_identifier(column, label="la columna de agrupación")


def default_aggregation_alias(function_name: str, column: str, table_alias: str) -> str:
    fn = normalize_aggregate_function(function_name)
    if column == "*":
        return f"{fn}_all"
    alias_part = sanitize_identifier(table_alias, label="el alias de la tabla")
    column_part = sanitize_identifier(column, label="la columna de la agregación")
    return f"{fn}_{alias_part}_{column_part}"


def normalize_aggregate_specs(
    tables: list[dict[str, Any]],
    group_by: list[dict[str, Any]],
    aggregations: list[dict[str, Any]],
    having: list[dict[str, Any]],
    order_by: list[dict[str, Any]],
) -> dict[str, Any]:
    alias_map = build_table_alias_map(tables)
    output_aliases: set[str] = set()
    group_aliases: set[str] = set()
    metric_aliases: set[str] = set()
    metric_sql_by_alias: dict[str, str] = {}

    normalized_group_by: list[dict[str, Any]] = []
    for group in group_by:
        table_alias = resolve_alias(tables, group.get("table"))
        column = sanitize_identifier(
            group.get("column"), label="la columna de agrupación"
        )
        output_alias = default_group_alias(group.get("alias"), column)
        if output_alias in output_aliases:
            raise ValueError(f"Alias de salida repetido: '{output_alias}'.")
        output_aliases.add(output_alias)
        group_aliases.add(output_alias)
        normalized_group_by.append(
            {
                "table_alias": table_alias,
                "column": column,
                "output_alias": output_alias,
                "sql_expression": f"{table_alias}.{column}",
            }
        )

    if not aggregations:
        raise ValueError("El modo agregación requiere al menos una agregación.")

    default_single_alias = (
        next(iter(alias_map.values())) if len(alias_map) == 1 else None
    )

    normalized_aggregations: list[dict[str, Any]] = []
    for metric in aggregations:
        fn = normalize_aggregate_function(metric.get("function"))
        raw_col = str(metric.get("column") or "").strip()
        if not raw_col:
            raise ValueError("Falta indicar la columna de la agregación.")

        if raw_col == "*":
            if fn != "count":
                raise ValueError("Solo COUNT admite la columna '*'.")
            table_alias = (
                resolve_alias(tables, metric.get("table"))
                if metric.get("table")
                else default_single_alias
            )
            sql_expression = "COUNT(*)"
        else:
            table_alias = resolve_alias(tables, metric.get("table"))
            col = sanitize_identifier(raw_col, label="la columna de la agregación")
            sql_expression = f"{fn.upper()}({table_alias}.{col})"

        metric_alias = metric.get("alias") or default_aggregation_alias(
            fn, raw_col, table_alias or "all"
        )
        metric_alias = sanitize_identifier(
            metric_alias, label="el alias de la agregación"
        )
        if metric_alias in output_aliases:
            raise ValueError(f"Alias de salida repetido: '{metric_alias}'.")
        output_aliases.add(metric_alias)
        metric_aliases.add(metric_alias)
        metric_sql_by_alias[metric_alias] = sql_expression
        normalized_aggregations.append(
            {
                "function": fn,
                "table_alias": table_alias,
                "column": raw_col,
                "metric_alias": metric_alias,
                "sql_expression": sql_expression,
            }
        )

    normalized_having: list[dict[str, Any]] = []
    for condition in having:
        metric_alias = sanitize_identifier(
            condition.get("metric"), label="la métrica del HAVING"
        )
        if metric_alias not in metric_aliases:
            raise ValueError(
                f"La métrica '{metric_alias}' del HAVING no existe entre las "
                "agregaciones."
            )
        op = ensure_operator_allowed(condition.get("op", "="), in_having=True)
        value = parse_json_if_string(condition.get("value"))
        normalized_having.append({"metric": metric_alias, "op": op, "value": value})

    sortable_fields = group_aliases | metric_aliases
    normalized_order_by: list[dict[str, Any]] = []
    for ordering in order_by:
        field = sanitize_identifier(
            ordering.get("field"), label="el campo de ordenamiento"
        )
        if field not in sortable_fields:
            raise ValueError(
                f"El campo de ordenamiento '{field}' debe ser un alias de "
                "agrupación o de agregación."
            )
        direction = normalize_sort_direction(ordering.get("direction", "asc"))
        normalized_order_by.append({"field": field, "direction": direction})

    return {
        "group_by": normalized_group_by,
        "aggregations": normalized_aggregations,
        "having": normalized_having,
        "order_by": normalized_order_by,
        "metric_sql_by_alias": metric_sql_by_alias,
    }


def is_aggregate_mode(
    query_mode: str,
    group_by: list[dict[str, Any]],
    aggregations: list[dict[str, Any]],
    having: list[dict[str, Any]],
    order_by: list[dict[str, Any]],
) -> bool:
    if str(query_mode or "").strip().lower() == "aggregate":
        return True
    return bool(group_by or aggregations or having or order_by)
