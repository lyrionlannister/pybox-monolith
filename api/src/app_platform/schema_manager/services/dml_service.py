"""DML dinámico administrativo: queries genéricas con joins/filtros/agregaciones."""

import json
import uuid
from typing import Any, Sequence

from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.schema_manager.constants.query_constants import (
    INVALID_QUERY_STATUS_CODE,
    JOIN_SQL_KEYWORDS,
    QUERY_FAILURE_STATUS_CODE,
    VALID_JOIN_TYPES,
)
from app_platform.schema_manager.utils.query_error_utils import describe_db_error
from app_platform.schema_manager.utils.query_utils import (
    build_select_parts,
    build_sql_condition,
    build_table_alias_map,
    build_tenant_scope_condition,
    build_where_clauses,
    decrypt_sensitive_value,
    encrypted_group_outputs,
    encrypted_output_columns,
    is_aggregate_mode,
    normalize_aggregate_specs,
    resolve_alias,
    resolve_full_table_name,
    sanitize_identifier,
    sanitize_table_name,
    serialize_value,
)
from core.config.logger import logger


class DmlService:
    """Mismo motivo que DdlService (ver ese docstring) para ejecutar SQL directo:
    DML dinámico sobre tablas/columnas arbitrarias, sin entidad de dominio fija."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute_query(
        self,
        tables: list[dict[str, Any]],
        joins: list[dict[str, Any]] | None = None,
        limit: int | None = None,
        query_mode: str = "detail",
        group_by: list[dict[str, Any]] | None = None,
        aggregations: list[dict[str, Any]] | None = None,
        having: list[dict[str, Any]] | None = None,
        order_by: list[dict[str, Any]] | None = None,
        portfolio_ids: list[uuid.UUID] | None = None,
        organization_ids: list[uuid.UUID] | None = None,
        decrypt_sensitive: bool = False,
    ) -> dict[str, Any]:
        """`portfolio_ids`/`organization_ids` acotan el resultado a esos tenants
        (usado por segments/reports). Si ambos quedan en None no se aplica ningún
        scoping: solo debe pasar así cuando el caller ya está gateado a admin
        global (ver database_controller).

        `decrypt_sensitive` devuelve en claro las columnas de ENCRYPTED_COLUMNS
        (p. ej. el documento del deudor). Es del caller: solo debe activarlo si el
        usuario tiene permiso sobre ese dato; por defecto salen cifradas, como
        están en la base.

        Nunca lanza: ante un fallo devuelve `success=False` con `error` (mensaje
        apto para mostrar al usuario, sin SQL) y `status_code` (422 si se corrige
        editando la consulta, 500 si es un fallo del servidor)."""
        try:
            joins = joins or []
            group_by = group_by or []
            aggregations = aggregations or []
            having = having or []
            order_by = order_by or []

            if not tables:
                raise ValueError("Se requiere al menos una tabla.")

            aggregate = is_aggregate_mode(
                query_mode, group_by, aggregations, having, order_by
            )

            if not aggregate and len(tables) == 1 and not joins:
                return await self._execute_single_table(
                    tables[0], limit, portfolio_ids, organization_ids, decrypt_sensitive
                )
            if aggregate:
                return await self._execute_aggregate(
                    tables,
                    joins,
                    group_by,
                    aggregations,
                    having,
                    order_by,
                    limit,
                    portfolio_ids,
                    organization_ids,
                    decrypt_sensitive,
                )
            return await self._execute_join(
                tables, joins, limit, portfolio_ids, organization_ids, decrypt_sensitive
            )

        # UnicodeDecodeError es subclase de ValueError: va antes para no reportarlo
        # como una configuración inválida (lo dispara `serialize_value` con una
        # columna binaria).
        except UnicodeDecodeError as e:
            return self._failure(
                "La consulta devolvió una columna binaria que no se puede "
                "mostrar como texto.",
                QUERY_FAILURE_STATUS_CODE,
                e,
            )
        # Los ValueError son los de validación de este módulo (identificadores,
        # operadores, tablas fuera del allowlist, joins faltantes): su mensaje ya
        # es el que corresponde.
        except ValueError as e:
            return self._failure(str(e), INVALID_QUERY_STATUS_CODE, e)
        except KeyError as e:
            field = e.args[0] if e.args else "desconocido"
            return self._failure(
                f"La configuración de la consulta está incompleta: falta el "
                f"campo '{field}'.",
                INVALID_QUERY_STATUS_CODE,
                e,
            )
        except DBAPIError as e:
            message, status_code = describe_db_error(e)
            return self._failure(message, status_code, e)
        except SQLAlchemyError as e:
            return self._failure(
                "Error interno al consultar la base de datos.",
                QUERY_FAILURE_STATUS_CODE,
                e,
            )
        except Exception as e:
            return self._failure(
                "Error inesperado al ejecutar la consulta.",
                QUERY_FAILURE_STATUS_CODE,
                e,
            )

    @staticmethod
    def _failure(message: str, status_code: int, exc: Exception) -> dict[str, Any]:
        """El detalle completo (SQL incluido) queda solo en el log; al caller solo
        llega `message`. Los rechazos por configuración inválida no son un bug:
        sin traceback."""
        if status_code >= QUERY_FAILURE_STATUS_CODE:
            logger.error("[DmlService] %s", message, exc_info=exc)
        else:
            logger.warning(
                "[DmlService] Consulta rechazada (%s): %s", type(exc).__name__, exc
            )
        return {
            "success": False,
            "rows": 0,
            "columns": [],
            "data": "[]",
            "error": message,
            "status_code": status_code,
        }

    async def _run_query(self, query: str, decrypt_columns: set[str]) -> dict[str, Any]:
        result = await self._session.execute(text(query))
        rows = result.fetchall()
        columns = list(result.keys())
        data = self._rows_to_dicts(columns, rows, decrypt_columns)
        return {
            "success": True,
            "rows": len(data),
            "columns": columns,
            "data": json.dumps(data),
            "error": "",
        }

    @staticmethod
    def _rows_to_dicts(
        columns: list[str], rows: Sequence[Sequence[Any]], decrypt_columns: set[str]
    ) -> list[dict[str, Any]]:
        """Un valor cifrado que no se puede descifrar (token corrupto o de otra
        clave) sale como None en vez de tumbar toda la consulta, igual que hace
        la campaña con el documento del deudor; se avisa una sola vez por
        consulta, no por fila."""
        undecryptable = 0
        data: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {}
            for col, val in zip(columns, row):
                if col in decrypt_columns:
                    try:
                        val = decrypt_sensitive_value(val)
                    except ValueError, InvalidTag:
                        undecryptable += 1
                        val = None
                item[col] = serialize_value(val)
            data.append(item)
        if undecryptable:
            logger.warning(
                "[DmlService] %d valores cifrados no se pudieron descifrar",
                undecryptable,
            )
        return data

    async def _execute_single_table(
        self,
        table: dict[str, Any],
        limit: int | None,
        portfolio_ids: list[uuid.UUID] | None,
        organization_ids: list[uuid.UUID] | None,
        decrypt_sensitive: bool,
    ) -> dict[str, Any]:
        schema, table_name = sanitize_table_name(table["name"])
        alias = sanitize_identifier(
            table.get("alias") or table_name, label="el alias de la tabla"
        )
        decrypt_columns = (
            encrypted_output_columns([table], prefixed=False)
            if decrypt_sensitive
            else set()
        )
        select_parts = build_select_parts(table, alias)
        query = (
            f"SELECT {', '.join(select_parts)} FROM {schema}.{table_name} AS {alias}"
        )

        where_clauses = []
        where = build_where_clauses(
            table.get("filters", []), alias, f"{schema}.{table_name}"
        )
        if where:
            where_clauses.append(where)
        if portfolio_ids is not None or organization_ids is not None:
            where_clauses.append(
                build_tenant_scope_condition(
                    f"{schema}.{table_name}",
                    alias,
                    portfolio_ids or [],
                    organization_ids or [],
                )
            )
        if where_clauses:
            query += f" WHERE {' AND '.join(where_clauses)}"
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"

        return await self._run_query(query, decrypt_columns)

    async def _execute_join(
        self,
        tables: list[dict[str, Any]],
        joins: list[dict[str, Any]],
        limit: int | None,
        portfolio_ids: list[uuid.UUID] | None,
        organization_ids: list[uuid.UUID] | None,
        decrypt_sensitive: bool,
    ) -> dict[str, Any]:
        if len(tables) > 1 and not joins:
            raise ValueError(
                "Se requieren uniones (joins) cuando hay más de una tabla."
            )

        # Valida que los alias sean únicos (soporta self-join); no hace falta
        # indexar en el dict acá, cada tabla ya trae su propio alias/nombre.
        build_table_alias_map(tables)
        decrypt_columns = (
            encrypted_output_columns(tables, prefixed=True)
            if decrypt_sensitive
            else set()
        )

        select_parts: list[str] = []
        for table in tables:
            _, table_name = sanitize_table_name(table["name"])
            alias = sanitize_identifier(
                table.get("alias") or table_name, label="el alias de la tabla"
            )
            select_parts.extend(build_select_parts(table, alias, prefixed_alias=True))

        first_schema, first_table = sanitize_table_name(tables[0]["name"])
        first_alias = sanitize_identifier(
            tables[0].get("alias") or first_table, label="el alias de la tabla"
        )
        query = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {first_schema}.{first_table} AS {first_alias}"
        )

        for join in joins:
            right_schema, right_table = sanitize_table_name(
                resolve_full_table_name(tables, join["right"])
            )
            left_alias = resolve_alias(tables, join["left"])
            right_alias = resolve_alias(tables, join["right"])
            left_on = sanitize_identifier(
                join["left_on"], label="la columna izquierda del join"
            )
            right_on = sanitize_identifier(
                join["right_on"], label="la columna derecha del join"
            )
            join_type = str(join.get("how", "inner") or "inner").strip().lower()
            if join_type not in VALID_JOIN_TYPES:
                raise ValueError(
                    f"Tipo de unión inválido: '{join_type}'. Usa inner, left, "
                    f"right o full."
                )
            query += (
                f" {JOIN_SQL_KEYWORDS[join_type]} {right_schema}.{right_table} "
                f"AS {right_alias}"
            )
            query += f" ON {left_alias}.{left_on} = {right_alias}.{right_on}"

        where_parts: list[str] = []
        for table in tables:
            schema, table_name = sanitize_table_name(table["name"])
            alias = sanitize_identifier(
                table.get("alias") or table_name, label="el alias de la tabla"
            )
            w = build_where_clauses(
                table.get("filters", []), alias, f"{schema}.{table_name}"
            )
            if w:
                where_parts.append(w)
            if portfolio_ids is not None or organization_ids is not None:
                where_parts.append(
                    build_tenant_scope_condition(
                        f"{schema}.{table_name}",
                        alias,
                        portfolio_ids or [],
                        organization_ids or [],
                    )
                )
        if where_parts:
            query += f" WHERE {' AND '.join(where_parts)}"
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"

        logger.debug("[DmlService] SQL join: %s", query)
        return await self._run_query(query, decrypt_columns)

    async def _execute_aggregate(
        self,
        tables: list[dict[str, Any]],
        joins: list[dict[str, Any]],
        group_by: list[dict[str, Any]],
        aggregations: list[dict[str, Any]],
        having: list[dict[str, Any]],
        order_by: list[dict[str, Any]],
        limit: int | None,
        portfolio_ids: list[uuid.UUID] | None,
        organization_ids: list[uuid.UUID] | None,
        decrypt_sensitive: bool,
    ) -> dict[str, Any]:
        if len(tables) > 1 and not joins:
            raise ValueError(
                "Se requieren uniones (joins) cuando hay más de una tabla."
            )

        normalized = normalize_aggregate_specs(
            tables, group_by, aggregations, having, order_by
        )
        alias_map = build_table_alias_map(tables)
        decrypt_columns = (
            encrypted_group_outputs(alias_map, normalized["group_by"])
            if decrypt_sensitive
            else set()
        )

        first_schema, first_table = sanitize_table_name(tables[0]["name"])
        first_alias = sanitize_identifier(
            tables[0].get("alias") or first_table, label="el alias de la tabla"
        )

        select_parts = [
            f"{g['sql_expression']} AS {g['output_alias']}"
            for g in normalized["group_by"]
        ] + [
            f"{m['sql_expression']} AS {m['metric_alias']}"
            for m in normalized["aggregations"]
        ]
        query = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {first_schema}.{first_table} AS {first_alias}"
        )

        for join in joins:
            right_schema, right_table = sanitize_table_name(
                resolve_full_table_name(tables, join["right"])
            )
            left_alias = resolve_alias(tables, join["left"])
            right_alias = resolve_alias(tables, join["right"])
            left_on = sanitize_identifier(
                join["left_on"], label="la columna izquierda del join"
            )
            right_on = sanitize_identifier(
                join["right_on"], label="la columna derecha del join"
            )
            join_type = str(join.get("how", "inner") or "inner").strip().lower()
            if join_type not in VALID_JOIN_TYPES:
                raise ValueError(
                    f"Tipo de unión inválido: '{join_type}'. Usa inner, left, "
                    f"right o full."
                )
            query += (
                f" {JOIN_SQL_KEYWORDS[join_type]} {right_schema}.{right_table} "
                f"AS {right_alias}"
            )
            query += f" ON {left_alias}.{left_on} = {right_alias}.{right_on}"

        where_parts2: list[str] = []
        for table in tables:
            schema, table_name = sanitize_table_name(table["name"])
            alias = sanitize_identifier(
                table.get("alias") or table_name, label="el alias de la tabla"
            )
            w = build_where_clauses(
                table.get("filters", []), alias, f"{schema}.{table_name}"
            )
            if w:
                where_parts2.append(w)
            if portfolio_ids is not None or organization_ids is not None:
                where_parts2.append(
                    build_tenant_scope_condition(
                        f"{schema}.{table_name}",
                        alias,
                        portfolio_ids or [],
                        organization_ids or [],
                    )
                )
        if where_parts2:
            query += f" WHERE {' AND '.join(where_parts2)}"

        if normalized["group_by"]:
            group_exprs = ", ".join(g["sql_expression"] for g in normalized["group_by"])
            query += f" GROUP BY {group_exprs}"

        if normalized["having"]:
            having_clauses = [
                build_sql_condition(
                    normalized["metric_sql_by_alias"][h["metric"]], h["op"], h["value"]
                )
                for h in normalized["having"]
            ]
            query += f" HAVING {' AND '.join(having_clauses)}"

        if normalized["order_by"]:
            order_parts = [
                f"{o['field']} {o['direction'].upper()}" for o in normalized["order_by"]
            ]
            query += f" ORDER BY {', '.join(order_parts)}"

        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"

        logger.debug("[DmlService] SQL aggregate: %s", query)
        return await self._run_query(query, decrypt_columns)
