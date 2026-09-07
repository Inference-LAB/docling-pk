"""
OCR wrapper for docling-pk.

Wraps EasyOCR and returns plain text plus average confidence. The
reader is created once per process and reused. Languages are
configurable: CNIC needs English plus Urdu, but certificates are
almost entirely English text, and testing showed the combined en+ur
model introduces Arabic-script noise into English words that a
single-language reader does not. Default stays en+ur; pass
languages=("en",) for documents that do not need Urdu.

Phone photos are sometimes shot in the wrong orientation. Preprocessing
only corrects small skew, not full 90/180/270 rotations, so run_ocr
tries all four right-angle rotations and keeps whichever one EasyOCR
reads with the highest confidence times detection count.
"""

import numpy as np
import easyocr

_reader = None
_reader_languages = [None]


def _get_reader(languages: tuple = ("en", "ur")) -> easyocr.Reader:
    global _reader
    if _reader is None or _reader_languages[0] != languages:
        _reader = easyocr.Reader(list(languages), gpu=True)
        _reader_languages[0] = languages
    return _reader


def _ocr_once(reader: easyocr.Reader, image: np.ndarray) -> tuple[str, float, int]:
    detections = reader.readtext(image)
    if not detections:
        return "", 0.0, 0

    lines = [text for (_, text, _) in detections]
    scores = [score for (_, _, score) in detections]
    raw_text = "\n".join(lines)
    avg_confidence = sum(scores) / len(scores)
    return raw_text, avg_confidence, len(detections)


def run_ocr(image: np.ndarray, languages: tuple = ("en", "ur")) -> tuple[str, float]:
    """
    Runs OCR on a preprocessed image, correcting 90-degree rotations.

    Args:
        image: single-channel numpy array, output of preprocessor.preprocess().
        languages: EasyOCR language list. Use ("en",) for English-only
            documents like certificates, which measurably reduces noise
            compared to the default en+ur reader.

    Returns:
        A tuple of (raw_text, average_confidence) from whichever of the
        four right-angle rotations scored best.
    """
    reader = _get_reader(languages)
    best_text, best_confidence, best_score = "", 0.0, -1.0

    for k in range(4):
        rotated = np.rot90(image, k=k)
        text, confidence, count = _ocr_once(reader, rotated)
        score = confidence * count
        if score > best_score:
            best_text, best_confidence, best_score = text, confidence, score

    return best_text, best_confidence