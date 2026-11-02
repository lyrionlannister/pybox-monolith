"""Credenciales de la cuenta propia de una organización en una pasarela de cobro."""

from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from core.base.encrypted_credential_model import EncryptedCredentialModel
from core.base.tenant_mixin import TenantMixin
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesGatewayProvider,
)


class OrganizationGatewayCredentialModel(TenantMixin, EncryptedCredentialModel):
    """Credenciales de la cuenta PROPIA de una organización en una pasarela de pago,
    usadas para cobrarle a SUS deudores (la plataforma nunca las recibe ni dispersa).

    Mismo diseño de cifrado que `messaging.provider_credentials` y
    `billing.provider_credentials` (ver `EncryptedCredentialModel` para las columnas
    compartidas); `lookup_key` resuelve por identificador del proveedor cuando el
    webhook lo trae (ver skill `wompi-gateway`).

    A diferencia de las otras dos tablas, aquí NO existe el concepto de credencial
    global: `organization_id` es obligatorio, porque la cuenta de una pasarela siempre
    es de una empresa concreta, nunca "de la plataforma" ni "por defecto"."""

    __tablename__ = "credenciales_pasarela_organizacion"
    __table_args__ = (
        Index(
            "uq_credencial_pasarela_organizacion_org_proveedor",
            "id_organizacion",
            "proveedor",
            unique=True,
            postgresql_where=text("eliminado_en IS NULL"),
        ),
    )

    provider: Mapped[ReceivablesGatewayProvider] = mapped_column(
        ENUM(
            ReceivablesGatewayProvider,
            name="proveedor_pasarela_organizacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="proveedor",
    )
