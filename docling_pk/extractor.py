"""
Main entry point for docling-pk. extract() ties preprocessing, OCR, and
the correct document-type parser together into one DocumentResult.
"""

from docling_pk.preprocessor import preprocess, TooBlurryError
from docling_pk.ocr import run_ocr
from docling_pk.parsers import cnic, matric, intermediate
from docling_pk.parsers._federal_board import detect_document_type
from docling_pk.schema import DocumentResult, FieldResult

SUPPORTED_TYPES = ("cnic", "matric", "intermediate")

# CNIC needs Urdu for label text; certificates read better English-only,
# since the combined en+ur model introduces noise into English-heavy text.
LANGUAGES_BY_TYPE = {
    "cnic": ("en", "ur"),
    "matric": ("en",),
    "intermediate": ("en",),
}

PARSERS = {
    "cnic": cnic,
    "matric": matric,
    "intermediate": intermediate,
}


def extract(image_path: str, document_type: str) -> DocumentResult:
    """
    Extracts structured fields from a document image.

    Args:
        image_path: path to the image file.
        document_type: one of "cnic", "matric", "intermediate". For
            matric/intermediate, the actual sub-type is confirmed
            against the certificate's own title text after OCR, since
            the two document types share a parser structure and the
            title is the reliable way to tell them apart.

    Returns:
        A DocumentResult with extracted fields, an overall confidence
        score (averaged across all fields, including ones not found),
        and any warnings, including a "too blurry" warning if the
        image could not be reliably processed.

    Raises:
        ValueError: if document_type is not one of the supported types,
            or if the image file is not a valid image.
        FileNotFoundError: if image_path does not exist.
    """
    if document_type not in SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported document_type: {document_type!r}. "
            f"Must be one of {SUPPORTED_TYPES}."
        )

    try:
        image = preprocess(image_path)
    except TooBlurryError as e:
        return DocumentResult(
            document_type=document_type,
            fields={},
            confidence=0.0,
            warnings=[str(e)],
            raw_text=None,
        )

    languages = LANGUAGES_BY_TYPE[document_type]
    raw_text, _ = run_ocr(image, languages=languages)

    if document_type in ("matric", "intermediate"):
        actual_type = detect_document_type(raw_text)
        parser = PARSERS[actual_type]
        document_type = actual_type
    else:
        parser = PARSERS[document_type]

    fields = parser.extract(raw_text)

    warnings = [f"{name} not found" for name, result in fields.items() if result.value is None]
    confidences = [result.confidence for result in fields.values()]
    overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return DocumentResult(
        document_type=document_type,
        fields=fields,
        confidence=round(overall_confidence, 2),
        warnings=warnings,
        raw_text=raw_text,
    )