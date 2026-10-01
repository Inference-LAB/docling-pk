"""
Matric (SSC) and Intermediate (HSSC) board certificate extraction.

Verified on real Federal Board (FBISE) certificates, both phone photos and a
digital copy. Label vocabulary also covers the wording used by the Punjab,
Khyber Pakhtunkhwa, Sindh and Balochistan boards, so their certificates are
parsed on a best-effort basis; the board is always reported in
``metadata["board"]`` so callers can decide how far to trust it.

The marks table is read spatially: the header row gives the x-position of
the "Maximum" and "Obtained" columns, and every row between the header and
the TOTAL row contributes ``(subject, max_marks, obtained_marks)``. The table
is then validated three ways (column sums equal the TOTAL row, obtained never
exceeds maximum, the total matches "Marks in words"), and numeric cells are
re-read with a digit-only allowlist when validation fails.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from docling_pk.layout import (
    ascii_ratio,
    boxes_right_of,
    clean_spaces,
    find_label,
    group_lines,
    label_score,
    normalize_label,
)
from docling_pk.ocr.base import TextBox
from docling_pk.parsers.base import clean_person_name, combine_confidence, make_field, respace
from docling_pk.pipeline import Page
from docling_pk.schema import FieldResult, FieldStatus
from docling_pk.validation.dates import find_dates
from docling_pk.validation.marks import check_subjects, words_to_number
from docling_pk.validation.text import digits_only, fix_digits

FIELD_NAMES = [
    "student_name",
    "father_name",
    "date_of_birth",
    "roll_number",
    "registration_number",
    "serial_number",
    "certificate_number",
    "board",
    "exam",
    "year",
    "session",
    "group",
    "institute",
    "grade",
    "total_marks",
    "max_marks",
]

#: (canonical board name, regex over the page text). Order matters: the
#: Federal Board title also contains generic words used by other boards.
BOARDS: Sequence[Tuple[str, str]] = (
    ("FBISE", r"federal\s*board"),
    ("AKU-EB", r"aga\s*khan\s*university\s*examination"),
    ("BIEK Karachi", r"board\s*of\s*intermediate\s*education\W*karachi"),
    ("BSEK Karachi", r"board\s*of\s*secondary\s*education\W*karachi"),
)
BOARD_CITIES = (
    "Lahore",
    "Gujranwala",
    "Faisalabad",
    "Multan",
    "Rawalpindi",
    "Sargodha",
    "Bahawalpur",
    "Dera Ghazi Khan",
    "D.G. Khan",
    "Sahiwal",
    "Peshawar",
    "Mardan",
    "Abbottabad",
    "Swat",
    "Kohat",
    "Bannu",
    "Malakand",
    "Dera Ismail Khan",
    "D.I. Khan",
    "Hyderabad",
    "Sukkur",
    "Larkana",
    "Mirpurkhas",
    "Quetta",
    "Mirpur",
)

SSC_TITLE = re.compile(r"(?<!higher\s)secondary\s+school\s+certificate|\bmatric", re.I)
HSSC_TITLE = re.compile(r"higher\s+secondary|intermediate\s+(?:part|examination|certificate)", re.I)
SESSION = re.compile(r"\b(annual|supplementary|special)\b\W{0,3}((?:19|20)[0-9OoIl]{2})", re.I)
GRADE = re.compile(r"grade\W{0,3}([A-E]\s?[1+]?|F)\b", re.I)
GROUPS = re.compile(
    r"\b(pre[\s\-]*medical|pre[\s\-]*engineering|science(?:\s+general)?|general\s+science|"
    r"humanities|arts|commerce|computer\s+science|ics|i\.?\s?com|general)\b",
    re.I,
)

NUMERIC_LABELS = {
    "serial_number": ("Serial No", "Sr No", "S No"),
    "roll_number": ("Roll No",),
    "certificate_number": ("Certificate No",),
    "registration_number": ("Registration No", "Regd No", "Enrolment No"),
}
NAME_LABELS = ("Certified that", "Name", "Name of Candidate", "Candidate Name", "This is to certify that")
FATHER_LABELS = (
    "Son / Daughter of",
    "Son/Daughter of",
    "Father's Name",
    "Father Name",
    "S/O D/O",
    "Son of",
    "Daughter of",
)
INSTITUTE_LABELS = ("Candidate from", "Institution", "Institute", "School", "College")
SKIP_IN_NAMES = re.compile(
    r"certif|board|education|secondary|intermediate|islamabad|whose|date of birth|qualified", re.I
)

_NUM = re.compile(r"[0-9OoIlSB]{2,4}")
#: FBISE certificate numbers: nine digits, a slash, six digits.
CERT_NO_FORMAT = re.compile(r"(?<![0-9])[0-9]{9}/[0-9]{6}(?![0-9])")


def detect_board(text: str) -> Optional[str]:
    """Identifies the issuing board from the page text, e.g. ``"FBISE"``."""
    for name, pattern in BOARDS:
        if re.search(pattern, text, re.I):
            return name
    if re.search(r"board\s*of\s*intermediate\s*(?:and|&)\s*secondary\s*education", text, re.I):
        for city in BOARD_CITIES:
            if re.search(re.escape(city).replace(r"\ ", r"\s*"), text, re.I):
                return f"BISE {city}"
        return "BISE"
    return None


def detect_level(text: str) -> Optional[str]:
    """``"intermediate"``, ``"matric"`` or ``None`` from the certificate title."""
    if HSSC_TITLE.search(text):
        return "intermediate"
    if SSC_TITLE.search(text):
        return "matric"
    return None


# ------------------------------------------------------------- labelled fields


def _label_any(boxes: Sequence[TextBox], labels: Sequence[str], threshold: float = 75) -> Optional[Tuple[TextBox, str]]:
    best = None
    for lab in labels:
        b = find_label(boxes, lab, threshold=threshold)
        if b is not None:
            s = label_score(b.text, lab)
            if best is None or s > best[2]:
                best = (b, lab, s)
    return (best[0], best[1]) if best else None


def _after_label(text: str, label: str) -> str:
    """Text remaining in a box after the letters of ``label``."""
    target = len(normalize_label(label))
    seen = 0
    for i, ch in enumerate(text):
        if ch.isascii() and ch.isalpha():
            seen += 1
            if seen >= target:
                return text[i + 1 :].strip(" :.-_")
    return ""


def _numeric_field(page: Page, labels: Sequence[str]) -> FieldResult:
    hit = _label_any(page.boxes, labels)
    if hit is None:
        return FieldResult.missing(f"'{labels[0]}' label not found")
    label, lab = hit
    candidates: List[Tuple[str, TextBox]] = []
    rest = _after_label(label.text, lab)
    if rest:
        candidates.append((rest, label))
    for b in boxes_right_of(page.boxes, label, max_gap=12):
        candidates.append((b.text, b))
    # Values printed slightly above or below the label line (FBISE prints
    # the serial number raised, in red).
    h = max(label.height, 1.0)
    near = [
        b
        for b in page.boxes
        if b is not label
        and b.x0 >= label.x1 - h
        and b.x0 - label.x1 < 10 * h
        and 0.6 * h <= abs(b.cy - label.cy) < 1.6 * h
    ]
    for b in sorted(near, key=lambda b: abs(b.cy - label.cy)):
        candidates.append((b.text, b))
    for text, box in candidates:
        token = fix_digits(text, 0.5).strip()
        m = re.search(r"[0-9][0-9/\-]{3,}[0-9]", token)
        if not m:
            continue
        value = m.group(0)
        allow = "0123456789/-" if "/" in value or "-" in value else "0123456789"
        if box is not label:
            rtext, rconf = page.reread(box, allowlist=allow)
            rm = re.search(r"[0-9][0-9/\-]{3,}[0-9]", rtext)
            if rm and rm.group(0) == value:
                return make_field(value, combine_confidence(box.confidence, rconf), raw=text)
            if rm and rconf > box.confidence + 0.2:
                f = make_field(rm.group(0), rconf * 0.7, raw=text, reason="OCR reads disagree; please verify")
                f.status = FieldStatus.LOW_CONFIDENCE
                return f
        return make_field(value, box.confidence, raw=text)
    return FieldResult.missing(f"no number next to '{lab}'")


def _name_after(
    page: Page, labels: Sequence[str], stop_before: Optional[TextBox] = None
) -> Tuple[FieldResult, Optional[TextBox]]:
    hit = _label_any(page.boxes, labels, threshold=78)
    if hit is None:
        return FieldResult.missing(f"'{labels[0]}' label not found"), None
    label, lab = hit
    cands: List[Tuple[str, TextBox]] = []
    rest = _after_label(label.text, lab)
    if rest:
        cands.append((rest, label))
    cands += [(b.text, b) for b in boxes_right_of(page.boxes, label, max_gap=20)]
    for text, box in cands:
        if SKIP_IN_NAMES.search(text) or ascii_ratio(text) < 0.8:
            continue
        name = clean_person_name(respace(page, box if box is not label else None, text))
        if name and len(name) >= 3:
            return make_field(name.upper(), box.confidence, raw=text), label
    return FieldResult.missing(f"no name next to '{lab}'"), label


def _name_on_line_above(page: Page, anchor: TextBox) -> FieldResult:
    """Fallback for a garbled "Certified that" label: the trailing run of
    uppercase words on the line directly above the father-name line."""
    lines = group_lines(page.boxes)
    for i, line in enumerate(lines):
        if anchor in line and i > 0:
            prev = lines[i - 1]
            text = " ".join(b.text for b in prev)
            m = re.search(r"((?:[A-Z][A-Z.'\-]+\s?){1,6})\s*$", text)
            if m:
                name = clean_person_name(m.group(1))
                if name and len(name) >= 3 and not SKIP_IN_NAMES.search(name):
                    f = make_field(
                        name.upper(),
                        min(b.confidence for b in prev) * 0.8,
                        raw=text,
                        reason="label unreadable; located by position",
                    )
                    f.status = FieldStatus.LOW_CONFIDENCE
                    return f
    return FieldResult.missing("'Certified that' label not found")


def _institute(page: Page) -> FieldResult:
    """Institution line: FBISE prints it on the line after "... Candidate from"."""
    lines = group_lines(page.boxes)
    for i, line in enumerate(lines):
        text = " ".join(b.text for b in line)
        if re.search(r"candidate\s*from|regular\s*candidate|private\s*candidate", text, re.I):
            rest = re.split(r"from", text, flags=re.I)[-1].strip(" :.")
            if len(rest) > 8 and not re.search(r"candidate", rest, re.I):
                conf = min(b.confidence for b in line)
                return make_field(clean_spaces(rest).upper(), conf, raw=text)
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                t = clean_spaces(" ".join(respace(page, b, b.text) for b in nxt))
                if len(t) > 5 and not re.search(r"statement|grade|marks", t, re.I):
                    conf = sum(b.confidence for b in nxt) / len(nxt)
                    return make_field(t.upper().strip(" ."), conf, raw=t)
    hit = _label_any(page.boxes, INSTITUTE_LABELS[1:], threshold=85)
    if hit:
        label, lab = hit
        right = boxes_right_of(page.boxes, label, max_gap=20)
        if right:
            t = clean_spaces(" ".join(b.text for b in right))
            return make_field(t.upper(), min(b.confidence for b in right), raw=t)
    return FieldResult.missing("institution not found")


# ------------------------------------------------------------------ marks table


def _int(text: str) -> Optional[int]:
    d = digits_only(text)
    return int(d) if d and len(d) <= 4 else None


def _numbers_in(line: Sequence[TextBox]) -> List[TextBox]:
    out = []
    for b in line:
        t = b.text.strip()
        if re.fullmatch(r"[0-9OoIlSB|]{2,4}", t) or (re.fullmatch(r"[0-9]{1,4}", t)):
            out.append(b)
    return out


def _column_x(boxes: Sequence[TextBox], words: Sequence[str]) -> Optional[float]:
    hit = _label_any(boxes, words, threshold=75)
    return hit[0].cx if hit else None


def extract_marks(page: Page) -> Tuple[List[Dict], Dict[str, FieldResult], List[str]]:
    """Reads the subject-wise marks table.

    Returns:
        ``(rows, totals, warnings)`` where rows are dicts with ``subject``,
        ``max_marks`` and ``obtained_marks`` and totals holds ``total_marks``
        and ``max_marks`` FieldResults.
    """
    boxes = page.boxes
    warnings: List[str] = []
    max_x = _column_x(boxes, ("Maximum", "Max Marks", "Total Marks"))
    obt_x = _column_x(boxes, ("Obtained", "Marks Obtained", "Obtained Marks"))
    header = _label_any(boxes, ("Subject(s)", "Subjects", "Subject"), threshold=78)
    total_label = _label_any(boxes, ("TOTAL", "Grand Total"), threshold=85)

    lines = group_lines(boxes)
    top = header[0].y1 if header else None
    bottom = total_label[0].cy if total_label else None

    rows: List[Dict] = []
    raw_rows: List[Tuple[str, Optional[int], Optional[int], List[TextBox]]] = []
    for line in lines:
        cy = sum(b.cy for b in line) / len(line)
        if top is not None and cy <= top:
            continue
        if bottom is not None and cy >= bottom - 2:
            continue
        nums = _numbers_in(line)
        words = [b for b in line if b not in nums and re.search(r"[A-Za-z]{3,}", b.text)]
        if not words or not nums:
            continue
        subject = clean_spaces(" ".join(b.text for b in words))
        subject = re.sub(r"^[0-9]+\s*[.)]?\s*", "", subject).strip(" .:")
        if re.search(r"marks in words|islamabad|dated|grade|statement", subject, re.I):
            continue
        mx, ob = _assign_columns(nums, max_x, obt_x)
        raw_rows.append((subject.upper(), mx, ob, nums))

    total_max = total_ob = None
    total_conf = 0.0
    if total_label is not None:
        tl = total_label[0]
        same = [b for b in boxes if abs(b.cy - tl.cy) < max(tl.height, 10) * 0.8 and b is not tl]
        nums = _numbers_in(same)
        total_max, total_ob = _assign_columns(nums, max_x, obt_x)
        total_conf = min((b.confidence for b in nums), default=0.0)

    words_total = None
    for line in lines:
        t = " ".join(b.text for b in line)
        if re.search(r"marks\s*in\s*words", t, re.I):
            words_total = words_to_number(re.split(r"words\W*", t, flags=re.I)[-1])
            break

    sub_rows = [(r[0], r[1], r[2]) for r in raw_rows]
    ok, problems = check_subjects(sub_rows, total_max, total_ob)
    if not ok and raw_rows:
        raw_rows = _repair_rows(page, raw_rows, max_x, obt_x)
        sub_rows = [(r[0], r[1], r[2]) for r in raw_rows]
        ok, problems = check_subjects(sub_rows, total_max, total_ob)

    # Resolve totals using every independent source.
    sum_ob = sum(r[2] or 0 for r in sub_rows) if sub_rows and all(r[2] is not None for r in sub_rows) else None
    sum_max = sum(r[1] or 0 for r in sub_rows) if sub_rows and all(r[1] is not None for r in sub_rows) else None
    sources = [v for v in (total_ob, words_total, sum_ob) if v is not None]
    totals: Dict[str, FieldResult] = {}
    if sources:
        best = max(set(sources), key=sources.count)
        agreeing = sources.count(best)
        conf = {1: 0.6, 2: 0.95, 3: 0.99}[min(agreeing, 3)]
        if total_ob is not None and best == total_ob:
            conf = max(conf, total_conf) if agreeing > 1 else min(conf, max(total_conf, 0.4))
        f = make_field(str(best), conf)
        if agreeing == 1 and len(sources) > 1:
            f.status = FieldStatus.LOW_CONFIDENCE
            f.reason = "table total, marks-in-words and subject sum disagree"
            warnings.append("marks total could not be confirmed by a second source")
        totals["total_marks"] = f
    else:
        totals["total_marks"] = FieldResult.missing("total marks not found")

    mx_sources = [v for v in (total_max, sum_max) if v is not None]
    if mx_sources:
        if len(mx_sources) == 2 and mx_sources[0] == mx_sources[1]:
            totals["max_marks"] = make_field(str(mx_sources[0]), 0.95)
        else:
            # Prefer the printed TOTAL row; flag it unless confirmed.
            best = total_max if total_max is not None else mx_sources[0]
            f = make_field(str(best), 0.5)
            f.status = FieldStatus.LOW_CONFIDENCE
            f.reason = "maximum marks could not be confirmed by the subject rows"
            totals["max_marks"] = f
    else:
        totals["max_marks"] = FieldResult.missing("maximum marks not found")

    for subject, mx, ob in sub_rows:
        rows.append({"subject": subject, "max_marks": mx, "obtained_marks": ob})
    if rows and not ok:
        warnings.append("marks table failed validation: " + "; ".join(problems[:3]))
    if not rows:
        warnings.append("marks table not found")
    return rows, totals, warnings


def _assign_columns(
    nums: List[TextBox], max_x: Optional[float], obt_x: Optional[float]
) -> Tuple[Optional[int], Optional[int]]:
    vals = [(b, _int(b.text)) for b in nums]
    vals = [(b, v) for b, v in vals if v is not None]
    if not vals:
        return None, None
    if max_x is not None and obt_x is not None:
        mx = min(vals, key=lambda t: abs(t[0].cx - max_x))
        ob = min(vals, key=lambda t: abs(t[0].cx - obt_x))
        if mx[0] is ob[0]:
            if abs(mx[0].cx - max_x) < abs(mx[0].cx - obt_x):
                return mx[1], None
            return None, ob[1]
        return mx[1], ob[1]
    if len(vals) >= 2:
        vals.sort(key=lambda t: t[0].cx)
        return vals[-2][1], vals[-1][1]
    return None, None


def _repair_rows(page: Page, rows, max_x, obt_x):
    """Re-reads numeric cells with a digit allowlist."""
    fixed = []
    for subject, mx, ob, nums in rows:
        new_nums = []
        for b in nums:
            text, conf = page.reread(b, allowlist="0123456789", pad_x=0.4)
            new_nums.append(TextBox(text or b.text, conf or b.confidence, b.polygon))
        mx2, ob2 = _assign_columns(new_nums, max_x, obt_x)
        fixed.append((subject, mx2 if mx2 is not None else mx, ob2 if ob2 is not None else ob, nums))
    return fixed


# ------------------------------------------------------------------------- main


def extract(page: Page, level_hint: Optional[str] = None) -> Tuple[Dict[str, FieldResult], List[str], Dict, List[Dict]]:
    """Extracts a board certificate.

    Args:
        level_hint: ``"matric"`` or ``"intermediate"`` from the caller; the
            certificate title overrides it when they disagree.

    Returns:
        ``(fields, warnings, metadata, subject_rows)``.
    """
    text = page.text
    warnings: List[str] = []
    fields: Dict[str, FieldResult] = {}

    level = detect_level(text)
    if level and level_hint and level != level_hint:
        warnings.append(f"requested {level_hint} but the certificate title says {level}; parsed as {level}")
    level = level or level_hint or "matric"
    board = detect_board(text)
    board_conf = 0.9
    if board is None and CERT_NO_FORMAT.search(text) and re.search(r"islamabad", text, re.I):
        # Title line unreadable, but FBISE's certificate-number format and its
        # Islamabad header are both present.
        board, board_conf = "FBISE", 0.7
    fields["board"] = make_field(board, board_conf) if board else FieldResult.missing("issuing board not recognized")
    if board and board != "FBISE":
        warnings.append(f"{board} layout has not been verified on real samples; check fields carefully")

    for name, labels in NUMERIC_LABELS.items():
        fields[name] = _numeric_field(page, labels)
    if fields["certificate_number"].value is None:
        m = CERT_NO_FORMAT.search(text)
        if m:
            f = make_field(m.group(0), 0.7, raw=m.group(0), reason="label unreadable; matched by number format")
            fields["certificate_number"] = f

    fields["student_name"], name_label = _name_after(page, NAME_LABELS)
    fields["father_name"], father_label = _name_after(page, FATHER_LABELS)
    if fields["student_name"].value is None and father_label is not None:
        fields["student_name"] = _name_on_line_above(page, father_label)

    dob = None
    for line in group_lines(page.boxes):
        t = " ".join(b.text for b in line)
        if re.search(r"date\s*of\s*birth|d\.?o\.?b", t, re.I):
            ds = find_dates(t)
            if ds:
                dob = make_field(ds[0], min(b.confidence for b in line), raw=t)
                break
    fields["date_of_birth"] = dob or FieldResult.missing("date of birth not printed or not found")

    m = SESSION.search(text)
    if m:
        year = fix_digits(m.group(2), 0.0)
        fields["session"] = make_field(m.group(1).upper(), 0.9)
        fields["year"] = make_field(year, 0.9)
    else:
        fields["session"] = FieldResult.missing("examination session not found")
        fields["year"] = FieldResult.missing("examination year not found")
    fields["exam"] = make_field("SSC" if level == "matric" else "HSSC", 0.9)

    gm = GROUPS.search(text)
    grp_label = _label_any(page.boxes, ("Group",), threshold=85)
    group_val = None
    if grp_label is not None:
        right = boxes_right_of(page.boxes, grp_label[0], max_gap=12)
        rest = _after_label(grp_label[0].text, "Group")
        cand = rest or (right[0].text if right else "")
        cand = re.sub(r"^[a-z]+(?=[A-Z])", "", cand.strip())
        if cand and GROUPS.search(cand):
            group_val = make_field(
                clean_spaces(cand).upper(),
                (right[0].confidence if right and not rest else grp_label[0].confidence),
                raw=cand,
            )
    if group_val is None and gm:
        group_val = make_field(clean_spaces(gm.group(1)).upper(), 0.6)
    fields["group"] = group_val or FieldResult.missing("group not found")

    gr = None
    for line in group_lines(page.boxes):
        t = " ".join(b.text for b in line)
        g = GRADE.search(t)
        if g:
            gr = make_field(g.group(1).replace(" ", "").upper(), min(b.confidence for b in line), raw=t)
            break
    fields["grade"] = gr or FieldResult.missing("grade not found (often printed in a font OCR misreads)")

    fields["institute"] = _institute(page)

    rows, totals, mw = extract_marks(page)
    fields.update(totals)
    warnings.extend(mw)

    meta = {"board": board, "level": level}
    ordered = {n: fields.get(n, FieldResult.missing("not found")) for n in FIELD_NAMES}
    return ordered, warnings, meta, rows
