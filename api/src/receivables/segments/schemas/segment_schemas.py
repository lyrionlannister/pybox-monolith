"""Schemas de segmentos de cartera: definición, ejecución y respuesta."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app_platform.schema_manager.schemas.database_schemas import (
    AggregationSpec,
    GroupByField,
    HavingCondition,
    JoinCondition,
    OrderBySpec,
    TableQuery,
)
from core.base.schema_base import BaseSchema


class SegmentQueryConfig(BaseSchema):
    tables: list[TableQuery] = Field(
        description="Tablas consultadas y sus columnas/filtros"
    )
    joins: list[JoinCondition] = Field(
        default_factory=list, description="Condiciones de join entre tablas"
    )
    query_mode: str = Field(
        default="detail", description="Modo de consulta: detail o aggregate"
    )
    group_by: list[GroupByField] = Field(
        default_factory=list, description="Campos de agrupación"
    )
    aggregations: list[AggregationSpec] = Field(
        default_factory=list, description="Funciones de agregación a calcular"
    )
    having: list[HavingCondition] = Field(
        default_factory=list,
        description="Condiciones aplicadas sobre los resultados agregados",
    )
    order_by: list[OrderBySpec] = Field(
        default_factory=list, description="Orden de los resultados"
    )


class SegmentCreateRequest(BaseSchema):
    name: str = Field(description="Nombre del segmento")
    description: str | None = Field(
        default=None, description="Descripción del segmento"
    )
    filter_criteria: SegmentQueryConfig = Field(
        description="Configuración de la consulta que define el segmento"
    )


class SegmentUpdateRequest(BaseSchema):
    name: str | None = Field(default=None, description="Nuevo nombre")
    description: str | None = Field(default=None, description="Nueva descripción")
    filter_criteria: SegmentQueryConfig | None = Field(
        default=None, description="Nueva configuración de la consulta"
    )


class SegmentExecuteRequest(BaseSchema):
    mode: Literal["preview", "audit"] = Field(
        default="preview",
        description=(
            "Modo de ejecución: preview (limitado) o audit (completo, se persiste)"
        ),
    )
    limit: int | None = Field(
        default=None, ge=1, description="Límite de filas a retornar en modo preview"
    )


class SegmentResponse(BaseSchema):
    id: uuid.UUID = Field(description="ID del segmento")
    name: str = Field(description="Nombre del segmento")
    description: str | None = Field(description="Descripción del segmento")
    filter_criteria: dict[str, Any] = Field(
        description="Configuración de la consulta que define el segmento"
    )
    portfolio_id: uuid.UUID = Field(description="ID del portafolio")
    created_at: datetime = Field(description="Fecha de creación")


class SegmentListResponse(BaseSchema):
    items: list[SegmentResponse] = Field(description="Segmentos de la página")
    total: int = Field(description="Total de registros")
    page: int = Field(description="Página actual")
    page_size: int = Field(description="Tamaño de página")


class SegmentExecuteResponse(BaseSchema):
    success: bool = Field(description="Indica si la ejecución fue exitosa")
    rows: int = Field(description="Cantidad de filas retornadas")
    columns: list[str] = Field(description="Nombres de las columnas resultantes")
    data: list[dict[str, Any]] = Field(description="Datos resultantes de la consulta")
    mode: str = Field(description="Modo en que se ejecutó: preview o audit")
    file_name: str | None = Field(
        default=None, description="Nombre del archivo exportado (modo audit)"
    )
    document_id: uuid.UUID | None = Field(
        default=None,
        description="ID del documento con el archivo exportado (modo audit)",
    )


class SegmentExecutionResponse(BaseSchema):
    id: uuid.UUID = Field(description="ID de la ejecución")
    segment_id: uuid.UUID = Field(description="ID del segmento ejecutado")
    mode: str = Field(description="Modo de ejecución: preview o audit")
    file_name: str | None = Field(description="Nombre del archivo exportado")
    document_id: uuid.UUID | None = Field(
        description="ID del documento con el archivo exportado"
    )
    rows: int = Field(description="Cantidad de filas obtenidas")
    columns: list[str] = Field(description="Nombres de las columnas resultantes")
    executed_by: uuid.UUID = Field(description="ID del usuario que ejecutó el segmento")
    created_at: datetime = Field(description="Fecha de ejecución")
