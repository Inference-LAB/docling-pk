"""
CNIC number validation.

A CNIC number has 13 digits printed as ``XXXXX-XXXXXXX-X``. Two structural
facts are used to cross-check OCR output:

* The first digit encodes the region of registration (1 Khyber
  Pakhtunkhwa, 2 former FATA, 3 Punjab, 4 Sindh, 5 Balochistan,
  6 Islamabad, 7 Gilgit-Baltistan, 8 Azad Jammu & Kashmir in practice).
  0 and 9 do not occur.
* The last digit encodes gender: odd for male, even for female.

Neither is a checksum, so a substituted middle digit cannot be detected.
That is why CNIC digits are also re-read from a tight crop with a digit-only
allowlist and compared across reads before being reported as ``ok``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from docling_pk.validation.text import fix_digits

REGION_CODES = {
    "1": "Khyber Pakhtunkhwa",
    "2": "Federally Administered Tribal Areas",
    "3": "Punjab",
    "4": "Sindh",
    "5": "Balochistan",
    "6": "Islamabad Capital Territory",
    "7": "Gilgit-Baltistan",
    "8": "Azad Jammu and Kashmir",
}

_SEP = r"[\s\-_.:,`~'–—=]{0,3}"
#: 5-7-1 digit groups with tolerant separators, after look-alike correction.
CNIC_GROUPED = re.compile(rf"(?<![0-9])([0-9]{{5}}){_SEP}([0-9]{{7}}){_SEP}([0-9])(?![0-9])")
#: Dash-anchored form without the leading boundary, for numbers glued to a
#: preceding token ("B-1235202-1234567-1" from a merged OCR box). The
#: explicit dash after the first five digits anchors the match.
CNIC_DASH_ANCHORED = re.compile(r"([0-9]{5})-([0-9]{7})[\-_.]?([0-9])(?![0-9])")
#: 13 consecutive digits.
CNIC_PLAIN = re.compile(r"(?<![0-9])([0-9]{13})(?![0-9])")


@dataclass(frozen=True)
class CNICCheck:
    """Outcome of validating a candidate CNIC number."""

    number: Optional[str]
    region: Optional[str]
    gender_digit: Optional[str]
    problems: tuple

    @property
    def valid(self) -> bool:
        return self.number is not None and not self.problems


def format_cnic(digits: str) -> str:
    """Formats 13 digits as ``XXXXX-XXXXXXX-X``."""
    return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"


def find_cnic(text: str) -> Optional[str]:
    """Finds the first CNIC-shaped number in ``text``.

    Tolerates the separator misreads seen in real OCR output (``_ : . `` and
    spaces) and letter-for-digit confusions (``O`` for ``0`` etc.).

    Example:
        >>> find_cnic("Identity Number 35202-1234567.1")
        '35202-1234567-1'
        >>> find_cnic("no number here") is None
        True
    """
    for token_text in (text, fix_digits(text, 0.6)):
        m = CNIC_GROUPED.search(token_text)
        if m:
            return format_cnic(m.group(1) + m.group(2) + m.group(3))
        m = CNIC_PLAIN.search(token_text)
        if m:
            return format_cnic(m.group(1))
    m = CNIC_DASH_ANCHORED.search(fix_digits(text, 0.6))
    if m:
        return format_cnic(m.group(1) + m.group(2) + m.group(3))
    return None


def check_cnic(number: Optional[str]) -> CNICCheck:
    """Validates a formatted CNIC number's structure.

    Example:
        >>> check_cnic("35202-1234567-9").valid
        True
        >>> check_cnic("95202-1234567-9").problems
        ('first digit 9 is not a valid region code',)
    """
    if not number:
        return CNICCheck(None, None, None, ("missing",))
    digits = re.sub(r"[^0-9]", "", number)
    if len(digits) != 13:
        return CNICCheck(None, None, None, (f"expected 13 digits, got {len(digits)}",))
    problems = []
    region = REGION_CODES.get(digits[0])
    if region is None:
        problems.append(f"first digit {digits[0]} is not a valid region code")
    return CNICCheck(format_cnic(digits), region, digits[-1], tuple(problems))


def gender_from_cnic(number: Optional[str]) -> Optional[str]:
    """Infers gender from the last digit: odd is ``"M"``, even is ``"F"``.

    Example:
        >>> gender_from_cnic("35202-1234567-9")
        'M'
    """
    if not number:
        return None
    digits = re.sub(r"[^0-9]", "", number)
    if len(digits) != 13:
        return None
    return "M" if int(digits[-1]) % 2 == 1 else "F"
