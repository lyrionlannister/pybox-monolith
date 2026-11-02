"""Portafolio de cartera de una organización."""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class PortfolioModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "portafolios"

    name: Mapped[str] = mapped_column(String, nullable=False, name="nombre")
    description: Mapped[str | None] = mapped_column(
        String, nullable=True, name="descripcion"
    )
    country: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("paises.codigo"), nullable=True, name="pais"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
