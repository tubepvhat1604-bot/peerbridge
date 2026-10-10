import re

from fastapi import HTTPException

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.-]*\d){9,10}(?!\d)")


def reject_personal_contact(value: str, field_name: str) -> None:
    if EMAIL_PATTERN.search(value) or PHONE_PATTERN.search(value):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} không được chứa email hoặc số điện thoại. Hãy trò chuyện an toàn trong ứng dụng.",
        )
