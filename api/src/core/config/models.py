"""Registro de todos los modelos en `Base.metadata` para que Alembic los detecte.

Cada import de este archivo es puramente por su efecto secundario y no se usa
directamente, de ahí el `disable=unused-import` a nivel de módulo.
"""

# pylint: disable=unused-import

import app_platform.branding.models.platform_branding_model
import app_platform.chats.models.chat_member_model
import app_platform.chats.models.chat_model
import app_platform.chats.models.message_model
import app_platform.chats.models.message_status_model
import app_platform.countries.models.country_document_type_model
import app_platform.countries.models.country_model
import app_platform.countries.models.document_type_model
import app_platform.documents.models.document_model
import app_platform.notifications.models.notification_model
import app_platform.support.models.support_ticket_event_model
import app_platform.support.models.support_ticket_message_model
import app_platform.support.models.support_ticket_model
import app_platform.support.models.ticket_document_model
import billing.invoices.models.invoice_item_model
import billing.invoices.models.invoice_model
import billing.invoices.models.payment_attempt_model
import billing.provider_credentials.models.provider_credential_model
import identity.auth.models.verification_code_model
import identity.organizations.models.organization_membership_model
import identity.organizations.models.organization_model
import identity.users.models.company_role_model
import identity.users.models.company_role_permission_model
import identity.users.models.permission_assignment_model
import identity.users.models.permission_model
import identity.users.models.role_assignment_model
import identity.users.models.user_company_role_model
import identity.users.models.user_model
import identity.users.models.user_preferences_model
import messaging.campaigns.models.campaign_model
import messaging.campaigns.models.campaign_result_model
import messaging.campaigns.models.campaign_time_model
import messaging.channels.models.channel_model
import messaging.contacts.models.contact_model
import messaging.ivr.models.ivr_execution_model
import messaging.ivr.models.ivr_flow_model
import messaging.ivr.models.ivr_interaction_model
import messaging.provider_credentials.models.provider_credential_model
import messaging.templates.models.template_model
import messaging.whatsapp.models.whatsapp_channel_request_model
import messaging.whatsapp.models.whatsapp_chat_model
import messaging.whatsapp.models.whatsapp_message_model
import messaging.whatsapp.models.whatsapp_org_credentials_model
import messaging.whatsapp.models.whatsapp_send_error_model
import messaging.whatsapp.models.whatsapp_template_data_model
import receivables.contact_methods.models.contact_method_model
import receivables.credits.models.credit_adjustment_model
import receivables.credits.models.credit_model
import receivables.credits.models.credit_settlement_ticket_model
import receivables.credits.models.uvr_quote_model
import receivables.debtors.models.address_model
import receivables.debtors.models.debtor_document_model
import receivables.debtors.models.debtor_model
import receivables.payment_gateways.models.payment_attempt_model
import receivables.payment_gateways.models.payment_source_model
import receivables.payment_methods.models.payment_method_model
import receivables.payments.models.payment_model
import receivables.payments.models.payment_ticket_model
import receivables.portfolios.models.portfolio_daily_counter_config_model
import receivables.portfolios.models.portfolio_document_model
import receivables.portfolios.models.portfolio_model
import receivables.portfolios.models.portfolio_user_access_model
import receivables.reports.models.report_execution_model
import receivables.reports.models.report_model
import receivables.segments.models.segment_execution_model
import receivables.segments.models.segment_model
import receivables.statements.models.statement_model
from receivables.judicial_notifications.models import (
    judicial_notification_document_model,
)
from receivables.judicial_notifications.models import judicial_notification_model
from receivables.payment_gateways.models import payment_gateway_credential_model
