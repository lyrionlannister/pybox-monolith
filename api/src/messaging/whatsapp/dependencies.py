"""Dependencias de FastAPI para inyectar los servicios de WhatsApp."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.support.services.support_service import SupportService
from core.database.database import get_main_session
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.templates.repository.template_repository import TemplateRepository
from messaging.whatsapp.repository.whatsapp_channel_request_repository import (
    WhatsAppChannelRequestRepository,
)
from messaging.whatsapp.repository.whatsapp_chat_repository import (
    WhatsAppChatRepository,
)
from messaging.whatsapp.repository.whatsapp_message_repository import (
    WhatsAppMessageRepository,
)
from messaging.whatsapp.repository.whatsapp_org_credentials_repository import (
    WhatsAppOrgCredentialsRepository,
)
from messaging.whatsapp.repository.whatsapp_send_error_repository import (
    WhatsAppSendErrorRepository,
)
from messaging.whatsapp.repository.whatsapp_template_data_repository import (
    WhatsAppTemplateDataRepository,
)
from messaging.whatsapp.services.whatsapp_assignment_service import (
    WhatsAppAssignmentService,
)
from messaging.whatsapp.services.whatsapp_channel_request_service import (
    WhatsAppChannelRequestService,
)
from messaging.whatsapp.services.whatsapp_chat_service import WhatsAppChatService
from messaging.whatsapp.services.whatsapp_client import WhatsAppCloudClient
from messaging.whatsapp.services.whatsapp_credentials_service import (
    WhatsAppCredentialsService,
)
from messaging.whatsapp.services.whatsapp_error_service import WhatsAppErrorService
from messaging.whatsapp.services.whatsapp_number_request_service import (
    WhatsAppNumberRequestService,
)
from messaging.whatsapp.services.whatsapp_template_service import (
    WhatsAppTemplateService,
)
from messaging.whatsapp.services.whatsapp_webhook_service import WhatsAppWebhookService
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)


def get_whatsapp_client() -> WhatsAppCloudClient:
    return WhatsAppCloudClient()


def get_whatsapp_credentials_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
) -> WhatsAppCredentialsService:
    return WhatsAppCredentialsService(WhatsAppOrgCredentialsRepository(session))


def get_whatsapp_template_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
    client: Annotated[WhatsAppCloudClient, Depends(get_whatsapp_client)],
) -> WhatsAppTemplateService:
    return WhatsAppTemplateService(
        template_repo=TemplateRepository(session),
        data_repo=WhatsAppTemplateDataRepository(session),
        portfolio_repo=PortfolioRepository(session),
        client=client,
    )


def get_whatsapp_channel_request_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
) -> WhatsAppChannelRequestService:
    return WhatsAppChannelRequestService(WhatsAppChannelRequestRepository(session))


def get_whatsapp_assignment_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
) -> WhatsAppAssignmentService:
    return WhatsAppAssignmentService(
        WhatsAppChatRepository(session),
        PermissionAssignmentRepository(session),
        PortfolioUserAccessRepository(session),
    )


def get_whatsapp_chat_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
    client: Annotated[WhatsAppCloudClient, Depends(get_whatsapp_client)],
) -> WhatsAppChatService:
    return WhatsAppChatService(
        WhatsAppChatRepository(session),
        WhatsAppMessageRepository(session),
        PortfolioUserAccessRepository(session),
        WhatsAppOrgCredentialsRepository(session),
        client,
        DebtorRepository(session),
        CreditRepository(session),
        PortfolioRepository(session),
        CampaignRepository(session),
        UserRepository(session),
        OrganizationRepository(session),
        OrganizationMembershipRepository(session),
    )


def get_whatsapp_error_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
) -> WhatsAppErrorService:
    return WhatsAppErrorService(WhatsAppSendErrorRepository(session))


def get_whatsapp_webhook_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
    assignment_service: Annotated[
        WhatsAppAssignmentService, Depends(get_whatsapp_assignment_service)
    ],
) -> WhatsAppWebhookService:
    return WhatsAppWebhookService(
        credentials_repo=WhatsAppOrgCredentialsRepository(session),
        contact_repo=ContactRepository(session),
        error_repo=WhatsAppSendErrorRepository(session),
        chat_repo=WhatsAppChatRepository(session),
        message_repo=WhatsAppMessageRepository(session),
        assignment_service=assignment_service,
    )


def get_whatsapp_number_request_service(
    session: Annotated[AsyncSession, Depends(get_main_session)],
) -> WhatsAppNumberRequestService:
    return WhatsAppNumberRequestService(
        WhatsAppOrgCredentialsRepository(session), SupportService(session)
    )


WhatsAppNumberRequestServiceDep = Annotated[
    WhatsAppNumberRequestService, Depends(get_whatsapp_number_request_service)
]
WhatsAppCredentialsServiceDep = Annotated[
    WhatsAppCredentialsService, Depends(get_whatsapp_credentials_service)
]
WhatsAppTemplateServiceDep = Annotated[
    WhatsAppTemplateService, Depends(get_whatsapp_template_service)
]
WhatsAppChannelRequestServiceDep = Annotated[
    WhatsAppChannelRequestService, Depends(get_whatsapp_channel_request_service)
]
WhatsAppChatServiceDep = Annotated[
    WhatsAppChatService, Depends(get_whatsapp_chat_service)
]
WhatsAppErrorServiceDep = Annotated[
    WhatsAppErrorService, Depends(get_whatsapp_error_service)
]
WhatsAppWebhookServiceDep = Annotated[
    WhatsAppWebhookService, Depends(get_whatsapp_webhook_service)
]
