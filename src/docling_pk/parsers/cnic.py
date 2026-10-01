"""
CNIC (Computerized National Identity Card) extraction.

Handles the front and back of the current card designs (2012+ CNIC and
Smart NICOP/SNIC, green layout with English labels). Field strategy:

* **Positions, not order.** Each value is the text box directly below (or
  beside) its label, located by fuzzy label matching, so it does not matter
  in what order the OCR engine emits boxes.
* **Formats, then cross-checks.** The CNIC number and dates are matched by
  format, re-read from a tight crop with a digit-only allowlist, and reported
  as ``ok`` only when the reads agree or validation passes.
* **Dates are assigned chronologically** when all three are present:
  birth < issue < expiry is true of every valid card regardless of how the
  layout scrambles labels relative to values (the failure documented in the
  original lab note). Label geometry is the fallback.
* **Gender is cross-checked** against the last CNIC digit (odd = male,
  even = female). When the printed letter is unreadable, the inferred value
  is returned with a lower confidence and a reason that says it was inferred.

The address is printed only on the back, in Urdu (Nastaliq). It is read with
an Urdu-capable recognizer when one is configured, and always reported as
``low_confidence``: Nastaliq OCR quality is not yet good enough to trust
without review.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional, Sequence, Tuple

from docling_pk.layout import ascii_ratio, clean_spaces, find_label, group_lines
from docling_pk.ocr.base import OCRBackend, TextBox
from docling_pk.parsers.base import (
    clean_person_name,
    combine_confidence,
    is_label_like,
    make_field,
    not_applicable,
    value_near_label,
)
from docling_pk.pipeline import Page
from docling_pk.schema import FieldResult, FieldStatus
from docling_pk.validation.cnic import check_cnic, find_cnic, gender_from_cnic
from docling_pk.validation.dates import find_dates, parse_date, to_date

FRONT_FIELDS = [
    "name",
    "father_name",
    "gender",
    "country_of_stay",
    "cnic_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
]
BACK_FIELDS = ["address", "permanent_address"]
FIELD_NAMES = FRONT_FIELDS + BACK_FIELDS

LABELS = {
    "name": "Name",
    "father_name": "Father Name",
    "husband_name": "Husband Name",
    "gender": "Gender",
    "country_of_stay": "Country of Stay",
    "cnic_number": "Identity Number",
    "date_of_birth": "Date of Birth",
    "date_of_issue": "Date of Issue",
    "date_of_expiry": "Date of Expiry",
}
ALL_LABEL_TEXTS = list(LABELS.values()) + [
    "Holder's Signature",
    "National Identity Card",
    "Islamic Republic of Pakistan",
    "Pakistan",
]

CNIC_ALLOWLIST = "0123456789-"
DATE_ALLOWLIST = "0123456789."

#: Fixed sentence printed on every card back ("if found, drop in a letter box").
_LOST_CARD_HINT = ("گمشدہ", "کارڈ", "لیٹر", "بکس")
_PRESENT_LABEL = ("موجودہ", "موجوده")
_PERMANENT_LABEL = ("مستقل",)


def detect_side(boxes: Sequence[TextBox]) -> str:
    """Returns ``"front"``, ``"back"`` or ``"unknown"`` for a CNIC page."""
    front_hits = sum(
        1
        for key in ("father_name", "gender", "cnic_number", "date_of_birth", "date_of_issue", "date_of_expiry")
        if find_label(boxes, LABELS[key], threshold=78) is not None
    )
    joined = " ".join(b.text for b in boxes)
    if front_hits >= 2 or re.search(r"national\s*identity", joined, re.I):
        return "front"
    urdu = sum(1 for b in boxes if ascii_ratio(b.text) < 0.3 and len(b.text) > 3)
    if find_cnic(joined) and (urdu >= 2 or re.search(r"registrar", joined, re.I)):
        return "back"
    if find_cnic(joined):
        return "front" if find_dates(joined) else "back"
    return "unknown"


# --------------------------------------------------------------------- numbers


def _cnic_candidates(page: Page) -> List[Tuple[str, float, TextBox]]:
    out = []
    for b in page.boxes:
        n = find_cnic(b.text)
        if n:
            out.append((n, b.confidence, b))
    if not out:
        # Number split across two boxes ("35202-" "1234567-1"): try line text.
        from docling_pk.layout import group_lines

        for line in group_lines(page.boxes):
            for i in range(len(line)):
                for j in range(i + 2, min(i + 4, len(line) + 1)):
                    part = line[i:j]
                    joined = "".join(b.text for b in part)
                    n = find_cnic(joined)
                    if not n:
                        continue
                    conf = min(b.confidence for b in part)
                    out.append(
                        (
                            n,
                            conf,
                            TextBox.from_rect(
                                joined,
                                conf,
                                min(b.x0 for b in part),
                                min(b.y0 for b in part),
                                max(b.x1 for b in part),
                                max(b.y1 for b in part),
                            ),
                        )
                    )
                    break
    return out


def _reread_candidates(page: Page) -> List[Tuple[str, float, TextBox]]:
    """Digit-heavy boxes whose first read was garbled ("35202 /2345671"):
    re-read them with a digit allowlist and keep any that now validate."""
    out = []
    for b in page.boxes:
        digits = sum(c.isdigit() for c in b.text)
        if digits < 9 or find_dates(b.text):
            continue
        text, conf = page.reread(b, allowlist=CNIC_ALLOWLIST)
        n = find_cnic(text)
        if n and check_cnic(n).valid:
            out.append((n, conf * 0.85, b))
    return out


def extract_cnic_number(page: Page) -> Tuple[FieldResult, Optional[TextBox]]:
    """Finds the CNIC number and confirms it with a digit-only re-read."""
    cands = _cnic_candidates(page)
    rescued = False
    if not cands:
        cands = _reread_candidates(page)
        rescued = bool(cands)
    if not cands:
        return FieldResult.missing("no 13-digit CNIC number pattern found"), None
    if rescued:
        number, conf, box = cands[0]
        f = make_field(number, conf, raw=box.text, reason="first read was garbled; recovered by a digit-only re-read")
        f.status = FieldStatus.LOW_CONFIDENCE
        return f, box
    label = find_label(page.boxes, LABELS["cnic_number"])
    if label is not None:
        cands.sort(key=lambda c: abs(c[2].cy - label.cy) + abs(c[2].cx - label.cx) * 0.2)
    number, conf, box = cands[0]

    reread_text, reread_conf = page.reread(box, allowlist=CNIC_ALLOWLIST)
    second = find_cnic(reread_text)
    check = check_cnic(number)
    if second == number:
        conf = combine_confidence(conf, reread_conf)
        reason = None
    elif second and check_cnic(second).valid and not check.valid:
        number, conf, reason = second, reread_conf * 0.8, "first read failed validation; used digit-only re-read"
    elif second:
        # Reads disagree: keep the more confident one but flag it.
        if reread_conf > conf:
            number, conf = second, reread_conf
        conf *= 0.6
        reason = "two OCR reads of the CNIC number disagree; please verify"
    else:
        reason = None
    check = check_cnic(number)
    if not check.valid:
        return FieldResult(None, 0.0, FieldStatus.INVALID, "; ".join(check.problems), raw=box.text), box
    f = make_field(check.number, conf, raw=box.text, reason=reason)
    if reason and f.status == FieldStatus.OK:
        f.status = FieldStatus.LOW_CONFIDENCE
    return f, box


# ----------------------------------------------------------------------- dates


def _date_boxes(page: Page) -> List[Tuple[str, float, TextBox]]:
    out = []
    for b in page.boxes:
        for d in find_dates(b.text):
            out.append((d, b.confidence, b))
    return out


def _reread_date(page: Page, value: str, conf: float, box: TextBox) -> Tuple[str, float, Optional[str]]:
    text, rconf = page.reread(box, allowlist=DATE_ALLOWLIST)
    second = parse_date(text)
    if second == value:
        return value, combine_confidence(conf, rconf), None
    if second is None:
        return value, conf, None
    if rconf > conf:
        return second, rconf * 0.6, "two OCR reads of this date disagree; please verify"
    return value, conf * 0.6, "two OCR reads of this date disagree; please verify"


def extract_dates(page: Page) -> Dict[str, FieldResult]:
    """Extracts birth, issue and expiry dates.

    With three distinct dates the chronological order decides the mapping;
    otherwise each date label claims the nearest date box below it.
    """
    names = ("date_of_birth", "date_of_issue", "date_of_expiry")
    found = _date_boxes(page)
    out: Dict[str, FieldResult] = {}
    assigned: Dict[str, Tuple[str, float, TextBox]] = {}

    unique: Dict[str, Tuple[str, float, TextBox]] = {}
    for d, c, b in found:
        if d not in unique or c > unique[d][1]:
            unique[d] = (d, c, b)

    if len(unique) >= 3:
        ordered = sorted(unique.values(), key=lambda t: to_date(t[0]) or _dt.date.min)
        if len(ordered) > 3:
            # Keep the three closest to their labels; extra dates are noise.
            ordered = sorted(ordered, key=lambda t: -t[1])[:3]
            ordered.sort(key=lambda t: to_date(t[0]) or _dt.date.min)
        for name, item in zip(names, ordered):
            assigned[name] = item
    else:
        used = set()
        for name in names:
            label = find_label(page.boxes, LABELS[name], threshold=70)
            if label is None:
                continue
            best = None
            for d, c, b in found:
                if id(b) in used or b.cy < label.cy - label.height * 0.5:
                    continue
                dist = abs(b.cy - label.cy) + abs(b.x0 - label.x0) * 0.5
                if best is None or dist < best[0]:
                    best = (dist, (d, c, b))
            if best is not None:
                assigned[name] = best[1]
                used.add(id(best[1][2]))

    for name in names:
        if name not in assigned:
            out[name] = FieldResult.missing(f"{LABELS[name].lower()} not found")
            continue
        value, conf, box = assigned[name]
        value, conf, reason = _reread_date(page, value, conf, box)
        out[name] = make_field(value, conf, raw=box.text, reason=reason)
        if reason:
            out[name].status = FieldStatus.LOW_CONFIDENCE
    return out


def check_date_logic(fields: Dict[str, FieldResult]) -> List[str]:
    """Plausibility checks across CNIC dates; returns warnings."""
    warnings = []
    dob = fields["date_of_birth"].as_date()
    doi = fields["date_of_issue"].as_date()
    doe = fields["date_of_expiry"].as_date()
    if dob and doi and not dob < doi:
        warnings.append("date of birth is not before date of issue; dates may be misread")
    if doi and doe and not doi < doe:
        warnings.append("date of issue is not before date of expiry; dates may be misread")
    for name in ("date_of_birth", "date_of_issue", "date_of_expiry"):
        if warnings and fields[name].status == FieldStatus.OK:
            fields[name].status = FieldStatus.LOW_CONFIDENCE
            fields[name].reason = "dates failed the birth < issue < expiry check"
    return warnings


# ----------------------------------------------------------------- text fields


def _name_value(text: str) -> bool:
    return ascii_ratio(text) >= 0.8 and clean_person_name(text) is not None and not is_label_like(text, ALL_LABEL_TEXTS)


def extract_names(page: Page) -> Dict[str, FieldResult]:
    boxes = page.boxes
    out: Dict[str, FieldResult] = {}
    father_label = find_label(boxes, LABELS["father_name"], exclude=[LABELS["name"]])
    husband_label = None
    if father_label is None:
        husband_label = find_label(boxes, LABELS["husband_name"], exclude=[LABELS["name"]])
    guardian_label = father_label or husband_label
    name_label = find_label(
        boxes, LABELS["name"], threshold=80, exclude=[LABELS["father_name"], LABELS["husband_name"]]
    )

    skip = [guardian_label] if guardian_label else []
    if name_label is not None:
        b = value_near_label(boxes, name_label, _name_value, "Name", max_gap=2.5, skip=skip)
        if b is not None and (guardian_label is None or b.cy < guardian_label.cy):
            out["name"] = make_field(clean_person_name(b.text), b.confidence, raw=b.text)
    if guardian_label is not None:
        lt = "Father Name" if father_label else "Husband Name"
        b = value_near_label(boxes, guardian_label, _name_value, lt, max_gap=2.5)
        if b is not None:
            f = make_field(clean_person_name(b.text), b.confidence, raw=b.text)
            if husband_label is not None:
                f.reason = "card prints Husband Name in this position"
            out["father_name"] = f
    if "name" not in out or "father_name" not in out:
        _names_by_position(page, out)
    out.setdefault("name", FieldResult.missing("name label or value not found"))
    out.setdefault("father_name", FieldResult.missing("father name label or value not found"))
    return out


def _names_by_position(page: Page, out: Dict[str, FieldResult]) -> None:
    """Fallback when labels are unreadable: on the card front the holder's
    name and the father's name are the first two Latin-script name lines
    below the header and above the gender / identity-number rows."""
    boxes = page.boxes
    header = find_label(boxes, "National Identity Card", threshold=70) or find_label(boxes, "PAKISTAN", threshold=80)
    stops = [b for b in boxes if find_cnic(b.text) or find_dates(b.text)]
    for key in ("gender", "country_of_stay", "cnic_number"):
        lab = find_label(boxes, LABELS[key], threshold=70)
        if lab is not None:
            stops.append(lab)
    top = header.y1 if header is not None else 0.0
    bottom = min((b.y0 for b in stops), default=float("inf"))
    names = [
        b
        for b in sorted(boxes, key=lambda b: b.cy)
        if top - 2 <= b.y0
        and b.y1 <= bottom + 2
        and _name_value(b.text)
        and len(re.sub(r"[^A-Za-z]", "", b.text)) >= 5
        and b.confidence >= 0.6
    ]
    taken = {f.raw for f in out.values()}
    names = [b for b in names if b.text not in taken]
    # Stay in the label column: values start near the left edge of the field
    # labels, not under the photo (which may carry other printed text).
    found_labels = [
        find_label(boxes, LABELS[k], threshold=70) for k in ("father_name", "gender", "cnic_number", "date_of_issue")
    ]
    column: List[TextBox] = [b for b in found_labels if b is not None]
    if column:
        left = min(b.x0 for b in column)
        unit = sorted(b.height for b in column)[len(column) // 2]
        names = [b for b in names if left - 3 * unit <= b.x0 <= left + 4 * unit]
    father = out.get("father_name")
    if "name" not in out and father is not None and father.value is not None:
        fbox = next((b for b in boxes if b.text == father.raw), None)
        if fbox is not None:  # the holder's name is printed above the father's
            names = [b for b in names if b.cy < fbox.cy]
    if names:
        # Values are printed larger than labels; garbled labels ("Fitay Home"
        # for "Father Name") would otherwise pass as names.
        tallest = max(b.height for b in names)
        names = [b for b in names if b.height >= 0.75 * tallest]
    if "name" in out:
        anchor = out["name"]
        names = [b for b in names if b.text != anchor.raw]
    slots = [k for k in ("name", "father_name") if k not in out]
    for key, b in zip(slots, names):
        f = make_field(
            clean_person_name(b.text),
            b.confidence * 0.85,
            raw=b.text,
            reason="label unreadable; located by position on the card",
        )
        f.status = FieldStatus.LOW_CONFIDENCE
        out[key] = f


def extract_gender(page: Page, cnic_number: Optional[str]) -> FieldResult:
    boxes = page.boxes
    inferred = gender_from_cnic(cnic_number)
    label = find_label(boxes, LABELS["gender"])

    def accept(t: str) -> bool:
        return re.fullmatch(r"\s*[MFX]\s*[.|]?\s*", t.upper()) is not None

    printed: Optional[TextBox] = None
    if label is not None:
        printed = value_near_label(boxes, label, accept, "Gender", max_gap=2.5)
    if printed is None:
        # Standalone M/F box anywhere above the identity number row.
        num_label = find_label(boxes, LABELS["cnic_number"])
        for b in boxes:
            if accept(b.text) and (num_label is None or b.cy < num_label.cy):
                printed = b
                break

    if printed is not None:
        value = printed.text.strip().upper()[0]
        if inferred and value != "X" and value != inferred:
            return make_field(
                value,
                printed.confidence * 0.5,
                raw=printed.text,
                reason=f"printed gender {value} disagrees with CNIC number (suggests {inferred})",
            )
        conf = printed.confidence
        if inferred == value:
            conf = combine_confidence(conf, 0.9)
        return make_field(value, conf, raw=printed.text)

    if inferred:
        f = make_field(inferred, 0.75, reason="gender not legible; inferred from last digit of CNIC number")
        f.status = FieldStatus.LOW_CONFIDENCE
        return f
    return FieldResult.missing("gender value not found")


def extract_country(page: Page) -> FieldResult:
    label = find_label(page.boxes, LABELS["country_of_stay"])
    if label is None:
        return FieldResult.missing("country of stay label not found")

    def accept(t: str) -> bool:
        t = t.strip()
        return (
            ascii_ratio(t) >= 0.9
            and len(re.sub(r"[^A-Za-z]", "", t)) >= 3
            and not is_label_like(t, list(LABELS.values()))
        )

    b = value_near_label(page.boxes, label, accept, "Country of Stay", max_gap=2.5)
    if b is None:
        return FieldResult.missing("country of stay value not found")
    value = clean_spaces(re.sub(r"[^A-Za-z ]", "", b.text)).title()
    return make_field(value, b.confidence, raw=b.text)


# -------------------------------------------------------------------- back side


URDU_WORK_SIDE = 2048


def _is_label_token(token: str, label: str) -> bool:
    from rapidfuzz import fuzz

    from docling_pk.urdu import _RASM

    t = token.strip(":،. ")
    return len(t) >= 3 and fuzz.ratio(t.translate(_RASM), label.translate(_RASM)) >= 70


def _strip_address_label(text: str) -> str:
    """Drops a leading "موجودہ پتہ :" / "مستقل پتہ :" label from a line."""
    tokens = text.split(" ")
    for i, tok in enumerate(tokens[:4]):
        if ":" in tok or _is_label_token(tok, "پتہ"):
            rest = " ".join(tokens[i + 1 :]).lstrip(": ")
            if rest:
                return rest
    return text


def extract_address(page: Page, urdu_backend: Optional[OCRBackend]) -> Dict[str, FieldResult]:
    """Reads the present and permanent addresses (Urdu) from a card back.

    The card back is re-read at a higher resolution with an Urdu recognizer,
    lines are ordered right to left, the two blocks are split at the
    "مستقل پتہ" (permanent address) label (or, failing that, at the largest
    vertical gap), and each block is normalized to standard Urdu code points
    and lexicon-corrected (see :mod:`docling_pk.urdu`).
    """
    from docling_pk.urdu import correct_address_tokens

    if urdu_backend is None:
        reason = 'address is printed in Urdu; install Urdu OCR with pip install "docling-pk[urdu]"'
        return {"address": FieldResult.missing(reason), "permanent_address": FieldResult.missing(reason)}

    from docling_pk.vision.geometry import resize_long_side

    image, _ = resize_long_side(page.image, max(URDU_WORK_SIDE, max(page.image.shape[:2])))
    boxes = urdu_backend.read(image)
    urdu = [b for b in boxes if ascii_ratio(b.text) < 0.6 or re.search(r"[A-Z]{1,2}-?[0-9]", b.text)]
    urdu = [b for b in urdu if not find_cnic(b.text) and not re.fullmatch(r"[0-9\s]{8,}", b.text)]

    lines = []
    for line in group_lines(urdu):
        line = sorted(line, key=lambda b: -b.x1)  # Urdu reads right to left
        text = clean_spaces(" ".join(b.text for b in line))
        if sum(text.count(w) for w in _LOST_CARD_HINT) >= 2 or "گمشد" in text:
            continue
        lines.append((line, text))

    split = None
    for i, (_, text) in enumerate(lines):
        if i > 0 and any(_is_label_token(t, "مستقل") for t in text.split(" ")[:3]):
            split = i
            break
    if split is None and len(lines) >= 3:
        gaps = [(lines[i + 1][0][0].y0 - max(b.y1 for b in lines[i][0]), i + 1) for i in range(len(lines) - 1)]
        gap, idx = max(gaps)
        heights = sorted(b.height for ln, _ in lines for b in ln)
        if gap > heights[len(heights) // 2] * 0.8:
            split = idx

    blocks = {"address": lines[:split] if split else lines, "permanent_address": lines[split:] if split else []}
    out = {}
    for key, block in blocks.items():
        parts = [_strip_address_label(t) for _, t in block]
        parts = [clean_spaces(p.replace(":", " ")).strip(" :،,") for p in parts]
        parts = [p for p in parts if len(p) >= 3]
        if not parts:
            reason = "Urdu address text not detected"
            if key == "permanent_address" and blocks["address"]:
                reason = "permanent address not separately printed or not detected"
            out[key] = FieldResult.missing(reason)
            continue
        confs = [b.confidence for line, _ in block for b in line]
        value = correct_address_tokens(" ".join(parts))
        out[key] = FieldResult(
            value=value,
            confidence=min(sum(confs) / len(confs), 0.5),
            status=FieldStatus.LOW_CONFIDENCE,
            reason="Urdu (Nastaliq) OCR is experimental; verify the address manually",
            raw=" | ".join(t for _, t in block),
        )
    return out


# ------------------------------------------------------------------------- main


def extract(page: Page, urdu_backend: Optional[OCRBackend] = None) -> Tuple[Dict[str, FieldResult], List[str], Dict]:
    """Extracts CNIC fields from a prepared page.

    Returns:
        ``(fields, warnings, metadata)``. ``fields`` always contains every
        name in :data:`FIELD_NAMES`; fields not printed on the detected side
        are ``not_applicable``.
    """
    side = detect_side(page.boxes)
    warnings: List[str] = []
    meta = {"side": side}
    fields: Dict[str, FieldResult] = {}

    number, _ = extract_cnic_number(page)
    fields["cnic_number"] = number

    if side == "back":
        for n in FRONT_FIELDS:
            if n != "cnic_number":
                fields[n] = not_applicable("printed on the front of the card")
        fields.update(extract_address(page, urdu_backend))
    else:
        if side == "unknown":
            warnings.append("could not confirm this is a CNIC; check document_type")
        fields.update(extract_names(page))
        fields.update(extract_dates(page))
        warnings.extend(check_date_logic(fields))
        fields["gender"] = extract_gender(page, number.value)
        fields["country_of_stay"] = extract_country(page)
        for n in BACK_FIELDS:
            fields[n] = not_applicable("printed on the back of the card; pass the back image too")

    ordered = {n: fields.get(n, FieldResult.missing("not found")) for n in FIELD_NAMES}
    return ordered, warnings, meta


def merge_sides(results: Sequence[Dict[str, FieldResult]]) -> Dict[str, FieldResult]:
    """Merges per-side field dicts (front + back) into one.

    For each field, a found value beats a missing one and higher confidence
    wins. If both sides read a CNIC number and they differ, the result is
    flagged.
    """
    merged: Dict[str, FieldResult] = {}
    for fields in results:
        for k, f in fields.items():
            cur = merged.get(k)
            if cur is None or cur.value is None and f.value is not None:
                merged[k] = f
            elif cur.value is not None and f.value is not None:
                if k == "cnic_number" and cur.value != f.value:
                    best = cur if cur.confidence >= f.confidence else f
                    merged[k] = FieldResult(
                        best.value,
                        best.confidence * 0.5,
                        FieldStatus.LOW_CONFIDENCE,
                        f"front and back CNIC numbers differ ({cur.value} vs {f.value})",
                        best.raw,
                    )
                elif k == "cnic_number":
                    merged[k] = FieldResult(
                        cur.value, combine_confidence(cur.confidence, f.confidence), cur.status, cur.reason, cur.raw
                    )
                elif f.confidence > cur.confidence:
                    merged[k] = f
            elif cur.status == FieldStatus.NOT_APPLICABLE and f.status != FieldStatus.NOT_APPLICABLE:
                merged[k] = f
    return merged
