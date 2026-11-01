"""Acceso a datos de las ejecuciones guardadas de un segmento."""

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.portfolios.models.portfolio_model import PortfolioModel
from receivables.segments.models.segment_execution_model import SegmentExecutionModel
from receivables.segments.models.segment_model import SegmentModel


class SegmentExecutionRepository(SoftDeleteRepositoryBase[SegmentExecutionModel]):
    model_class = SegmentExecutionModel

    async def get_by_segment(
        self, segment_id: uuid.UUID
    ) -> Sequence[SegmentExecutionModel]:
        result = await self.session.execute(
            select(SegmentExecutionModel)
            .where(SegmentExecutionModel.segment_id == segment_id)
            .order_by(SegmentExecutionModel.created_at.desc())
        )
        return result.scalars().all()

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de las ejecuciones de los segmentos de los portafolios
        de la organización con el sello de la organización."""
        await self.soft_delete_where(
            SegmentExecutionModel.segment_id.in_(
                select(SegmentModel.id).where(
                    SegmentModel.portfolio_id.in_(
                        select(PortfolioModel.id).where(
                            PortfolioModel.organization_id == organization_id
                        )
                    )
                )
            ),
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Inverso de ``soft_delete_by_organization``: solo lo que cayó con la
        organización."""
        await self.restore_where(
            SegmentExecutionModel.segment_id.in_(
                select(SegmentModel.id).where(
                    SegmentModel.portfolio_id.in_(
                        select(PortfolioModel.id).where(
                            PortfolioModel.organization_id == organization_id
                        )
                    )
                )
            ),
            deleted_at=deleted_at,
        )
