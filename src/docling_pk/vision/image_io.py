"""
Loading documents into images.

Accepts file paths (images or PDFs), raw bytes, NumPy arrays and PIL images,
so the library works the same whether the caller has a file on disk, an
upload from a web form, or a frame already in memory.

Paths are read with ``np.fromfile`` + ``cv2.imdecode`` rather than
``cv2.imread`` because ``cv2.imread`` silently returns ``None`` for paths
with non-ASCII characters on Windows (for example a folder named in Urdu),
which would surface as a misleading "not a valid image" error.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Union

import cv2
import numpy as np

from docling_pk.errors import ImageLoadError

ImageSource = Union[str, "os.PathLike[str]", bytes, bytearray, np.ndarray, Any]

PDF_SUFFIXES = {".pdf"}
PDF_RENDER_DPI = 200


def load_pages(source: ImageSource, max_pages: int = 10) -> List[np.ndarray]:
    """Loads a document as a list of BGR ``uint8`` images, one per page.

    Args:
        source: A path to an image or PDF, the file's bytes, a NumPy array
            (grayscale, BGR or BGRA) or a ``PIL.Image.Image``.
        max_pages: Upper bound on PDF pages rendered.

    Raises:
        FileNotFoundError: If ``source`` is a path that does not exist.
        ImageLoadError: If the data cannot be decoded as an image or PDF.
            ``ImageLoadError`` is a ``ValueError`` subclass.
    """
    if isinstance(source, np.ndarray):
        return [_normalize_array(source)]

    if _is_pil_image(source):
        rgb = np.asarray(source.convert("RGB"))  # type: ignore[union-attr]
        return [cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)]

    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        if data[:5] == b"%PDF-":
            return _render_pdf(data, max_pages)
        return [_decode(np.frombuffer(data, dtype=np.uint8), "<bytes>")]

    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        if not path.is_file():
            raise ImageLoadError(f"Not a file: {path}")
        if path.suffix.lower() in PDF_SUFFIXES:
            return _render_pdf(path.read_bytes(), max_pages)
        return [_decode(np.fromfile(str(path), dtype=np.uint8), str(path))]

    raise TypeError(
        f"Unsupported input type {type(source).__name__}; pass a path, bytes, a NumPy array or a PIL image."
    )


def load_image(source: ImageSource) -> np.ndarray:
    """Loads the first page of ``source`` as a BGR ``uint8`` image.

    Example:
        >>> img = load_image(np.zeros((10, 10), dtype=np.uint8))
        >>> img.shape
        (10, 10, 3)
    """
    return load_pages(source, max_pages=1)[0]


def _decode(buffer: np.ndarray, label: str) -> np.ndarray:
    img = cv2.imdecode(buffer, cv2.IMREAD_COLOR) if buffer.size else None
    if img is None:
        raise ImageLoadError(
            f"Could not read image: {label}. Check the file is a valid PNG, JPEG, BMP, TIFF or WebP image (or a PDF)."
        )
    return img


def _normalize_array(arr: np.ndarray) -> np.ndarray:
    if arr.size == 0:
        raise ImageLoadError("Empty image array.")
    if arr.dtype != np.uint8:
        if np.issubdtype(arr.dtype, np.floating) and arr.max() <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    if arr.ndim == 3 and arr.shape[2] == 3:
        return np.ascontiguousarray(arr)
    raise ImageLoadError(f"Unsupported image array shape {arr.shape}.")


def _is_pil_image(obj: Any) -> bool:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - PIL ships with easyocr
        return False
    return isinstance(obj, Image.Image)


def _render_pdf(data: bytes, max_pages: int) -> List[np.ndarray]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError('Reading PDFs needs PyMuPDF: pip install "docling-pk[pdf]"') from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ImageLoadError(f"Could not open PDF: {exc}") from exc
    pages = []
    zoom = PDF_RENDER_DPI / 72.0
    with doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_GRAY2BGR))
    if not pages:
        raise ImageLoadError("PDF has no pages.")
    return pages
