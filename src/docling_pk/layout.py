"""
Spatial helpers over OCR text boxes.

The original parsers worked on newline-joined OCR text and assumed a value
always follows its label in reading order. Real EasyOCR output breaks that
assumption: on CNICs it reads all three date labels as one group and the
three date values as another, and the field-to-value mapping silently
depended on card layout. Working on positions instead of order removes that
whole class of failure: "the value is the text directly below its label,
in the same column" holds no matter how the OCR engine orders its output.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from rapidfuzz import fuzz

from docling_pk.ocr.base import TextBox

_SPACE = re.compile(r"\s+")


def normalize_label(text: str) -> str:
    """Lowercases and strips everything but ASCII letters, for label matching."""
    return re.sub(r"[^a-z]", "", text.lower())


def label_score(text: str, label: str) -> float:
    """Fuzzy similarity (0-100) between OCR text and an expected label.

    Uses the letters only, so "Date 0/ 8irth" still scores well against
    "Date of Birth".
    """
    a, b = normalize_label(text), normalize_label(label)
    if not a or not b:
        return 0.0
    return float(fuzz.ratio(a, b))


def find_label(
    boxes: Sequence[TextBox],
    label: str,
    threshold: float = 72.0,
    exclude: Iterable[str] = (),
) -> Optional[TextBox]:
    """Finds the box that best matches ``label``.

    A box can also *start* with the label (e.g. "Gender M"), which is scored
    on the leading part of the box only.

    Args:
        exclude: Other labels that must not match better than ``label``
            (prevents "Father Name" matching the "Name" label).
    """
    best, best_score = None, threshold
    target = normalize_label(label)
    for b in boxes:
        norm = normalize_label(b.text)
        if not norm:
            continue
        score = label_score(b.text, label)
        if len(norm) > len(target) + 2:
            score = max(score, float(fuzz.ratio(norm[: len(target)], target)) - 5)
        if score < best_score:
            continue
        if any(label_score(b.text, e) > score for e in exclude):
            continue
        best, best_score = b, score
    return best


def boxes_below(
    boxes: Sequence[TextBox],
    anchor: TextBox,
    max_gap: float = 3.0,
    min_overlap: float = 0.0,
    x_tolerance: float = 0.5,
) -> List[TextBox]:
    """Boxes below ``anchor`` in roughly the same column, nearest first.

    Args:
        max_gap: Maximum vertical gap, in multiples of the anchor's height.
        x_tolerance: How far a box may start left of the anchor, in multiples
            of the anchor height (values are often slightly left-aligned).
    """
    h = max(anchor.height, 1.0)
    out = []
    for b in boxes:
        if b is anchor or b.cy <= anchor.cy + h * 0.5:
            continue
        if b.y0 - anchor.y1 > max_gap * h:
            continue
        left_ok = b.x0 >= anchor.x0 - x_tolerance * h * 4
        overlap = min(b.x1, anchor.x1 + h * 8) - max(b.x0, anchor.x0 - h)
        if left_ok and overlap > min_overlap:
            out.append(b)
    return sorted(out, key=lambda b: (b.y0, b.x0))


def boxes_right_of(boxes: Sequence[TextBox], anchor: TextBox, max_gap: float = 8.0) -> List[TextBox]:
    """Boxes on the same text line to the right of ``anchor``, nearest first."""
    h = max(anchor.height, 1.0)
    out = [
        b
        for b in boxes
        if b is not anchor
        and b.x0 >= anchor.x1 - h * 1.0
        and b.cx > anchor.x1
        and abs(b.cy - anchor.cy) < h * 0.6
        and b.x0 - anchor.x1 < max_gap * h
    ]
    return sorted(out, key=lambda b: b.x0)


def group_lines(boxes: Sequence[TextBox], tolerance: float = 0.55) -> List[List[TextBox]]:
    """Groups boxes into text lines (top to bottom, each line left to right)."""
    lines: List[List[TextBox]] = []
    for b in sorted(boxes, key=lambda b: b.cy):
        for line in lines:
            ref = line[-1]
            h = max(min(ref.height, b.height), 1.0)
            if abs(ref.cy - b.cy) < h * tolerance:
                line.append(b)
                break
        else:
            lines.append([b])
    return [sorted(line, key=lambda b: b.x0) for line in lines]


def reading_order_text(boxes: Sequence[TextBox]) -> str:
    """Joins boxes into plain text, one visual line per output line."""
    return "\n".join(" ".join(b.text for b in line) for line in group_lines(boxes))


def clean_spaces(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def ascii_ratio(text: str) -> float:
    """Fraction of characters that are printable ASCII letters or digits."""
    t = text.replace(" ", "")
    if not t:
        return 0.0
    return sum(1 for c in t if c.isascii() and c.isalnum()) / len(t)
