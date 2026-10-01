"""
Main entry point: :func:`extract`.

Ties together loading, image quality checks, page normalization (rotation,
deskew, OCR), document-type routing and the per-type parsers, and returns a
:class:`~docling_pk.schema.DocumentResult`.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence, Union

from docling_pk import __version__
from docling_pk.errors import UnsupportedDocumentTypeError
from docling_pk.ocr.base import OCRBackend
from docling_pk.parsers import certificate, cnic, degree
from docling_pk.pipeline import Page, prepare_page
from docling_pk.schema import DocumentResult, FieldResult, FieldStatus
from docling_pk.validation.cnic import find_cnic
from docling_pk.vision.image_io import ImageSource, load_pages
from docling_pk.vision.quality import assess

#: Accepted ``document_type`` values (aliases map onto these).
SUPPORTED_TYPES = ("cnic", "matric", "intermediate", "degree")
_ALIASES = {
    "auto": "auto",
    "cnic": "cnic",
    "nic": "cnic",
    "id": "cnic",
    "id_card": "cnic",
    "snic": "cnic",
    "matric": "matric",
    "ssc": "matric",
    "secondary": "matric",
    "intermediate": "intermediate",
    "inter": "intermediate",
    "hssc": "intermediate",
    "fsc": "intermediate",
    "degree": "degree",
    "transcript": "degree",
    "university": "degree",
}

BackendSpec = Union[str, OCRBackend]


def _make_backend(spec: BackendSpec, gpu: Optional[bool]) -> OCRBackend:
    if isinstance(spec, OCRBackend):
        return spec
    name = str(spec).lower()
    if name == "auto":
        import importlib.util

        if importlib.util.find_spec("rapidocr") is not None:
            name = "rapidocr"
        elif importlib.util.find_spec("easyocr") is not None:
            name = "easyocr"
        else:  # pragma: no cover - depends on environment
            raise ImportError("No OCR engine installed: pip install docling-pk")
    if name == "easyocr":
        from docling_pk.ocr.easyocr_backend import EasyOCRBackend

        return EasyOCRBackend(("en",), gpu=gpu)
    if name == "rapidocr":
        from docling_pk.ocr.rapidocr_backend import RapidOCRBackend

        return RapidOCRBackend()
    raise ValueError(f"Unknown OCR backend {spec!r}; use 'auto', 'rapidocr', 'easyocr' or an OCRBackend instance.")


def _easyocr_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("easyocr") is not None


def _urdu_backend(gpu: Optional[bool]) -> Optional[OCRBackend]:
    if not _easyocr_available():
        return None
    from docling_pk.ocr.easyocr_backend import EasyOCRBackend

    return EasyOCRBackend(("ur", "en"), gpu=gpu)


def _verifier(primary: OCRBackend, verify: bool, gpu: Optional[bool]) -> Optional[OCRBackend]:
    """A second engine for re-reading critical fields, if one is installed."""
    if not verify or primary.name == "easyocr" or not _easyocr_available():
        return None
    from docling_pk.ocr.easyocr_backend import EasyOCRBackend

    return EasyOCRBackend(("en",), gpu=gpu)


def normalize_document_type(document_type: str) -> str:
    """Maps aliases (``"ssc"``, ``"fsc"``, ``"transcript"``...) to a canonical type.

    Raises:
        UnsupportedDocumentTypeError: for unknown types.
    """
    key = re.sub(r"[\s\-]+", "_", str(document_type).strip().lower())
    if key not in _ALIASES:
        raise UnsupportedDocumentTypeError(
            f"Unsupported document_type: {document_type!r}. Must be one of {('auto',) + SUPPORTED_TYPES}."
        )
    return _ALIASES[key]


def classify(page: Page) -> Optional[str]:
    """Guesses the document type from OCR text. Returns ``None`` if unsure."""
    text = page.text
    level = certificate.detect_level(text)
    if level and (certificate.detect_board(text) or re.search(r"marks|subject", text, re.I)):
        return level
    if re.search(r"identity\s*(?:card|number)|country\s*of\s*stay|holder", text, re.I):
        return "cnic"
    if re.search(r"university|transcript|degree|bachelor|master\s+of|cgpa", text, re.I):
        return "degree"
    if level:
        return level
    if find_cnic(text) and cnic.detect_side(page.boxes) != "unknown":
        return "cnic"
    return None


def _overall_confidence(fields: Dict[str, FieldResult]) -> float:
    applicable = [f for f in fields.values() if f.status != FieldStatus.NOT_APPLICABLE]
    if not applicable:
        return 0.0
    return round(sum(f.confidence for f in applicable) / len(applicable), 4)


def _field_warnings(fields: Dict[str, FieldResult]) -> List[str]:
    out = []
    for name, f in fields.items():
        if f.status in (FieldStatus.NOT_FOUND, FieldStatus.INVALID):
            out.append(f"{name}: {f.reason or f.status.value}")
        elif f.status == FieldStatus.LOW_CONFIDENCE:
            out.append(f"{name}: low confidence ({f.reason or 'verify manually'})")
    return out


def extract(
    source: Union[ImageSource, Sequence[ImageSource]],
    document_type: str = "auto",
    *,
    backend: BackendSpec = "auto",
    urdu: bool = True,
    verify: bool = True,
    gpu: Optional[bool] = None,
    auto_rotate: bool = True,
    include_raw_text: bool = True,
) -> DocumentResult:
    """Extracts structured fields from a Pakistani document image.

    Args:
        source: Path to an image or PDF, raw bytes, a NumPy array, a PIL
            image, or a list of these. For CNICs, pass ``[front, back]`` to
            get the address (printed on the back) in the same result.
        document_type: ``"cnic"``, ``"matric"``, ``"intermediate"``,
            ``"degree"`` (also covers transcripts), or ``"auto"`` to detect it.
            Aliases such as ``"ssc"``, ``"hssc"``, ``"fsc"`` are accepted.
            Matric and intermediate are confirmed against the certificate
            title, which wins if the two disagree (a warning says so).
        backend: OCR engine: ``"auto"`` (default: RapidOCR if installed,
            else EasyOCR), ``"rapidocr"``, ``"easyocr"`` (needs the ``urdu``
            extra) or any :class:`~docling_pk.ocr.base.OCRBackend`.
        urdu: Read the Urdu address on CNIC backs (needs EasyOCR; its Urdu
            model is downloaded on first use).
        verify: Re-read high-stakes fields (CNIC number, dates, marks) with a
            second, independent OCR engine when one is installed, and only
            mark them ``ok`` when the engines agree.
        gpu: Force GPU use on/off for EasyOCR. ``None`` auto-detects CUDA.
        auto_rotate: Detect and fix 90/180/270 degree rotation and skew.
        include_raw_text: Keep the full OCR text on ``result.raw_text``.

    Returns:
        A :class:`~docling_pk.schema.DocumentResult`. Never raises for a bad
        *document*: unreadable fields come back with ``value=None``, a status
        and a reason, and the overall ``warnings`` list explains problems.

    Raises:
        FileNotFoundError: ``source`` is a path that does not exist.
        ImageLoadError: the file is not a decodable image or PDF (subclass of
            ``ValueError``).
        UnsupportedDocumentTypeError: unknown ``document_type`` (subclass of
            ``ValueError``).

    Example:
        >>> from docling_pk import extract
        >>> result = extract("cnic_front.jpg", document_type="cnic")  # doctest: +SKIP
        >>> result.fields["cnic_number"].value  # doctest: +SKIP
        '35202-1234567-9'
        >>> print(result.to_json())  # doctest: +SKIP
    """
    requested = normalize_document_type(document_type)
    started = time.perf_counter()

    sources = list(source) if isinstance(source, (list, tuple)) else [source]
    images = []
    for s in sources:
        images.extend(load_pages(s))

    ocr = _make_backend(backend, gpu)
    verifier = _verifier(ocr, verify, gpu)
    warnings: List[str] = []
    quality = []
    pages: List[Page] = []
    for img in images:
        q = assess(img)
        quality.append(q.to_dict())
        for w in q.warnings:
            if w not in warnings:
                warnings.append(w)
        pages.append(prepare_page(img, ocr, auto_rotate=auto_rotate, verifier=verifier))

    doc_type = requested
    if requested == "auto":
        guesses = [classify(p) for p in pages]
        doc_type = next((g for g in guesses if g), None) or ""
        if not doc_type:
            warnings.append("could not recognize the document type; pass document_type explicitly")
            return DocumentResult(
                document_type="unknown",
                fields={},
                confidence=0.0,
                warnings=warnings,
                raw_text="\n\n".join(p.text for p in pages) if include_raw_text else None,
                metadata={"version": __version__, "quality": quality},
            )

    tables: Dict[str, list] = {}
    metadata: Dict = {
        "version": __version__,
        "ocr_backend": ocr.name,
        "verifier": verifier.name if verifier else None,
    }

    if doc_type == "cnic":
        urdu_ocr = _urdu_backend(gpu) if urdu else None
        per_side, sides = [], []
        for p in pages:
            f, side_warnings, m = cnic.extract(p, urdu_backend=urdu_ocr)
            per_side.append(f)
            sides.append(m["side"])
            warnings.extend(side_warnings)
        fields = cnic.merge_sides(per_side) if len(per_side) > 1 else per_side[0]
        metadata["sides"] = sides
        if urdu and urdu_ocr is None and "back" in sides:
            warnings.append('reading the Urdu address needs EasyOCR: pip install "docling-pk[urdu]"')
    elif doc_type in ("matric", "intermediate"):
        fields, parser_warnings, m, rows = certificate.extract(pages[0], level_hint=doc_type)
        doc_type = m["level"]
        warnings.extend(parser_warnings)
        metadata.update(board=m["board"])
        if rows:
            tables["subjects"] = rows
    elif doc_type == "degree":
        fields, parser_warnings, m = degree.extract(pages[0])
        warnings.extend(parser_warnings)
        metadata.update(variant=m["variant"])
    else:  # pragma: no cover - normalize_document_type guards this
        raise UnsupportedDocumentTypeError(doc_type)

    warnings.extend(_field_warnings(fields))
    metadata["pages"] = [
        {"rotation_degrees": p.rotation * 90, "skew_degrees": round(p.skew, 2), "quality": q}
        for p, q in zip(pages, quality)
    ]
    metadata["seconds"] = round(time.perf_counter() - started, 2)

    return DocumentResult(
        document_type=doc_type,
        fields=fields,
        confidence=_overall_confidence(fields),
        warnings=list(dict.fromkeys(warnings)),
        raw_text="\n\n".join(p.text for p in pages) if include_raw_text else None,
        tables=tables,
        metadata=metadata,
    )
