"""
Output schema for docling-pk.

Every parser (cnic, matric, intermediate, degree) returns a dict of
FieldResult objects, wrapped in a DocumentResult by the extractor. This
is the one shape every other module builds against, so a change here
affects the CLI, the tests, and every parser at once.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FieldResult:
    """A single extracted field. value is None when the field could not
    be reliably read, not a guess. confidence is 0.0 in that case."""
    value: Optional[str]
    confidence: float


@dataclass
class DocumentResult:
    """
    The full result of extracting one document.

    confidence is the average across all fields, including ones that
    were not found, not just the ones that succeeded. An earlier
    version of this averaged only the found fields, which reported a
    misleadingly high score on a document that was actually missing
    several fields. Averaging across all fields gives a lower, more
    honest number, and is the version used throughout this project.
    """
    document_type: str
    fields: dict[str, FieldResult]
    confidence: float
    warnings: list[str] = field(default_factory=list)
    raw_text: Optional[str] = None