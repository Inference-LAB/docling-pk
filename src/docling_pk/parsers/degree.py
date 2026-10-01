"""
University degree certificate and transcript extraction.

Degree and transcript layouts vary by university far more than board
certificates do, so this parser relies on the phrases that recur across
Pakistani universities rather than on positions: "<NAME> s/o <FATHER>",
"Bachelor/Master/Doctor of ...", "Registration No", "CGPA", "First
Division", "Date of Issue". Verified on COMSATS University Islamabad
documents; other universities are best-effort.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from docling_pk.layout import clean_spaces, group_lines
from docling_pk.parsers.base import clean_person_name, combine_confidence, make_field
from docling_pk.pipeline import Page
from docling_pk.schema import FieldResult, FieldStatus
from docling_pk.validation.dates import find_dates

FIELD_NAMES = [
    "student_name",
    "father_name",
    "degree",
    "institution",
    "campus",
    "registration_number",
    "serial_number",
    "cgpa",
    "division",
    "date_of_birth",
    "date_of_issue",
    "year",
]

_RELATION = r"(?:s|d|w)\s*[/\\|.]?\s*o\b|son\s+of|daughter\s+of|wife\s+of"
NAME_PAIR = re.compile(
    rf"(?:certified\s+that\s+|that\s+)?([A-Z][A-Za-z.'\- ]{{2,60}}?)\s+(?:{_RELATION})\s+([A-Z][A-Za-z.'\- ]{{2,60}}?)"
    r"(?=\s*$|\s*[,(]|\s+(?:registration|reg\.?|roll|of\b|has\b|department|enrol|bearing))",
    re.I | re.M,
)
DEGREE = re.compile(
    r"\b((?:Bachelor|Master|Doctor)\s+of\s+[A-Z][A-Za-z&,()]*(?:\s+(?:in|of|and|&|\(|[A-Z])[A-Za-z&,()]*){0,8}"
    # The abbreviation must end at a word boundary, or "MAHMOOD" reads as "MA" + "HMOOD".
    r"|(?:BS|MS|MPhil|M\.Phil|PhD|Ph\.D|BBA|MBA|BSc|B\.Sc|MSc|M\.Sc|BE|B\.E|MBBS|LLB|BA|MA)\b\.?\s*(?:\(Hons\)\s*)?(?:in\s+)?[A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,5})",
)
INSTITUTION = re.compile(
    r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,5}\s+University(?:\s+of\s+[A-Z][A-Za-z&]+(?:\s+(?:and\s+)?[A-Z][A-Za-z&]+){0,3})?(?:,?\s+(?:Islamabad|Lahore|Karachi|Peshawar|Quetta|Multan|Faisalabad|Rawalpindi))?"
    r"|University\s+of\s+[A-Z][A-Za-z&]+(?:\s+(?:and\s+)?[A-Z][A-Za-z&]+){0,4}"
    r"|[A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,4}\s+Institute\s+of\s+[A-Z][A-Za-z&]+(?:\s+(?:and\s+)?[A-Z][A-Za-z&]+){0,3})"
)
_NO = r"(?:no|n[o0]|[0-9a-z]o|number|#)"  # blackletter "No" is often read as "3o"/"2o"
REGISTRATION = re.compile(
    rf"(?:registration|reg(?:d)?\.?|enrol(?:l)?ment)\s*{_NO}?\.?\s*[:\-]?\s*"
    r"([A-Z0-9]{2,}[/\-][A-Z0-9/\-]{3,}(?:\s?[/\-]\s?[A-Z0-9]{2,}){0,2}|[0-9]{6,})",
    re.I,
)
SERIAL = re.compile(rf"serial\s*{_NO}\.?\s*[:\-]?\s*([0-9]{{4,}})", re.I)
CGPA = re.compile(r"\bC\.?\s?G\.?\s?P\.?\s?A\.?\s*[:\-]?\s*([0-4][.,][0-9]{1,2})\b", re.I)
DIVISION = re.compile(r"\b(first|second|third|1st|2nd|3rd)\s+division\b", re.I)
CAMPUS = re.compile(r"(?:from|of|at)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+Campus", re.I)
TRANSCRIPT = re.compile(r"transcript|semester|course\s*code|credit\s*hours", re.I)


_UNIVERSITY_TYPO = re.compile(r"\bUni[a-z]ersit[yv]\b|\bUnivers[il1]ty\b", re.I)


def fix_common_words(text: str) -> str:
    """Repairs OCR misreads of words the patterns depend on ("Unibersity")."""
    return _UNIVERSITY_TYPO.sub("University", text)


def detect_variant(text: str) -> str:
    """``"transcript"`` or ``"degree"``."""
    return "transcript" if TRANSCRIPT.search(text) else "degree"


def _flat(page: Page) -> Tuple[str, float]:
    lines = group_lines(page.boxes)
    text = "\n".join(" ".join(b.text for b in line) for line in lines)
    confs = [b.confidence for b in page.boxes] or [0.0]
    return text, sum(confs) / len(confs)


def _conf_for(page: Page, snippet: str, default: float) -> float:
    """Mean confidence of the boxes whose text overlaps ``snippet``."""
    words = set(w.lower() for w in re.findall(r"[A-Za-z0-9]{3,}", snippet))
    hits = [b.confidence for b in page.boxes if words & set(w.lower() for w in re.findall(r"[A-Za-z0-9]{3,}", b.text))]
    return sum(hits) / len(hits) if hits else default


def _verify_id(page: Page, value: str, conf: float, raw: str) -> FieldResult:
    """Re-reads an alphanumeric ID with the verifier engine, if configured.

    IDs such as ``UNI/SP22-BCS-001/ISB`` have no checksum, and I/l/1 and
    I/H confusions are common. If an independent engine reads the same box
    differently, the value is kept but downgraded to ``low_confidence``.
    """
    if page.verifier is None:
        return make_field(value, conf, raw=raw)
    head = value.split("/")[0][:4]
    box = next((b for b in page.boxes if head and head.lower() in b.text.lower().replace(" ", "")), None)
    if box is None:
        return make_field(value, conf, raw=raw)
    other, oconf = page.reread(box, pad_x=0.1, pad_y=0.15)
    norm = lambda t: re.sub(r"[^A-Z0-9]", "", t.upper())  # noqa: E731
    first = norm(value)[: max(len(norm(head)), 4)]
    if first and first in norm(other):
        return make_field(value, combine_confidence(conf, oconf * 0.5), raw=raw)
    f = make_field(value, conf * 0.6, raw=raw, reason=f"second OCR engine read '{other.strip()}'; please verify")
    f.status = FieldStatus.LOW_CONFIDENCE
    return f


def extract(page: Page) -> Tuple[Dict[str, FieldResult], List[str], Dict]:
    """Extracts a degree certificate or transcript.

    Returns:
        ``(fields, warnings, metadata)``.
    """
    text, mean_conf = _flat(page)
    text = fix_common_words(text)
    lines = [clean_spaces(line) for line in text.splitlines() if line.strip()]
    one_line = clean_spaces(" ".join(lines))
    fields: Dict[str, FieldResult] = {}
    warnings: List[str] = []
    variant = detect_variant(text)

    m = next((NAME_PAIR.search(ln) for ln in lines if NAME_PAIR.search(ln)), None) or NAME_PAIR.search(one_line)
    if m:
        name, father = clean_person_name(m.group(1)), clean_person_name(m.group(2))
        name = re.sub(r"^(?:certified\s+that|that)\s+", "", name or "", flags=re.I) or None
        c = _conf_for(page, m.group(0), mean_conf)
        fields["student_name"] = make_field(name.upper() if name else None, c, raw=m.group(1))
        fields["father_name"] = make_field(father.upper() if father else None, c, raw=m.group(2))
    else:
        fields["student_name"] = FieldResult.missing("no '<name> s/o <father>' phrase found")
        fields["father_name"] = FieldResult.missing("no '<name> s/o <father>' phrase found")

    m = next((DEGREE.search(ln) for ln in lines if DEGREE.search(ln)), None)
    if m:
        deg = clean_spaces(re.split(r"\s+(?:on|from|with|taught|at|,)\s", m.group(1) + " ")[0])
        fields["degree"] = make_field(deg, _conf_for(page, deg, mean_conf), raw=m.group(1))
    else:
        fields["degree"] = FieldResult.missing("degree title not found")

    m = next((INSTITUTION.search(ln) for ln in lines if INSTITUTION.search(ln)), None)
    fields["institution"] = (
        make_field(clean_spaces(m.group(1)), _conf_for(page, m.group(1), mean_conf), raw=m.group(1))
        if m
        else FieldResult.missing("institution name not found")
    )
    m = CAMPUS.search(one_line)
    fields["campus"] = (
        make_field(m.group(1).title(), _conf_for(page, m.group(1), mean_conf))
        if m
        else FieldResult.missing("campus not printed")
    )

    m = next((REGISTRATION.search(ln) for ln in lines if REGISTRATION.search(ln)), None)
    if m and m.group(1).endswith(("-", "/")):
        # Wrapped onto the next line ("CIIT/SP22-" / "BAI-010/ATK").
        idx = next(i for i, ln in enumerate(lines) if m.group(1) in ln)
        if idx + 1 < len(lines):
            cont = re.match(r"\s*([A-Z0-9/\-]{3,})", lines[idx + 1], re.I)
            if cont:
                m = REGISTRATION.search(m.string.replace(m.group(1), m.group(1) + cont.group(1)))
    if m:
        reg = re.sub(r"\s+", "", m.group(1)).upper()
        reg = re.split(r"(?<=[A-Z0-9])(?=DEPARTMENT|DEPT)", reg)[0]
        fields["registration_number"] = _verify_id(page, reg, _conf_for(page, m.group(1), mean_conf), m.group(1))
    else:
        fields["registration_number"] = FieldResult.missing("registration number not found")

    m = SERIAL.search(one_line)
    fields["serial_number"] = (
        make_field(m.group(1), _conf_for(page, m.group(1), mean_conf))
        if m
        else FieldResult.missing("serial number not found")
    )

    m = CGPA.search(one_line)
    fields["cgpa"] = (
        make_field(m.group(1).replace(",", "."), _conf_for(page, m.group(0), mean_conf))
        if m
        else FieldResult.missing("CGPA not printed or not found")
    )
    m = DIVISION.search(one_line)
    fields["division"] = (
        make_field(m.group(1).title() + " Division", 0.8) if m else FieldResult.missing("division not printed")
    )

    dob = None
    issue = None
    for line in group_lines(page.boxes):
        t = " ".join(b.text for b in line)
        ds = find_dates(t)
        if not ds:
            continue
        c = min(b.confidence for b in line)
        if re.search(r"birth", t, re.I) and dob is None:
            dob = make_field(ds[0], c, raw=t)
        elif re.search(r"issu|date\s*[:\-]|dated|given", t, re.I) and issue is None:
            issue = make_field(ds[0], c, raw=t)
    fields["date_of_birth"] = dob or FieldResult.missing("date of birth not printed")
    fields["date_of_issue"] = issue or FieldResult.missing("date of issue not found")
    if issue is not None:
        fields["year"] = make_field((issue.value or "")[-4:] or None, issue.confidence)
    else:
        years = re.findall(r"\b(?:19|20)[0-9]{2}\b", one_line)
        fields["year"] = make_field(years[-1], 0.5) if years else FieldResult.missing("year not found")

    meta = {"variant": variant}
    ordered = {n: fields.get(n, FieldResult.missing("not found")) for n in FIELD_NAMES}
    return ordered, warnings, meta
