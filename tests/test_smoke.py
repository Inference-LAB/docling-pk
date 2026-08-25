

from docling_pk.schema import FieldResult, DocumentResult
from docling_pk.parsers import cnic


def test_field_result_holds_value_and_confidence():
    result = FieldResult(value="test", confidence=0.9)
    assert result.value == "test"
    assert result.confidence == 0.9


def test_document_result_defaults():
    result = DocumentResult(document_type="cnic", fields={}, confidence=0.0)
    assert result.warnings == []
    assert result.raw_text is None


def test_cnic_extract_finds_number_from_known_text():
    """
    Real parsing logic tested against known raw text, not a live
    image, so this runs in CI without needing OCR or a GPU.
    """
    raw_text = "Identity Number\n37406-5772542-1\nGender\nM"
    fields = cnic.extract(raw_text)
    assert fields["cnic_number"].value == "37406-5772542-1"
    assert fields["gender"].value == "M"


def test_cnic_extract_returns_none_for_missing_field_not_a_crash():
    """A field genuinely absent from the text returns None, not an exception."""
    fields = cnic.extract("some unrelated text with no real fields in it")
    assert fields["cnic_number"].value is None
    assert fields["cnic_number"].confidence == 0.0