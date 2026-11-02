"""Columnas compartidas por las tablas de credenciales cifradas de un proveedor."""

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class EncryptedCredentialModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Forma común de una credencial cifrada de un proveedor externo, compartida por
    `billing.provider_credentials`, `messaging.provider_credentials` y
    `receivables.payment_gateways`: secretos cifrados individualmente en `secrets`
    (JSONB), configuración en claro en `public_config`, `lookup_key` para resolver por
    identificador del proveedor cuando el webhook lo trae. Cada tabla concreta agrega
    su propia columna de alcance (país u organización), su enum de proveedor y su
    índice único — eso varía por dominio y no se fuerza aquí."""

    __abstract__ = True

    secrets: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, name="secretos"
    )
    public_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, name="config_publica"
    )
    lookup_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, name="clave_busqueda"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
