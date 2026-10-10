from enum import StrEnum


class Role(StrEnum):
    STUDENT = "STUDENT"
    INSTRUCTOR = "INSTRUCTOR"


class ConnectionStatus(StrEnum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ModerationAction(StrEnum):
    ALLOW = "ALLOW"
    GUIDE = "GUIDE"
    WARN = "WARN"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    OVERRIDE = "OVERRIDE"
    INTERVENE = "INTERVENE"
