import re
import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException

from ai_tutor.config import get_settings


def normalize_grade(value: str) -> str:
    value = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).strip()
    match = re.fullmatch(r"(?:grade\s*)?(1[0-2]|[1-9])", value, re.IGNORECASE)
    return match.group(1) if match else value.upper()


@dataclass(frozen=True)
class Identity:
    student_id: str
    tenant_id: str
    grade: str


def require_identity(
    authorization: str = Header(default=""),
    x_tutor_student: str = Header(default=""),
    x_tutor_tenant: str = Header(default=""),
    x_tutor_grade: str = Header(default=""),
) -> Identity:
    token = get_settings().tutor_service_token
    if not token:
        raise HTTPException(503, "Tutor integration is not configured")
    if not secrets.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Invalid service credentials")
    if not all(re.fullmatch(r"[0-9a-f]{24}", value) for value in (x_tutor_student, x_tutor_tenant)):
        raise HTTPException(400, "Invalid student or school identity")
    grade = normalize_grade(x_tutor_grade)
    if grade not in {"KG1", "KG2", *(str(n) for n in range(1, 13))}:
        raise HTTPException(400, "Invalid student grade")
    return Identity(x_tutor_student, x_tutor_tenant, grade)
