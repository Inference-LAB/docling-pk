"""
docling-pk: structured data extraction from Pakistani identity and education
documents.

Example:
    >>> from docling_pk import extract
    >>> result = extract("cnic.jpg", document_type="cnic")  # doctest: +SKIP
    >>> result.fields["cnic_number"].value  # doctest: +SKIP
    '35202-1234567-9'
"""

__version__ = "1.0.0"

from docling_pk.errors import DoclingPKError, ImageLoadError, UnsupportedDocumentTypeError  # noqa: E402
from docling_pk.extractor import SUPPORTED_TYPES, extract  # noqa: E402
from docling_pk.schema import DocumentResult, FieldResult, FieldStatus  # noqa: E402

__all__ = [
    "extract",
    "SUPPORTED_TYPES",
    "DocumentResult",
    "FieldResult",
    "FieldStatus",
    "DoclingPKError",
    "ImageLoadError",
    "UnsupportedDocumentTypeError",
    "__version__",
]
