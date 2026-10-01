"""Output schema, image loading, quality and geometry helpers."""

import datetime as dt
import json

import cv2
import numpy as np
import pytest

from docling_pk.errors import ImageLoadError
from docling_pk.ocr.base import TextBox
from docling_pk.schema import DocumentResult, FieldResult, FieldStatus
from docling_pk.vision import geometry, quality
from docling_pk.vision.image_io import load_image, load_pages

# ------------------------------------------------------------------ schema


class TestFieldResult:
    def test_missing_value_forces_zero_confidence(self):
        f = FieldResult(None, 0.9)
        assert f.confidence == 0.0 and f.status == FieldStatus.NOT_FOUND and not f.ok

    def test_confidence_clamped(self):
        assert FieldResult("x", 1.7).confidence == 1.0
        assert FieldResult("x", -1).confidence == 0.0

    def test_missing_constructor(self):
        f = FieldResult.missing("gone", status=FieldStatus.NOT_APPLICABLE, raw="r")
        assert f.value is None and f.reason == "gone" and f.raw == "r"
        assert f.status == FieldStatus.NOT_APPLICABLE

    def test_as_date(self):
        assert FieldResult("14-02-2004", 0.9).as_date() == dt.date(2004, 2, 14)
        assert FieldResult("nope", 0.9).as_date() is None
        assert FieldResult(None, 0).as_date() is None

    def test_to_dict(self):
        f = FieldResult("A", 0.5, FieldStatus.LOW_CONFIDENCE, "why", raw="a")
        assert f.to_dict() == {"value": "A", "confidence": 0.5, "status": "low_confidence", "reason": "why"}
        assert f.to_dict(include_raw=True)["raw"] == "a"


class TestDocumentResult:
    def _result(self):
        return DocumentResult(
            "cnic",
            {"cnic_number": FieldResult("35202-1234567-9", 0.9), "name": FieldResult.missing("x")},
            0.45,
            ["w"],
            raw_text="RAW",
            tables={"subjects": [{"subject": "A", "max_marks": 1, "obtained_marks": 1}]},
            metadata={"k": 1},
        )

    def test_dict_style_access_matches_brief(self):
        r = self._result()
        assert r["fields"]["cnic_number"]["value"] == "35202-1234567-9"
        assert r["document_type"] == "cnic"
        assert r["raw_text"] == "RAW"
        assert "fields" in list(r.keys())

    def test_helpers(self):
        r = self._result()
        assert r.get("cnic_number") == "35202-1234567-9"
        assert r.get("unknown") is None
        assert r.missing_fields == ["name"]

    def test_raw_text_excluded_by_default(self):
        d = self._result().to_dict()
        assert "raw_text" not in d
        assert self._result().to_dict(include_raw=True)["raw_text"] == "RAW"

    def test_json_keeps_urdu_readable(self):
        r = DocumentResult("cnic", {"address": FieldResult("گوجرانوالہ", 0.4)}, 0.4)
        s = r.to_json()
        assert "گوجرانوالہ" in s
        assert json.loads(s)["fields"]["address"]["value"] == "گوجرانوالہ"

    def test_defaults(self):
        r = DocumentResult("cnic", {}, 0.0)
        assert r.warnings == [] and r.raw_text is None and r.tables == {} and r.metadata == {}
        assert "tables" not in r.to_dict()


# -------------------------------------------------------------- image io


def _png_bytes(img):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class TestLoadImage:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_image(tmp_path / "nope.jpg")

    def test_not_an_image(self, tmp_path):
        p = tmp_path / "x.jpg"
        p.write_text("not an image")
        with pytest.raises(ImageLoadError):
            load_image(p)
        with pytest.raises(ValueError):  # ImageLoadError is a ValueError
            load_image(str(p))

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        with pytest.raises(ImageLoadError):
            load_image(p)

    def test_directory(self, tmp_path):
        with pytest.raises(ImageLoadError):
            load_image(tmp_path)

    def test_unicode_path(self, tmp_path):
        """cv2.imread fails on non-ASCII Windows paths; we must not."""
        folder = tmp_path / "دستاویزات"
        folder.mkdir()
        p = folder / "شناختی کارڈ.png"
        p.write_bytes(_png_bytes(np.full((20, 30, 3), 200, np.uint8)))
        assert load_image(p).shape == (20, 30, 3)

    def test_bytes(self):
        img = load_image(_png_bytes(np.zeros((5, 7, 3), np.uint8)))
        assert img.shape == (5, 7, 3)

    def test_bad_bytes(self):
        with pytest.raises(ImageLoadError):
            load_image(b"garbage")

    @pytest.mark.parametrize(
        "arr,shape",
        [
            (np.zeros((4, 6), np.uint8), (4, 6, 3)),
            (np.zeros((4, 6, 1), np.uint8), (4, 6, 3)),
            (np.zeros((4, 6, 4), np.uint8), (4, 6, 3)),
            (np.zeros((4, 6, 3), np.float32), (4, 6, 3)),
            (np.zeros((4, 6, 3), np.uint16), (4, 6, 3)),
        ],
    )
    def test_arrays(self, arr, shape):
        out = load_image(arr)
        assert out.shape == shape and out.dtype == np.uint8

    def test_bad_arrays(self):
        with pytest.raises(ImageLoadError):
            load_image(np.zeros((0,), np.uint8))
        with pytest.raises(ImageLoadError):
            load_image(np.zeros((2, 2, 2), np.uint8))

    def test_pil(self):
        from PIL import Image

        im = Image.new("RGB", (8, 4), (255, 0, 0))
        out = load_image(im)
        assert out.shape == (4, 8, 3) and tuple(out[0, 0]) == (0, 0, 255)

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            load_image(12345)

    def test_pdf_requires_pymupdf_or_renders(self, tmp_path):
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 50), "Roll No 123456")
        p = tmp_path / "doc.pdf"
        doc.save(str(p))
        pages = load_pages(p)
        assert len(pages) == 1 and pages[0].ndim == 3
        assert len(load_pages(p.read_bytes())) == 1


# ------------------------------------------------------------- quality


class TestQuality:
    def test_sharp_vs_blurry(self):
        rng = np.random.default_rng(0)
        sharp = (rng.random((600, 900)) > 0.5).astype(np.uint8) * 255
        blurry = cv2.GaussianBlur(sharp, (51, 51), 20)
        assert quality.sharpness(sharp) > quality.sharpness(blurry)
        assert any("blurry" in w for w in quality.assess(blurry).warnings)
        assert not any("blurry" in w for w in quality.assess(sharp).warnings)

    def test_dark_bright_glare_lowres(self):
        assert any("dark" in w for w in quality.assess(np.full((800, 800), 10, np.uint8)).warnings)
        bright = quality.assess(np.full((800, 800, 3), 255, np.uint8))
        assert any("overexposed" in w for w in bright.warnings)
        assert not any("Glare" in w for w in bright.warnings)  # white paper is not glare
        photo = np.full((800, 800), 120, np.uint8)
        photo[100:300, 100:400] = 255  # specular highlight on a mid-tone photo
        assert any("Glare" in w for w in quality.assess(photo).warnings)
        assert any("Low resolution" in w for w in quality.assess(np.full((100, 100), 128, np.uint8)).warnings)

    def test_report_dict(self):
        d = quality.assess(np.full((50, 60), 128, np.uint8)).to_dict()
        assert d["width"] == 60 and d["height"] == 50


# ------------------------------------------------------------ geometry


class TestGeometry:
    def test_resize_long_side(self):
        img, s = geometry.resize_long_side(np.zeros((100, 200, 3), np.uint8), 400)
        assert img.shape == (200, 400, 3) and s == 2.0
        same, s1 = geometry.resize_long_side(img, 400)
        assert same is img and s1 == 1.0

    @pytest.mark.parametrize("k", [0, 1, 2, 3, 4, -1])
    def test_right_angle_rotation_matches_numpy(self, k):
        img = np.arange(24, dtype=np.uint8).reshape(4, 6)
        assert np.array_equal(geometry.rotate_right_angle(img, k), np.rot90(img, k))

    def test_rotate_bound_keeps_corners(self):
        img = np.zeros((100, 200, 3), np.uint8)
        out = geometry.rotate_bound(img, 30)
        assert out.shape[0] > 100 and out.shape[1] > 200
        assert geometry.rotate_bound(img, 0.0) is img

    def test_estimate_skew(self):
        def tilted(x, y, w, h, deg):
            import math

            a = math.radians(deg)
            dx, dy = w * math.cos(a), -w * math.sin(a)
            return TextBox.from_polygon("text", 0.9, [(x, y), (x + dx, y + dy), (x + dx, y + dy + h), (x, y + h)])

        boxes = [tilted(10, 100 + i * 40, 300, 20, 7.0) for i in range(5)]
        assert abs(geometry.estimate_skew(boxes) - 7.0) < 0.5
        assert geometry.estimate_skew(boxes[:2]) == 0.0
        assert geometry.estimate_skew([TextBox.from_rect("x", 0.9, 0, 0, 10, 10)] * 5) == 0.0

    def test_crop_box_clamps(self):
        img = np.zeros((50, 50, 3), np.uint8)
        crop = geometry.crop_box(img, TextBox.from_rect("x", 1, 40, 40, 60, 60))
        assert crop.shape[0] <= 50 and crop.shape[1] <= 50
