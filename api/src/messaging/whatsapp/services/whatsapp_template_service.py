"""Alta de plantillas de WhatsApp ante Meta y su sincronización de estado."""

import re
import uuid
from collections.abc import Awaitable
from typing import TypeVar

import httpx
from fastapi import HTTPException, status

from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.templates.enums.template_enums import TemplateChannel, TemplateStatus
from messaging.templates.models.template_model import TemplateModel
from messaging.templates.repository.template_repository import TemplateRepository
from messaging.whatsapp.models.whatsapp_template_data_model import (
    WhatsAppTemplateDataModel,
)
from messaging.whatsapp.repository.whatsapp_template_data_repository import (
    WhatsAppTemplateDataRepository,
)
from messaging.whatsapp.schemas.whatsapp_template_data_schemas import (
    WhatsAppTemplateCreateRequest,
    WhatsAppTemplateVariableSlotResponse,
)
from messaging.whatsapp.services.whatsapp_client import WhatsAppCloudClient
from messaging.whatsapp.utils.whatsapp_error_utils import meta_error_to_http_exception
from messaging.whatsapp.utils.whatsapp_template_parser import extract_variable_slots
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)

_APPROVED = "APPROVED"
_INACTIVE_STATUSES = {"REJECTED", "PAUSED", "DISABLED"}
_SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")

T = TypeVar("T")


def _meta_name(portfolio_id: uuid.UUID, name: str) -> str:
    # Meta exige nombres en minúsculas, sin espacios ni acentos; se antepone un prefijo
    # corto del portafolio para no chocar con plantillas de otras organizaciones que
    # comparten la misma WABA.
    slug = _SLUG_PATTERN.sub("_", name.strip().lower()).strip("_")
    return f"{str(portfolio_id)[:8]}_{slug}"


class WhatsAppTemplateService:
    def __init__(
        self,
        template_repo: TemplateRepository,
        data_repo: WhatsAppTemplateDataRepository,
        portfolio_repo: PortfolioRepository,
        client: WhatsAppCloudClient,
    ) -> None:
        self._template_repo = template_repo
        self._data_repo = data_repo
        self._portfolio_repo = portfolio_repo
        self._client = client

    @staticmethod
    async def _call_meta(call: Awaitable[T]) -> T:
        """Ejecuta una llamada a la Graph API y traduce sus fallos a un `HTTPException`
        con mensaje en español; sin esto un 401/4xx de Meta salía como 500 genérico."""
        try:
            return await call
        except httpx.HTTPError as exc:
            raise meta_error_to_http_exception(exc) from exc

    async def _check_access(
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
        data: WhatsAppTemplateCreateRequest,
        user_session: UserSession,
    ) -> tuple[TemplateModel, WhatsAppTemplateDataModel]:
        await self._check_access(user_session, portfolio_id)

        template = await self._template_repo.add(
            TemplateModel(
                portfolio_id=portfolio_id,
                name=data.name,
                channel=TemplateChannel.WHATSAPP,
                status=TemplateStatus.DRAFT,
                body=None,
            )
        )

        meta_name = _meta_name(portfolio_id, data.name)
        response = await self._call_meta(
            self._client.create_template(
                name=meta_name,
                category=data.category.value,
                language=data.language,
                components=data.components,
            )
        )

        whatsapp_data = await self._data_repo.add(
            WhatsAppTemplateDataModel(
                template_id=template.id,
                meta_template_id=response.get("id"),
                meta_name=meta_name,
                language=data.language,
                category=data.category,
                meta_status=response.get("status", "PENDING"),
            )
        )
        return template, whatsapp_data

    async def list_by_org(
        self,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
        user_session: UserSession,
    ) -> tuple[list[tuple[TemplateModel, WhatsAppTemplateDataModel | None]], int]:
        await self._check_access(user_session, portfolio_id)
        templates, total = await self._template_repo.list_by_portfolio(
            portfolio_id, page, page_size, channel=TemplateChannel.WHATSAPP
        )
        data_rows = await self._data_repo.get_by_template_ids([t.id for t in templates])
        data_by_template = {row.template_id: row for row in data_rows}
        return [(t, data_by_template.get(t.id)) for t in templates], total

    async def _get_with_data(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> tuple[TemplateModel, WhatsAppTemplateDataModel]:
        await self._check_access(user_session, portfolio_id)
        template = await self._template_repo.get_by_id_and_portfolio(
            template_id, portfolio_id
        )
        if template is None or template.channel != TemplateChannel.WHATSAPP:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Plantilla de WhatsApp no encontrada"
            )
        whatsapp_data = await self._data_repo.get_by_template_id(template_id)
        if whatsapp_data is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Plantilla de WhatsApp no encontrada"
            )
        return template, whatsapp_data

    async def refresh_status(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> tuple[TemplateModel, WhatsAppTemplateDataModel]:
        template, whatsapp_data = await self._get_with_data(
            template_id, portfolio_id, user_session
        )
        if whatsapp_data.meta_template_id is None:
            return template, whatsapp_data

        response = await self._call_meta(
            self._client.get_template(whatsapp_data.meta_template_id)
        )
        new_status = response.get("status", whatsapp_data.meta_status)
        whatsapp_data.meta_status = new_status
        whatsapp_data = await self._data_repo.update(whatsapp_data)

        if new_status == _APPROVED:
            template.status = TemplateStatus.ACTIVE
        elif new_status in _INACTIVE_STATUSES:
            template.status = TemplateStatus.INACTIVE
        template = await self._template_repo.update(template)

        return template, whatsapp_data

    async def list_variables(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> list[WhatsAppTemplateVariableSlotResponse]:
        _, whatsapp_data = await self._get_with_data(
            template_id, portfolio_id, user_session
        )
        if whatsapp_data.meta_template_id is None:
            return []
        response = await self._call_meta(
            self._client.get_template(whatsapp_data.meta_template_id)
        )
        slots = extract_variable_slots(response.get("components", []))
        return [
            WhatsAppTemplateVariableSlotResponse(
                component=slot.component, name=slot.name, example=slot.example
            )
            for slot in slots
        ]

    async def delete(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> None:
        template, whatsapp_data = await self._get_with_data(
            template_id, portfolio_id, user_session
        )
        await self._call_meta(self._client.delete_template(whatsapp_data.meta_name))
        await self._data_repo.delete(whatsapp_data)
        await self._template_repo.delete(template)

    async def restore(self, template_id: uuid.UUID) -> TemplateModel:
        """Solo Admin Global. El borrado en Meta (`delete_template`, arriba) es
        irreversible: esto restaura únicamente las filas locales, la plantilla queda
        marcada activa de nuevo pero ya NO existe del lado de Meta hasta que se
        resubmita — no se intenta recrearla acá."""
        template = await self._template_repo.get_by_id_including_deleted(template_id)
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plantilla no encontrada")
        whatsapp_data = await self._data_repo.get_by_template_id_including_deleted(
            template_id
        )
        if whatsapp_data is not None:
            await self._data_repo.restore(whatsapp_data)
        return await self._template_repo.restore(template)
