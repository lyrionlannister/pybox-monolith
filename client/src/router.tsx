import { lazy } from "react";
import { Navigate, useSearchParams } from "react-router";

const AuthPage = lazy(() => import("./auth/pages/auth-page").then((m) => ({ default: m.AuthPage })));
const SignUpPage = lazy(() => import("./auth/pages/sign-up-page").then((m) => ({ default: m.SignUpPage })));
const ForgotPasswordPage = lazy(() => import("./auth/pages/forgot-password-page").then((m) => ({ default: m.ForgotPasswordPage })));
const ChangePasswordPage = lazy(() => import("./profile/pages/change-password-page").then((m) => ({ default: m.ChangePasswordPage })));
const MyCompaniesPage = lazy(() => import("./companies/pages/my-companies-page").then((m) => ({ default: m.MyCompaniesPage })));
const CreateOrgPage = lazy(() => import("./companies/pages/create-org-page").then((m) => ({ default: m.CreateOrgPage })));
const CreatePortfolioPage = lazy(() => import("./companies/pages/create-portfolio-page").then((m) => ({ default: m.CreatePortfolioPage })));
const EditPortfolioPage = lazy(() => import("./companies/pages/edit-portfolio-page").then((m) => ({ default: m.EditPortfolioPage })));
const UploadInstallmentsPage = lazy(() => import("./companies/pages/upload-installments-page").then((m) => ({ default: m.UploadInstallmentsPage })));
const MyPortfoliosPage = lazy(() => import("./companies/pages/my-portfolios-page").then((m) => ({ default: m.MyPortfoliosPage })));
const PortfolioDebtorsPage = lazy(() => import("./companies/pages/portfolio-debtors-page").then((m) => ({ default: m.PortfolioDebtorsPage })));
const DebtorDetailPage = lazy(() => import("./companies/pages/debtor-detail-page").then((m) => ({ default: m.DebtorDetailPage })));
const DebtorPaymentsPage = lazy(() => import("./companies/pages/debtor-payments-page").then((m) => ({ default: m.DebtorPaymentsPage })));
const DebtorHistoryPage = lazy(() => import("./companies/pages/debtor-history-page").then((m) => ({ default: m.DebtorHistoryPage })));
const DebtorDocumentsPage = lazy(() => import("./companies/pages/debtor-documents-page").then((m) => ({ default: m.DebtorDocumentsPage })));
const DebtorStatementsPage = lazy(() => import("./companies/pages/debtor-statements-page").then((m) => ({ default: m.DebtorStatementsPage })));
const DebtorJudicialPage = lazy(() => import("./companies/pages/debtor-judicial-page").then((m) => ({ default: m.DebtorJudicialPage })));
const PortfolioSettingsPage = lazy(() => import("./companies/pages/portfolio-settings-page").then((m) => ({ default: m.PortfolioSettingsPage })));
const OrgSettingsPage = lazy(() => import("./companies/pages/org-settings-page").then((m) => ({ default: m.OrgSettingsPage })));
const PaymentMethodsPage = lazy(() => import("./companies/pages/payment-methods-page").then((m) => ({ default: m.PaymentMethodsPage })));
const PaymentGatewayCredentialsPage = lazy(() => import("./companies/pages/payment-gateway-credentials-page").then((m) => ({ default: m.PaymentGatewayCredentialsPage })));
const CreatePaymentMethodPage = lazy(() => import("./companies/pages/create-payment-method-page").then((m) => ({ default: m.CreatePaymentMethodPage })));
const EditPaymentMethodPage = lazy(() => import("./companies/pages/edit-payment-method-page").then((m) => ({ default: m.EditPaymentMethodPage })));
const BillingPage = lazy(() => import("./billing/pages/billing-page").then((m) => ({ default: m.BillingPage })));
const BillingInvoiceDetailPage = lazy(() => import("./billing/pages/billing-invoice-detail-page").then((m) => ({ default: m.BillingInvoiceDetailPage })));
const BillingAdminPage = lazy(() => import("./billing/pages/billing-admin-page").then((m) => ({ default: m.BillingAdminPage })));
const HomePage = lazy(() => import("./home/pages/home-page").then((m) => ({ default: m.HomePage })));
const MyCreditsPage = lazy(() => import("./credits/pages/my-credits-page").then((m) => ({ default: m.MyCreditsPage })));
const MyStatementsPage = lazy(() => import("./credits/pages/my-statements-page").then((m) => ({ default: m.MyStatementsPage })));
const CreditDetailPage = lazy(() => import("./credits/pages/credit-detail-page").then((m) => ({ default: m.CreditDetailPage })));
const PaymentRedirectReturnPage = lazy(() => import("./credits/pages/payment-redirect-return-page").then((m) => ({ default: m.PaymentRedirectReturnPage })));
const NotificationDetailPage = lazy(() => import("./notifications/pages/notification-detail-page").then((m) => ({ default: m.NotificationDetailPage })));
const NotificationsPage = lazy(() => import("./notifications/pages/notifications-page").then((m) => ({ default: m.NotificationsPage })));
const ProfilePhotoPage = lazy(() => import("./profile/pages/profile-photo-page").then((m) => ({ default: m.ProfilePhotoPage })));
const ProfilePage = lazy(() => import("./profile/pages/profile-page").then((m) => ({ default: m.ProfilePage })));
const ProfileEditPage = lazy(() => import("./profile/pages/profile-edit-page").then((m) => ({ default: m.ProfileEditPage })));
const CreateTicketPage = lazy(() => import("./support/pages/create-ticket-page").then((m) => ({ default: m.CreateTicketPage })));
const TicketDetailPage = lazy(() => import("./support/pages/ticket-detail-page").then((m) => ({ default: m.TicketDetailPage })));
const TicketsPage = lazy(() => import("./support/pages/tickets-page").then((m) => ({ default: m.TicketsPage })));
const FileViewerPage = lazy(() => import("./support/pages/file-viewer-page").then((m) => ({ default: m.FileViewerPage })));
const UsersPage = lazy(() => import("./users/pages/users-page").then((m) => ({ default: m.UsersPage })));
const UserDetailPage = lazy(() => import("./users/pages/user-detail-page").then((m) => ({ default: m.UserDetailPage })));
const UserEditPage = lazy(() => import("./users/pages/user-edit-page").then((m) => ({ default: m.UserEditPage })));
const UserSettingsPage = lazy(() => import("./users/pages/user-settings-page").then((m) => ({ default: m.UserSettingsPage })));
const CompanyRolesPage = lazy(() => import("./users/pages/company-roles-page").then((m) => ({ default: m.CompanyRolesPage })));
const UserPortfoliosPage = lazy(() => import("./users/pages/user-portfolios-page").then((m) => ({ default: m.UserPortfoliosPage })));
const CreateUserPage = lazy(() => import("./users/pages/create-user-page").then((m) => ({ default: m.CreateUserPage })));
const ChatPage = lazy(() => import("./chat/pages/chat-page").then((m) => ({ default: m.ChatPage })));
const WhatsAppChatsPage = lazy(() => import("./whatsapp/pages/whatsapp-chats-page").then((m) => ({ default: m.WhatsAppChatsPage })));
const CommunicationsHubPage = lazy(() => import("./companies/pages/communications-hub-page").then((m) => ({ default: m.CommunicationsHubPage })));
const SegmentsPage = lazy(() => import("./segments/pages/segments-page").then((m) => ({ default: m.SegmentsPage })));
const ReportsPage = lazy(() => import("./reports/pages/reports-page").then((m) => ({ default: m.ReportsPage })));
const TemplatesPage = lazy(() => import("./templates/pages/templates-page").then((m) => ({ default: m.TemplatesPage })));
const TemplateEditorPage = lazy(() => import("./templates/pages/template-editor-page").then((m) => ({ default: m.TemplateEditorPage })));
const CampaignsPage = lazy(() => import("./campaigns/pages/campaigns-page").then((m) => ({ default: m.CampaignsPage })));
const CampaignEditorPage = lazy(() => import("./campaigns/pages/campaign-editor-page").then((m) => ({ default: m.CampaignEditorPage })));
const IvrDesignerPage = lazy(() => import("./ivr/pages/ivr-designer-page").then((m) => ({ default: m.IvrDesignerPage })));
const IvrMonitorPage = lazy(() => import("./ivr/monitor/pages/ivr-monitor-page").then((m) => ({ default: m.IvrMonitorPage })));
const IvrReportPage = lazy(() => import("./ivr/monitor/pages/ivr-report-page").then((m) => ({ default: m.IvrReportPage })));
const BulkSendPage = lazy(() => import("./bulk-send/pages/bulk-send-page").then((m) => ({ default: m.BulkSendPage })));
const BoldPaymentResultPage = lazy(() => import("./billing/pages/bold-payment-result-page").then((m) => ({ default: m.BoldPaymentResultPage })));
const DatabaseExplorerPage = lazy(() => import("./databases/pages/database-explorer-page").then((m) => ({ default: m.DatabaseExplorerPage })));
const CreateTablePage = lazy(() => import("./databases/pages/create-table-page").then((m) => ({ default: m.CreateTablePage })));
const AlterTablePage = lazy(() => import("./databases/pages/alter-table-page").then((m) => ({ default: m.AlterTablePage })));
const MessagingCredentialsPage = lazy(() => import("./messaging-credentials/pages/messaging-credentials-page").then((m) => ({ default: m.MessagingCredentialsPage })));
const PlatformGatewayCredentialsPage = lazy(() => import("./platform-gateway-credentials/pages/platform-gateway-credentials-page").then((m) => ({ default: m.PlatformGatewayCredentialsPage })));
const PlatformBrandingPage = lazy(() => import("./companies/pages/platform-branding-page").then((m) => ({ default: m.PlatformBrandingPage })));
const NotFound = lazy(() => import("./ui/pages/not-found").then((m) => ({ default: m.NotFound })));

const DebtorsRoute: React.FC = () => {
  const [searchParams] = useSearchParams();
  return searchParams.get("clientId") ? <DebtorDetailPage /> : <PortfolioDebtorsPage />;
};

const BillingRoute: React.FC = () => {
  const [searchParams] = useSearchParams();
  return searchParams.get("invoice") ? <BillingInvoiceDetailPage /> : <BillingPage />;
};

const BillingAdminRoute: React.FC = () => {
  const [searchParams] = useSearchParams();
  return searchParams.get("invoice") ? <BillingInvoiceDetailPage /> : <BillingAdminPage />;
};

export const noAuthRouter = [
  {
    path: "/admin/sign-in",
    element: <AuthPage />,
  },
  {
    path: "/admin/sign-up",
    element: <SignUpPage />,
  },
  {
    path: "/admin/forgot-password",
    element: <ForgotPasswordPage />,
  },
  {
    path: "/billing/payment-result",
    element: <BoldPaymentResultPage />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

export const authRouter = [
  {
    path: "/",
    element: <Navigate to="/home" replace />,
  },
  {
    path: "/home",
    element: <HomePage />,
  },
  {
    path: "/my-credits",
    element: <MyCreditsPage />,
  },
  {
    path: "/my-credits/:creditId",
    element: <CreditDetailPage />,
  },
  {
    path: "/credits/payments/payment-return",
    element: <PaymentRedirectReturnPage />,
  },
  {
    path: "/my-statements",
    element: <MyStatementsPage />,
  },
  {
    path: "/profile",
    element: <ProfilePage />,
  },
  {
    path: "/profile/edit",
    element: <ProfileEditPage />,
  },
  {
    path: "/profile/photo",
    element: <ProfilePhotoPage />,
  },
  {
    path: "/profile/change-password",
    element: <ChangePasswordPage />,
  },
  {
    path: "/my-companies",
    element: <MyCompaniesPage />,
  },
  {
    path: "/my-companies/add",
    element: <CreateOrgPage />,
  },
  {
    path: "/my-companies/portfolios",
    element: <MyPortfoliosPage />,
  },
  {
    path: "/my-companies/add-portfolio",
    element: <CreatePortfolioPage />,
  },
  {
    path: "/my-companies/portfolios/upload/append",
    element: <EditPortfolioPage />,
  },
  {
    path: "/my-companies/portfolios/upload/update",
    element: <EditPortfolioPage />,
  },
  {
    path: "/my-companies/portfolios/upload/installments",
    element: <UploadInstallmentsPage />,
  },
  {
    path: "/my-companies/portfolios/debtors",
    element: <DebtorsRoute />,
  },
  {
    path: "/my-companies/portfolios/debtors/payments",
    element: <DebtorPaymentsPage />,
  },
  {
    path: "/my-companies/portfolios/debtors/history",
    element: <DebtorHistoryPage />,
  },
  {
    path: "/my-companies/portfolios/debtors/documents",
    element: <DebtorDocumentsPage />,
  },
  {
    path: "/my-companies/portfolios/debtors/statements",
    element: <DebtorStatementsPage />,
  },
  {
    path: "/my-companies/portfolios/debtors/judicial",
    element: <DebtorJudicialPage />,
  },
  {
    path: "/my-companies/portfolios/settings",
    element: <PortfolioSettingsPage />,
  },
  {
    path: "/my-companies/portfolios/communications",
    element: <CommunicationsHubPage />,
  },
  {
    path: "/my-companies/portfolios/segments",
    element: <SegmentsPage />,
  },
  {
    path: "/my-companies/settings",
    element: <OrgSettingsPage />,
  },
  {
    path: "/my-companies/payment-methods",
    element: <PaymentMethodsPage />,
  },
  {
    path: "/my-companies/payment-gateway-credentials",
    element: <PaymentGatewayCredentialsPage />,
  },
  {
    path: "/my-companies/reports",
    element: <ReportsPage />,
  },
  {
    path: "/my-companies/payment-methods/new",
    element: <CreatePaymentMethodPage />,
  },
  {
    path: "/my-companies/payment-methods/:id/edit",
    element: <EditPaymentMethodPage />,
  },
  {
    path: "/my-companies/billing",
    element: <BillingRoute />,
  },
  {
    path: "/billing",
    element: <BillingAdminRoute />,
  },
  {
    path: "/my-companies/templates",
    element: <TemplatesPage />,
  },
  {
    path: "/my-companies/templates/new",
    element: <TemplateEditorPage />,
  },
  {
    path: "/my-companies/templates/:id/edit",
    element: <TemplateEditorPage />,
  },
  {
    path: "/my-companies/campaigns",
    element: <CampaignsPage />,
  },
  {
    path: "/my-companies/bulk-send",
    element: <BulkSendPage />,
  },
  {
    path: "/my-companies/campaigns/new",
    element: <CampaignEditorPage />,
  },
  {
    path: "/my-companies/campaigns/:id/edit",
    element: <CampaignEditorPage />,
  },
  {
    path: "/my-companies/campaigns/ivr",
    element: <IvrDesignerPage />,
  },
  {
    path: "/my-companies/campaigns/:id/monitor",
    element: <IvrMonitorPage />,
  },
  {
    path: "/my-companies/campaigns/:id/results",
    element: <IvrReportPage />,
  },
  {
    path: "/my-users",
    element: <UsersPage />,
  },
  {
    path: "/my-companies/users",
    element: <UsersPage />,
  },
  {
    path: "/my-companies/company-roles",
    element: <CompanyRolesPage />,
  },
  {
    path: "/my-users/add",
    element: <CreateUserPage />,
  },
  {
    path: "/my-users/:id",
    element: <UserDetailPage />,
  },
  {
    path: "/my-users/:id/edit",
    element: <UserEditPage />,
  },
  {
    path: "/my-users/:id/settings",
    element: <UserSettingsPage />,
  },
  {
    path: "/my-users/:id/portfolios",
    element: <UserPortfoliosPage />,
  },
  {
    path: "/notifications",
    element: <NotificationsPage />,
  },
  {
    path: "/notifications/:id",
    element: <NotificationDetailPage />,
  },
  {
    path: "/chats",
    element: <ChatPage />,
  },
  {
    path: "/my-companies/whatsapp/chats",
    element: <WhatsAppChatsPage />,
  },
  {
    path: "/cs/tickets",
    element: <TicketsPage />,
  },
  {
    path: "/cs/tickets/new",
    element: <CreateTicketPage />,
  },
  {
    path: "/cs/tickets/:id",
    element: <TicketDetailPage />,
  },
  {
    path: "/files/viewer",
    element: <FileViewerPage />,
  },
  {
    path: "/databases",
    element: <DatabaseExplorerPage />,
  },
  {
    path: "/databases/tables/new",
    element: <CreateTablePage />,
  },
  {
    path: "/databases/tables/alter",
    element: <AlterTablePage />,
  },
  {
    path: "/messaging-credentials",
    element: <MessagingCredentialsPage />,
  },
  {
    path: "/platform-gateway-credentials",
    element: <PlatformGatewayCredentialsPage />,
  },
  {
    path: "/platform/branding",
    element: <PlatformBrandingPage />,
  },
];
