"""
End-to-end tests: real OCR (RapidOCR) on the synthetic fixtures.

Covers the fixture categories the project brief requires: clean scans,
rotated images, low-resolution photos and partially obscured fields, plus an
unreadable image and PDF input. Marked ``ocr``: the first run downloads the
small ONNX models (~15 MB). Deselect with ``pytest -m "not ocr"``.

Two kinds of assertions:

* **Correctness** on fields the brief singles out (CNIC number, dates, marks).
* **Safety**: a field reported with status ``ok`` must never be wrong. A
  missing value is acceptable on a degraded image; a confident wrong one is
  not, because downstream KYC/admissions systems auto-accept ``ok`` fields.
"""

import json
import re
from pathlib import Path

import pytest

from docling_pk import extract

pytestmark = pytest.mark.ocr
pytest.importorskip("rapidocr")

SYNTH = Path(__file__).parent / "fixtures" / "synthetic"
CASES = json.loads((SYNTH / "labels.json").read_text(encoding="utf-8"))["cases"]
BY_ID = {c["id"]: c for c in CASES}


def norm(v):
    return None if v is None else re.sub(r"[\s,.]+", " ", str(v)).strip().upper()


def run(case_id, **kw):
    case = BY_ID[case_id]
    kw.setdefault("verify", False)
    kw.setdefault("urdu", False)
    return case, extract(str(SYNTH / case["image"]), case["doc_type"], backend="rapidocr", **kw)


def assert_no_confident_errors(case, result):
    for name, expected in case["expected"].items():
        if name == "subjects":
            continue
        f = result.fields[name]
        if f.status.value == "ok":
            assert norm(f.value) == norm(expected), f"{case['id']}.{name}: ok-status value {f.value!r} != {expected!r}"


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_no_confident_errors_on_any_fixture(case_id):
    case, result = run(case_id)
    assert_no_confident_errors(case, result)


@pytest.mark.parametrize(
    "case_id",
    [
        "00_cnic_front_clean",
        "02_cnic_front_rotated90",
        "03_cnic_front_rotated270",
        "04_cnic_front_upside_down",
        "06_cnic_front_photo",
        "08_cnic_front_low_res",
        "09_cnic_front_blurry",
    ],
)
def test_cnic_front_key_fields(case_id):
    case, r = run(case_id)
    exp = case["expected"]
    assert r.document_type == "cnic"
    for name in ("cnic_number", "date_of_birth", "date_of_issue", "date_of_expiry"):
        assert r.fields[name].value == exp[name], name
    assert r.confidence > 0.75


def test_rotation_is_reported():
    _, r = run("02_cnic_front_rotated90")
    assert r.metadata["pages"][0]["rotation_degrees"] in (90, 270)


def test_obscured_name_returns_none_with_warning():
    case, r = run("11_cnic_front_occluded_name")
    assert r.fields["name"].value is None
    assert any(w.startswith("name") for w in r.warnings)
    assert r.fields["cnic_number"].value == case["expected"]["cnic_number"]


def test_unreadable_image_degrades_gracefully():
    case, r = run("10_cnic_front_very_blurry")
    assert any("blurry" in w for w in r.warnings)
    assert r.confidence < 0.5
    assert_no_confident_errors(case, r)


def test_cnic_back():
    case, r = run("12_cnic_back_clean")
    assert r.metadata["sides"] == ["back"]
    assert r.fields["cnic_number"].value == case["expected"]["cnic_number"]
    assert r.fields["name"].status.value == "not_applicable"


@pytest.mark.parametrize(
    "case_id", ["14_matric_clean", "15_matric_rotated90", "18_intermediate_clean", "20_intermediate_photo"]
)
def test_certificate_marks(case_id):
    case, r = run(case_id)
    exp = case["expected"]
    assert r.document_type == case["doc_type"]
    assert r.fields["total_marks"].value == exp["total_marks"]
    assert r.fields["roll_number"].value == exp["roll_number"]
    rows = [(s["subject"], s["max_marks"], s["obtained_marks"]) for s in r.tables["subjects"]]
    assert rows == [tuple(x) for x in exp["subjects"]]


def test_degree():
    case, r = run("21_degree_clean")
    for name in ("student_name", "father_name", "degree", "institution", "cgpa"):
        assert norm(r.fields[name].value) == norm(case["expected"][name]), name


def test_auto_document_type():
    for case_id, expected in [
        ("00_cnic_front_clean", "cnic"),
        ("14_matric_clean", "matric"),
        ("18_intermediate_clean", "intermediate"),
        ("21_degree_clean", "degree"),
    ]:
        r = extract(str(SYNTH / BY_ID[case_id]["image"]), backend="rapidocr", verify=False, urdu=False)
        assert r.document_type == expected, case_id


def test_pdf_input(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page(width=600, height=380)
    page.insert_image(page.rect, filename=str(SYNTH / BY_ID["00_cnic_front_clean"]["image"]))
    pdf = tmp_path / "cnic.pdf"
    doc.save(str(pdf))
    r = extract(str(pdf), "cnic", backend="rapidocr", verify=False, urdu=False)
    assert r.fields["cnic_number"].value == BY_ID["00_cnic_front_clean"]["expected"]["cnic_number"]


def test_brief_contract_shape():
    """The exact JSON shape promised in the project brief."""
    _, r = run("00_cnic_front_clean")
    d = json.loads(r.to_json())
    assert set(d) >= {"document_type", "fields", "confidence", "warnings"}
    for key in (
        "name",
        "father_name",
        "cnic_number",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
        "gender",
        "address",
    ):
        assert {"value", "confidence"} <= set(d["fields"][key])
    assert 0.0 <= d["confidence"] <= 1.0
    assert re.fullmatch(r"\d{5}-\d{7}-\d", d["fields"]["cnic_number"]["value"])
