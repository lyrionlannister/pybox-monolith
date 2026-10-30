"""Listado, detalle y envío de mensajes de un chat de WhatsApp."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app_platform.countries.repository.country_repository import CountryRepository
from core.security.constants.permissions import MANAGE_WHATSAPP_CHATS
from core.security.policies.security_policies import (
    require_org_admin,
    require_permission,
)
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import UserRole
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import UserSession
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.provider_credentials.enums.provider_credential_enums import (
    MessagingCredentialProvider,
)
from messaging.provider_credentials.services.provider_credential_service import (
    MessagingProviderCredentialService,
)
from messaging.whatsapp.enums.whatsapp_enums import MessageDirection
from messaging.whatsapp.models.whatsapp_chat_model import WhatsAppChatModel
from messaging.whatsapp.models.whatsapp_message_model import WhatsAppMessageModel
from messaging.whatsapp.repository.whatsapp_chat_repository import (
    OrgChatScope,
    WhatsAppChatRepository,
)
from messaging.whatsapp.repository.whatsapp_message_repository import (
    WhatsAppMessageRepository,
)
from messaging.whatsapp.repository.whatsapp_org_credentials_repository import (
    WhatsAppOrgCredentialsRepository,
)
from messaging.whatsapp.schemas.whatsapp_chat_schemas import (
    WhatsAppChatCampaignInfo,
    WhatsAppChatDetailsResponse,
    WhatsAppChatPortfolioInfo,
    WhatsAppChatResponse,
)
from messaging.whatsapp.services.whatsapp_client import WhatsAppCloudClient
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.debtors.schemas.debtor_schemas import (
    DebtorCreditResponse,
    DebtorResponse,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)

# Ventana de servicio al cliente de Meta: solo se puede enviar texto libre (fuera de
# plantilla) dentro de las 24h posteriores al último mensaje del deudor.
_CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)


def _is_org_admin(user_session: UserSession, organization_id: uuid.UUID) -> bool:
    if user_session.is_global:
        return True
    org_entry = user_session.orgs.get(str(organization_id))
    return org_entry is not None and org_entry.role == UserRole.ADMIN


class WhatsAppChatService:
    def __init__(
        self,
        chat_repo: WhatsAppChatRepository,
        message_repo: WhatsAppMessageRepository,
        portfolio_access_repo: PortfolioUserAccessRepository,
        credentials_repo: WhatsAppOrgCredentialsRepository,
        client: WhatsAppCloudClient,
        debtor_repo: DebtorRepository,
        credit_repo: CreditRepository,
        portfolio_repo: PortfolioRepository,
        campaign_repo: CampaignRepository,
        user_repo: UserRepository,
        org_repo: OrganizationRepository,
        membership_repo: OrganizationMembershipRepository,
    ) -> None:
        self._org_repo = org_repo
        self._membership_repo = membership_repo
        self._chat_repo = chat_repo
        self._message_repo = message_repo
        self._portfolio_access_repo = portfolio_access_repo
        self._credentials_repo = credentials_repo
        self._client = client
        self._debtor_repo = debtor_repo
        self._credit_repo = credit_repo
        self._portfolio_repo = portfolio_repo
        self._campaign_repo = campaign_repo
        self._user_repo = user_repo
        self._country_repo = CountryRepository(portfolio_repo.session)
        self._credential_service = MessagingProviderCredentialService(
            portfolio_repo.session
        )

    async def _build_scope(
        self, organization_id: uuid.UUID, user_session: UserSession
    ) -> OrgChatScope:
        # Solo un admin de la org (o usuario global) ve todos los hilos; un agente de
        # WhatsApp (USER con el permiso otorgado) solo ve lo que le asignaron, y dentro
        # de eso, solo hilos de portafolios que tiene asignados (los sin portafolio
        # resuelto quedan fuera — ver accesos_usuario_portafolio).
        if _is_org_admin(user_session, organization_id):
            return OrgChatScope(organization_id=organization_id)
        accesses = await self._portfolio_access_repo.get_active_by_user_and_org(
            user_session.user_id, organization_id
        )
        return OrgChatScope(
            organization_id=organization_id,
            assigned_user_id=user_session.user_id,
            portfolio_ids=[access.portfolio_id for access in accesses],
        )

    async def list_chats(
        self,
        page: int,
        page_size: int,
        user_session: UserSession,
        organization_id: uuid.UUID | None = None,
    ) -> tuple[list[WhatsAppChatResponse], int]:
        """Sin `organization_id` lista los hilos de todas las organizaciones donde el
        usuario tenga el permiso, en una sola página ordenada por último mensaje.
        """
        unrestricted = False
        if organization_id is not None:
            require_permission(
                MANAGE_WHATSAPP_CHATS, user_session, str(organization_id)
            )
            scopes = [await self._build_scope(organization_id, user_session)]
        elif user_session.is_global:
            # El usuario global no tiene entradas en `orgs`: su alcance
            # es toda la tabla.
            scopes = []
            unrestricted = True
        else:
            scopes = [
                await self._build_scope(uuid.UUID(org_id), user_session)
                for org_id, entry in user_session.orgs.items()
                if MANAGE_WHATSAPP_CHATS in entry.permissions
            ]

        chats, total = await self._chat_repo.list_by_scopes(
            scopes, page, page_size, unrestricted
        )
        org_names = await self._org_names_by_id(
            [chat.organization_id for chat in chats]
        )
        items = [
            WhatsAppChatResponse.model_validate(chat).model_copy(
                update={"organization_name": org_names.get(chat.organization_id, "")}
            )
            for chat in chats
        ]
        return items, total

    async def _org_names_by_id(
        self, organization_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        unique_ids = list(set(organization_ids))
        if not unique_ids:
            return {}
        return {org.id: org.name for org in await self._org_repo.get_by_ids(unique_ids)}

    async def _get_chat_for_user(
        self, chat_id: uuid.UUID, organization_id: uuid.UUID, user_session: UserSession
    ) -> WhatsAppChatModel:
        # Sin gate de permiso a nivel de organización acá: el acceso
        # por-hilo lo deciden las reglas de abajo (admin de la org ve
        # todo; agente ve solo lo asignado + su portafolio).
        # `MANAGE_WHATSAPP_CHATS` es para `list_chats` (visibilidad
        # masiva), no para esto -- exigirlo acá bloqueaba por completo la
        # ruta de agente asignado.
        chat = await self._chat_repo.get_by_id(chat_id)
        if chat is None or chat.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Hilo no encontrado")
        if not _is_org_admin(user_session, organization_id):
            if chat.assigned_user_id != user_session.user_id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Este hilo no está asignado a este usuario",
                )
            has_portfolio_access = (
                chat.portfolio_id is not None
                and await self._portfolio_access_repo.check_active_access(
                    user_session.user_id, chat.portfolio_id, organization_id
                )
            )
            if not has_portfolio_access:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Sin acceso al portafolio de este hilo"
                )
        return chat

    async def list_messages(
        self, chat_id: uuid.UUID, organization_id: uuid.UUID, user_session: UserSession
    ) -> list[WhatsAppMessageModel]:
        chat = await self._get_chat_for_user(chat_id, organization_id, user_session)
        return await self._message_repo.list_by_chat(chat.id)

    async def assign(
        self,
        chat_id: uuid.UUID,
        organization_id: uuid.UUID,
        assigned_user_id: uuid.UUID,
        user_session: UserSession,
    ) -> WhatsAppChatModel:
        require_org_admin(user_session, str(organization_id))
        chat = await self._chat_repo.get_by_id(chat_id)
        if chat is None or chat.organization_id != organization_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Hilo no encontrado")
        memberships = await self._membership_repo.get_by_user_id(assigned_user_id)
        if not any(m.organization_id == organization_id for m in memberships):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El usuario asignado no pertenece a esta organización.",
            )
        chat.assigned_user_id = assigned_user_id
        return await self._chat_repo.update(chat)

    async def send_message(
        self,
        chat_id: uuid.UUID,
        organization_id: uuid.UUID,
        body: str,
        user_session: UserSession,
    ) -> WhatsAppMessageModel:
        chat = await self._get_chat_for_user(chat_id, organization_id, user_session)

        now = datetime.now(timezone.utc)
        last_inbound = await self._message_repo.get_last_inbound(chat.id)
        if (
            last_inbound is None
            or now - last_inbound.sent_at > _CUSTOMER_SERVICE_WINDOW
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Pasaron más de 24h desde el último mensaje del deudor; "
                "no se puede enviar texto libre.",
            )

        credentials = await self._credentials_repo.get_by_organization(organization_id)
        if credentials is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La organización no tiene WhatsApp configurado",
            )

        wa_cred = await self._credential_service.get_decrypted(
            None, MessagingCredentialProvider.WHATSAPP_CLOUD
        )
        ok, wamid = await self._client.send_text(
            credentials.phone_number_id,
            chat.phone,
            body,
            token=wa_cred.get("access_token") if wa_cred else None,
        )
        if not ok:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "No se pudo enviar el mensaje"
            )

        message = await self._message_repo.add(
            WhatsAppMessageModel(
                chat_id=chat.id,
                direction=MessageDirection.OUTBOUND,
                wamid=wamid,
                message_type="text",
                content=body,
                raw_payload={"type": "text", "text": {"body": body}},
                sent_at=now,
            )
        )
        chat.last_message_at = now
        await self._chat_repo.update(chat)
        return message

    async def get_chat_details(
        self, chat_id: uuid.UUID, organization_id: uuid.UUID, user_session: UserSession
    ) -> WhatsAppChatDetailsResponse:
        chat = await self._get_chat_for_user(chat_id, organization_id, user_session)

        portfolio = (
            await self._portfolio_repo.get_by_id(chat.portfolio_id)
            if chat.portfolio_id is not None
            else None
        )
        portfolio_info = (
            WhatsAppChatPortfolioInfo(id=portfolio.id, name=portfolio.name)
            if portfolio is not None
            else None
        )

        debtor_response: DebtorResponse | None = None
        is_self_registered = False
        credits: list[DebtorCreditResponse] = []

        if chat.debtor_id is not None:
            debtor = await self._debtor_repo.get_by_id(chat.debtor_id)
            if debtor is not None:
                debtor_response = DebtorResponse(
                    id=debtor.id,
                    full_name=debtor.full_name,
                    debtor_type=debtor.debtor_type,
                    document_type=debtor.document_type,
                    document_number=encrypt_service.decrypt_to_str(
                        debtor.document_number
                    ),
                )
                registered_user = await self._user_repo.get_by_document(
                    debtor.document_type, debtor.document_number_hash
                )
                is_self_registered = registered_user is not None

                if portfolio is not None:
                    currency_code = await self._country_repo.get_currency_code(
                        portfolio.country
                    )
                    credit_models = await self._credit_repo.get_by_debtor_and_portfolio(
                        chat.debtor_id, chat.portfolio_id
                    )
                    credits = [
                        DebtorCreditResponse(
                            id=c.id,
                            credit_number=c.credit_number,
                            credit_type=c.credit_type,
                            disbursed_date=c.disbursed_date,
                            total_credit_balance=float(c.total_credit_balance),
                            overdue_principal_balance=float(
                                c.overdue_principal_balance
                            ),
                            days_overdue_at_cutoff=c.days_overdue_at_cutoff,
                            overdue_installments=c.overdue_installments,
                            pending_installments=c.pending_installments,
                            currency_code=currency_code,
                        )
                        for c in credit_models
                    ]

        campaign_info: WhatsAppChatCampaignInfo | None = None
        if chat.campaign_id is not None:
            campaign = await self._campaign_repo.get_by_id_and_organization_id(
                chat.campaign_id, organization_id
            )
            if campaign is not None:
                campaign_info = WhatsAppChatCampaignInfo(
                    id=campaign.id, name=campaign.name, status=campaign.status
                )

        return WhatsAppChatDetailsResponse(
            debtor=debtor_response,
            is_self_registered=is_self_registered,
            portfolio=portfolio_info,
            campaign=campaign_info,
            credits=credits,
        )
