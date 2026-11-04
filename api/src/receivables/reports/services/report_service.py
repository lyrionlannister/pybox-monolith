"""Generación y ejecución de reportes de cartera, con auditoría en almacenamiento."""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

import polars as pl
from fastapi import HTTPException, status

from app_platform.documents.enums.document_enums import CSV_CONTENT_TYPE
from app_platform.documents.services.document_service import DocumentService
from app_platform.schema_manager.services.dml_service import DmlService
from core.config.logger import logger
from core.tools.csv_tools import neutralize_formulas
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.reports.models.report_execution_model import ReportExecutionModel
from receivables.reports.models.report_model import ReportModel
from receivables.reports.repository.report_execution_repository import (
    REPORT_DOCUMENT_STORAGE_DOMAIN,
    ReportExecutionRepository,
)
from receivables.reports.repository.report_repository import ReportRepository
from receivables.reports.schemas.report_schemas import (
    ReportCreateRequest,
    ReportExecuteRequest,
    ReportUpdateRequest,
)


class ReportService:
    def __init__(
        self,
        report_repo: ReportRepository,
        execution_repo: ReportExecutionRepository,
        dml_service: DmlService,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._report_repo = report_repo
        self._execution_repo = execution_repo
        self._dml = dml_service
        self._portfolio_repo = portfolio_repo
        # El CSV lo guarda el modulo de documentos: aca solo se persiste el id.
        self._document_service = DocumentService(report_repo.session)

    async def create(
        self, organization_id: uuid.UUID, data: ReportCreateRequest
    ) -> ReportModel:
        report = ReportModel(
            name=data.name,
            description=data.description,
            report_config=data.report_config.model_dump(by_alias=False),
            organization_id=organization_id,
        )
        return await self._report_repo.add(report)

    async def list_by_org(
        self, organization_id: uuid.UUID, page: int, page_size: int
    ) -> tuple[list[ReportModel], int]:
        return await self._report_repo.get_by_organization_id(
            organization_id, page, page_size
        )

    async def get(
        self, report_id: uuid.UUID, organization_id: uuid.UUID
    ) -> ReportModel:
        report = await self._report_repo.get_by_id(report_id)
        if not report or report.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reporte no encontrado")
        return report

    async def update(
        self,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: ReportUpdateRequest,
    ) -> ReportModel:
        report = await self.get(report_id, organization_id)
        if data.name is not None:
            report.name = data.name
        if data.description is not None:
            report.description = data.description
        if data.report_config is not None:
            report.report_config = data.report_config.model_dump(by_alias=False)
        return await self._report_repo.update(report)

    async def delete(self, report_id: uuid.UUID, organization_id: uuid.UUID) -> None:
        report = await self.get(report_id, organization_id)
        await self._report_repo.delete(report)

    async def restore(self, report_id: uuid.UUID) -> ReportModel:
        """Solo Admin Global: sin scope de organización, ya autorizado por policy."""
        report = await self._report_repo.get_by_id_including_deleted(report_id)
        if report is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reporte no encontrado")
        return await self._report_repo.restore(report)

    async def execute(
        self,
        report_id: uuid.UUID,
        organization_id: uuid.UUID,
        request: ReportExecuteRequest,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        report = await self.get(report_id, organization_id)
        config = report.report_config

        portfolios = await self._portfolio_repo.get_by_organization_id(organization_id)
        portfolio_ids = [p.id for p in portfolios]

        result = await self._dml.execute_query(
            tables=config.get("tables", []),
            joins=config.get("joins", []),
            limit=request.limit,
            query_mode=config.get("query_mode", "detail"),
            group_by=config.get("group_by", []),
            aggregations=config.get("aggregations", []),
            having=config.get("having", []),
            order_by=config.get("order_by", []),
            portfolio_ids=portfolio_ids,
            organization_ids=[organization_id],
        )

        if not result["success"]:
            logger.error(
                "[ReportService] Error ejecutando reporte %s: %s",
                report_id,
                result["error"],
            )
            raise HTTPException(
                result.get("status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
                result["error"],
            )

        df = self._to_dataframe(result)
        file_name: str | None = None
        document_id: uuid.UUID | None = None

        if request.mode == "audit":
            file_name, document_id = await self._save_audit_file(
                organization_id=organization_id,
                report_name=report.name,
                df=df,
                user_id=user_id,
            )
            execution = ReportExecutionModel(
                report_id=report_id,
                mode=request.mode,
                file_name=file_name,
                document_id=document_id,
                rows=len(df),
                columns=df.columns,
                executed_by=user_id,
            )
            await self._execution_repo.add(execution)

        return {
            "success": True,
            "rows": len(df),
            "columns": df.columns,
            "data": df.to_dicts(),
            "mode": request.mode,
            "file_name": file_name,
            "document_id": document_id,
        }

    async def list_executions(
        self, report_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Sequence[ReportExecutionModel]:
        await self.get(report_id, organization_id)
        return await self._execution_repo.get_by_report(report_id)

    def _to_dataframe(self, result: dict[str, Any]) -> pl.DataFrame:
        data = json.loads(result["data"])
        if not data:
            return pl.DataFrame(schema={col: pl.Utf8 for col in result["columns"]})
        return pl.DataFrame(data)

    async def _save_audit_file(
        self,
        organization_id: uuid.UUID,
        report_name: str,
        df: pl.DataFrame,
        user_id: uuid.UUID,
    ) -> tuple[str, uuid.UUID]:
        """Guarda el CSV de auditoria en el almacen de objetos.

        Devuelve (nombre, id del documento). El id se persiste en
        `ejecuciones_reportes.id_documento`, que es una FK real contra
        `documentos`: antes iba dentro de la columna de texto `ruta_archivo`, sin
        ninguna integridad detras. No hace falta tabla de union porque la relacion
        es 1:1.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", report_name)
        file_name = f"{timestamp}_{safe_name}.csv"

        document = await self._document_service.store_generated(
            content=neutralize_formulas(df).write_csv().encode("utf-8"),
            filename=file_name,
            content_type=CSV_CONTENT_TYPE,
            domain=REPORT_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(organization_id),
            uploaded_by=user_id,
            organization_id=organization_id,
        )
        return file_name, document.id
