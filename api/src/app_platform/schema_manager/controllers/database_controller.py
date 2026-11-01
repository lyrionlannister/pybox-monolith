"""Endpoints admin de DDL/DML dinámico sobre bases de datos gestionadas."""

from fastapi import HTTPException, status

from app_platform.schema_manager.constants.query_constants import (
    TENANT_SCOPED_TABLES,
)
from app_platform.schema_manager.dependencies import (
    DdlServiceDep,
    DmlServiceDep,
    InspectorServiceDep,
)
from app_platform.schema_manager.schemas.database_schemas import (
    AlterTableRequest,
    CreateDatabaseRequest,
    CreateTableRequest,
    DynamicQueryRequest,
    DynamicQueryResponse,
    FieldInfo,
    OperationResponse,
)
from app_platform.schema_manager.utils.query_utils import sanitize_table_name
from core.config.api_router import APIRouter
from core.config.database_config import db_config
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import (
    require_global_admin,
    require_org_or_global,
)

router = APIRouter(prefix="/databases", tags=["Bases de datos"])


# ------------------------------------------------------------------
# Inspección (global only)
#
# Estos endpoints exponen introspección y consulta libre sobre cualquier
# esquema/tabla de la base de datos sin scoping por organización/portafolio,
# por lo que se restringen a administradores globales. Los consumidores
# internos que sí necesitan datos acotados a un tenant (segments, reports)
# llaman a DmlService directamente en proceso, aplicando su propio chequeo
# de portfolio/organización antes — no pasan por este router HTTP.
# ------------------------------------------------------------------


@router.get("/schemas", response_model=list[str], summary="Listar esquemas")
async def list_schemas(
    session: CurrentSession, service: InspectorServiceDep
) -> list[str]:
    require_global_admin(session)
    return await service.get_schemas()


@router.get(
    "/schemas/{schema_name}/tables",
    response_model=list[str],
    summary="Listar tablas de un esquema",
)
async def list_tables(
    schema_name: str,
    session: CurrentSession,
    service: InspectorServiceDep,
) -> list[str]:
    require_global_admin(session)
    return await service.get_tables(schema_name)


@router.get(
    "/schemas/{schema_name}/tables/{table_name}/fields",
    response_model=list[FieldInfo],
    summary="Listar campos de una tabla",
)
async def list_table_fields(
    schema_name: str,
    table_name: str,
    session: CurrentSession,
    service: InspectorServiceDep,
) -> list[FieldInfo]:
    # Excepción a la regla "global only" de este router: el query-builder de
    # segmentos/reportes necesita listar los campos de una tabla para construir
    # filtros. Solo expone nombres/tipos de columnas (no datos), por lo que se
    # permite a cualquier usuario con acceso a una organización -- pero acotado al
    # mismo catálogo que ya usa DmlService (TENANT_SCOPED_TABLES), no cualquier
    # tabla física de la base: si no, cualquier usuario con organización podría
    # inspeccionar el esquema de tablas fuera del alcance de reportes/segmentos
    # (ej. usuarios, facturación). Un admin global sigue viendo cualquier tabla:
    # este mismo router lo deja crear/alterar tablas arbitrarias más abajo, y
    # necesita poder inspeccionar el resultado.
    require_org_or_global(session)
    schema, table = sanitize_table_name(f"{schema_name}.{table_name}")
    if not session.is_global and f"{schema}.{table}" not in TENANT_SCOPED_TABLES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tabla no encontrada")
    raw = await service.get_table_fields(schema, table)
    return [
        FieldInfo(
            name=col["name"], type=str(col["type"]), enum_values=col["enum_values"]
        )
        for col in raw
    ]


# ------------------------------------------------------------------
# Consulta dinámica (global only, ver nota arriba)
# ------------------------------------------------------------------


@router.post(
    "/query", response_model=DynamicQueryResponse, summary="Ejecutar consulta dinámica"
)
async def execute_query(
    body: DynamicQueryRequest,
    session: CurrentSession,
    service: DmlServiceDep,
) -> DynamicQueryResponse:
    require_global_admin(session)
    result = await service.execute_query(
        tables=[t.model_dump() for t in body.tables],
        joins=[j.model_dump() for j in body.joins],
        limit=body.limit,
        query_mode=body.query_mode,
        group_by=[g.model_dump() for g in body.group_by],
        aggregations=[a.model_dump() for a in body.aggregations],
        having=[h.model_dump() for h in body.having],
        order_by=[o.model_dump() for o in body.order_by],
    )
    return DynamicQueryResponse(**result)


# ------------------------------------------------------------------
# DDL (solo administradores globales)
#
# Restringido a require_global_admin (no require_global): son operaciones
# destructivas/estructurales, a diferencia de la inspección de solo lectura
# de arriba. `database_name` no se pide al cliente: el monolito opera sobre
# una única base de datos física (db_config.database_name), a diferencia de
# pybox donde cada dominio tenía su propia BD.
# ------------------------------------------------------------------


@router.post(
    "/",
    response_model=OperationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear base de datos",
)
async def create_database(
    body: CreateDatabaseRequest,
    session: CurrentSession,
    service: DdlServiceDep,
) -> OperationResponse:
    require_global_admin(session)
    result = await service.create_database(body.database_name)
    return OperationResponse(**result)


@router.post(
    "/schemas/{schema_name}/tables",
    response_model=OperationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tabla",
)
async def create_table(
    schema_name: str,
    body: CreateTableRequest,
    session: CurrentSession,
    service: DdlServiceDep,
) -> OperationResponse:
    require_global_admin(session)
    result = await service.create_table(
        db_config.database_name, schema_name, body.table_name, body.columns
    )
    if not result["success"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result["message"])
    return OperationResponse(**result)


@router.patch(
    "/schemas/{schema_name}/tables/{table_name}",
    response_model=OperationResponse,
    summary="Alterar tabla",
)
async def alter_table(
    schema_name: str,
    table_name: str,
    body: AlterTableRequest,
    session: CurrentSession,
    service: DdlServiceDep,
) -> OperationResponse:
    require_global_admin(session)
    result = await service.alter_table(
        db_config.database_name,
        schema_name,
        table_name,
        body.action,
        body.column,
        body.column_name,
        body.new_column_name,
    )
    return OperationResponse(**result)
