"""Degree/transcript parser, Urdu post-processing and layout helpers."""

import pytest

from conftest import FakeBackend, box, make_page
from docling_pk import layout
from docling_pk.parsers import degree
from docling_pk.schema import FieldStatus
from docling_pk.urdu import correct_address_tokens, normalize_urdu


def lines_to_boxes(lines, conf=0.97):
    return [box(t, 60, 50 + i * 50, w=len(t) * 14, h=28, conf=conf) for i, t in enumerate(lines)]


DEGREE_LINES = [
    "Serial 3o: 100200 Registration 2o: UNI/SP22-BCS-001/ISB",
    "COMSATS Unibersity Islamabad",
    "ALI HASSAN KHAN s/o TARIQ MAHMOOD",
    "Of",
    "Lahore Campus",
    "has been conferred upon the degree of",
    "Bachelor of Science in Artificial Intelligence",
    "Date of Issuance: 20th July 2026",
]

TRANSCRIPT_LINES = [
    "Example University of Technology",
    "TRANSCRIPT",
    "Date: 20-Jul-2026",
    "Certified that SANA KHAN d/o IMRAN KHAN Registration No. EX/FA20-",
    "BCS-007 Department of Computer Science has completed",
    "examinations for the degree of Bachelor of Science in Computer Science , on 6th July 2026",
    "Date of Birth : 14-Feb-2004",
    "Course Code Semester Credit Hours",
    "CGPA: 3.41 First Division",
]


class TestDegree:
    def test_degree_certificate(self):
        fields, warnings, meta = degree.extract(make_page(lines_to_boxes(DEGREE_LINES)))
        assert meta["variant"] == "degree"
        assert fields["student_name"].value == "ALI HASSAN KHAN"
        assert fields["father_name"].value == "TARIQ MAHMOOD"
        assert fields["institution"].value == "COMSATS University Islamabad"
        assert fields["degree"].value == "Bachelor of Science in Artificial Intelligence"
        assert fields["campus"].value == "Lahore"
        assert fields["registration_number"].value == "UNI/SP22-BCS-001/ISB"
        assert fields["serial_number"].value == "100200"
        assert fields["date_of_issue"].value == "20-07-2026"
        assert fields["year"].value == "2026"
        assert fields["cgpa"].value is None
        assert list(fields) == degree.FIELD_NAMES

    def test_transcript_with_wrapped_registration(self):
        fields, _, meta = degree.extract(make_page(lines_to_boxes(TRANSCRIPT_LINES)))
        assert meta["variant"] == "transcript"
        assert fields["student_name"].value == "SANA KHAN"
        assert fields["father_name"].value == "IMRAN KHAN"
        assert fields["registration_number"].value == "EX/FA20-BCS-007"
        assert fields["institution"].value == "Example University of Technology"
        assert fields["cgpa"].value == "3.41"
        assert fields["division"].value == "First Division"
        assert fields["date_of_birth"].value == "14-02-2004"
        assert fields["date_of_issue"].value == "20-07-2026"

    def test_nothing_found(self):
        fields, _, _ = degree.extract(make_page([box("random", 10, 10)]))
        assert all(f.value is None for f in fields.values())
        assert "s/o" in fields["student_name"].reason

    def test_year_fallback_without_issue_date(self):
        fields, _, _ = degree.extract(make_page(lines_to_boxes(["Example University of Technology", "class of 2019"])))
        assert fields["year"].value == "2019" and fields["year"].status == FieldStatus.LOW_CONFIDENCE

    def test_registration_verifier_disagreement(self):
        page = make_page(lines_to_boxes(DEGREE_LINES), rereads={"*": ("XXXX/SP22", 0.9)})
        page.verifier = FakeBackend(rereads={"*": ("XXXX/SP22", 0.9)})
        fields, _, _ = degree.extract(page)
        assert fields["registration_number"].status == FieldStatus.LOW_CONFIDENCE

    def test_registration_verifier_agreement(self):
        page = make_page(lines_to_boxes(DEGREE_LINES))
        page.verifier = FakeBackend(rereads={"*": ("Registration No: UNI/SP22-BCS-001/ISB", 0.9)})
        fields, _, _ = degree.extract(page)
        assert fields["registration_number"].status == FieldStatus.OK

    @pytest.mark.parametrize(
        "line,degree_text",
        [
            ("BS (Hons) in Computer Science", "BS (Hons) in Computer Science"),
            ("MBA Finance", "MBA Finance"),
            ("AHMED s/o MAHMOOD BASHIR", None),  # names starting with MA/BA/BS are not degrees
        ],
    )
    def test_degree_abbreviations(self, line, degree_text):
        m = degree.DEGREE.search(line)
        assert (m.group(1).strip() if m else None) == degree_text

    @pytest.mark.parametrize("text", ["Uniuersity", "Unibersity", "Universlty"])
    def test_fix_common_words(self, text):
        assert degree.fix_common_words(f"COMSATS {text} Islamabad") == "COMSATS University Islamabad"


class TestUrdu:
    def test_normalize(self):
        assert normalize_urdu("محلّه نوري") == "محلہ نوری"
        assert normalize_urdu("كراچی،  ") == "کراچی،"

    def test_corrections(self):
        assert correct_address_tokens("خصیل کامونکی ضع گوجرانوالا") == "تحصیل کامونکی ضلع گوجرانوالہ"

    def test_leaves_numbers_latin_and_unknown_words(self):
        assert correct_address_tokens("مکان نمبر B-12 گلی 4") == "مکان نمبر B-12 گلی 4"

    def test_does_not_invent_place_names_from_noise(self):
        assert correct_address_tokens("ززز") == "ززز"


class TestLayout:
    def test_find_label_fuzzy_and_exclude(self):
        boxes = [box("Name", 10, 10), box("Fathgr Namg", 10, 100)]
        assert layout.find_label(boxes, "Father Name").text == "Fathgr Namg"
        assert layout.find_label(boxes, "Name", exclude=["Father Name"]).text == "Name"
        assert layout.find_label(boxes, "Date of Birth") is None

    def test_find_label_prefix(self):
        assert layout.find_label([box("Gender M", 0, 0)], "Gender").text == "Gender M"

    def test_label_score_empty(self):
        assert layout.label_score("123", "Name") == 0.0
        assert layout.find_label([box("1234", 0, 0)], "Name") is None

    def test_group_lines_and_reading_order(self):
        boxes = [box("world", 200, 12), box("hello", 10, 10), box("next", 10, 60)]
        assert layout.reading_order_text(boxes) == "hello world\nnext"

    def test_below_and_right(self):
        label = box("Name", 100, 100, h=20)
        below = box("Ali Khan", 105, 130, h=30)
        far = box("Other", 105, 400, h=30)
        right = box("value", 200, 102, h=20)
        assert layout.boxes_below([label, below, far, right], label) == [below]
        assert layout.boxes_right_of([label, below, right], label) == [right]

    def test_ascii_ratio(self):
        assert layout.ascii_ratio("abc") == 1.0
        assert layout.ascii_ratio("") == 0.0
        assert layout.ascii_ratio("مکان") == 0.0
