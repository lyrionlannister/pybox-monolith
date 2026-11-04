"""Alta, edición y envío de prueba de plantillas de mensajería."""

import uuid

from fastapi import HTTPException, status

from core.config.logger import logger
from core.database.redis import redis_client
from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.campaigns.utils.substitution_utils import build_sub
from messaging.dispatcher import MessageDispatcher
from messaging.provider_credentials.services.provider_credential_service import (
    MessagingProviderCredentialService,
)
from messaging.templates.enums.template_enums import TemplateChannel, TemplateStatus
from messaging.templates.models.template_model import TemplateModel
from messaging.templates.repository.template_repository import TemplateRepository
from messaging.templates.schemas.template_schemas import (
    TemplateCreateRequest,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateSendRequest,
    TemplateSendResponse,
    TemplateUpdateRequest,
)
from messaging.templates.services.template_renderer import TemplateRenderer
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)

# Módulo-nivel, igual que en automation_service.py: un solo dispatcher compartido,
# no uno por instancia de servicio (cada canal mantiene su propio cliente HTTP).
_DISPATCHER = MessageDispatcher()


TEST_SENDS_PER_HOUR = 20


class TemplateService:
    def __init__(
        self,
        template_repo: TemplateRepository,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._repo = template_repo
        self._portfolio_repo = portfolio_repo
        self._renderer = TemplateRenderer()
        self._credential_service = MessagingProviderCredentialService(
            portfolio_repo.session
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

    async def list_by_org(
        self,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
        user_session: UserSession,
        channel: TemplateChannel | None = None,
        search: str | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> tuple[list[TemplateModel], int]:
        await self._check_portfolio_access(user_session, portfolio_id)
        return await self._repo.list_by_portfolio(
            portfolio_id, page, page_size, channel, search, sort_by, sort_order
        )

    async def list_all_by_org(
        self,
        portfolio_id: uuid.UUID,
        user_session: UserSession,
        channel: TemplateChannel | None = None,
    ) -> list[TemplateModel]:
        await self._check_portfolio_access(user_session, portfolio_id)
        return await self._repo.list_all_by_portfolio(portfolio_id, channel)

    async def get_by_id(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> TemplateModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        template = await self._repo.get_by_id_and_portfolio(template_id, portfolio_id)
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plantilla no encontrada")
        return template

    async def create(
        self,
        portfolio_id: uuid.UUID,
        data: TemplateCreateRequest,
        user_session: UserSession,
    ) -> TemplateModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        template = TemplateModel(
            portfolio_id=portfolio_id,
            name=data.name,
            channel=data.channel,
            status=data.status,
            body=data.body,
            design=data.design,
            subject=data.subject,
            sender_name=data.sender_name,
            sender_email=data.sender_email,
            reply_to=data.reply_to,
        )
        return await self._repo.add(template)

    async def update(
        self,
        template_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: TemplateUpdateRequest,
        user_session: UserSession,
    ) -> TemplateModel:
        template = await self.get_by_id(template_id, portfolio_id, user_session)
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(template, key, value)
        return await self._repo.update(template)

    async def delete(
        self, template_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> None:
        template = await self.get_by_id(template_id, portfolio_id, user_session)
        await self._repo.delete(template)

    async def restore(self, template_id: uuid.UUID) -> TemplateModel:
        """Solo Admin Global: sin scope de portafolio, ya autorizado por policy."""
        template = await self._repo.get_by_id_including_deleted(template_id)
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plantilla no encontrada")
        return await self._repo.restore(template)

    async def preview(
        self,
        template_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: TemplatePreviewRequest,
        user_session: UserSession,
    ) -> TemplatePreviewResponse:
        template = await self.get_by_id(template_id, portfolio_id, user_session)

        combined = (template.body or "") + " " + (template.subject or "")
        variables_used = sorted(self._renderer.find_variables(combined))

        html, rendered_subject = self._renderer.render_fields(
            template.body or "", template.subject, data.sub
        )

        return TemplatePreviewResponse(
            html=html,
            subject=rendered_subject,
            variables_used=variables_used,
        )

    async def send(
        self,
        template_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: TemplateSendRequest,
        user_session: UserSession,
    ) -> TemplateSendResponse:
        template = await self.get_by_id(template_id, portfolio_id, user_session)
        # Envío de prueba: solo al correo del propio usuario. Con destinatario y
        # asunto libres este endpoint era un relé de correo con el remitente de la
        # plataforma (phishing/spam); los envíos reales van por campañas.
        if str(data.to).lower() != user_session.email.lower():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El envío de prueba solo puede ir a tu propio correo.",
            )
        sends = await redis_client.increment(
            f"template-test-send:{user_session.user_id}", 3600
        )
        if sends > TEST_SENDS_PER_HOUR:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Alcanzaste el límite de envíos de prueba por hora.",
            )
        if template.channel != TemplateChannel.EMAIL:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Solo se pueden enviar plantillas de EMAIL desde acá.",
            )
        if template.status != TemplateStatus.ACTIVE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "La plantilla debe estar activa para enviarse.",
            )

        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)

        # Igual que en el envío de campañas: el cuerpo/asunto viajan con sus
        # `{variable}` sin resolver -- el proveedor hace la sustitución de su lado con
        # `sub` (ver TemplateRenderer, que sí resuelve local pero solo para /preview).
        # El envío pasa por el Gateway (`MessageDispatcher`) según `template.channel`,
        # igual que campañas/envío masivo -- nunca se llama al proveedor directo, así
        # se resuelve la credencial (token/remitente) por país igual que cualquier
        # otro envío del sistema, en vez de depender siempre de las env vars globales.
        ok, _ids_by_recipient, _sending_id = await _DISPATCHER.send(
            template.channel,
            [data.to],
            template.body or "",
            subject=data.subject or template.subject or "",
            sub=build_sub(data.sub),
            campaign_name=f"template-{template.id}",
            credential_service=self._credential_service,
            country=portfolio.country if portfolio else None,
        )
        if not ok:
            logger.error(
                "[templates] envío fallido | template=%s to=%s", template.id, data.to
            )
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "No se pudo enviar el email. Intenta de nuevo.",
            )

        logger.info("[templates] enviado | template=%s to=%s", template.id, data.to)
        return TemplateSendResponse(message="Email enviado correctamente.")
