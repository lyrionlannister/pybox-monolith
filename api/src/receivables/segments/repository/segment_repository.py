"""Acceso a datos de los segmentos de cartera de un portafolio."""

import uuid
from datetime import datetime

from sqlalchemy import func, select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from receivables.portfolios.models.portfolio_model import PortfolioModel
from receivables.segments.models.segment_model import SegmentModel


class SegmentRepository(SoftDeleteRepositoryBase[SegmentModel]):
    model_class = SegmentModel

    async def get_all_by_portfolio(self, portfolio_id: uuid.UUID) -> list[SegmentModel]:
        result = await self.session.execute(
            select(SegmentModel)
            .where(
                SegmentModel.portfolio_id == portfolio_id,
                SegmentModel.deleted_at.is_(None),
            )
            .order_by(SegmentModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_and_portfolio(
        self,
        segment_id: uuid.UUID,
        portfolio_id: uuid.UUID,
    ) -> SegmentModel | None:
        result = await self.session.execute(
            select(SegmentModel).where(
                SegmentModel.id == segment_id,
                SegmentModel.portfolio_id == portfolio_id,
                SegmentModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_portfolio(
        self,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[SegmentModel], int]:
        query = select(SegmentModel).where(
            SegmentModel.portfolio_id == portfolio_id,
            SegmentModel.deleted_at.is_(None),
        )

        total: int = (
            await self.session.scalar(
                select(func.count()).select_from(query.subquery())
            )
            or 0
        )

        result = await self.session.execute(
            query.order_by(SegmentModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de los segmentos de los portafolios de la organización
        con el sello de la organización."""
        await self.soft_delete_where(
            SegmentModel.portfolio_id.in_(
                select(PortfolioModel.id).where(
                    PortfolioModel.organization_id == organization_id
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
            SegmentModel.portfolio_id.in_(
                select(PortfolioModel.id).where(
                    PortfolioModel.organization_id == organization_id
                )
            ),
            deleted_at=deleted_at,
        )
