"""Pipeline (orientation, skew, variants), extract() wiring, CLI and backend wrappers.

OCR engines are replaced by fakes so these run in milliseconds.
"""

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

import docling_pk
from conftest import FakeBackend, box, cnic_front_boxes
from docling_pk import extractor, pipeline
from docling_pk.cli import app
from docling_pk.errors import ImageLoadError, UnsupportedDocumentTypeError
from docling_pk.ocr.base import OCRBackend, TextBox
from docling_pk.schema import DocumentResult, FieldResult, FieldStatus
from docling_pk.vision.geometry import rotate_right_angle

LATIN = [box("PAKISTAN National Identity Card", 10, 10, conf=0.99), box("Name Father Name Gender", 10, 60, conf=0.95)]
JUNK = [box("؟ّ", 10, 10, conf=0.4), box("٧؟", 40, 10, conf=0.4), box("xq", 10, 50, conf=0.2)]


class MarkerBackend(OCRBackend):
    """Reads 'good' text only when the white marker block is top-left."""

    name = "marker"

    def __init__(self):
        self.calls = 0

    def read(self, image):
        self.calls += 1
        h, w = image.shape[:2]
        corner = image[: max(h // 10, 1), : max(w // 10, 1)]
        return list(LATIN) if corner.mean() > 200 else list(JUNK)


def marked_image():
    img = np.zeros((600, 900, 3), np.uint8)
    img[:120, :180] = 255
    return img


# ------------------------------------------------------------------ pipeline


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_detect_orientation_recovers_rotation(k):
    rotated = rotate_right_angle(marked_image(), k)
    turns, scores = pipeline.detect_orientation(rotated, MarkerBackend())
    assert (k + turns) % 4 == 0
    assert scores[turns] == max(scores.values())


def test_upright_short_circuits():
    be = MarkerBackend()
    pipeline.detect_orientation(marked_image(), be)
    assert be.calls == 1


def test_latin_score_penalizes_tall_boxes():
    wide = [TextBox.from_rect("PAKISTAN", 0.99, 0, 0, 200, 30)]
    tall = [TextBox.from_rect("PAKISTAN", 0.99, 0, 0, 30, 200)]
    assert pipeline.latin_score(wide) > 0 and pipeline.latin_score(tall) == 0


def test_drop_noise_boxes():
    real = [box(f"Real text {i}", 10, i * 40, h=30, conf=0.95) for i in range(4)]
    noise = [box("MABRD", 300, 5, h=10, conf=0.5)]
    small_confident = [box("ISLAMIC REPUBLIC", 300, 100, h=10, conf=0.97)]
    kept = pipeline.drop_noise_boxes(real + noise + small_confident)
    assert noise[0] not in kept and small_confident[0] in kept
    assert pipeline.drop_noise_boxes(noise) == noise  # too little evidence: keep all


def test_suppress_light_ink():
    img = np.full((50, 50), 255, np.uint8)
    img[10:20, 10:40] = 180  # light micro-text
    img[30:40, 10:40] = 20  # dark ink
    out = pipeline.suppress_light_ink(img)
    assert out.shape == (50, 50, 3)
    assert out[15, 15, 0] == 255 and out[35, 15, 0] == 20


class SkewBackend(OCRBackend):
    name = "skew"

    def __init__(self):
        self.calls = 0

    def read(self, image):
        self.calls += 1
        if self.calls == 1 or self.calls == 2:  # probe (upright accepted) then first main read
            a = math.radians(6)
            return [
                TextBox.from_polygon(
                    "PAKISTAN National Identity Card Name Gender",
                    0.99,
                    [
                        (10, 100 + i * 50),
                        (410, 100 + i * 50 - 400 * math.tan(a)),
                        (410, 130 + i * 50 - 400 * math.tan(a)),
                        (10, 130 + i * 50),
                    ],
                )
                for i in range(5)
            ]
        return list(LATIN)


def test_prepare_page_deskews():
    be = SkewBackend()
    page = pipeline.prepare_page(np.full((600, 900, 3), 255, np.uint8), be)
    assert abs(page.skew - 6) < 0.5
    assert be.calls == 3
    assert page.text.startswith("PAKISTAN")


class WatermarkBackend(OCRBackend):
    name = "wm"

    def read(self, image):
        if (image == 255).mean() > 0.8:  # ink-only variant: light background whitened
            return [box(f"Clean line {i}", 10, i * 40, h=30, conf=0.99) for i in range(6)]
        real = [box(f"Real text {i}", 10, i * 40, h=30, conf=0.95) for i in range(3)]
        return real + [box("HDARY", 400, i * 12, h=10, conf=0.5) for i in range(30)]


def test_ink_only_variant_used_for_micro_text():
    img = np.full((800, 600, 3), 200, np.uint8)  # light micro-text background
    img[700:760, 50:550] = 20  # dark ink
    page = pipeline.prepare_page(img, WatermarkBackend(), auto_rotate=False)
    assert "ink_only_variant" in page.timings
    assert page.boxes[0].text == "Clean line 0"


def test_page_reread_uses_verifier_and_upscales():
    main, verifier = FakeBackend(rereads={"*": ("main", 0.5)}), FakeBackend(rereads={"*": ("verifier", 0.9)})
    page = pipeline.Page(np.full((100, 200, 3), 255, np.uint8), [], main, verifier=verifier)
    assert page.reread(box("x", 10, 10, h=10)) == ("verifier", 0.9)
    assert verifier.last_crop_shape[0] >= 48
    page.verifier = None
    assert page.reread(box("x", 10, 10, h=10)) == ("main", 0.5)
    assert page.reread(TextBox.from_rect("x", 1, 500, 500, 600, 600)) == ("", 0.0)


def test_base_recognize_joins_left_to_right():
    be = FakeBackend([box("World", 100, 0), box("Hello", 0, 0)])
    assert OCRBackend.recognize(be, np.zeros((5, 5, 3), np.uint8)) == ("Hello World", 0.95)
    assert OCRBackend.recognize(FakeBackend([]), np.zeros((5, 5), np.uint8)) == ("", 0.0)
    with pytest.raises(NotImplementedError):
        OCRBackend().read(np.zeros((5, 5), np.uint8))


# ----------------------------------------------------------------- extractor


def _img():
    return np.full((630, 1000, 3), 230, np.uint8)


def test_extract_cnic_with_fake_backend():
    r = docling_pk.extract(_img(), "cnic", backend=FakeBackend(cnic_front_boxes()), urdu=False, verify=False)
    assert isinstance(r, DocumentResult)
    assert r.document_type == "cnic"
    assert r["fields"]["cnic_number"]["value"] == "35202-1234567-9"
    assert r.metadata["sides"] == ["front"] and r.metadata["ocr_backend"] == "fake"
    assert 0.9 < r.confidence <= 1.0
    assert r.raw_text and "PAKISTAN" in r.raw_text


def test_extract_auto_classifies_cnic():
    r = docling_pk.extract(_img(), backend=FakeBackend(cnic_front_boxes()), urdu=False, verify=False)
    assert r.document_type == "cnic"


def test_extract_unknown_document():
    r = docling_pk.extract(_img(), backend=FakeBackend([box("lorem ipsum", 10, 10)]), verify=False)
    assert r.document_type == "unknown" and r.fields == {} and r.confidence == 0.0
    assert any("could not recognize" in w for w in r.warnings)


def test_extract_front_and_back_merge(monkeypatch):
    monkeypatch.setattr(extractor, "_easyocr_available", lambda: False)
    back = [box("35202-1234567-9", 650, 30, h=34), box("مکان نمبر 12 گلی 4", 100, 100), box("ضلع ملتان", 300, 160)]

    class TwoSided(FakeBackend):
        def read(self, image):
            return list(cnic_front_boxes() if image.mean() > 200 else back)

    r = docling_pk.extract([_img(), np.full((630, 1000, 3), 150, np.uint8)], "cnic", backend=TwoSided())
    assert r.metadata["sides"] == ["front", "back"]
    assert r.fields["name"].value == "Muhammad Ali"
    assert r.fields["address"].status in (FieldStatus.NOT_FOUND,)
    assert any("urdu" in w.lower() for w in r.warnings)


def test_extract_certificate_and_degree_routes():
    from test_certificate_parser import fbise_boxes
    from test_degree_urdu_layout import DEGREE_LINES, lines_to_boxes

    r = docling_pk.extract(_img(), "ssc", backend=FakeBackend(fbise_boxes()), verify=False)
    assert r.document_type == "matric" and r.metadata["board"] == "FBISE"
    assert len(r.tables["subjects"]) == 3
    r = docling_pk.extract(_img(), "auto", backend=FakeBackend(fbise_boxes(level="intermediate")), verify=False)
    assert r.document_type == "intermediate"
    r = docling_pk.extract(_img(), "transcript", backend=FakeBackend(lines_to_boxes(DEGREE_LINES)), verify=False)
    assert r.document_type == "degree" and r.fields["degree"].value.startswith("Bachelor")


def test_include_raw_text_false():
    r = docling_pk.extract(
        _img(), "cnic", backend=FakeBackend(cnic_front_boxes()), urdu=False, verify=False, include_raw_text=False
    )
    assert r.raw_text is None


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("CNIC", "cnic"),
        ("fsc", "intermediate"),
        ("Inter", "intermediate"),
        ("SSC", "matric"),
        ("transcript", "degree"),
        ("auto", "auto"),
    ],
)
def test_document_type_aliases(alias, canonical):
    assert extractor.normalize_document_type(alias) == canonical


def test_errors():
    with pytest.raises(UnsupportedDocumentTypeError):
        docling_pk.extract(_img(), "passport")
    with pytest.raises(ValueError):
        docling_pk.extract(_img(), "passport")
    with pytest.raises(FileNotFoundError):
        docling_pk.extract("does_not_exist.jpg", "cnic")
    with pytest.raises(ValueError):
        extractor._make_backend("tesseract", None)


def test_bad_image_file(tmp_path):
    p = tmp_path / "not_an_image.jpg"
    p.write_text("text")
    with pytest.raises(ImageLoadError):
        docling_pk.extract(str(p), "cnic")


def test_verifier_selection(monkeypatch):
    monkeypatch.setattr(extractor, "_easyocr_available", lambda: False)
    assert extractor._verifier(FakeBackend(), True, None) is None
    assert extractor._urdu_backend(None) is None
    monkeypatch.setattr(extractor, "_easyocr_available", lambda: True)
    assert extractor._verifier(FakeBackend(), False, None) is None
    v = extractor._verifier(FakeBackend(), True, False)
    assert v.name == "easyocr" and v.languages == ("en",)
    assert extractor._urdu_backend(False).languages == ("ur", "en")


def test_make_backend_names():
    assert extractor._make_backend("rapidocr", None).name == "rapidocr"
    assert extractor._make_backend("easyocr", False).name == "easyocr"
    assert extractor._make_backend("auto", None).name in ("rapidocr", "easyocr")
    fake = FakeBackend()
    assert extractor._make_backend(fake, None) is fake


# --------------------------------------------------------- backend wrappers


def test_easyocr_wrapper(monkeypatch):
    from docling_pk.ocr import easyocr_backend as eb

    class FakeReader:
        def readtext(self, image, detail, paragraph):
            return [([[0, 0], [50, 0], [50, 10], [0, 10]], "Hello", 0.9), ([[0, 0], [5, 0], [5, 5], [0, 5]], " ", 0.1)]

        def recognize(self, gray, horizontal_list, free_list, allowlist, detail):
            assert gray.ndim == 2 and allowlist == "0123"
            return [(None, "0123", 0.8)]

    monkeypatch.setattr(eb, "get_reader", lambda languages, gpu: FakeReader())
    be = eb.EasyOCRBackend(("en",), gpu=False)
    boxes = be.read(np.zeros((10, 50), np.uint8))
    assert [b.text for b in boxes] == ["Hello"] and boxes[0].x1 == 50
    assert be.recognize(np.zeros((10, 50, 3), np.uint8), allowlist="0123") == ("0123", 0.8)

    class EmptyReader(FakeReader):
        def recognize(self, *a, **k):
            return []

    monkeypatch.setattr(eb, "get_reader", lambda languages, gpu: EmptyReader())
    assert eb.EasyOCRBackend().recognize(np.zeros((10, 50), np.uint8)) == ("", 0.0)


def test_easyocr_reader_cache(monkeypatch):
    import sys

    from docling_pk.ocr import easyocr_backend as eb

    created = []
    fake_module = SimpleNamespace(Reader=lambda langs, gpu, verbose: created.append((tuple(langs), gpu)) or object())
    monkeypatch.setitem(sys.modules, "easyocr", fake_module)
    monkeypatch.setattr(eb, "_READERS", {})
    r1 = eb.get_reader(("en",), gpu=False)
    r2 = eb.get_reader(("en",), gpu=False)
    assert r1 is r2 and created == [(("en",), False)]
    eb.get_reader(("en",), gpu=True)  # different device -> new reader
    assert len(created) == 2


def test_rapidocr_wrapper(monkeypatch):
    from docling_pk.ocr import rapidocr_backend as rb

    def engine(image, use_det=True, use_cls=False, use_rec=True):
        if use_det:
            return SimpleNamespace(
                boxes=[[[0, 0], [40, 0], [40, 10], [0, 10]], [[0, 0], [1, 0], [1, 1], [0, 1]]],
                txts=("Roll No", ""),
                scores=(0.97, 0.1),
            )
        return SimpleNamespace(boxes=None, txts=("654301",), scores=(0.99,))

    monkeypatch.setattr(rb, "_get_engine", lambda: engine)
    be = rb.RapidOCRBackend()
    assert [b.text for b in be.read(np.zeros((10, 40), np.uint8))] == ["Roll No"]
    assert be.recognize(np.zeros((10, 40, 3), np.uint8)) == ("654301", 0.99)
    monkeypatch.setattr(rb, "_get_engine", lambda: lambda *a, **k: SimpleNamespace(boxes=None, txts=None, scores=None))
    assert be.read(np.zeros((10, 40), np.uint8)) == []
    assert be.recognize(np.zeros((10, 40), np.uint8)) == ("", 0.0)


# ---------------------------------------------------------------------- CLI

runner = CliRunner()


def _fake_result(empty=False):
    fields = {
        "cnic_number": FieldResult(None if empty else "35202-1234567-9", 0.97),
        "name": FieldResult.missing("label not found"),
    }
    return DocumentResult(
        "cnic",
        fields,
        0.48,
        ["name: label not found"],
        raw_text="RAW",
        tables={"subjects": [{"subject": "MATHEMATICS", "max_marks": 150, "obtained_marks": 99}]},
    )


@pytest.fixture
def fake_extract(monkeypatch):
    calls = []

    def fake(source, **kwargs):
        calls.append((source, kwargs))
        if "missing" in str(source):
            raise FileNotFoundError(f"Image not found: {source}")
        if "bad" in str(source):
            raise ImageLoadError("Could not read image")
        return _fake_result(empty="empty" in str(source))

    monkeypatch.setattr(docling_pk, "extract", fake)
    return calls


def test_cli_json(fake_extract, tmp_path):
    img = tmp_path / "card.jpg"
    img.write_bytes(b"x")
    result = runner.invoke(app, ["extract", str(img), "--type", "cnic", "--no-urdu", "--cpu", "--no-verify"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["fields"]["cnic_number"]["value"] == "35202-1234567-9"
    assert "raw_text" not in data
    _, kwargs = fake_extract[0]
    assert kwargs["urdu"] is False and kwargs["gpu"] is False and kwargs["verify"] is False


def test_cli_raw_and_multiple_files(fake_extract, tmp_path):
    a, b = tmp_path / "front.jpg", tmp_path / "back.jpg"
    a.write_bytes(b"x"), b.write_bytes(b"x")
    result = runner.invoke(app, ["extract", str(a), str(b), "--raw"])
    assert json.loads(result.stdout)["raw_text"] == "RAW"
    assert isinstance(fake_extract[0][0], list)


def test_cli_table_and_out_file(fake_extract, tmp_path):
    img = tmp_path / "card.jpg"
    img.write_bytes(b"x")
    result = runner.invoke(app, ["extract", str(img), "-o", "table"])
    assert result.exit_code == 0 and "35202-1234567-9" in result.stdout and "MATHEMATICS" in result.stdout
    out = tmp_path / "out.json"
    result = runner.invoke(app, ["extract", str(img), "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["document_type"] == "cnic"


def test_cli_exit_codes(fake_extract, tmp_path):
    assert runner.invoke(app, ["extract", "missing.jpg"]).exit_code == 2
    assert runner.invoke(app, ["extract", "bad.jpg"]).exit_code == 2
    img = tmp_path / "card.jpg"
    img.write_bytes(b"x")
    assert runner.invoke(app, ["extract", str(img), "-o", "xml"]).exit_code == 2
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"x")
    assert runner.invoke(app, ["extract", str(empty)]).exit_code == 1


def test_cli_batch(fake_extract, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "bad.png").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("skip me")
    out = tmp_path / "res.jsonl"
    result = runner.invoke(app, ["batch", str(tmp_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["file"] for r in records] == ["a.jpg", "bad.png"]
    assert "error" in records[1] and records[0]["document_type"] == "cnic"
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert runner.invoke(app, ["batch", str(empty_dir)]).exit_code == 2


def test_cli_info_and_version():
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0 and "docling-pk" in result.stdout and "rapidocr" in result.stdout
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and docling_pk.__version__ in result.stdout
