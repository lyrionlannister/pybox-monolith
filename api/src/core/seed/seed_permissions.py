"""Crea o actualiza el catálogo de permisos base y sus asignaciones por rol."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.security.constants.permissions import (
    MANAGE_WHATSAPP_CHATS,
    ORG_BILLING,
    ORG_CAMPAIGNS,
    ORG_PAYMENT_METHODS,
    ORG_PORTFOLIOS,
    ORG_REPORTS,
    ORG_TEMPLATES,
    ORG_USERS,
    PORTFOLIO_CLIENTS,
    PORTFOLIO_COMMUNICATIONS,
    PORTFOLIO_UPLOAD_NEW,
    PORTFOLIO_UPLOAD_UPDATE,
)
from identity.users.models.permission_model import PermissionModel

_PERMISSIONS: list[tuple[str, str]] = [
    (ORG_PORTFOLIOS, "Mis Portafolios"),
    (ORG_PAYMENT_METHODS, "Métodos de Pago"),
    (ORG_REPORTS, "Reportes"),
    (ORG_USERS, "Usuarios"),
    (ORG_CAMPAIGNS, "Campañas"),
    (ORG_TEMPLATES, "Plantillas"),
    (ORG_BILLING, "Facturación"),
    (PORTFOLIO_CLIENTS, "Clientes"),
    (PORTFOLIO_UPLOAD_NEW, "Subir nuevos clientes"),
    (PORTFOLIO_UPLOAD_UPDATE, "Actualizar clientes"),
    (PORTFOLIO_COMMUNICATIONS, "Comunicaciones"),
    (MANAGE_WHATSAPP_CHATS, "Chats de WhatsApp"),
]


async def seed_permissions(session: AsyncSession) -> None:
    existing = {
        row[0] for row in (await session.execute(select(PermissionModel.name))).all()
    }
    new_permissions = []
    for name, label in _PERMISSIONS:
        if name not in existing:
            new_permissions.append(PermissionModel(name=name, label=label))
        else:
            await session.execute(
                update(PermissionModel)
                .where(PermissionModel.name == name)
                .values(label=label)
            )
    if new_permissions:
        session.add_all(new_permissions)
