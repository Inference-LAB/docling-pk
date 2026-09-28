"""
Intermediate (Higher Secondary School Certificate) extraction, Federal
Board Islamabad format. No date_of_birth field, this board does not
print it on the Intermediate certificate.
"""

from docling_pk.schema import FieldResult
from docling_pk.parsers._federal_board import extract_common_fields

FIELD_NAMES = [
    "serial_number", "certificate_number", "roll_number", "registration_number",
    "group", "session_year", "grade", "name", "father_name", "institute",
    "total_marks_possible", "total_marks_obtained",
]


def extract(raw_text: str) -> dict[str, FieldResult]:
    return extract_common_fields(raw_text)
