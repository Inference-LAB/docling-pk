"""
Geometric normalization: resizing, right-angle rotation and skew correction.

Skew is estimated from the OCR engine's own text-line polygons rather than
from dark pixels. The original ``_deskew`` used ``cv2.minAreaRect`` over
every dark pixel in the frame; on real photos it returned -90 degrees for
15 of 16 samples (a no-op) because the background, the photo and the
document edges dominate the pixel set, and on OpenCV >= 4.5 the angle
convention changed so the correction formula was wrong anyway. Text lines
are exactly the structure we want horizontal, and the OCR detector already
finds them while ignoring backgrounds such as striped fabric.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

import cv2
import numpy as np

from docling_pk.ocr.base import TextBox


def resize_long_side(image: np.ndarray, target: int) -> Tuple[np.ndarray, float]:
    """Scales ``image`` so its long side equals ``target``.

    Returns:
        ``(resized, scale)`` where ``scale`` maps original to resized pixels.
    """
    h, w = image.shape[:2]
    scale = target / float(max(h, w))
    if abs(scale - 1.0) < 1e-3:
        return image, 1.0
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=interp), scale


def rotate_right_angle(image: np.ndarray, quarter_turns_ccw: int) -> np.ndarray:
    """Rotates by a multiple of 90 degrees counter-clockwise (lossless)."""
    k = quarter_turns_ccw % 4
    if k == 0:
        return image
    codes = {1: cv2.ROTATE_90_COUNTERCLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_CLOCKWISE}
    return cv2.rotate(image, codes[k])


def rotate_bound(image: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotates counter-clockwise by ``angle_deg``, enlarging the canvas so no
    corner is cropped. Border pixels are replicated, not black, so the OCR
    detector does not see a hard artificial edge."""
    if abs(angle_deg) < 0.05:
        return image
    h, w = image.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2.0 - w / 2.0
    m[1, 2] += nh / 2.0 - h / 2.0
    return cv2.warpAffine(image, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def estimate_skew(boxes: Sequence[TextBox], min_aspect: float = 2.5) -> float:
    """Estimates document skew in degrees from text-line polygons.

    Only clearly horizontal-ish, elongated boxes vote; the result is the
    confidence-weighted median of their top-edge angles. Positive means the
    text rises to the right; ``rotate_bound(image, -skew)`` levels it.
    Returns 0.0 when there is not enough evidence.
    """
    angles, weights = [], []
    for b in boxes:
        if len(b.polygon) < 4:
            continue
        (x0, y0), (x1, y1) = b.polygon[0], b.polygon[1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1 or b.height < 1 or length / max(b.height, 1.0) < min_aspect:
            continue
        a = math.degrees(math.atan2(-dy, dx))
        if abs(a) > 30:
            continue
        angles.append(a)
        weights.append(length * max(b.confidence, 0.05))
    if len(angles) < 3:
        return 0.0
    order = np.argsort(angles)
    sorted_angles = np.asarray(angles)[order]
    w = np.asarray(weights)[order]
    cum = np.cumsum(w)
    return float(sorted_angles[np.searchsorted(cum, cum[-1] / 2.0)])


def crop_box(image: np.ndarray, box: TextBox, pad_x: float = 0.25, pad_y: float = 0.25) -> np.ndarray:
    """Crops a text box with padding proportional to its height."""
    h, w = image.shape[:2]
    py = box.height * pad_y
    px = box.height * pad_x
    x0 = int(max(0, math.floor(box.x0 - px)))
    x1 = int(min(w, math.ceil(box.x1 + px)))
    y0 = int(max(0, math.floor(box.y0 - py)))
    y1 = int(min(h, math.ceil(box.y1 + py)))
    return image[y0:y1, x0:x1]
