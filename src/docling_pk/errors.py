"""Exceptions raised by docling-pk.

Only problems with the *call* raise (missing file, undecodable data, unknown
document type). Problems with the *document* (blur, glare, an unreadable
field) never raise: they come back as warnings and per-field statuses on a
partial :class:`~docling_pk.schema.DocumentResult`.
"""


class DoclingPKError(Exception):
    """Base class for all docling-pk errors."""


class ImageLoadError(DoclingPKError, ValueError):
    """The input exists but could not be decoded as an image or PDF.

    Subclasses ``ValueError`` so ``except ValueError`` keeps working.
    """


class UnsupportedDocumentTypeError(DoclingPKError, ValueError):
    """``document_type`` is not one of the supported types."""
