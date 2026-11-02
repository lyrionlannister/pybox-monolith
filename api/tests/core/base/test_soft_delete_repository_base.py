"""Tests de `SoftDeleteRepositoryBase` contra la base de datos real: los UPDATE
masivos (`delete_many`, `restore_many`, `soft_delete_where`, `restore_where`) deben
actualizar `updated_at`, igual que el ORM lo hace fila por fila en `delete`/`restore`.

Se ejercitan con `ContactRepository` (un subtipo concreto cualquiera) porque
`SoftDeleteRepositoryBase` es abstracto y no tiene `model_class` propio.
"""

from datetime import datetime, timezone

from messaging.contacts.models.contact_model import ContactModel
from messaging.contacts.repository.contact_repository import ContactRepository
from tests.messaging.contacts.test_contact_repository import make_contact


class TestDeleteManySetsUpdatedAt:
    async def test_delete_many_sets_updated_at(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact()
        db_session.add(contact)
        await db_session.flush()

        await repo.delete_many([contact])
        await db_session.refresh(contact)

        assert contact.deleted_at is not None
        assert contact.updated_at is not None


class TestRestoreManySetsUpdatedAt:
    async def test_restore_many_sets_updated_at(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact()
        contact.deleted_at = datetime.now(timezone.utc)
        db_session.add(contact)
        await db_session.flush()

        await repo.restore_many([contact])
        await db_session.refresh(contact)

        assert contact.deleted_at is None
        assert contact.updated_at is not None


class TestSoftDeleteWhereSetsUpdatedAt:
    async def test_soft_delete_where_sets_updated_at(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact()
        db_session.add(contact)
        await db_session.flush()
        stamp = datetime.now(timezone.utc)

        await repo.soft_delete_where(ContactModel.id == contact.id, deleted_at=stamp)
        await db_session.refresh(contact)

        assert contact.deleted_at == stamp
        assert contact.updated_at is not None


class TestRestoreWhereSetsUpdatedAt:
    async def test_restore_where_sets_updated_at(self, db_session):
        repo = ContactRepository(db_session)
        stamp = datetime.now(timezone.utc)
        contact = make_contact()
        contact.deleted_at = stamp
        db_session.add(contact)
        await db_session.flush()

        await repo.restore_where(ContactModel.id == contact.id, deleted_at=stamp)
        await db_session.refresh(contact)

        assert contact.deleted_at is None
        assert contact.updated_at is not None
