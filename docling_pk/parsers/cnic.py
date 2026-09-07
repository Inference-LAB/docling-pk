import re

from docling_pk.schema import FieldResult


CNIC_PATTERN = re.compile(r"\b\d{5}-\d{7}-\d\b")
GENDER_PATTERN = re.compile(r"\b(?:gender\s*[:\-]?\s*)?(male|female|m|f)\b", re.IGNORECASE)


def extract(raw_text: str) -> dict[str, FieldResult]:
    cnic_match = CNIC_PATTERN.search(raw_text or "")
    gender_match = GENDER_PATTERN.search(raw_text or "")

    cnic_value = cnic_match.group(0) if cnic_match else None
    gender_value = gender_match.group(1).upper() if gender_match else None

    return {
        "cnic_number": FieldResult(value=cnic_value, confidence=0.95 if cnic_value else 0.0),
        "gender": FieldResult(value=gender_value, confidence=0.9 if gender_value else 0.0),
    }
