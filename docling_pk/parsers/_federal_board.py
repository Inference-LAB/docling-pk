"""
Shared field extraction for Federal Board of Intermediate and Secondary
Education (Islamabad) certificates.

Digit matching restricted to ASCII 0-9 explicitly, not \\d, since \\d and
int() both silently accept Unicode digits (Arabic-Indic included),
which showed up in real testing as a silently wrong number instead of
a correctly failed match.

Label patterns are kept loose since testing found labels misread in
ways that keep breaking stricter patterns ("Certiiicate", "Cerlificate",
"erlific3te"). Letter-for-digit misreads (O/o/l/I for 0/0/1/1) are
corrected inside number tokens, confirmed necessary on a real roll
number read as "1217O6" instead of "121706". The name/father-name
anchor tolerates common misspellings of "daughter" found across real
samples. The TOTAL row search stops at an all-caps subject-name line
(a hard boundary), confirmed necessary on a real sample where the true
total-possible value drifted far from the label and the search
otherwise crossed into a subject row and wrongly grabbed that
subject's own marks instead.
"""

import re
from docling_pk.schema import FieldResult

SERIAL_LABEL = re.compile(r"ser\w*\s*n[oa]", re.IGNORECASE)
CERTIFICATE_LABEL = re.compile(r"cer\w*\s*n[oa]", re.IGNORECASE)
ROLL_LABEL = re.compile(r"roll\s*n[oa]", re.IGNORECASE)
REGISTRATION_LABEL = re.compile(r"reg\w*\s*n[oa]", re.IGNORECASE)
GROUP_KEYWORDS = re.compile(r"\b(SCIENCE(?:\s+GENERAL)?|ARTS|COMMERCE|HUMANITIES)\b", re.IGNORECASE)
SESSION_YEAR = re.compile(r"annual\W*([0-9]{4})", re.IGNORECASE)
GRADE = re.compile(r"grade\s+([A-Z])\b", re.IGNORECASE)
DAUGHTER_OF_ANCHOR = re.compile(r"d[ao]ugh\w*\s*[o0]f", re.IGNORECASE)
DOB = re.compile(r"date of birth is\s+([0-9./-]+)", re.IGNORECASE)
TOTAL_LABEL = re.compile(r"\btotal\b", re.IGNORECASE)
NUMBER_RUN = re.compile(r"[0-9][0-9OolI./\s]{2,}[0-9]|[0-9]{3,}")
HARD_BOUNDARY = re.compile(r"^[A-Z\s]{4,}$")

SKIP_LINE = re.compile(r"certif|cerif|^that$|board|education|islamabad|secondary|intermediate", re.IGNORECASE)


def _clean_number(raw: str) -> str:
    corrected = raw.translate(str.maketrans("OolI", "0011"))
    return re.sub(r"[^0-9/]", "", corrected)


def _find_number_near_label(lines: list[str], label_pattern: re.Pattern, window: int = 2) -> FieldResult:
    for i, line in enumerate(lines):
        if not label_pattern.search(line):
            continue

        same_line = label_pattern.sub("", line)
        match = NUMBER_RUN.search(same_line)
        if match:
            return FieldResult(value=_clean_number(match.group()), confidence=0.75)

        offsets = []
        for d in range(1, window + 1):
            offsets.append(d)
            offsets.append(-d)
        for offset in offsets:
            j = i + offset
            if 0 <= j < len(lines):
                match = NUMBER_RUN.search(lines[j])
                if match:
                    return FieldResult(value=_clean_number(match.group()), confidence=0.65)
        return FieldResult(value=None, confidence=0.0)

    return FieldResult(value=None, confidence=0.0)


def _find_name_pair(lines: list[str]) -> tuple[FieldResult, FieldResult]:
    anchor_idx = None
    for i, line in enumerate(lines):
        if DAUGHTER_OF_ANCHOR.search(line):
            anchor_idx = i
            break

    if anchor_idx is None:
        return FieldResult(value=None, confidence=0.0), FieldResult(value=None, confidence=0.0)

    name = FieldResult(value=None, confidence=0.0)
    for offset in (1, 2, 3):
        j = anchor_idx - offset
        if j < 0:
            break
        candidate = lines[j].strip(" '.-")
        if len(candidate) >= 5 and not SKIP_LINE.search(candidate):
            name = FieldResult(value=candidate, confidence=0.6)
            break

    father_name = FieldResult(value=None, confidence=0.0)
    for offset in (1, 2):
        j = anchor_idx + offset
        if j >= len(lines):
            break
        candidate = lines[j].strip(" '.-")
        if len(candidate) >= 5 and not SKIP_LINE.search(candidate):
            father_name = FieldResult(value=candidate, confidence=0.6)
            break

    return name, father_name


def _find_total(lines: list[str]) -> tuple[FieldResult, FieldResult]:
    for i, line in enumerate(lines):
        if not TOTAL_LABEL.search(line):
            continue

        numbers = []
        misses = 0
        for offset in range(1, 6):
            j = i - offset
            if j < 0:
                break
            candidate = lines[j].strip()
            if HARD_BOUNDARY.match(candidate):
                break
            match = NUMBER_RUN.search(candidate)
            if match:
                cleaned = _clean_number(match.group())
                if cleaned:
                    numbers.append(int(cleaned))
                    misses = 0
            else:
                misses += 1
                if misses >= 2:
                    break
            if len(numbers) == 2:
                break

        if len(numbers) == 2:
            possible, obtained = max(numbers), min(numbers)
            return (
                FieldResult(value=str(possible), confidence=0.7),
                FieldResult(value=str(obtained), confidence=0.7),
            )
        return FieldResult(value=None, confidence=0.0), FieldResult(value=None, confidence=0.0)

    return FieldResult(value=None, confidence=0.0), FieldResult(value=None, confidence=0.0)


def extract_common_fields(raw_text: str) -> dict[str, FieldResult]:
    lines = raw_text.splitlines()

    fields = {
        "serial_number": _find_number_near_label(lines, SERIAL_LABEL),
        "certificate_number": _find_number_near_label(lines, CERTIFICATE_LABEL),
        "roll_number": _find_number_near_label(lines, ROLL_LABEL),
        "registration_number": _find_number_near_label(lines, REGISTRATION_LABEL),
    }

    group_match = GROUP_KEYWORDS.search(raw_text)
    fields["group"] = FieldResult(value=group_match.group(1).upper(), confidence=0.75) if group_match else FieldResult(value=None, confidence=0.0)

    year_match = SESSION_YEAR.search(raw_text)
    fields["session_year"] = FieldResult(value=year_match.group(1), confidence=0.8) if year_match else FieldResult(value=None, confidence=0.0)

    grade_match = GRADE.search(raw_text)
    fields["grade"] = FieldResult(value=grade_match.group(1), confidence=0.6) if grade_match else FieldResult(value=None, confidence=0.0)

    fields["name"], fields["father_name"] = _find_name_pair(lines)
    fields["total_marks_possible"], fields["total_marks_obtained"] = _find_total(lines)
    fields["institute"] = FieldResult(value=None, confidence=0.0)

    return fields


def detect_document_type(raw_text: str) -> str:
    if re.search(r"higher\s+secondary\s+school\s+certificate", raw_text, re.IGNORECASE):
        return "intermediate"
    return "matric"
