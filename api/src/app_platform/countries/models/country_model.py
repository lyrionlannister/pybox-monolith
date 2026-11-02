"""País soportado por la plataforma."""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CountryModel(CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Fuente de verdad de los países soportados. Reemplaza al enum `Nationality`
    y a los diccionarios derivados (nombre, prefijo, zona horaria, moneda) como
    autoridad: agregar un país es un INSERT, no un cambio de código."""

    __tablename__ = "paises"

    code: Mapped[str] = mapped_column(String(2), primary_key=True, name="codigo")
    name: Mapped[str] = mapped_column(String(100), nullable=False, name="nombre")
    phone_prefix: Mapped[str] = mapped_column(
        String(8), nullable=False, name="prefijo_telefonico"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, name="zona_horaria"
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, name="codigo_moneda"
    )
    flag_url: Mapped[str] = mapped_column(
        String(255), nullable=False, name="url_bandera"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
