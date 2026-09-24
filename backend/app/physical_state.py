from __future__ import annotations


CARD_CONDITIONS = frozenset(
    {
        "Near Mint",
        "Lightly Played",
        "Moderately Played",
        "Heavily Played",
        "Damaged",
    }
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def validate_physical_state(
    *,
    product_type: str,
    condition: str | None,
    seal_status: str | None,
    grading_company: str | None,
    grade: str | None,
    certificate_number: str | None = None,
) -> None:
    """Keep raw condition, grading and seal state semantically separate."""

    condition = _clean(condition)
    grading_company = _clean(grading_company)
    grade = _clean(grade)
    certificate_number = _clean(certificate_number)

    if (grading_company is None) != (grade is None):
        raise ValueError("Grading company and grade must both be set or both cleared")

    if certificate_number is not None and grading_company is None:
        raise ValueError("Certificate number requires grading company and grade")

    if product_type == "CARD":
        if seal_status is not None:
            raise ValueError("Card inventory does not use seal status")
        if condition is not None and condition not in CARD_CONDITIONS:
            raise ValueError("Raw card condition must use the Drop Rate / TCGplayer condition scale")
        if grading_company is not None and condition is not None:
            raise ValueError("Graded cards must not also have a raw card condition")
        return

    if condition is not None:
        raise ValueError("Sealed or collection products do not use raw card condition")
    if grading_company is not None or grade is not None or certificate_number is not None:
        raise ValueError("Sealed or collection products do not use card grading fields")
