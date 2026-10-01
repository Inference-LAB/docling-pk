"""EasyOCR backend (the default engine, per the project brief)."""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from docling_pk.ocr.base import OCRBackend, TextBox, as_bgr

_READERS: Dict[Tuple[Tuple[str, ...], bool], object] = {}
_LOCK = threading.Lock()


def _gpu_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # pragma: no cover - torch import problems
        return False


def get_reader(languages: Sequence[str] = ("en",), gpu: Optional[bool] = None):
    """Returns a cached ``easyocr.Reader``.

    Creating a reader loads two neural networks from disk (and downloads them
    on first use), so readers are created once per process and per language
    set, then reused.
    """
    try:
        import easyocr
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError('The EasyOCR backend needs the urdu extra: pip install "docling-pk[urdu]"') from exc

    use_gpu = _gpu_available() if gpu is None else gpu
    key = (tuple(languages), use_gpu)
    with _LOCK:
        if key not in _READERS:
            _READERS[key] = easyocr.Reader(list(languages), gpu=use_gpu, verbose=False)
        return _READERS[key]


class EasyOCRBackend(OCRBackend):
    """Wraps :class:`easyocr.Reader`.

    Args:
        languages: EasyOCR language codes. ``("en",)`` for English documents;
            add ``"ur"`` only where Urdu text must be read, since the combined
            model injects Arabic-script noise into English words.
        gpu: Force GPU on or off. ``None`` (default) uses CUDA if available.
    """

    name = "easyocr"

    def __init__(self, languages: Sequence[str] = ("en",), gpu: Optional[bool] = None):
        self.languages = tuple(languages)
        self.gpu = gpu

    @property
    def reader(self):
        return get_reader(self.languages, self.gpu)

    def read(self, image: np.ndarray) -> List[TextBox]:
        results = self.reader.readtext(as_bgr(image), detail=1, paragraph=False)
        return [TextBox.from_polygon(text, conf, box) for box, text, conf in results if text.strip()]

    def recognize(self, image: np.ndarray, allowlist: Optional[str] = None) -> Tuple[str, float]:
        import cv2

        gray = image if image.ndim == 2 else cv2.cvtColor(as_bgr(image), cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        results = self.reader.recognize(
            gray,
            horizontal_list=[[0, w, 0, h]],
            free_list=[],
            allowlist=allowlist,
            detail=1,
        )
        if not results:
            return "", 0.0
        _, text, conf = results[0]
        return text, float(conf)
