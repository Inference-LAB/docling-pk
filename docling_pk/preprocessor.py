from pathlib import Path

import cv2


class TooBlurryError(ValueError):
    """Raised when an image is too blurry for reliable extraction."""


def preprocess(image_path: str):
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image path does not exist: {image_path}")

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Invalid image file: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharpness < 25.0:
        raise TooBlurryError("Image is too blurry to process reliably")

    return image
