"""Registro central de todos los routers de la API bajo el prefijo /api/v1."""

from fastapi import FastAPI

from app_platform.branding.controllers.platform_branding_controller import (
    router as platform_branding_router,
)
from app_platform.chats.controllers.chat_controller import router as chats_router
from app_platform.countries.controllers.countries_controller import (
    router as countries_router,
)
from app_platform.dashboard.controllers.dashboard_controller import (
    router as dashboard_router,
)
from app_platform.documents.controllers.admin_document_controller import (
    router as admin_documents_router,
)
from app_platform.notifications.controllers.notification_controller import (
    router as notifications_router,
)
from app_platform.schema_manager.controllers.database_controller import (
    router as schema_manager_router,
)
from app_platform.support.controllers.support_controller import router as support_router
from billing.billing_dashboard.controllers.billing_dashboard_controller import (
    router as billing_dashboard_router,
)
from billing.billing_status.controllers.billing_status_controller import (
    router as billing_status_router,
)
from billing.bold.controllers.bold_webhook_controller import (
    router as billing_bold_webhook_router,
)
from billing.invoices.controllers.invoice_controller import router as invoices_router
from billing.mercadopago.controllers.mercadopago_webhook_controller import (
    router as mercadopago_webhook_router,
)
from billing.provider_credentials.controllers.provider_credential_controller import (
    router as platform_gateway_credentials_router,
)
from identity.auth.controllers.auth_controller import router as auth_router
from identity.onboarding.controllers.onboarding_controller import (
    router as onboarding_router,
)
from identity.organizations.controllers.org_members_controller import (
    router as org_members_router,
)
from identity.organizations.controllers.organization_controller import (
    router as organizations_router,
)
from identity.users.controllers.company_roles_controller import (
    router as company_roles_router,
)
from identity.users.controllers.global_users_controller import (
    router as global_users_router,
)
from identity.users.controllers.permissions_controller import (
    router as permissions_router,
)
from identity.users.controllers.user_controller import router as users_router
from messaging.bulk_send.controllers.bulk_send_controller import (
    router as bulk_send_router,
)
from messaging.campaigns.controllers.campaign_controller import (
    router as campaigns_router,
)
from messaging.channels.controllers.channel_controller import router as channels_router
from messaging.contacts.controllers.contact_controller import router as contacts_router
from messaging.ivr.controllers.audio_controller import router as ivr_audios_router
from messaging.ivr.controllers.contact_policy_controller import (
    router as ivr_contact_policy_router,
)
from messaging.ivr.controllers.helena_webhook_controller import (
    router as helena_webhook_router,
)
from messaging.ivr.controllers.ivr_control_controller import (
    router as ivr_control_router,
)
from messaging.ivr.controllers.ivr_flow_controller import router as ivr_flows_router
from messaging.ivr.controllers.ivr_monitor_controller import (
    router as ivr_monitor_router,
)
from messaging.ivr.controllers.ivr_report_controller import router as ivr_report_router
from messaging.ivr.controllers.test_call_controller import (
    router as ivr_test_call_router,
)
from messaging.provider_credentials.controllers.provider_credential_controller import (
    router as messaging_credentials_router,
)
from messaging.results.controllers.results_controller import router as results_router
from messaging.templates.controllers.template_controller import (
    router as templates_router,
)
from messaging.whatsapp.controllers.whatsapp_channel_request_controller import (
    router as whatsapp_channel_requests_router,
)
from messaging.whatsapp.controllers.whatsapp_chat_controller import (
    router as whatsapp_chats_router,
)
from messaging.whatsapp.controllers.whatsapp_credentials_controller import (
    router as whatsapp_credentials_router,
)
from messaging.whatsapp.controllers.whatsapp_error_controller import (
    router as whatsapp_errors_router,
)
from messaging.whatsapp.controllers.whatsapp_template_controller import (
    router as whatsapp_templates_router,
)
from messaging.whatsapp.controllers.whatsapp_webhook_controller import (
    router as whatsapp_webhook_router,
)
from receivables.credits.controllers.credit_catalog_controller import (
    router as credit_catalog_router,
)
from receivables.credits.controllers.credit_selfservice_controller import (
    router as credit_selfservice_router,
)
from receivables.credits.controllers.my_credits_controller import (
    router as my_credits_router,
)
from receivables.debtors.controllers.debtor_controller import router as debtors_router
from receivables.debtors.controllers.debtor_identity_controller import (
    router as debtor_identity_router,
)
from receivables.debtors.controllers.my_documents_controller import (
    router as my_debtor_documents_router,
)

# pylint: disable-next=line-too-long
from receivables.judicial_notifications.controllers.judicial_notification_controller import (
    router as judicial_notifications_router,
)
from receivables.payment_gateways.controllers.bold_webhook_controller import (
    router as receivables_bold_webhook_router,
)
from receivables.payment_gateways.controllers.epayco_webhook_controller import (
    router as epayco_webhook_router,
)
from receivables.payment_gateways.controllers.payment_checkout_controller import (
    router as payment_checkout_router,
)
from receivables.payment_gateways.controllers.payu_webhook_controller import (
    router as payu_webhook_router,
)

# pylint: disable-next=line-too-long
from receivables.payment_gateways.controllers.payment_gateway_credential_controller import (
    router as payment_gateway_credentials_router,
)
from receivables.payment_gateways.controllers.wompi_webhook_controller import (
    router as wompi_webhook_router,
)
from receivables.payment_methods.controllers.payment_method_controller import (
    router as payment_methods_router,
)
from receivables.payments.controllers.payment_catalog_controller import (
    router as payment_catalog_router,
)
from receivables.payments.controllers.payment_selfservice_controller import (
    router as payment_selfservice_router,
)
from receivables.portfolios.controllers.csv_template_controller import (
    router as csv_templates_router,
)
from receivables.portfolios.controllers.installment_controller import (
    router as installments_router,
)
from receivables.portfolios.controllers.portfolio_controller import (
    router as portfolios_router,
)
from receivables.reports.controllers.report_controller import router as reports_router
from receivables.segments.controllers.segment_controller import (
    router as segments_router,
)
from receivables.statements.controllers.my_statements_controller import (
    router as my_statements_router,
)
from receivables.statements.controllers.statement_controller import (
    router as statements_router,
)

API_PREFIX = "/api/v1"


def register_routers(app: FastAPI) -> None:
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(platform_branding_router, prefix=API_PREFIX)
    app.include_router(invoices_router, prefix=API_PREFIX)
    app.include_router(dashboard_router, prefix=API_PREFIX)
    app.include_router(billing_dashboard_router, prefix=API_PREFIX)
    app.include_router(billing_bold_webhook_router, prefix=API_PREFIX)
    app.include_router(mercadopago_webhook_router, prefix=API_PREFIX)
    app.include_router(billing_status_router, prefix=API_PREFIX)
    app.include_router(contacts_router, prefix=API_PREFIX)
    app.include_router(admin_documents_router, prefix=API_PREFIX)
    app.include_router(debtors_router, prefix=API_PREFIX)
    app.include_router(debtor_identity_router, prefix=API_PREFIX)
    app.include_router(my_debtor_documents_router, prefix=API_PREFIX)
    app.include_router(countries_router, prefix=API_PREFIX)
    app.include_router(messaging_credentials_router, prefix=API_PREFIX)
    app.include_router(platform_gateway_credentials_router, prefix=API_PREFIX)
    app.include_router(payment_gateway_credentials_router, prefix=API_PREFIX)
    app.include_router(payment_checkout_router, prefix=API_PREFIX)
    app.include_router(wompi_webhook_router, prefix=API_PREFIX)
    app.include_router(receivables_bold_webhook_router, prefix=API_PREFIX)
    app.include_router(epayco_webhook_router, prefix=API_PREFIX)
    app.include_router(payu_webhook_router, prefix=API_PREFIX)
    app.include_router(credit_catalog_router, prefix=API_PREFIX)
    app.include_router(judicial_notifications_router, prefix=API_PREFIX)
    app.include_router(my_credits_router, prefix=API_PREFIX)
    app.include_router(credit_selfservice_router, prefix=API_PREFIX)
    app.include_router(payment_catalog_router, prefix=API_PREFIX)
    app.include_router(payment_selfservice_router, prefix=API_PREFIX)
    app.include_router(notifications_router, prefix=API_PREFIX)
    app.include_router(onboarding_router, prefix=API_PREFIX)
    app.include_router(organizations_router, prefix=API_PREFIX)
    app.include_router(org_members_router, prefix=API_PREFIX)
    app.include_router(payment_methods_router, prefix=API_PREFIX)
    app.include_router(portfolios_router, prefix=API_PREFIX)
    app.include_router(installments_router, prefix=API_PREFIX)
    app.include_router(csv_templates_router, prefix=API_PREFIX)
    app.include_router(chats_router, prefix=API_PREFIX)
    app.include_router(support_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(global_users_router, prefix=API_PREFIX)
    app.include_router(permissions_router, prefix=API_PREFIX)
    app.include_router(company_roles_router, prefix=API_PREFIX)
    app.include_router(schema_manager_router, prefix=API_PREFIX)
    app.include_router(segments_router, prefix=API_PREFIX)
    app.include_router(reports_router, prefix=API_PREFIX)
    app.include_router(statements_router, prefix=API_PREFIX)
    app.include_router(my_statements_router, prefix=API_PREFIX)
    app.include_router(campaigns_router, prefix=API_PREFIX)
    app.include_router(channels_router, prefix=API_PREFIX)
    app.include_router(ivr_flows_router, prefix=API_PREFIX)
    app.include_router(ivr_audios_router, prefix=API_PREFIX)
    app.include_router(ivr_test_call_router, prefix=API_PREFIX)
    app.include_router(helena_webhook_router, prefix=API_PREFIX)
    app.include_router(ivr_monitor_router, prefix=API_PREFIX)
    app.include_router(ivr_report_router, prefix=API_PREFIX)
    app.include_router(ivr_control_router, prefix=API_PREFIX)
    app.include_router(ivr_contact_policy_router, prefix=API_PREFIX)
    app.include_router(templates_router, prefix=API_PREFIX)
    app.include_router(results_router, prefix=API_PREFIX)
    app.include_router(bulk_send_router, prefix=API_PREFIX)
    app.include_router(whatsapp_templates_router, prefix=API_PREFIX)
    app.include_router(whatsapp_webhook_router, prefix=API_PREFIX)
    app.include_router(whatsapp_errors_router, prefix=API_PREFIX)
    app.include_router(whatsapp_chats_router, prefix=API_PREFIX)
    app.include_router(whatsapp_credentials_router, prefix=API_PREFIX)
    app.include_router(whatsapp_channel_requests_router, prefix=API_PREFIX)
