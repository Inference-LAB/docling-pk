"""Shared helpers for document parsers."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

from docling_pk.layout import ascii_ratio, boxes_below, boxes_right_of, clean_spaces
from docling_pk.ocr.base import TextBox
from docling_pk.schema import FieldResult, FieldStatus

#: Below this confidence a found value is reported as LOW_CONFIDENCE.
LOW_CONFIDENCE = 0.55

_NAME_CHARS = re.compile(r"[^A-Za-z .'\-]")


def make_field(
    value: Optional[str],
    confidence: float,
    raw: Optional[str] = None,
    reason: Optional[str] = None,
    low: float = LOW_CONFIDENCE,
) -> FieldResult:
    """Builds a FieldResult, downgrading weak values to LOW_CONFIDENCE."""
    if value is None:
        return FieldResult.missing(reason or "not found", raw=raw)
    status = FieldStatus.OK
    if confidence < low:
        status = FieldStatus.LOW_CONFIDENCE
        reason = reason or f"OCR confidence {confidence:.2f} is low; please verify"
    return FieldResult(value=value, confidence=confidence, status=status, reason=reason, raw=raw)


def combine_confidence(*confs: float) -> float:
    """Confidence that agreeing independent reads are all wrong is the product
    of their error rates; this returns 1 minus that product."""
    err = 1.0
    for c in confs:
        err *= 1.0 - max(0.0, min(1.0, c))
    return 1.0 - err


def clean_person_name(text: str) -> Optional[str]:
    """Normalizes an OCR'd person name, or returns ``None`` if it is not one.

    Keeps letters, spaces, dots, apostrophes and hyphens; requires at least
    two letters and rejects anything containing digits.

    Example:
        >>> clean_person_name(" Ali  Hassan Khan. ")
        'Ali Hassan Khan'
        >>> clean_person_name("35202") is None
        True
    """
    if re.search(r"[0-9]", text):
        return None
    t = clean_spaces(_NAME_CHARS.sub(" ", text)).strip(" .-'")
    if sum(c.isalpha() for c in t) < 2:
        return None
    return t


_GLUED = re.compile(r"[A-Za-z]{11,}")


def respace(page, box: Optional[TextBox], text: str) -> str:
    """Restores dropped word spaces ("SAUDIARABIA") using the verifier engine.

    Only runs when the text contains a suspiciously long unbroken word and a
    second engine is configured. The verifier's spacing is adopted only if
    its letters are identical to the original, so this can fix spacing but
    can never change a character.
    """
    if box is None or page is None or getattr(page, "verifier", None) is None or not _GLUED.search(text):
        return text
    other, _ = page.reread(box, pad_x=0.15, pad_y=0.15)

    def letters(t: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", t).upper()

    if other and letters(other) == letters(text) and other.count(" ") > text.count(" "):
        return clean_spaces(other.upper() if text.isupper() else other)
    return text


def value_near_label(
    boxes: Sequence[TextBox],
    label: TextBox,
    accept,
    label_text: str = "",
    max_gap: float = 3.0,
    skip: Iterable[TextBox] = (),
) -> Optional[TextBox]:
    """First box below (or right of) ``label`` whose text passes ``accept``.

    Also handles a value printed in the same box as its label ("Gender M").
    """
    skip_set = set(id(b) for b in skip)
    if label_text:
        rest = label.text
        lt = re.sub(r"[^a-z]", "", label_text.lower())
        letters = 0
        for i, ch in enumerate(rest):
            if ch.isalpha():
                letters += 1
            if letters >= len(lt):
                rest = rest[i + 1 :]
                break
        else:
            rest = ""
        rest = rest.strip(" :.-")
        if rest and accept(rest):
            return TextBox(rest, label.confidence, label.polygon)
    for b in boxes_right_of(boxes, label, max_gap=4.0) + boxes_below(boxes, label, max_gap=max_gap):
        if id(b) in skip_set:
            continue
        if accept(b.text):
            return b
    return None


def is_label_like(text: str, labels: Sequence[str]) -> bool:
    """True if ``text`` is (a fragment of) one of the printed labels.

    Fragments matter: OCR often splits "Country of Stay" into "Country" and
    "Of Stay", and the fragment must not be taken as a value.
    """
    from rapidfuzz import fuzz

    from docling_pk.layout import label_score, normalize_label

    norm = normalize_label(text)
    for lab in labels:
        if label_score(text, lab) >= 72:
            return True
        target = normalize_label(lab)
        if len(norm) >= 4 and len(norm) < len(target) and fuzz.partial_ratio(norm, target) >= 90:
            return True
    return False


def latin_text(text: str, min_ratio: float = 0.8) -> bool:
    return ascii_ratio(text) >= min_ratio


def fields_template(names: Sequence[str], reason: str = "not found") -> Dict[str, FieldResult]:
    return {n: FieldResult.missing(reason) for n in names}


def not_applicable(reason: str) -> FieldResult:
    return FieldResult.missing(reason, status=FieldStatus.NOT_APPLICABLE)


def first(items: List, default=None):
    return items[0] if items else default
