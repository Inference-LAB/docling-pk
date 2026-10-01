"""
Page normalization: from an arbitrary photo to an upright, deskewed page with
positioned OCR text boxes.

Steps:

1. Scale to a working resolution (large phone photos are slow to OCR and
   gain nothing; tiny images lose characters).
2. Pick the right-angle orientation (0/90/180/270) by reading a low-res copy
   with an *English-only* reader and scoring how much of the output is
   confident Latin text. The original pipeline scored ``confidence x
   detection_count`` with an English+Urdu reader; on a sideways card the Urdu
   model produced dozens of confident one-character Arabic-script fragments,
   so a sideways read beat the correct upright one and the cleanest CNIC
   photo in the sample set extracted 0 of 8 fields.
3. Correct residual skew from text-line angles.
4. Full-resolution OCR, producing :class:`~docling_pk.ocr.base.TextBox` es.

The result, :class:`Page`, also supports re-reading a single region
(``Page.reread``), which parsers use to get a second, character-restricted
read of high-stakes fields such as the CNIC number.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from docling_pk.layout import ascii_ratio, reading_order_text
from docling_pk.ocr.base import OCRBackend, TextBox
from docling_pk.vision.geometry import (
    crop_box,
    estimate_skew,
    resize_long_side,
    rotate_bound,
    rotate_right_angle,
)

#: Long side used for orientation probing.
PROBE_SIDE = 960
#: Long side for the main OCR pass. Upscales small images, downsizes huge ones.
WORK_SIDE = 1800
#: Skew (degrees) below which no rotation is applied.
MIN_SKEW = 1.0

#: Words that only read correctly when the page is upright. Matching any of
#: them strongly confirms an orientation.
ANCHOR_WORDS = (
    "pakistan",
    "national",
    "identity",
    "card",
    "name",
    "father",
    "gender",
    "country",
    "birth",
    "issue",
    "expiry",
    "federal",
    "board",
    "education",
    "certificate",
    "secondary",
    "intermediate",
    "roll",
    "registration",
    "serial",
    "university",
    "transcript",
    "degree",
    "bachelor",
    "subject",
    "marks",
    "total",
    "islamabad",
    "lahore",
    "certified",
    "signature",
)
_WORD = re.compile(r"[A-Za-z]{3,}")


@dataclass
class Page:
    """An upright, deskewed page image and its OCR text boxes."""

    image: np.ndarray
    boxes: List[TextBox]
    backend: OCRBackend
    rotation: int = 0
    skew: float = 0.0
    verifier: Optional[OCRBackend] = None
    timings: Dict[str, float] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """All text in reading order."""
        return reading_order_text(self.boxes)

    def reread(
        self,
        box: TextBox,
        allowlist: Optional[str] = None,
        pad_x: float = 0.3,
        pad_y: float = 0.25,
        min_height: int = 48,
        backend: Optional[OCRBackend] = None,
    ) -> Tuple[str, float]:
        """Re-recognizes the text inside ``box`` from a padded, upscaled crop.

        When a ``verifier`` backend is configured (a second, independent OCR
        engine), it does the re-read: agreement between two different engines
        is far stronger evidence than the same engine agreeing with itself.

        Args:
            allowlist: Restrict output characters (e.g. ``"0123456789-"``).
            min_height: Crops shorter than this are upscaled to it; the
                recognizers were trained on text roughly this tall.
        """
        crop = crop_box(self.image, box, pad_x=pad_x, pad_y=pad_y)
        if crop.size == 0:
            return "", 0.0
        h = crop.shape[0]
        if h < min_height:
            s = min_height / float(h)
            crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        engine = backend or self.verifier or self.backend
        return engine.recognize(crop, allowlist=allowlist)


def latin_score(boxes: Sequence[TextBox]) -> float:
    """How strongly a set of OCR boxes looks like correctly oriented text.

    Sums, over boxes, confidence x number of Latin letters/digits, counting
    only boxes that are mostly ASCII. Each recognized anchor word adds a large
    bonus, because a word like "PAKISTAN" essentially never appears when the
    image is upside down or sideways.

    The sum is then scaled by the share of multi-character boxes that are
    wider than tall. Some engines (RapidOCR) rotate tall crops before
    recognizing them, so they read sideways text correctly and the text
    alone cannot tell a sideways page from an upright one; the box shapes
    can.
    """
    score = 0.0
    shaped = horizontal = 0
    for b in boxes:
        t = b.text.strip()
        if len(t) >= 3:
            shaped += 1
            horizontal += b.width >= b.height
        if ascii_ratio(t) < 0.7:
            continue
        n = sum(1 for c in t if c.isascii() and c.isalnum())
        score += b.confidence * n
        for w in _WORD.findall(t.lower()):
            if w in ANCHOR_WORDS and b.confidence > 0.3:
                score += 25.0
    if shaped:
        score *= horizontal / shaped
    return score


def drop_noise_boxes(boxes: Sequence[TextBox]) -> List[TextBox]:
    """Removes boxes that look like security-paper micro-text.

    Board certificates are printed on paper covered in tiny repeated text
    ("FEDERAL BOARD OF INTERMEDIATE..."). OCR engines read it as dozens of
    low-confidence junk boxes that interleave with real lines and break
    line grouping. Real text on a document is printed at a consistent size,
    so boxes much smaller than the confident text *and* themselves
    unconfident are dropped. Confident small text (e.g. "ISLAMIC REPUBLIC
    OF PAKISTAN" on a CNIC) is kept.
    """
    ref = sorted(b.height for b in boxes if b.confidence >= 0.9 and len(b.text.strip()) >= 3)
    if len(ref) < 3:
        return list(boxes)
    median = ref[len(ref) // 2]
    return [b for b in boxes if not (b.height < 0.6 * median and b.confidence < 0.8)]


def suppress_light_ink(image: np.ndarray) -> np.ndarray:
    """Whitens everything lighter than the dark ink.

    Security micro-text and background guilloche patterns are printed in
    light ink; the data is printed in dark ink. The cut-off is chosen per
    image with Otsu's method. Unlike binarization, pixels darker than the
    cut-off keep their gray levels, so character edges stay anti-aliased the
    way OCR models expect.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out = gray.copy()
    out[out > thresh] = 255
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def detect_orientation(image: np.ndarray, backend: OCRBackend) -> Tuple[int, Dict[int, float]]:
    """Returns the counter-clockwise quarter turns that make ``image`` upright.

    Upright is tried first; the other three orientations are only read when
    the upright read is not already convincing, so already-upright scans pay
    for one low-resolution OCR pass, not four.
    """
    probe, _ = resize_long_side(image, PROBE_SIDE)
    scores: Dict[int, float] = {}
    scores[0] = latin_score(backend.read(probe))
    if scores[0] >= 150.0:
        return 0, scores
    for k in (1, 3, 2):
        scores[k] = latin_score(backend.read(rotate_right_angle(probe, k)))
    best = max(scores, key=lambda k: scores[k])
    return best, scores


def prepare_page(
    image: np.ndarray,
    backend: OCRBackend,
    orientation_backend: Optional[OCRBackend] = None,
    auto_rotate: bool = True,
    verifier: Optional[OCRBackend] = None,
) -> Page:
    """Runs orientation, deskew and full OCR on a BGR image.

    Args:
        backend: Backend for the main read.
        orientation_backend: Backend used for orientation probing; must be an
            English/Latin reader. Defaults to ``backend``.
        verifier: Optional second engine used by :meth:`Page.reread`.
        auto_rotate: Set ``False`` to trust the input orientation.
    """
    timings: Dict[str, float] = {}
    t0 = time.perf_counter()
    work, _ = resize_long_side(image, WORK_SIDE)

    rotation = 0
    if auto_rotate:
        rotation, _ = detect_orientation(work, orientation_backend or backend)
        work = rotate_right_angle(work, rotation)
    timings["orientation"] = time.perf_counter() - t0

    t1 = time.perf_counter()
    boxes = backend.read(work)
    skew = estimate_skew(boxes)
    if abs(skew) >= MIN_SKEW:
        work = rotate_bound(work, -skew)
        boxes = backend.read(work)
    kept = drop_noise_boxes(boxes)
    dropped = len(boxes) - len(kept)
    boxes = kept
    if dropped >= max(10, 0.2 * (len(boxes) + dropped)):
        # Heavy micro-text background: try an ink-only copy, keep the better read.
        variant = suppress_light_ink(work)
        alt = drop_noise_boxes(backend.read(variant))
        if latin_score(alt) > latin_score(boxes):
            work, boxes = variant, alt
            timings["ink_only_variant"] = 1.0
    timings["ocr"] = time.perf_counter() - t1

    return Page(
        image=work,
        boxes=boxes,
        backend=backend,
        rotation=rotation,
        skew=skew,
        verifier=verifier,
        timings=timings,
    )
