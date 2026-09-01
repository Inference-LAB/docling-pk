"""
Tests for preprocessor.py per the Week 3 Integration Engineer spec:
returns a numpy array, handles rotated images, raises FileNotFoundError
and ValueError correctly.
"""

import numpy as np
import pytest
from pathlib import Path

from docling_pk.preprocessor import preprocess, TooBlurryError

FIXTURES = Path(__file__).parent / "fixtures"


def test_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        preprocess("this/path/does/not/exist.jpg")


def test_invalid_image_raises_value_error(tmp_path):
    bad_file = tmp_path / "not_an_image.jpg"
    bad_file.write_text("this is not image data")
    with pytest.raises(ValueError):
        preprocess(str(bad_file))


@pytest.mark.skipif(not (FIXTURES / "cnic_clean.jpg").exists(), reason="fixture not added yet")
def test_returns_numpy_array():
    result = preprocess(str(FIXTURES / "cnic_clean.jpg"))
    assert isinstance(result, np.ndarray)


@pytest.mark.skipif(not (FIXTURES / "cnic_rotated.jpg").exists(), reason="fixture not added yet")
def test_handles_rotated_image_without_crashing():
    """
    preprocess() itself only corrects small skew, not full 90-degree
    rotation (that is handled in ocr.py's rotation trial), so this
    test only confirms it does not crash or raise on a rotated image,
    not that the output is already upright.
    """
    result = preprocess(str(FIXTURES / "cnic_rotated.jpg"))
    assert isinstance(result, np.ndarray)


@pytest.mark.skipif(not (FIXTURES / "cnic_blurry.jpg").exists(), reason="fixture not added yet")
def test_too_blurry_raises_too_blurry_error():
    with pytest.raises(TooBlurryError):
        preprocess(str(FIXTURES / "cnic_blurry.jpg"))