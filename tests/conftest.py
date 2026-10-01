"""Shared test helpers.

Most tests run the real parsers on *constructed* OCR output (text boxes at
known positions) via :class:`FakeBackend`. That exercises every line of
parsing, validation and layout logic without downloading OCR models, so the
suite runs in seconds on CI. Tests marked ``ocr`` run the real EasyOCR
models on synthetic fixture images.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest

from docling_pk.ocr.base import OCRBackend, TextBox
from docling_pk.pipeline import Page

FIXTURES = Path(__file__).parent / "fixtures"


def box(text: str, x: float, y: float, w: Optional[float] = None, h: float = 20, conf: float = 0.95) -> TextBox:
    """A text box with its top-left corner at (x, y)."""
    w = w if w is not None else max(len(text) * h * 0.55, h)
    return TextBox.from_rect(text, conf, x, y, x + w, y + h)


class FakeBackend(OCRBackend):
    """Returns preset boxes; ``recognize`` returns preset re-reads by text."""

    name = "fake"

    def __init__(self, boxes: Sequence[TextBox] = (), rereads: Optional[Dict[str, Tuple[str, float]]] = None):
        self.boxes = list(boxes)
        self.rereads = rereads or {}
        self.last_crop_shape = None
        self.calls = 0

    def read(self, image: np.ndarray) -> List[TextBox]:
        self.calls += 1
        return list(self.boxes)

    def recognize(self, image: np.ndarray, allowlist: Optional[str] = None) -> Tuple[str, float]:
        self.last_crop_shape = image.shape
        return self.rereads.get("*", ("", 0.0))


def make_page(boxes: Sequence[TextBox], rereads=None, size=(1000, 1600)) -> Page:
    backend = FakeBackend(boxes, rereads)
    image = np.full((size[0], size[1], 3), 255, dtype=np.uint8)
    return Page(image=image, boxes=list(boxes), backend=backend)


def cnic_front_boxes(
    name="Muhammad Ali",
    father="Muhammad Akram",
    gender="M",
    number="35202-1234567-9",
    dob="01.01.1995",
    doi="15.03.2020",
    doe="14.03.2030",
    shuffle_dates=False,
) -> List[TextBox]:
    """Boxes laid out like the front of a current CNIC."""
    b = [
        box("PAKISTAN", 300, 40, h=40),
        box("National Identity Card", 620, 45, h=28),
        box("ISLAMIC REPUBLIC OF PAKISTAN", 300, 100, h=16),
        box("Name", 340, 160, h=18),
        box(name, 350, 185, h=30),
        box("Father Name", 340, 310, h=18),
        box(father, 350, 335, h=30),
        box("Gender", 335, 470, h=18),
        box("Country of Stay", 455, 470, h=18),
        box(gender, 350, 505, h=28) if gender else None,
        box("Pakistan", 470, 505, h=28),
        box("Identity Number", 335, 575, h=18),
        box("Date of Birth", 635, 575, h=18),
        box(number, 345, 605, h=30),
        box(dob, 650, 605, h=30),
        box("Date of Issue", 335, 665, h=18),
        box("Date of Expiry", 635, 665, h=18),
        box(doi, 345, 700, h=30),
        box(doe, 650, 700, h=30),
        box("Holder's Signature", 910, 745, h=18),
    ]
    b = [x for x in b if x is not None]
    if shuffle_dates:
        b.reverse()
    return b


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
