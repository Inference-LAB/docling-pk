"""
Output schema for docling-pk.

Every parser returns a dict of :class:`FieldResult` objects, which the
extractor wraps in a :class:`DocumentResult`. This is the one shape every
other module builds against: the CLI, the benchmark, and the tests all
consume it, so changes here are public API changes.

Two access styles are supported on purpose. Attribute access is the typed,
IDE-friendly way::

    result.fields["cnic_number"].value

Dictionary access mirrors the JSON output exactly, which is what the
project brief's examples use::

    result["fields"]["cnic_number"]["value"]
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple


class FieldStatus(str, Enum):
    """Why a field has the value it has.

    The status exists because a field can fail for different reasons on
    different documents, and callers need to tell them apart: a field that
    is genuinely not printed on this side of the card needs a different
    response than one that is printed but unreadable.
    """

    OK = "ok"
    """Extracted and passed every validation check that applies to it."""

    LOW_CONFIDENCE = "low_confidence"
    """Extracted, but OCR confidence or a cross-check was weak. Review it."""

    INVALID = "invalid"
    """Text was found but failed format validation. ``value`` is ``None`` and
    the offending text is kept in ``raw``."""

    NOT_FOUND = "not_found"
    """The field should be on this document but could not be located."""

    NOT_APPLICABLE = "not_applicable"
    """The field is not printed on this document variant (for example the
    address on the front of a Smart CNIC)."""


@dataclass
class FieldResult:
    """A single extracted field.

    Attributes:
        value: Normalized value, or ``None`` when the field could not be read
            reliably. docling-pk never returns a guess in ``value``.
        confidence: 0.0 to 1.0. Combines OCR recognition confidence with
            validation outcomes; 0.0 whenever ``value`` is ``None``.
        status: A :class:`FieldStatus` explaining the outcome.
        reason: Human-readable explanation for any status other than ``OK``.
        raw: The OCR text the value was derived from, before normalization.

    Example:
        >>> f = FieldResult("35202-1234567-9", 0.97)
        >>> f.ok
        True
    """

    value: Optional[str]
    confidence: float
    status: FieldStatus = FieldStatus.OK
    reason: Optional[str] = None
    raw: Optional[str] = None

    def __post_init__(self) -> None:
        self.confidence = round(max(0.0, min(1.0, float(self.confidence))), 4)
        if self.value is None:
            self.confidence = 0.0
            if self.status in (FieldStatus.OK, FieldStatus.LOW_CONFIDENCE):
                self.status = FieldStatus.NOT_FOUND

    @classmethod
    def missing(
        cls,
        reason: str,
        status: FieldStatus = FieldStatus.NOT_FOUND,
        raw: Optional[str] = None,
    ) -> FieldResult:
        """Builds an empty field that records *why* it is empty."""
        return cls(value=None, confidence=0.0, status=status, reason=reason, raw=raw)

    @property
    def ok(self) -> bool:
        """``True`` if a value was extracted (whatever its confidence)."""
        return self.value is not None

    def as_date(self) -> Optional[_dt.date]:
        """Parses a ``DD-MM-YYYY`` value into a :class:`datetime.date`.

        Returns:
            The date, or ``None`` if the value is missing or not a date.

        Example:
            >>> FieldResult("14-02-2004", 0.9).as_date()
            datetime.date(2004, 2, 14)
        """
        if not self.value:
            return None
        try:
            return _dt.datetime.strptime(self.value, "%d-%m-%Y").date()
        except ValueError:
            return None

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        """Serializes to plain JSON-compatible types."""
        out: Dict[str, Any] = {
            "value": self.value,
            "confidence": self.confidence,
            "status": self.status.value,
        }
        if self.reason:
            out["reason"] = self.reason
        if include_raw and self.raw is not None:
            out["raw"] = self.raw
        return out


@dataclass
class DocumentResult:
    """The full result of extracting one document.

    Attributes:
        document_type: Canonical type, e.g. ``"cnic"``, ``"matric"``.
        fields: Field name to :class:`FieldResult`. The key set is fixed per
            document type, so callers can rely on every key being present.
        confidence: Overall document confidence. Averaged across *all*
            expected fields, including missing ones, so a document with
            several unreadable fields cannot report a high score.
        warnings: Non-fatal issues, written for an end user to read.
        raw_text: Full OCR text in reading order, for debugging.
        tables: Tabular data such as the subject-wise marks statement.
        metadata: Processing details: detected variant, board, rotation
            applied, image quality scores, OCR backend, timings.

    Example:
        >>> r = DocumentResult("cnic", {"cnic_number": FieldResult("35202-1234567-9", 0.9)}, 0.9)
        >>> r["fields"]["cnic_number"]["value"]
        '35202-1234567-9'
    """

    document_type: str
    fields: Dict[str, FieldResult]
    confidence: float
    warnings: List[str] = field(default_factory=list)
    raw_text: Optional[str] = None
    tables: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Optional[str]:
        """Shortcut for ``fields[name].value``; ``None`` for unknown names."""
        f = self.fields.get(name)
        return f.value if f is not None else None

    @property
    def missing_fields(self) -> List[str]:
        """Names of fields that have no value."""
        return [k for k, v in self.fields.items() if v.value is None]

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        """Serializes to plain JSON-compatible types.

        Args:
            include_raw: Also include ``raw_text`` and per-field ``raw`` OCR
                text. Off by default because raw OCR output can contain
                personal data that is not part of any extracted field.
        """
        out: Dict[str, Any] = {
            "document_type": self.document_type,
            "fields": {k: v.to_dict(include_raw) for k, v in self.fields.items()},
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }
        if self.tables:
            out["tables"] = self.tables
        if self.metadata:
            out["metadata"] = self.metadata
        if include_raw:
            out["raw_text"] = self.raw_text
        return out

    def to_json(self, include_raw: bool = False, indent: Optional[int] = 2) -> str:
        """Serializes to a JSON string (UTF-8 safe, Urdu kept readable)."""
        return json.dumps(self.to_dict(include_raw), ensure_ascii=False, indent=indent)

    # Mapping-style access so result["fields"]["name"]["value"] works.
    def __getitem__(self, key: str) -> Any:
        if key == "raw_text":
            return self.raw_text
        return self.to_dict(include_raw=True)[key]

    def keys(self) -> Iterator[str]:
        return iter(self.to_dict(include_raw=True).keys())


BBox = Tuple[int, int, int, int]
