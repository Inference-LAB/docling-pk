"""
Test scaffold for CNIC extraction.

Skeleton only, per this week's scope: structure and fixtures are in
place, but most tests are marked skip until fixture images are added
to tests/fixtures/. This lets the Research/Implementation Engineer's
code land and run against these immediately, without scrambling to
write tests at that point.

Known discrepancy, flagged here rather than silently worked around:
the clean-scan test below asserts confidence > 0.85 per the Week 2
guide. Real testing against actual CNIC photos measured name and
father_name at 0.65 and dates at 0.8, reflecting genuine extraction-
method uncertainty (label-adjacency matching, not a made-up number).
Document-level confidence also structurally cannot reach 0.85 while
gender and address remain unreliable by design. This test is written
to the spec as given; whether the 0.85 threshold itself needs
revisiting is a separate, already-raised question for Khadija.
"""

import pytest
from pathlib import Path

from docling_pk.preprocessor import preprocess, TooBlurryError
from docling_pk.ocr import run_ocr
from docling_pk.parsers import cnic

FIXTURES = Path(__file__).parent / "fixtures"


def _extract(image_path: Path):
    image = preprocess(str(image_path))
    raw_text, _ = run_ocr(image)
    return cnic.extract(raw_text)


@pytest.mark.skipif(not (FIXTURES / "cnic_clean.jpg").exists(), reason="fixture not added yet")
def test_clean_scan_all_fields_high_confidence():
    """Clean scan: all fields should extract with confidence > 0.85."""
    fields = _extract(FIXTURES / "cnic_clean.jpg")
    for name, result in fields.items():
        assert result.confidence > 0.85, f"{name} confidence {result.confidence} below 0.85"


@pytest.mark.skipif(not (FIXTURES / "cnic_rotated.jpg").exists(), reason="fixture not added yet")
def test_rotated_image_cnic_number_still_extracts():
    """A sideways or upside-down photo should still recover the CNIC number."""
    fields = _extract(FIXTURES / "cnic_rotated.jpg")
    assert fields["cnic_number"].value is not None


@pytest.mark.skipif(not (FIXTURES / "cnic_obscured_field.jpg").exists(), reason="fixture not added yet")
def test_obscured_field_returns_none_not_crash():
    """A partially obscured field should return None with a warning, not raise."""
    fields = _extract(FIXTURES / "cnic_obscured_field.jpg")
    obscured_result = fields["gender"]
    assert obscured_result.value is None
    assert obscured_result.confidence == 0.0


def test_invalid_path_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        preprocess("this/path/does/not/exist.jpg")


def test_invalid_image_raises_value_error(tmp_path):
    bad_file = tmp_path / "not_an_image.jpg"
    bad_file.write_text("this is not image data")
    with pytest.raises(ValueError):
        preprocess(str(bad_file))


def test_too_blurry_image_raises_too_blurry_error():
    """
    Not in the original Week 2 spec, added since blur detection is
    already implemented and tested against real samples. A blurry
    image should raise TooBlurryError, not return garbage output.
    """
    pytest.skip("needs a real blurry fixture image, see samples used in manual testing")