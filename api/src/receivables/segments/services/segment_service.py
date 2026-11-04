"""Generación y ejecución de segmentos de cartera, con auditoría en almacenamiento."""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

import polars as pl
from fastapi import HTTPException, status
from pydantic import TypeAdapter

from app_platform.documents.enums.document_enums import CSV_CONTENT_TYPE
from app_platform.documents.services.document_service import DocumentService
from app_platform.schema_manager.services.dml_service import DmlService
from core.cache.cache_service import cache_service
from core.config.logger import logger
from core.security.constants.permissions import (
    PORTFOLIO_CLIENTS,
    PORTFOLIO_COMMUNICATIONS,
)
from core.security.policies.security_policies import (
    check_portfolio_org_access,
    has_permission,
)
from identity.users.schemas.user_session_schema import UserSession
from receivables.portfolios.enums.portfolio_document_enums import (
    PortfolioDocumentCategory,
)
from receivables.portfolios.models.portfolio_document_model import (
    PortfolioDocumentModel,
)
from receivables.portfolios.repository.portfolio_document_repository import (
    PORTFOLIO_DOCUMENT_STORAGE_DOMAIN,
    PortfolioDocumentRepository,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.models.segment_execution_model import SegmentExecutionModel
from receivables.segments.models.segment_model import SegmentModel
from receivables.segments.repository.segment_execution_repository import (
    SegmentExecutionRepository,
)
from receivables.segments.repository.segment_repository import SegmentRepository
from receivables.segments.schemas.segment_schemas import (
    SegmentCreateRequest,
    SegmentExecuteRequest,
    SegmentResponse,
    SegmentUpdateRequest,
)
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)

_segment_list_adapter: TypeAdapter[list[SegmentResponse]] = TypeAdapter(
    list[SegmentResponse]
)


class SegmentService:
    def __init__(
        self,
        segment_repo: SegmentRepository,
        execution_repo: SegmentExecutionRepository,
        dml_service: DmlService,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._segment_repo = segment_repo
        self._execution_repo = execution_repo
        self._dml = dml_service
        self._portfolio_repo = portfolio_repo
        # El CSV lo guarda el modulo de documentos: aca solo se persiste el id.
        self._document_service = DocumentService(segment_repo.session)
        # La exportacion cuelga del portafolio via `documentos_portafolio`.
        self._portfolio_document_repo = PortfolioDocumentRepository(
            segment_repo.session
        )

    async def _check_portfolio_access(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ) -> None:
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        await check_portfolio_org_access(
            user_session,
            portfolio,
            PORTFOLIO_COMMUNICATIONS,
            check_access=PortfolioUserAccessService(
                self._portfolio_repo.session
            ).check_access,
        )

    async def create(
        self,
        portfolio_id: uuid.UUID,
        data: SegmentCreateRequest,
        user_session: UserSession,
    ) -> SegmentModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        segment = SegmentModel(
            name=data.name,
            description=data.description,
            filter_criteria=data.filter_criteria.model_dump(by_alias=False),
            portfolio_id=portfolio_id,
        )
        result = await self._segment_repo.add(segment)
        await cache_service.bust(f"segment:list:{portfolio_id}")
        return result

    async def list_by_org(
        self,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
        user_session: UserSession,
    ) -> tuple[list[SegmentModel], int]:
        await self._check_portfolio_access(user_session, portfolio_id)
        return await self._segment_repo.get_by_portfolio(portfolio_id, page, page_size)

    async def list_all_by_org(
        self, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> list[SegmentResponse]:
        await self._check_portfolio_access(user_session, portfolio_id)

        async def _fetch() -> list[SegmentResponse]:
            models = await self._segment_repo.get_all_by_portfolio(portfolio_id)
            return [SegmentResponse.model_validate(m) for m in models]

        return await cache_service.get_or_set(
            key=f"segment:list:{portfolio_id}",
            fetch=_fetch,
            adapter=_segment_list_adapter,
            ttl=120,
        )

    async def get(
        self, segment_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> SegmentModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        segment = await self._segment_repo.get_by_id(segment_id)
        if not segment or segment.portfolio_id != portfolio_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento no encontrado")
        return segment

    async def update(
        self,
        segment_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: SegmentUpdateRequest,
        user_session: UserSession,
    ) -> SegmentModel:
        segment = await self.get(segment_id, portfolio_id, user_session)
        if data.name is not None:
            segment.name = data.name
        if data.description is not None:
            segment.description = data.description
        if data.filter_criteria is not None:
            segment.filter_criteria = data.filter_criteria.model_dump(by_alias=False)
        result = await self._segment_repo.update(segment)
        await cache_service.bust(f"segment:list:{portfolio_id}")
        await cache_service.bust_prefix(f"campaign:recipient-count:{segment_id}")
        return result

    async def delete(
        self, segment_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> None:
        segment = await self.get(segment_id, portfolio_id, user_session)
        await self._segment_repo.delete(segment)
        await cache_service.bust(f"segment:list:{portfolio_id}")
        await cache_service.bust_prefix(f"campaign:recipient-count:{segment_id}")

    async def restore(self, segment_id: uuid.UUID) -> SegmentModel:
        """Solo Admin Global: sin scope de portafolio, ya autorizado por policy."""
        segment = await self._segment_repo.get_by_id_including_deleted(segment_id)
        if segment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento no encontrado")
        restored = await self._segment_repo.restore(segment)
        await cache_service.bust(f"segment:list:{segment.portfolio_id}")
        return restored

    async def execute(
        self,
        segment_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        request: SegmentExecuteRequest,
        user_id: uuid.UUID,
        user_session: UserSession,
    ) -> dict[str, Any]:
        segment = await self.get(segment_id, portfolio_id, user_session)
        criteria = segment.filter_criteria

        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        organization_ids = [portfolio.organization_id] if portfolio else []
        # El documento del deudor se ve con portfolio.clients (DebtorService);
        # ejecutar un segmento solo exige portfolio.communications, así que sin
        # aquel permiso sale cifrado.
        can_view_documents = portfolio is not None and has_permission(
            PORTFOLIO_CLIENTS, user_session, str(portfolio.organization_id)
        )

        result = await self._dml.execute_query(
            tables=criteria.get("tables", []),
            joins=criteria.get("joins", []),
            limit=request.limit,
            query_mode=criteria.get("query_mode", "detail"),
            group_by=criteria.get("group_by", []),
            aggregations=criteria.get("aggregations", []),
            having=criteria.get("having", []),
            order_by=criteria.get("order_by", []),
            portfolio_ids=[portfolio_id],
            organization_ids=organization_ids,
            decrypt_sensitive=can_view_documents,
        )

        if not result["success"]:
            logger.error(
                "[SegmentService] Error ejecutando segmento %s: %s",
                segment_id,
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
                portfolio_id=portfolio_id,
                segment_name=segment.name,
                df=df,
                user_id=user_id,
            )
            execution = SegmentExecutionModel(
                segment_id=segment_id,
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
        self, segment_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> Sequence[SegmentExecutionModel]:
        await self.get(segment_id, portfolio_id, user_session)
        return await self._execution_repo.get_by_segment(segment_id)

    def _to_dataframe(self, result: dict[str, Any]) -> pl.DataFrame:
        data = json.loads(result["data"])
        if not data:
            return pl.DataFrame(schema={col: pl.Utf8 for col in result["columns"]})
        return pl.DataFrame(data)

    async def _save_audit_file(
        self,
        portfolio_id: uuid.UUID,
        segment_name: str,
        df: pl.DataFrame,
        user_id: uuid.UUID,
    ) -> tuple[str, uuid.UUID]:
        """Guarda el CSV de auditoria en el almacen de objetos.

        Devuelve (nombre, id del documento). El id se persiste en
        `ejecuciones_segmentos.id_documento`, una FK real contra `documentos` (mismo
        patrón que `ReportService._save_audit_file`). Cuelga del portafolio via
        `documentos_portafolio`, y la entidad dueña se denormaliza ahi desde el mismo
        portafolio para poder aislar por organizacion al descargarlo.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", segment_name)
        file_name = f"{timestamp}_{safe_name}.csv"

        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado")
        document = await self._document_service.store_generated(
            content=df.write_csv().encode("utf-8"),
            filename=file_name,
            content_type=CSV_CONTENT_TYPE,
            domain=PORTFOLIO_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(portfolio_id),
            uploaded_by=user_id,
            organization_id=portfolio.organization_id,
        )
        await self._portfolio_document_repo.add(
            PortfolioDocumentModel(
                portfolio_id=portfolio_id,
                organization_id=portfolio.organization_id,
                category=PortfolioDocumentCategory.SEGMENT_EXPORT,
                document_id=document.id,
            )
        )
        return file_name, document.id
