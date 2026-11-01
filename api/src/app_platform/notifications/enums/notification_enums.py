"""Categoría y tipo visual de una notificación in-app."""

from enum import StrEnum


class NotificationCategory(StrEnum):
    SUPPORT = "support"
    SUPPORT_MESSAGE = "support_message"
    ORG_VERIFICATION = "org_verification"
    IDENTITY_VERIFICATION = "identity_verification"
    PORTFOLIO = "portfolio"
    REPORT = "report"
    JUDICIAL = "judicial"


class NotificationType(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
