"""`TenantMixin` debe producir exactamente la misma columna `organization_id` que los
15 modelos migrados declaraban a mano: mismo nombre de columna, tipo, nullable, índice
y FK -- la Fase 3 de la auditoría de modelos base exige que el esquema no cambie.
"""

from receivables.debtors.models.debtor_model import DebtorModel
from receivables.portfolios.models.portfolio_model import PortfolioModel


class TestTenantMixinColumnShape:
    def test_produces_the_same_column_as_before(self):
        column = PortfolioModel.__table__.columns["id_organizacion"]

        assert column.name == "id_organizacion"
        assert not column.nullable
        assert column.index
        assert len(column.foreign_keys) == 1
        fk = next(iter(column.foreign_keys))
        assert fk.target_fullname == "entidades.id"

    def test_is_shared_across_every_migrated_model(self):
        debtor_column = DebtorModel.__table__.columns["id_organizacion"]
        portfolio_column = PortfolioModel.__table__.columns["id_organizacion"]

        assert debtor_column.type.python_type == portfolio_column.type.python_type
        assert debtor_column.nullable == portfolio_column.nullable
