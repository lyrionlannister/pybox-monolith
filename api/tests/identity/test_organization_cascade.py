"""Baja lógica de una organización: arrastra membresías, roles, permisos y portafolios
(con sus créditos y campañas). Los usuarios NO se eliminan: quedan sin organización.
`restore_organization` revierte solo lo que cayó con ella.
"""

from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.organizations.services.organization_service import OrganizationService
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.models.segment_model import SegmentModel
from receivables.segments.repository.segment_repository import SegmentRepository
from tests.messaging.campaigns.conftest import build_campaign, get_channel_id
from tests.receivables.conftest import (
    add_organization,
    build_credit,
    build_debtor,
    build_portfolio,
    real_admin_user_id,
)


def build_service(db_session) -> OrganizationService:
    return OrganizationService(
        org_repo=OrganizationRepository(db_session),
        membership_repo=OrganizationMembershipRepository(db_session),
        role_assignment_repo=RoleAssignmentRepository(db_session),
        user_repo=UserRepository(db_session),
    )


async def _organization_with_everything(db_session, user_id):
    org = await add_organization(db_session)
    portfolio = build_portfolio(org.id)
    debtor = build_debtor(org.id)
    db_session.add_all([portfolio, debtor])
    await db_session.flush()
    credit = build_credit(portfolio.id, debtor.id)
    campaign = build_campaign(portfolio.id, await get_channel_id(db_session))
    segment = SegmentModel(
        name="Segmento X", filter_criteria={}, portfolio_id=portfolio.id
    )
    membership = OrganizationMembershipModel(
        user_id=user_id, organization_id=org.id, created_by=user_id
    )
    role = RoleAssignmentModel(
        user_id=user_id,
        role=UserRole.ADMIN,
        scope=UserScope.ORGANIZATION,
        organization_id=org.id,
    )
    db_session.add_all([credit, campaign, segment, membership, role])
    await db_session.flush()
    return org, portfolio, credit, campaign, segment


class TestSoftDeleteOrganizationCascade:
    async def test_cascades_to_members_roles_portfolios_credits_campaigns_and_segments(
        self, db_session, real_admin_user_id
    ):
        org, portfolio, credit, campaign, segment = await _organization_with_everything(
            db_session, real_admin_user_id
        )

        await build_service(db_session).soft_delete_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura

        assert await OrganizationRepository(db_session).get_by_id(org.id) is None
        assert (
            await OrganizationMembershipRepository(db_session).get_by_organization_id(
                org.id
            )
            == []
        )
        assert (
            await RoleAssignmentRepository(db_session).get_admin_org_ids(
                real_admin_user_id
            )
            == []
        )
        assert await PortfolioRepository(db_session).get_by_id(portfolio.id) is None
        assert await CreditRepository(db_session).get_by_id(credit.id) is None
        assert await CampaignRepository(db_session).get_by_id(campaign.id) is None
        assert await SegmentRepository(db_session).get_by_id(segment.id) is None

    async def test_users_are_kept_without_an_organization(
        self, db_session, real_admin_user_id
    ):
        org, *_ = await _organization_with_everything(db_session, real_admin_user_id)

        await build_service(db_session).soft_delete_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura

        assert (
            await UserRepository(db_session).get_by_id(real_admin_user_id) is not None
        )
        assert (
            await OrganizationMembershipRepository(db_session).get_by_user_id(
                real_admin_user_id
            )
            == []
        )


class TestRestoreOrganizationCascade:
    async def test_restores_everything_that_fell_with_the_organization(
        self, db_session, real_admin_user_id
    ):
        org, portfolio, credit, campaign, segment = await _organization_with_everything(
            db_session, real_admin_user_id
        )
        service = build_service(db_session)
        await service.soft_delete_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura

        await service.restore_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura

        assert await OrganizationRepository(db_session).get_by_id(org.id) is not None
        assert (
            len(
                await OrganizationMembershipRepository(
                    db_session
                ).get_by_organization_id(org.id)
            )
            == 1
        )
        assert await RoleAssignmentRepository(db_session).get_admin_org_ids(
            real_admin_user_id
        ) == [org.id]
        assert await PortfolioRepository(db_session).get_by_id(portfolio.id) is not None
        assert await CreditRepository(db_session).get_by_id(credit.id) is not None
        assert await CampaignRepository(db_session).get_by_id(campaign.id) is not None
        assert await SegmentRepository(db_session).get_by_id(segment.id) is not None

    async def test_does_not_restore_a_portfolio_deleted_before_the_organization(
        self, db_session, real_admin_user_id
    ):
        org, _, _, _, _ = await _organization_with_everything(
            db_session, real_admin_user_id
        )
        old_portfolio = build_portfolio(org.id)
        db_session.add(old_portfolio)
        await db_session.flush()
        portfolio_repo = PortfolioRepository(db_session)
        await portfolio_repo.delete(old_portfolio)  # baja anterior, con su propio sello

        service = build_service(db_session)
        await service.soft_delete_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura
        await service.restore_organization(org.id)
        db_session.expunge_all()  # el UPDATE en bloque no refresca lo ya cargado: forzar relectura

        assert await portfolio_repo.get_by_id(old_portfolio.id) is None
