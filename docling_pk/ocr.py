from typing import Iterable

import numpy as np


def run_ocr(image: np.ndarray, languages: Iterable[str] = ("en",)) -> tuple[str, float]:
    import easyocr

    reader = easyocr.Reader(list(languages), gpu=False)
    results = reader.readtext(image)

    text_parts = [item[1] for item in results]
    confidences = [float(item[2]) for item in results]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return "\n".join(text_parts), avg_confidence
