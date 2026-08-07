"""Privacy helpers for role-aware patient data responses."""

from app.dependencies import ADMIN_ROLES, CASHIER_ROLES, CLINICAL_ROLES, REGISTRAR_ROLES

FULL_PATIENT_IDENTITY_ROLES = ADMIN_ROLES | CASHIER_ROLES | CLINICAL_ROLES | REGISTRAR_ROLES


def mask_identity(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    visible_prefix = min(6, len(value) // 3)
    visible_suffix = min(4, len(value) - visible_prefix)
    return value[:visible_prefix] + "*" * (len(value) - visible_prefix - visible_suffix) + value[-visible_suffix:]


def mask_phone(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 7:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 7) + value[-4:]


def can_view_full_patient_identity(user_role: str) -> bool:
    return user_role in FULL_PATIENT_IDENTITY_ROLES
