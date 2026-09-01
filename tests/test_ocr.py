"""
Tests for ocr.py per the Week 3 Integration Engineer spec: returns a
non-empty string on a valid image, returns something recognizable on a
known fixture. These require the actual EasyOCR model and a GPU/CPU
capable of running it, so they are skipped in CI until a lightweight
testing strategy (small fixtures, mocked reader) is added, consistent
with the approach already documented in test_smoke.py.
"""

import pytest
from pathlib import Path

from docling_pk.preprocessor import preprocess
from docling_pk.ocr import run_ocr

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(not (FIXTURES / "cnic_clean.jpg").exists(), reason="fixture not added yet, and requires a downloaded EasyOCR model")
def test_returns_non_empty_string_on_valid_image():
    image = preprocess(str(FIXTURES / "cnic_clean.jpg"))
    text, confidence = run_ocr(image)
    assert isinstance(text, str)
    assert len(text) > 0
    assert confidence > 0.0


@pytest.mark.skipif(not (FIXTURES / "cnic_clean.jpg").exists(), reason="fixture not added yet, and requires a downloaded EasyOCR model")
def test_recognizes_known_content_on_fixture():
    """Known fixture should contain the word 'PAKISTAN' somewhere in the raw text."""
    image = preprocess(str(FIXTURES / "cnic_clean.jpg"))
    text, _ = run_ocr(image)
    assert "PAKISTAN" in text.upper()