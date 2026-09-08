"""
CNIC field extraction.

Labels are matched loosely since real OCR misreads them in small,
specific ways ("Gender" as "GenUer", "of" as "o{"/"o/", "Father Name"
as "Fathgr Name"/"Father Namg"). Dates and cnic_number use format-based
matching instead of label matching, since testing showed date labels
and values are read as two separate groups, not adjacent lines.

Digit matching is restricted to ASCII 0-9 explicitly, not the regex \\d
shorthand. Python's \\d and int() both silently accept Unicode digits
(Arabic-Indic included), so a garbled OCR read could otherwise parse
as a different, wrong number with full confidence instead of correctly
failing to match.

Gender's search window was widened after testing with the adaptive
threshold step removed (see preprocessor.py): with cleaner OCR text,
the M/F value can appear further from its label than a 1-line window
would catch.
"""

import re
from typing import Optional
from docling_pk.schema import FieldResult

CNIC_PATTERN = re.compile(r"\b([0-9]{5}-[0-9]{7}-[0-9])\b")
DATE_PATTERN = re.compile(r"\b([0-9]{2})[.,]([0-9]{2})[.,]([0-9]{4})\b")

FIELD_NAMES = [
    "name", "father_name", "cnic_number",
    "date_of_birth", "date_of_issue", "date_of_expiry",
    "gender", "address",
]

FATHER_NAME_LABEL = re.compile(r"fath\w*", re.IGNORECASE)
NAME_LABEL = re.compile(r"\bname\b", re.IGNORECASE)
GENDER_LABEL = re.compile(r"gen.er", re.IGNORECASE)
ADDRESS_LABEL = re.compile(r"address", re.IGNORECASE)


def extract_cnic_number(raw_text: str) -> FieldResult:
    """
    Extracts the CNIC number (format XXXXX-XXXXXXX-X). OCR sometimes
    reads the dash as an underscore, colon, or backtick; all are
    normalized before matching.
    """
    normalized = raw_text.replace("_", "-").replace(":", "-").replace("`", "-")
    match = CNIC_PATTERN.search(normalized)
    if match:
        return FieldResult(value=match.group(1), confidence=0.92)
    return FieldResult(value=None, confidence=0.0)


def _value_after_label(lines: list[str], label_pattern: re.Pattern, exclude: re.Pattern = None) -> Optional[tuple[str, int]]:
    for i, line in enumerate(lines):
        if exclude and exclude.search(line):
            continue
        if label_pattern.search(line):
            return line, i
    return None


def _text_value(lines: list[str], label_pattern: re.Pattern, exclude: re.Pattern = None) -> FieldResult:
    found = _value_after_label(lines, label_pattern, exclude)
    if found is None:
        return FieldResult(value=None, confidence=0.0)

    line, idx = found
    same_line = label_pattern.sub("", line).strip(" :-")
    if same_line:
        return FieldResult(value=same_line, confidence=0.75)

    if idx + 1 < len(lines) and lines[idx + 1].strip():
        return FieldResult(value=lines[idx + 1].strip(), confidence=0.65)

    return FieldResult(value=None, confidence=0.0)


def _all_dates(raw_text: str) -> list[str]:
    matches = DATE_PATTERN.findall(raw_text)
    return [f"{d}.{m}.{y}" for (d, m, y) in matches]


def _dates_by_position(raw_text: str) -> tuple[FieldResult, FieldResult, FieldResult]:
    """
    Assigns dates by order of appearance, not proximity to a label.
    NADRA prints birth, issue, expiry in that fixed order, and testing
    shows EasyOCR reads the value block in that order even when
    separated from the labels.
    """
    dates = _all_dates(raw_text)
    results = []
    for i in range(3):
        if i < len(dates):
            results.append(FieldResult(value=dates[i], confidence=0.8))
        else:
            results.append(FieldResult(value=None, confidence=0.0))
    return tuple(results)


def extract_gender(raw_text: str) -> FieldResult:
    """
    Extracts gender as 'M' or 'F'. Searches up to 4 lines after the
    label, not just the next line, since cleaner OCR (no adaptive
    threshold) places the value further from the label than before.
    """
    lines = raw_text.splitlines()
    found = _value_after_label(lines, GENDER_LABEL)
    if found is None:
        return FieldResult(value=None, confidence=0.0)

    line, idx = found
    remainder = GENDER_LABEL.sub("", line).strip(" :-")
    match = re.search(r"\b([MF])\b", remainder.upper())
    if match:
        return FieldResult(value=match.group(1), confidence=0.8)

    for offset in range(1, 5):
        j = idx + offset
        if j >= len(lines):
            break
        match = re.search(r"\b([MF])\b", lines[j].strip().upper())
        if match:
            return FieldResult(value=match.group(1), confidence=0.7)

    return FieldResult(value=None, confidence=0.0)


def extract(raw_text: str) -> dict[str, FieldResult]:
    """
    Extracts all CNIC fields from raw OCR text. Missing fields return
    FieldResult(None, 0.0) rather than raising.
    """
    lines = raw_text.splitlines()

    father_name = _text_value(lines, FATHER_NAME_LABEL)
    name = _text_value(lines, NAME_LABEL, exclude=FATHER_NAME_LABEL)
    dob, issue, expiry = _dates_by_position(raw_text)

    return {
        "name": name,
        "father_name": father_name,
        "cnic_number": extract_cnic_number(raw_text),
        "date_of_birth": dob,
        "date_of_issue": issue,
        "date_of_expiry": expiry,
        "gender": extract_gender(raw_text),
        "address": _text_value(lines, ADDRESS_LABEL),
    }