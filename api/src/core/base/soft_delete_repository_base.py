"""Repository base para modelos con borrado lógico (`deleted_at`)."""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select, update

from core.base.repository_base import RepositoryBase, T


class SoftDeleteRepositoryBase(RepositoryBase[T]):
    """
    Repository base for models that use SoftDeleteMixin.
    get_by_id / get_all exclude deleted records by default.
    Use the _including_deleted variants when admin access is needed.
    """

    @staticmethod
    def _touch(**values: Any) -> dict[str, Any]:
        """Agrega `updated_at` a los valores de un UPDATE masivo.

        Un UPDATE armado con `update()` de SQLAlchemy Core no pasa por el ORM,
        así que el `onupdate` de la columna (que solo dispara en flush) nunca
        se ejecuta -- hay que setear `updated_at` a mano en cada uno.
        """
        return {**values, "updated_at": func.now()}

    async def get_by_id(self, id: object) -> Optional[T]:
        instance = await self.session.get(self.model_class, id)
        if instance is None:
            return None
        if instance.deleted_at is not None:  # type: ignore[union-attr]
            return None
        return instance

    async def get_all(self) -> Sequence[T]:
        result = await self.session.execute(
            select(self.model_class).where(
                self.model_class.deleted_at.is_(None)  # type: ignore[union-attr]
            )
        )
        return result.scalars().all()

    async def delete(self, instance: T) -> T:
        attached = await self.session.merge(instance)
        attached.deleted_at = datetime.now(timezone.utc)  # type: ignore[union-attr]
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def restore(self, instance: T) -> T:
        attached = await self.session.merge(instance)
        attached.deleted_at = None  # type: ignore[union-attr]
        await self.session.flush()
        await self.session.refresh(attached)
        return attached

    async def delete_many(self, instances: Sequence[T]) -> None:
        """Igual que delete() pero en un solo UPDATE — evita un flush+refresh por fila
        al dar de baja en cascada (ej. todas las membresías de una organización)."""
        ids = [instance.id for instance in instances]  # type: ignore[attr-defined]
        if not ids:
            return
        await self.session.execute(
            update(self.model_class)
            .where(self.model_class.id.in_(ids))
            .values(**self._touch(deleted_at=datetime.now(timezone.utc)))  # type: ignore[attr-defined]
        )
        await self.session.flush()

    async def restore_many(self, instances: Sequence[T]) -> None:
        """Igual que restore() pero en un solo UPDATE."""
        ids = [instance.id for instance in instances]  # type: ignore[attr-defined]
        if not ids:
            return
        await self.session.execute(
            update(self.model_class)
            .where(self.model_class.id.in_(ids))
            .values(**self._touch(deleted_at=None))  # type: ignore[attr-defined]
        )
        await self.session.flush()

    async def soft_delete_where(self, *conditions, deleted_at: datetime) -> None:
        """Baja en cascada de las filas VIVAS que cumplen ``conditions``, todas con el
        mismo ``deleted_at``.

        Ese sello compartido es lo que permite deshacer la cascada sin resucitar lo
        que ya estaba dado de baja antes: ``restore_where`` solo revive las filas
        marcadas con exactamente ese instante (el del padre que se eliminó/restaura)."""
        await self.session.execute(
            update(self.model_class)
            .where(
                self.model_class.deleted_at.is_(None),  # type: ignore[union-attr]
                *conditions,
            )
            .values(**self._touch(deleted_at=deleted_at))
        )
        await self.session.flush()

    async def restore_where(self, *conditions, deleted_at: datetime) -> None:
        """Inverso de ``soft_delete_where``: revive solo las filas dadas de baja en esa
        cascada (mismo ``deleted_at``), no las que ya estaban eliminadas antes."""
        await self.session.execute(
            update(self.model_class)
            .where(
                self.model_class.deleted_at == deleted_at,  # type: ignore[union-attr]
                *conditions,
            )
            .values(**self._touch(deleted_at=None))
        )
        await self.session.flush()

    async def get_by_id_including_deleted(self, id: object) -> Optional[T]:
        return await self.session.get(self.model_class, id)

    async def get_all_including_deleted(self) -> Sequence[T]:
        result = await self.session.execute(select(self.model_class))
        return result.scalars().all()

    async def get_deleted(self) -> Sequence[T]:
        """Solo las filas dadas de baja — la papelera.

        Va acá y no filtrando `get_all_including_deleted()` en Python a propósito: el
        filtro en memoria obliga a traer la tabla entera para descartar casi todo
        (over-fetching sobre una tabla de crecimiento no acotado). Con el `WHERE` en SQL
        el motor solo devuelve lo borrado, que es el subconjunto chico.
        """
        result = await self.session.execute(
            select(self.model_class)
            .where(self.model_class.deleted_at.is_not(None))  # type: ignore[union-attr]
            .order_by(self.model_class.deleted_at.desc())  # type: ignore[union-attr]
        )
        return result.scalars().all()
