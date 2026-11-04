"""Alta y consulta de notificaciones judiciales, con sus documentos adjuntos."""

import uuid
from typing import Sequence

from fastapi import HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.services.document_service import DocumentService
from app_platform.documents.utils.document_naming import (
    resolve_content_type,
    safe_original_name,
)
from app_platform.documents.utils.upload_limits import read_within_limit
from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from app_platform.notifications.services.notification_service import NotificationService
from core.security.constants.permissions import PORTFOLIO_JUDICIAL
from core.security.policies.security_policies import (
    get_self_identity,
    require_org_visibility,
    require_permission,
)
from identity.users.enums.user_enums import IdentityVerificationStatus
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import UserSession
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.judicial_notifications.enums.judicial_notification_enums import (
    JUDICIAL_PRIORITY_LABELS,
    JudicialPriority,
)
from receivables.judicial_notifications.models.judicial_notification_document_model import (  # pylint: disable=line-too-long
    JudicialNotificationDocumentModel,
)
from receivables.judicial_notifications.models.judicial_notification_model import (
    JudicialNotificationModel,
)
from receivables.judicial_notifications.repository.judicial_notification_document_repository import (  # pylint: disable=line-too-long
    JUDICIAL_NOTIFICATION_DOCUMENT_STORAGE_DOMAIN,
    JudicialNotificationDocumentRepository,
)
from receivables.judicial_notifications.repository.judicial_notification_repository import (  # pylint: disable=line-too-long
    JudicialNotificationRepository,
    JudicialNotificationRow,
)
from receivables.judicial_notifications.schemas.judicial_notification_schemas import (
    JudicialInboxResponse,
    JudicialNotificationAttachment,
    JudicialNotificationCreate,
    JudicialNotificationResponse,
    JudicialPriorityOption,
)

# Prioridad judicial → tipo visual de la campana (enum de NotificationModel).
_PRIORITY_NOTIF_TYPE: dict[JudicialPriority, NotificationType] = {
    JudicialPriority.URGENT: NotificationType.ERROR,
    JudicialPriority.MEDIUM: NotificationType.WARNING,
    JudicialPriority.LOW: NotificationType.INFO,
    JudicialPriority.INFORMATIVE: NotificationType.INFO,
}


class JudicialNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = JudicialNotificationRepository(session)
        self._debtor_repo = DebtorRepository(session)
        self._user_repo = UserRepository(session)
        # Mutar notificaciones de la campana es del módulo notifications: se delega en
        # su service, que persiste y emite el SSE en un solo lugar.
        self._notification_service = NotificationService(session)
        # Los adjuntos son documentos: ningún módulo habla con el storage directamente,
        # todos delegan en este service.
        self._document_service = DocumentService(session)
        # El enlace adjunto↔notificación vive en `documentos_notificacion_judicial`, con
        # FK real a las dos tablas.
        self._document_repo = JudicialNotificationDocumentRepository(session)

    # ── Catálogo ─────────────────────────────────────────────────────────────

    def list_priorities(self) -> list[JudicialPriorityOption]:
        return [
            JudicialPriorityOption(
                value=priority.value, label=JUDICIAL_PRIORITY_LABELS[priority]
            )
            for priority in JudicialPriority
        ]

    # ── Buzón del titular ────────────────────────────────────────────────────

    async def get_my_inbox(self, session: UserSession) -> JudicialInboxResponse:
        debtor_ids = [d.id for d in await self._require_debtors(session)]
        rows = await self._repo.get_inbox_by_debtor_ids(debtor_ids)
        unread = await self._repo.count_unread_by_debtor_ids(debtor_ids)
        attachments_by_notification = await self._get_attachments_by_notification(rows)
        return JudicialInboxResponse(
            items=[
                self._to_response(
                    row, attachments_by_notification.get(str(row.notification.id), [])
                )
                for row in rows
            ],
            unread_count=unread,
        )

    async def mark_read(self, session: UserSession, notification_id: uuid.UUID) -> None:
        debtors = await self._require_debtors(session)
        # El repo filtra por deudor: si la notificación no es suya vuelve None y
        # respondemos 404, sin confirmarle que existe.
        notification = await self._repo.get_owned_by_debtor(
            notification_id, [d.id for d in debtors]
        )
        if notification is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada")
        if notification.is_read:
            return
        notification.is_read = True
        await self._repo.update(notification)
        await self._notify_creator_viewed(notification, debtors[0])

    async def mark_all_read(self, session: UserSession) -> None:
        debtors = await self._require_debtors(session)
        await self._repo.mark_all_read_by_debtor_ids([d.id for d in debtors])

    # ── Emisión desde el panel de la entidad ─────────────────────────────────

    async def create(
        self, session: UserSession, payload: JudicialNotificationCreate
    ) -> JudicialNotificationResponse:
        # El permiso se evalúa contra la entidad dueña del crédito, que solo se
        # conoce consultando la BD: por eso el gate vive acá y no en una dependency.
        organization_id = await self._repo.get_credit_organization_id(payload.credit_id)
        if organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado")
        require_org_visibility(session, str(organization_id))
        require_permission(PORTFOLIO_JUDICIAL, session, str(organization_id))

        notification = JudicialNotificationModel(
            credit_id=payload.credit_id,
            title=payload.title,
            body=payload.body,
            priority=payload.priority,
            created_by=session.user_id,
        )
        if payload.notified_at is not None:
            notification.notified_at = payload.notified_at

        created = await self._repo.add(notification)
        row = await self._repo.get_row_by_id(created.id)
        if row is None:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "No se pudo leer la notificación creada",
            )

        response = self._to_response(row)
        await self._notify_recipients(response)
        return response

    async def list_by_credit(
        self, session: UserSession, credit_id: uuid.UUID
    ) -> list[JudicialNotificationResponse]:
        organization_id = await self._repo.get_credit_organization_id(credit_id)
        if organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado")
        require_org_visibility(session, str(organization_id))
        require_permission(PORTFOLIO_JUDICIAL, session, str(organization_id))
        rows = await self._repo.get_by_credit_id(credit_id)
        attachments_by_notification = await self._get_attachments_by_notification(rows)
        return [
            self._to_response(
                row, attachments_by_notification.get(str(row.notification.id), [])
            )
            for row in rows
        ]

    # ── Adjuntos (solo la entidad emisora puede subir) ───────────────────────

    async def upload_attachments(
        self, session: UserSession, notification_id: uuid.UUID, files: list[UploadFile]
    ) -> JudicialNotificationResponse:
        row = await self._repo.get_row_by_id(notification_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada")
        organization_id = await self._repo.get_credit_organization_id(
            row.notification.credit_id
        )
        if organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado")
        require_org_visibility(session, str(organization_id))
        require_permission(PORTFOLIO_JUDICIAL, session, str(organization_id))

        for upload in files:
            content_type = resolve_content_type(upload.filename)
            content = await read_within_limit(upload, MAX_DOCUMENT_SIZE_BYTES)
            document = await self._document_service.store_verified_upload(
                content=content,
                filename=safe_original_name(upload.filename),
                content_type=content_type,
                domain=JUDICIAL_NOTIFICATION_DOCUMENT_STORAGE_DOMAIN,
                owner_id=str(notification_id),
                uploaded_by=session.user_id,
                organization_id=organization_id,
            )
            await self._document_repo.add(
                JudicialNotificationDocumentModel(
                    judicial_notification_id=notification_id,
                    document_id=document.id,
                )
            )

        rows = await self._document_repo.list_by_notification(notification_id)
        return self._to_response(row, [document for _, document in rows])

    async def get_attachment_content(
        self, session: UserSession, notification_id: uuid.UUID, document_id: uuid.UUID
    ) -> Response:
        row = await self._repo.get_row_by_id(notification_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada")

        if session.is_self:
            debtors = await self._require_debtors(session)
            # El repo filtra por deudor: si la notificación no es suya vuelve None y
            # respondemos 404, sin confirmarle a quien pregunta que existe.
            owned = await self._repo.get_owned_by_debtor(
                notification_id, [d.id for d in debtors]
            )
            if owned is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, "Notificación no encontrada"
                )
        else:
            organization_id = await self._repo.get_credit_organization_id(
                row.notification.credit_id
            )
            if organization_id is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado")
            require_org_visibility(session, str(organization_id))
            require_permission(PORTFOLIO_JUDICIAL, session, str(organization_id))

        # Último eslabón: el adjunto tiene que colgar de ESA notificación. Si no, 404 —
        # no se le confirma a quien pregunta que el documento existe.
        owned_document = await self._document_repo.get_owned(
            notification_id, document_id
        )
        if owned_document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
        return await self._document_service.to_content_response(
            owned_document[1], session.user_id
        )

    # ── Internos ─────────────────────────────────────────────────────────────

    async def _get_attachments_by_notification(
        self, rows: list[JudicialNotificationRow]
    ) -> dict[str, list[DocumentModel]]:
        """Adjuntos de varias notificaciones en una sola consulta, agrupados por
        notificación, para que listar el buzón/panel no dispare una query por fila.

        La agrupación usa `id_notificacion_judicial` de la tabla de unión, que es una FK
        real — antes era `documentos.id_dueno`, una columna sin FK que podía apuntar a
        cualquier cosa.
        """
        notification_ids = [row.notification.id for row in rows]
        links = await self._document_repo.list_by_notifications(notification_ids)
        by_notification: dict[str, list[DocumentModel]] = {}
        for link, document in links:
            by_notification.setdefault(str(link.judicial_notification_id), []).append(
                document
            )
        return by_notification

    async def _notify_recipients(self, response: JudicialNotificationResponse) -> None:
        """Avisa por campana + SSE a quienes verán la notificación en su buzón.

        Los destinatarios son el deudor y el codeudor del crédito, el mismo criterio con
        el que se arma el buzón. Se enlazan a su usuario por documento (tipo + hash),
        porque `deudores` y `usuarios` son tablas distintas: un titular que todavía no
        creó su cuenta no tiene a quién emitirle, y se salta sin romper la emisión.
        """
        recipients = await self._repo.get_credit_recipients(response.credit_id)
        for debtor in recipients:
            user = await self._user_repo.get_by_document(
                debtor.document_type, debtor.document_number_hash
            )
            if user is None:
                continue
            await self._notification_service.create_notification(
                user_id=user.id,
                title="Nueva notificación judicial",
                body=f"{response.entity_name} · {response.title}",
                category=NotificationCategory.JUDICIAL,
                notif_type=_PRIORITY_NOTIF_TYPE[response.priority],
                link="/home",
                details={
                    "judicialNotificationId": str(response.id),
                    "creditId": str(response.credit_id),
                    "creditNumber": response.credit_number,
                    "entityName": response.entity_name,
                    "priority": response.priority.value,
                },
            )

    async def _notify_creator_viewed(
        self, notification: JudicialNotificationModel, debtor: DebtorModel
    ) -> None:
        """Avisa por campana + SSE a quien creó la notificación judicial que el deudor
        ya la vio, mismo mecanismo que `_notify_recipients` pero en la dirección
        contraria. Solo se llama la primera vez que pasa a leída -- `mark_read` corta
        antes si `is_read` ya era True, así que no se repite en cada apertura."""
        await self._notification_service.create_notification(
            user_id=notification.created_by,
            title="Notificación judicial vista",
            body=f"{debtor.full_name} vio la notificación «{notification.title}».",
            category=NotificationCategory.JUDICIAL,
            notif_type=NotificationType.INFO,
            link="/home",
            details={
                "judicialNotificationId": str(notification.id),
                "creditId": str(notification.credit_id),
            },
        )

    async def _require_debtors(self, session: UserSession) -> list[DebtorModel]:
        """Resuelve las filas de deudor (una por empresa) detrás de la sesión SELF. El
        documento va cifrado en la tabla, así que la búsqueda es por hash."""
        document_type, document_number_hash = get_self_identity(session)
        try:
            doc_type = UserDocumentType(document_type)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Tipo de documento no reconocido"
            ) from e

        debtors = await self._debtor_repo.list_by_document(
            doc_type, document_number_hash
        )
        if not debtors:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "No encontramos obligaciones a tu nombre"
            )
        # Ver StatementService._require_self_debtors: conocer tipo+número de documento
        # de alguien no es secreto, así que además de ser deudor conocido se exige
        # identidad verificada (documento subido + aprobado por Atención al Cliente).
        if session.identity_verification_status != IdentityVerificationStatus.APPROVED:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Verificación de identidad pendiente. Sube tu documento de "
                "identidad para acceder a tu información crediticia.",
            )
        return debtors

    @staticmethod
    def _to_response(
        row: JudicialNotificationRow, documents: Sequence[DocumentModel] = ()
    ) -> JudicialNotificationResponse:
        return JudicialNotificationResponse(
            id=row.notification.id,
            title=row.notification.title,
            body=row.notification.body,
            priority=row.notification.priority,
            is_read=row.notification.is_read,
            notified_at=row.notification.notified_at,
            credit_id=row.notification.credit_id,
            credit_number=row.credit_number,
            credit_type=row.credit_type,
            entity_name=row.entity_name,
            attachments=[
                JudicialNotificationAttachment(
                    id=document.id,
                    name=document.original_name,
                    url=(
                        f"/judicial-notifications/{row.notification.id}/"
                        f"documents/{document.id}/content"
                    ),
                    size=document.size_bytes or 0,
                )
                for document in documents
            ],
        )
