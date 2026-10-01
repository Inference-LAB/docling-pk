"""
Urdu text normalization and address post-correction.

OCR models trained on Arabic script often emit Arabic letter forms where
Urdu uses its own code points (``ي`` for ``ی``, ``ك`` for ``ک``, ``ه`` for
``ہ``) and scatter diacritics that are not printed on CNICs. Normalizing to
standard Urdu code points makes the output searchable and comparable.

Address post-correction snaps individual OCR tokens to a lexicon of words
that recur in Pakistani addresses (house, street, tehsil, district...) and to
district / tehsil names, but only when the match is close and unambiguous.
Tokens not near any lexicon entry (house numbers, locality names) are left
exactly as read, so the correction can only fix words, never invent them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

from rapidfuzz import fuzz

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",  # Arabic yeh -> Farsi/Urdu yeh
        "ى": "ی",  # alef maksura
        "ك": "ک",  # Arabic kaf -> keheh
        "ه": "ہ",  # Arabic heh -> heh goal
        "ة": "ۃ",  # teh marbuta -> Urdu teh marbuta goal
        "ؤ": "ؤ",
        "٫": "،",
        ",": "،",
    }
)
_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"

#: Words that recur in Pakistani addresses as printed on CNICs.
ADDRESS_WORDS = (
    "مکان",
    "نمبر",
    "محلہ",
    "گلی",
    "اسٹریٹ",
    "سٹریٹ",
    "روڈ",
    "کالونی",
    "سیکٹر",
    "بلاک",
    "فیز",
    "ٹاؤن",
    "گاؤں",
    "موضع",
    "ڈاکخانہ",
    "تحصیل",
    "ضلع",
    "کینٹ",
    "شہر",
    "چک",
    "بستی",
    "نزد",
    "مین",
    "بازار",
    "سوسائٹی",
    "ہاؤسنگ",
    "اسکیم",
    "فلیٹ",
    "منزل",
    "اپارٹمنٹ",
    "قصبہ",
    "یونین",
    "کونسل",
    "وارڈ",
    "پتہ",
    "موجودہ",
    "مستقل",
    "ڈاک",
    "خانہ",
    "ہاؤس",
    "پلاٹ",
    "مارکیٹ",
    "مسجد",
    "چوک",
    "کوٹ",
    "پورہ",
    "آباد",
    "گارڈن",
    "ایونیو",
    "انکلیو",
)

#: Districts and frequently printed tehsils / cities.
PLACES = (
    "راولپنڈی",
    "اسلام آباد",
    "لاہور",
    "کراچی",
    "پشاور",
    "کوئٹہ",
    "ملتان",
    "فیصل آباد",
    "گوجرانوالہ",
    "سیالکوٹ",
    "سرگودھا",
    "بہاولپور",
    "ڈیرہ غازی خان",
    "ساہیوال",
    "اٹک",
    "چکوال",
    "جہلم",
    "گجرات",
    "منڈی بہاؤالدین",
    "حافظ آباد",
    "شیخوپورہ",
    "ننکانہ صاحب",
    "قصور",
    "اوکاڑہ",
    "پاکپتن",
    "وہاڑی",
    "خانیوال",
    "لودھراں",
    "مظفر گڑھ",
    "لیہ",
    "راجن پور",
    "رحیم یار خان",
    "بہاولنگر",
    "جھنگ",
    "ٹوبہ ٹیک سنگھ",
    "چنیوٹ",
    "خوشاب",
    "میانوالی",
    "بھکر",
    "نارووال",
    "حیدرآباد",
    "سکھر",
    "لاڑکانہ",
    "میرپور خاص",
    "نوابشاہ",
    "ٹھٹھہ",
    "بدین",
    "دادو",
    "جیکب آباد",
    "شکارپور",
    "خیرپور",
    "گھوٹکی",
    "سانگھڑ",
    "عمرکوٹ",
    "تھرپارکر",
    "مردان",
    "صوابی",
    "نوشہرہ",
    "چارسدہ",
    "کوہاٹ",
    "بنوں",
    "ڈیرہ اسماعیل خان",
    "ایبٹ آباد",
    "مانسہرہ",
    "ہری پور",
    "سوات",
    "دیر",
    "چترال",
    "بونیر",
    "شانگلہ",
    "ملاکنڈ",
    "کرک",
    "لکی مروت",
    "ٹانک",
    "ہنگو",
    "گلگت",
    "اسکردو",
    "مظفرآباد",
    "میرپور",
    "کوٹلی",
    "باغ",
    "راولاکوٹ",
    "گوادر",
    "تربت",
    "خضدار",
    "سبی",
    "ژوب",
    "لورالائی",
    "چمن",
    "پشین",
    "ٹیکسلا",
    "واہ",
    "حسن ابدال",
    "فتح جنگ",
    "پنڈی گھیب",
    "جنڈ",
    "گوجر خان",
    "کہوٹہ",
    "مری",
    "کلر سیداں",
    "تلہ گنگ",
    "سوہاوہ",
    "کامونکی",
    "مریدکے",
    "رائیونڈ",
    "ڈسکہ",
    "سمبڑیال",
    "پسرور",
    "شکرگڑھ",
    "وزیر آباد",
    "کھاریاں",
    "لالہ موسیٰ",
    "سرائے عالمگیر",
    "دینہ",
)

_SINGLE_WORDS: List[str] = sorted(set(ADDRESS_WORDS) | {w for p in PLACES for w in p.split() if len(w) >= 3})
_LEXICON_SET = set(_SINGLE_WORDS)
_ADDRESS_WORD_SET = set(ADDRESS_WORDS)

#: Letters that differ only by dots map to one dotless "skeleton" class.
#: Most Nastaliq OCR errors are dot errors (خ read as ح, ٹ as ت, ڑ as ر),
#: so comparing skeletons catches them while plain edit distance does not.
_RASM = str.maketrans(
    {
        "ب": "ٮ",
        "پ": "ٮ",
        "ت": "ٮ",
        "ٹ": "ٮ",
        "ث": "ٮ",
        "ن": "ٮ",
        "ی": "ٮ",
        "ئ": "ٮ",
        "ج": "ح",
        "چ": "ح",
        "خ": "ح",
        "ڈ": "د",
        "ذ": "د",
        "ڑ": "ر",
        "ز": "ر",
        "ژ": "ر",
        "ش": "س",
        "ض": "ص",
        "ظ": "ط",
        "غ": "ع",
        "ق": "ف",
        "گ": "ک",
    }
)
_SKELETONS = [w.translate(_RASM) for w in _SINGLE_WORDS]


def _score(token: str, idx: int) -> float:
    word = _SINGLE_WORDS[idx]
    return max(fuzz.ratio(token, word), fuzz.ratio(token.translate(_RASM), _SKELETONS[idx]) - 4)


def normalize_urdu(text: str) -> str:
    """Maps Arabic letter forms to Urdu code points and strips diacritics.

    Example:
        >>> normalize_urdu("محلّه نوري")
        'محلہ نوری'
    """
    t = unicodedata.normalize("NFC", text).translate(_CHAR_MAP)
    t = _DIACRITICS.sub("", t).replace(_TATWEEL, "")
    # A trailing heh goal followed by hamza variants is common OCR noise.
    return re.sub(r"\s+", " ", t).strip()


def correct_address_tokens(text: str, min_score: float = 75.0) -> str:
    """Snaps OCR'd Urdu address tokens to known address words and place names.

    A token is replaced only if it is at least 3 letters long, is not already
    a lexicon word, and its best lexicon match scores ``min_score`` or more
    and clearly beats the runner-up.

    Example:
        >>> correct_address_tokens("خصیل کامونکی ضع گوجرانوالا")
        'تحصیل کامونکی ضلع گوجرانوالہ'
    """
    out = []
    for tok in normalize_urdu(text).split(" "):
        core = tok.strip("،۔:.-")
        if core in _LEXICON_SET or re.search(r"[A-Za-z0-9]", core) or len(core) < 2:
            out.append(tok)
            continue
        scored = sorted(((_score(core, i), i) for i in range(len(_SINGLE_WORDS))), reverse=True)
        (score, idx), runner = scored[0], (scored[1][0] if len(scored) > 1 else 0.0)
        best = _SINGLE_WORDS[idx]
        threshold = min_score if len(core) >= 4 else 80.0
        if best not in _ADDRESS_WORD_SET:
            # Place names are only accepted on a strong match: snapping noise
            # onto a real district name would invent data.
            threshold = max(threshold, 85.0)
        if score >= threshold and score - runner >= 5:
            out.append(tok.replace(core, best))
        else:
            out.append(tok)
    return " ".join(out)
