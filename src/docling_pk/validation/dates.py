"""
Date parsing for the formats printed on Pakistani documents.

All dates are normalized to ``DD-MM-YYYY`` (the format used in the project
brief and familiar to Pakistani users). ``FieldResult.as_date()`` converts
that to :class:`datetime.date` when a real date object is needed.

Formats seen on real documents:

* ``14.02.2004``  CNIC (OCR also produces ``14,02.2004`` and ``14.02 2004``)
* ``14-02-2004``  board certificates (date of birth)
* ``14-Feb-2004`` university transcripts
* ``February 22, 2022`` / ``Feb 01, 2024``  certificate issue dates
* ``20th July 2026``  degree issuance dates
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import List, Optional

from rapidfuzz import process

from docling_pk.validation.text import fix_digits

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_KEYS = list(MONTHS) + [m[:3] for m in MONTHS] + ["sept"]

MIN_YEAR, MAX_YEAR = 1900, 2100

_NUMERIC = re.compile(
    r"(?<![0-9])([0-9OoIlS]{1,2})\s?[.,\-/]\s?([0-9OoIlS]{1,2})\s?[.,\-/ ]\s?([0-9OoIlS]{4})(?![0-9])"
)
_DAY_MON_YEAR = re.compile(r"(?<![0-9])([0-9]{1,2})(?:st|nd|rd|th)?[\s\-.,/]*([A-Za-z]{3,10})\.?[\s\-.,/]*([0-9]{4})")
_MON_DAY_YEAR = re.compile(r"([A-Za-z]{3,10})\.?\s+([0-9]{1,2})(?:st|nd|rd|th)?\s*[,.]?\s*([0-9]{4})")


def _month_number(word: str) -> Optional[int]:
    w = word.lower().strip(".")
    if w in MONTHS:
        return MONTHS[w]
    if len(w) < 3:
        return None
    match = process.extractOne(w, _MONTH_KEYS, score_cutoff=75)
    if not match:
        return None
    key = match[0]
    if key == "sept":
        return 9
    for name, num in MONTHS.items():
        if name.startswith(key[:3]):
            return num
    return None  # pragma: no cover


def _build(day: int, month: int, year: int) -> Optional[str]:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    try:
        _dt.date(year, month, day)
    except ValueError:
        return None
    return f"{day:02d}-{month:02d}-{year:04d}"


def parse_date(text: str) -> Optional[str]:
    """Parses the first date in ``text`` into ``DD-MM-YYYY``.

    Returns ``None`` if no valid calendar date is found (``31.02.2003`` is
    rejected rather than silently corrected).

    Example:
        >>> parse_date("Date of Birth 14.02.2004")
        '14-02-2004'
        >>> parse_date("Islamabad Dated February 22, 2022")
        '22-02-2022'
        >>> parse_date("20th July 2026")
        '20-07-2026'
    """
    found = find_dates(text)
    return found[0] if found else None


def find_dates(text: str) -> List[str]:
    """All valid dates in ``text``, in order of appearance, as ``DD-MM-YYYY``."""
    hits = []
    for m in _NUMERIC.finditer(text):
        d, mo, y = (fix_digits(g, 0.0) for g in m.groups())
        try:
            value = _build(int(d), int(mo), int(y))
        except ValueError:
            value = None
        if value:
            hits.append((m.start(), value))
    for m in _DAY_MON_YEAR.finditer(text):
        month = _month_number(m.group(2))
        if month:
            value = _build(int(m.group(1)), month, int(m.group(3)))
            if value:
                hits.append((m.start(), value))
    for m in _MON_DAY_YEAR.finditer(text):
        month = _month_number(m.group(1))
        if month:
            value = _build(int(m.group(2)), month, int(m.group(3)))
            if value:
                hits.append((m.start(), value))
    hits.sort()
    out: List[str] = []
    for _, v in hits:
        if v not in out:
            out.append(v)
    return out


def to_date(value: Optional[str]) -> Optional[_dt.date]:
    """Converts a ``DD-MM-YYYY`` string to :class:`datetime.date`."""
    if not value:
        return None
    try:
        return _dt.datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError:
        return None
