"""
Image quality signals.

These produce *warnings*, not rejections. The original pipeline rejected any
image whose Laplacian variance was below 35, a threshold calibrated on four
photos. Laplacian variance depends heavily on resolution and content, and on
real samples that gate rejected perfectly readable photos (a clean CNIC back
scored 15.8) while accepting worse ones. Measuring at a fixed working
resolution and reporting instead of rejecting lets the OCR result decide
whether the image was usable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import cv2
import numpy as np

#: Long side, in pixels, at which sharpness is measured.
SHARPNESS_REFERENCE_SIDE = 1000

SHARPNESS_WARN = 60.0
DARK_WARN = 60.0
BRIGHT_WARN = 225.0
GLARE_WARN = 0.04
MIN_LONG_SIDE = 640


@dataclass
class QualityReport:
    """Image quality measurements and the warnings they triggered."""

    sharpness: float
    brightness: float
    contrast: float
    glare_fraction: float
    width: int
    height: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, float]:
        return {
            "sharpness": round(self.sharpness, 1),
            "brightness": round(self.brightness, 1),
            "contrast": round(self.contrast, 1),
            "glare_fraction": round(self.glare_fraction, 4),
            "width": self.width,
            "height": self.height,
        }


def _to_gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def sharpness(image: np.ndarray) -> float:
    """Variance of the Laplacian at a fixed reference resolution."""
    gray = _to_gray(image)
    h, w = gray.shape[:2]
    scale = SHARPNESS_REFERENCE_SIDE / max(h, w)
    if abs(scale - 1.0) > 0.05:
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=interp)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def assess(image: np.ndarray) -> QualityReport:
    """Measures sharpness, exposure, contrast and glare of ``image``."""
    gray = _to_gray(image)
    h, w = gray.shape[:2]
    report = QualityReport(
        sharpness=sharpness(gray),
        brightness=float(gray.mean()),
        contrast=float(gray.std()),
        glare_fraction=float((gray >= 250).mean()),
        width=int(w),
        height=int(h),
    )
    if report.sharpness < SHARPNESS_WARN:
        report.warnings.append(
            f"Image looks blurry (sharpness {report.sharpness:.0f}); results may be "
            "incomplete. Retake the photo in focus if fields are missing."
        )
    if report.brightness < DARK_WARN:
        report.warnings.append("Image is very dark; use more light.")
    elif report.brightness > BRIGHT_WARN:
        report.warnings.append("Image is overexposed; reduce light or flash.")
    # Saturated pixels on a page that is mostly white are just paper, not
    # glare; only photos with a darker overall tone can show specular glare.
    if report.glare_fraction > GLARE_WARN and float(np.median(gray)) < 200:
        report.warnings.append(
            f"Glare covers {report.glare_fraction:.0%} of the image; tilt the document or remove plastic sleeves."
        )
    if max(h, w) < MIN_LONG_SIDE:
        report.warnings.append(f"Low resolution ({w}x{h}); small text may be misread.")
    return report
