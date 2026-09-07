"""
Image preprocessing for docling-pk.

Prepares a document photo for OCR. Order: grayscale, then blur check,
then deskew, then denoise. Adaptive thresholding was tested directly
(A/B test comparing thresholded output against plain grayscale on real
CNIC and certificate samples) and removed: it consistently lowered
EasyOCR's own confidence on every sample tested (CNIC 0.551 vs 0.759,
Matric 0.485 vs 0.660, Intermediate 0.481 vs 0.675, all worse with
thresholding). EasyOCR's detector is trained on natural photos, not
pre-binarized ones, so feeding it our own black-and-white conversion
worked against it rather than for it. This also matches the earlier
finding on the blurry sample, where thresholding turned soft edges into
hollow, unreadable outlines.
"""

import cv2
import numpy as np
from pathlib import Path

BLUR_VARIANCE_THRESHOLD = 35.0


class TooBlurryError(ValueError):
    """Raised when an image is too blurry to reliably OCR."""


def preprocess(image_path: str) -> np.ndarray:
    """
    Prepares a document image for OCR.

    Steps:
    1. Load and validate
    2. Grayscale
    3. Blur check
    4. Deskew
    5. Denoise

    Args:
        image_path: path to the input image file.

    Returns:
        A single-channel numpy array ready for OCR.

    Raises:
        FileNotFoundError: if image_path does not exist.
        ValueError: if the file cannot be read as an image.
        TooBlurryError: if the image is too blurry to reliably OCR.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}. Check the file is a valid PNG/JPG.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _check_blur(gray)

    deskewed = _deskew(gray)
    denoised = cv2.fastNlMeansDenoising(deskewed, h=10)
    return denoised


def _check_blur(gray: np.ndarray) -> None:
    """
    Measures sharpness using the variance of the Laplacian. Threshold of
    35 picked from 4 real samples: two failing blurry images scored 12.9
    and 27.1, two working images scored 48.2 and 54.9. Small sample,
    should be recalibrated as more images are tested.
    """
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    if variance < BLUR_VARIANCE_THRESHOLD:
        raise TooBlurryError(
            f"Image too blurry to process (sharpness score {variance:.1f}, "
            f"minimum {BLUR_VARIANCE_THRESHOLD}). Please retake the photo."
        )


def _deskew(gray: np.ndarray) -> np.ndarray:
    """
    Estimates and corrects rotation using the minimum-area bounding box
    of dark pixels. Known limitation, confirmed by direct testing: this
    fails against cluttered or textured backgrounds (fabric, patterned
    surfaces), since the angle is estimated from every dark pixel in the
    frame, not the document specifically. v1 assumes a plain background.
    """
    inverted = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))

    if coords.shape[0] < 50:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = gray.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated