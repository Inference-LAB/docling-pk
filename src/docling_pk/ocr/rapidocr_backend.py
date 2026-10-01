"""RapidOCR backend (PP-OCR models on ONNX Runtime).

Optional: ``pip install "docling-pk[rapidocr]"``. Much smaller than the
EasyOCR + PyTorch stack, runs fast on CPU, and is a useful second opinion
for ensembles. English/Latin only as configured here.
"""

from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np

from docling_pk.ocr.base import OCRBackend, TextBox, as_bgr

_ENGINE = None
_LOCK = threading.Lock()


def _get_engine():
    global _ENGINE
    with _LOCK:
        if _ENGINE is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise ImportError(
                    'The RapidOCR backend needs extra packages: pip install "docling-pk[rapidocr]"'
                ) from exc
            # max_candidates: the default (1000) silently drops every region past
            # the 1000th contour. Certificates printed on micro-text security
            # paper exceed it, and the dropped regions were the whole top half
            # of the page (name, roll number, board) in testing.
            _ENGINE = RapidOCR(params={"Global.log_level": "critical", "Det.max_candidates": 8000})
        return _ENGINE


class RapidOCRBackend(OCRBackend):
    """Wraps ``rapidocr.RapidOCR``."""

    name = "rapidocr"

    def read(self, image: np.ndarray) -> List[TextBox]:
        out = _get_engine()(as_bgr(image), use_det=True, use_cls=False, use_rec=True)
        if out is None or out.boxes is None or out.txts is None:
            return []
        return [TextBox.from_polygon(t, s, b) for b, t, s in zip(out.boxes, out.txts, out.scores) if t and t.strip()]

    def recognize(self, image: np.ndarray, allowlist: Optional[str] = None) -> Tuple[str, float]:
        out = _get_engine()(as_bgr(image), use_det=False, use_cls=False, use_rec=True)
        if out is None or not out.txts:
            return "", 0.0
        return str(out.txts[0]), float(out.scores[0])
