"""Character-level cleanup for OCR output in numeric contexts."""

from __future__ import annotations

import re

#: Letters OCR engines commonly produce in place of digits. Only applied to
#: tokens that are already mostly digits, never to free text.
DIGIT_CONFUSIONS = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "Q": "0",
        "D": "0",
        "U": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "i": "1",
        "L": "1",
        "!": "1",
        "J": "1",
        "]": "1",
        "[": "1",
        "Z": "2",
        "z": "2",
        "S": "5",
        "s": "5",
        "$": "5",
        "G": "6",
        "b": "6",
        "T": "7",
        "B": "8",
        "g": "9",
        "q": "9",
    }
)

#: Arabic-Indic and Extended Arabic-Indic digits (Urdu uses the extended set).
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_ASCII_DIGIT = re.compile(r"[0-9]")


def eastern_to_ascii_digits(text: str) -> str:
    """Converts Arabic-Indic / Urdu digits to ASCII digits.

    Done explicitly and up front so the rest of the code can match with
    ``[0-9]``: Python's ``\\d`` and ``int()`` silently accept Unicode digits,
    which would let a garbled read parse as a different number.
    """
    return text.translate(_EASTERN_DIGITS)


def fix_digits(token: str, min_digit_ratio: float = 0.5) -> str:
    """Maps letter look-alikes to digits inside a mostly-numeric token.

    Example:
        >>> fix_digits("6543O1")
        '654301'
        >>> fix_digits("Name")
        'Name'
    """
    token = eastern_to_ascii_digits(token)
    core = re.sub(r"[\s\-._,:/]", "", token)
    if not core:
        return token
    ratio = len(_ASCII_DIGIT.findall(core)) / len(core)
    if ratio < min_digit_ratio:
        return token
    return token.translate(DIGIT_CONFUSIONS)


def digits_only(text: str) -> str:
    """Keeps ASCII digits only (after look-alike correction)."""
    return re.sub(r"[^0-9]", "", fix_digits(text, 0.0))
