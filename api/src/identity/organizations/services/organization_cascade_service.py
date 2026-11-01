"""Baja lógica en cascada de todos los datos de una organización eliminada."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.documents.repository.document_repository import DocumentRepository
from messaging.campaigns.repository.campaign_result_repository import (
    CampaignResultRepository,
)
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.ivr.repository.ivr_execution_repository import IvrExecutionRepository
from messaging.ivr.repository.ivr_flow_repository import IvrFlowRepository
from messaging.ivr.repository.ivr_interaction_repository import IvrInteractionRepository
from messaging.whatsapp.repository.whatsapp_chat_repository import (
    WhatsAppChatRepository,
)
from messaging.whatsapp.repository.whatsapp_message_repository import (
    WhatsAppMessageRepository,
)
from messaging.whatsapp.repository.whatsapp_org_credentials_repository import (
    WhatsAppOrgCredentialsRepository,
)
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.debtors.repository.address_repository import AddressRepository
from receivables.debtors.repository.debtor_document_repository import (
    DebtorDocumentRepository,
)
from receivables.debtors.repository.debtor_repository import DebtorRepository

# pylint: disable-next=line-too-long
from receivables.judicial_notifications.repository.judicial_notification_document_repository import (
    JudicialNotificationDocumentRepository,
)

# pylint: disable-next=line-too-long
from receivables.judicial_notifications.repository.judicial_notification_repository import (
    JudicialNotificationRepository,
)
from receivables.portfolios.repository.portfolio_document_repository import (
    PortfolioDocumentRepository,
)
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)
from receivables.reports.repository.report_execution_repository import (
    ReportExecutionRepository,
)
from receivables.reports.repository.report_repository import ReportRepository
from receivables.segments.repository.segment_execution_repository import (
    SegmentExecutionRepository,
)
from receivables.segments.repository.segment_repository import SegmentRepository
from receivables.statements.repository.statement_repository import StatementRepository


class OrganizationCascadeService:
    """Baja lógica (y su reversa) de los datos de una organización que no son
    membresías, roles ni portafolios: deudores y lo que cuelga de ellos, chats y
    credenciales de WhatsApp, IVR, resultados de campañas, reportes, segmentos,
    documentos y accesos a portafolios.

    Todo lleva el mismo `deleted_at` que la organización, así `restore` revierte
    solo lo que cayó con ella y no resucita filas eliminadas antes por otra vía.
    Quedan fuera a propósito las facturas y los tickets de soporte.
    """

    def __init__(self, session: AsyncSession):
        self._debtor_repo = DebtorRepository(session)
        self._contact_method_repo = ContactMethodRepository(session)
        self._address_repo = AddressRepository(session)
        self._debtor_document_repo = DebtorDocumentRepository(session)
        self._contact_repo = ContactRepository(session)
        self._statement_repo = StatementRepository(session)
        self._judicial_notification_repo = JudicialNotificationRepository(session)
        self._judicial_notification_document_repo = (
            JudicialNotificationDocumentRepository(session)
        )
        self._whatsapp_chat_repo = WhatsAppChatRepository(session)
        self._whatsapp_message_repo = WhatsAppMessageRepository(session)
        self._whatsapp_credentials_repo = WhatsAppOrgCredentialsRepository(session)
        self._ivr_flow_repo = IvrFlowRepository(session)
        self._ivr_execution_repo = IvrExecutionRepository(session)
        self._ivr_interaction_repo = IvrInteractionRepository(session)
        self._campaign_result_repo = CampaignResultRepository(session)
        self._report_repo = ReportRepository(session)
        self._report_execution_repo = ReportExecutionRepository(session)
        self._segment_repo = SegmentRepository(session)
        self._segment_execution_repo = SegmentExecutionRepository(session)
        self._document_repo = DocumentRepository(session)
        self._portfolio_document_repo = PortfolioDocumentRepository(session)
        self._portfolio_user_access_repo = PortfolioUserAccessRepository(session)

    async def soft_delete_for_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        for repo in self._repositories():
            await repo.soft_delete_by_organization(organization_id, deleted_at)

    async def restore_for_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        for repo in self._repositories():
            await repo.restore_by_organization(organization_id, deleted_at)

    def _repositories(self):
        return (
            self._debtor_repo,
            self._contact_method_repo,
            self._address_repo,
            self._debtor_document_repo,
            self._contact_repo,
            self._statement_repo,
            self._judicial_notification_repo,
            self._judicial_notification_document_repo,
            self._whatsapp_chat_repo,
            self._whatsapp_message_repo,
            self._whatsapp_credentials_repo,
            self._ivr_flow_repo,
            self._ivr_execution_repo,
            self._ivr_interaction_repo,
            self._campaign_result_repo,
            self._report_repo,
            self._report_execution_repo,
            self._segment_repo,
            self._segment_execution_repo,
            self._document_repo,
            self._portfolio_document_repo,
            self._portfolio_user_access_repo,
        )
