"""
OCR backend interface.

Parsers never see an OCR library directly. They receive a list of
:class:`TextBox` objects (text + confidence + position), which is what makes
layout-aware extraction possible: the original pipeline flattened OCR output
into plain text lines and then guessed which line belonged to which label,
which broke whenever EasyOCR grouped labels and values separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]


@dataclass(frozen=True)
class TextBox:
    """One detected piece of text and where it is on the page.

    Coordinates are in pixels of the image passed to the backend, with the
    origin at the top-left corner.
    """

    text: str
    confidence: float
    polygon: Tuple[Point, ...]

    @classmethod
    def from_polygon(cls, text: str, confidence: float, polygon: Sequence[Sequence[float]]) -> TextBox:
        pts = tuple((float(p[0]), float(p[1])) for p in polygon)
        return cls(text=text, confidence=float(confidence), polygon=pts)

    @classmethod
    def from_rect(cls, text: str, confidence: float, x0: float, y0: float, x1: float, y1: float) -> TextBox:
        return cls(text, float(confidence), ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))

    @property
    def x0(self) -> float:
        return min(p[0] for p in self.polygon)

    @property
    def x1(self) -> float:
        return max(p[0] for p in self.polygon)

    @property
    def y0(self) -> float:
        return min(p[1] for p in self.polygon)

    @property
    def y1(self) -> float:
        return max(p[1] for p in self.polygon)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def translated(self, dx: float, dy: float) -> TextBox:
        return TextBox(self.text, self.confidence, tuple((x + dx, y + dy) for x, y in self.polygon))

    def scaled(self, s: float) -> TextBox:
        return TextBox(self.text, self.confidence, tuple((x * s, y * s) for x, y in self.polygon))

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "box": [round(self.x0), round(self.y0), round(self.x1), round(self.y1)],
        }


class OCRBackend:
    """Base class for OCR engines.

    Subclasses implement :meth:`read` (detect and recognize every text region
    on a page) and may override :meth:`recognize` (read one pre-cropped text
    line, optionally restricted to a character allowlist) when the engine
    supports it more efficiently than a full page read.
    """

    #: Short identifier reported in ``DocumentResult.metadata``.
    name: str = "base"

    def read(self, image: np.ndarray) -> List[TextBox]:
        """Detects and recognizes all text on ``image`` (BGR or grayscale)."""
        raise NotImplementedError

    def recognize(self, image: np.ndarray, allowlist: Optional[str] = None) -> Tuple[str, float]:
        """Recognizes the text of a single cropped line.

        The default implementation runs a full :meth:`read` on the crop and
        joins the results left to right. ``allowlist`` is a hint that
        backends may ignore.

        Returns:
            ``(text, confidence)``; ``("", 0.0)`` when nothing was read.
        """
        boxes = sorted(self.read(image), key=lambda b: b.x0)
        if not boxes:
            return "", 0.0
        text = " ".join(b.text for b in boxes)
        conf = sum(b.confidence for b in boxes) / len(boxes)
        return text, conf


def as_bgr(image: np.ndarray) -> np.ndarray:
    """Returns a 3-channel uint8 copy of ``image`` suitable for any backend."""
    import cv2

    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image
