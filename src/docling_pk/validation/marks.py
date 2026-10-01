"""
Marks-table validation for board certificates.

Board certificates carry two independent copies of the total: the TOTAL row
of the marks table and the "Marks in words" line. They also carry per-subject
marks that must add up to the total. Together these give a free consistency
check that catches most single-digit OCR errors in the numbers that matter
most for admissions.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Tuple

from rapidfuzz import process

_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fourty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000}
_VOCAB = list(_UNITS) + list(_TENS) + list(_SCALES)
_IGNORED = {"and", "only", "marks"}


def _canonical_word(word: str) -> Optional[str]:
    w = word.lower()
    if w in _UNITS or w in _TENS or w in _SCALES:
        return w
    if w in _IGNORED or len(w) < 3:
        return None
    hit = process.extractOne(w, _VOCAB, score_cutoff=80)
    return hit[0] if hit else None


def words_to_number(text: str) -> Optional[int]:
    """Converts English number words to an integer, tolerating OCR typos.

    Example:
        >>> words_to_number("Seven Hundred Eighty Seven")
        787
        >>> words_to_number("EIGHT HUNDRED EIGHTY-TWO")
        882
        >>> words_to_number("Five Hundred Fiffy Four")
        554
        >>> words_to_number("no numbers here") is None
        True
    """
    words = [w for w in re.split(r"[^A-Za-z]+", text) if w]
    total, current, seen = 0, 0, False
    for raw in words:
        w = _canonical_word(raw)
        if w is None:
            continue
        seen = True
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w == "thousand":
            total += max(current, 1) * 1000
            current = 0
    return total + current if seen else None


def check_subjects(
    rows: Sequence[Tuple[str, Optional[int], Optional[int]]],
    total_max: Optional[int],
    total_obtained: Optional[int],
) -> Tuple[bool, list]:
    """Checks subject rows against the totals.

    Args:
        rows: ``(subject, max_marks, obtained_marks)`` tuples.

    Returns:
        ``(consistent, problems)``. ``consistent`` is ``True`` only if every
        row is complete, no obtained mark exceeds its maximum, and both
        column sums equal the printed totals.
    """
    problems = []
    if not rows:
        return False, ["no subject rows found"]
    for name, mx, ob in rows:
        if mx is None or ob is None:
            problems.append(f"{name}: incomplete row")
        elif ob > mx:
            problems.append(f"{name}: obtained {ob} exceeds maximum {mx}")
    if problems:
        return False, problems
    sum_max = sum(r[1] for r in rows)  # type: ignore[misc]
    sum_ob = sum(r[2] for r in rows)  # type: ignore[misc]
    if total_max is not None and sum_max != total_max:
        problems.append(f"maximum marks add up to {sum_max}, total says {total_max}")
    if total_obtained is not None and sum_ob != total_obtained:
        problems.append(f"obtained marks add up to {sum_ob}, total says {total_obtained}")
    return not problems, problems


def agree(values: Iterable[Optional[int]]) -> Optional[int]:
    """Returns the value if all non-``None`` values are equal, else ``None``."""
    vals = {v for v in values if v is not None}
    return vals.pop() if len(vals) == 1 else None
