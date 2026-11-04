"""Schema de la solicitud de llamada de prueba desde el diseñador de flujos IVR."""

import uuid
from typing import Any

from pydantic import Field

from core.base.schema_base import BaseSchema


class IvrTestCallRequest(BaseSchema):
    """Solicitud de llamada de prueba desde el diseñador de flujos IVR."""

    phone: str = Field(description="Número de teléfono a marcar (solo dígitos)")
    config: dict[str, Any] = Field(
        description="CampaignIvrConfig compilado del flujo que se quiere probar"
    )
    variables: dict[str, Any] | None = Field(
        default=None, description="Variables para Helena (AMD_*, PJSIP_TRUNK, …)"
    )
    customer_name: str | None = Field(
        default=None, description="Nombre del cliente (reportería)"
    )
    customer_document: str | None = Field(
        default=None, description="Documento del cliente"
    )
    portfolio_id: uuid.UUID = Field(
        description="Portafolio cuyo flujo se prueba (autoriza la llamada)"
    )
    redial_config: dict[str, Any] | None = Field(
        default=None,
        description="Configuración de remarcado (maxAttempts, retryDelaySeconds)",
    )
