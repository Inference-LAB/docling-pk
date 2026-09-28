"""
Matric (Secondary School Certificate) extraction, Federal Board Islamabad
format. Adds date_of_birth on top of the shared fields, since this board
prints DOB on the Matric certificate but not on the Intermediate one.
"""

from docling_pk.schema import FieldResult
from docling_pk.parsers._federal_board import extract_common_fields, DOB

FIELD_NAMES = [
    "serial_number", "certificate_number", "roll_number", "registration_number",
    "group", "session_year", "grade", "name", "father_name", "institute",
    "date_of_birth", "total_marks_possible", "total_marks_obtained",
]


def extract(raw_text: str) -> dict[str, FieldResult]:
    fields = extract_common_fields(raw_text)
    match = DOB.search(raw_text)
    fields["date_of_birth"] = FieldResult(value=match.group(1), confidence=0.8) if match else FieldResult(value=None, confidence=0.0)
    return fields
