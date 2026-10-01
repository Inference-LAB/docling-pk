"""Matric / Intermediate certificate parsing on constructed OCR layouts."""

import pytest

from conftest import box, make_page
from docling_pk.parsers import certificate as cert
from docling_pk.schema import FieldStatus

SUBJECTS = [("ENGLISH (COMPULSORY)", "150", "118"), ("URDU (COMPULSORY)", "150", "086"), ("MATHEMATICS", "150", "102")]


def fbise_boxes(
    level="matric",
    total_ob="306",
    words="Three Hundred Six",
    subjects=SUBJECTS,
    total_max="450",
    title_board=True,
    dob=True,
    grade="A",
):
    title = (
        "SECONDARY SCHOOL CERTIFICATE EXAMINATION"
        if level == "matric"
        else "HIGHER SECONDARY SCHOOL CERTIFICATE EXAMINATION"
    )
    b = []
    if title_board:
        b.append(box("FEDERAL BOARD OF INTERMEDIATE AND SECONDARY EDUCATION", 100, 40, w=1000, h=36))
    b += [
        box("ISLAMABAD", 520, 90, h=32),
        box("1234567", 240, 150, h=34),  # serial printed raised above its label line
        box("Serial No.", 90, 185, h=26),
        box("Certificate No.", 760, 185, h=26),
        box("123456789/012345", 950, 185, h=26),
        box("Roll No.", 90, 250, h=26),
        box("654301", 228, 250, h=26),
        box("Registration No.", 760, 250, h=26),
        box("1234500001", 970, 250, h=26),
        box("Group", 90, 315, h=26),
        box("SCIENCE", 230, 315, h=26),
        box("Attempt(s)", 760, 315, h=26),
        box("FIRST", 970, 315, h=26),
        box(title, 300, 400, w=640, h=26),
        box("ANNUAL 2019", 520, 440, h=26),
        box("Certified that", 90, 500, h=26),
        box("ALI HASSAN KHAN", 260, 500, h=26),
        box("Son / Daughter of", 90, 550, h=26),
        box("TARIQ MAHMOOD", 345, 550, h=26),
    ]
    if dob:
        b.append(
            box("whose date of birth is 14-02-2004 (Fourteenth February, Two Thousand and Four)", 90, 600, w=950, h=26)
        )
    b += [
        box(
            "at the examination held in the month(s) of March / April as a Regular Candidate from",
            90,
            650,
            w=1000,
            h=26,
        ),
        box("MODEL SCHOOL, SECTOR F-8, ISLAMABAD", 90, 700, w=600, h=26),
        box(f"as per statement of marks given below and has obtained grade {grade}", 90, 750, w=900, h=26),
        box("SUBJECT-WISE STATEMENT OF MARKS", 400, 800, w=420, h=26),
        box("S.No.", 90, 860, h=24),
        box("Subject(s)", 400, 860, h=24),
        box("Maximum", 780, 870, h=22),
        box("Obtained", 980, 870, h=22),
    ]
    y = 920
    for i, (s, mx, ob) in enumerate(subjects, 1):
        b += [box(str(i), 100, y, h=22), box(s, 180, y, h=22), box(mx, 800, y, h=22), box(ob, 1000, y, h=22)]
        y += 46
    b += [box("TOTAL", 420, y, h=26), box(total_max, 795, y, h=26), box(total_ob, 1000, y, h=26)]
    y += 80
    b += [box("(Marks in words)", 90, y, h=26), box(words, 320, y, w=420, h=26)]
    return b


def test_full_fbise_matric():
    fields, warnings, meta, rows = cert.extract(make_page(fbise_boxes(), size=(1600, 1240)), level_hint="matric")
    assert meta == {"board": "FBISE", "level": "matric"}
    expect = {
        "student_name": "ALI HASSAN KHAN",
        "father_name": "TARIQ MAHMOOD",
        "date_of_birth": "14-02-2004",
        "roll_number": "654301",
        "registration_number": "1234500001",
        "serial_number": "1234567",
        "certificate_number": "123456789/012345",
        "board": "FBISE",
        "exam": "SSC",
        "year": "2019",
        "session": "ANNUAL",
        "group": "SCIENCE",
        "grade": "A",
        "total_marks": "306",
        "max_marks": "450",
    }
    for k, v in expect.items():
        assert fields[k].value == v, k
    assert fields["institute"].value.startswith("MODEL SCHOOL")
    assert rows == [
        {"subject": "ENGLISH (COMPULSORY)", "max_marks": 150, "obtained_marks": 118},
        {"subject": "URDU (COMPULSORY)", "max_marks": 150, "obtained_marks": 86},
        {"subject": "MATHEMATICS", "max_marks": 150, "obtained_marks": 102},
    ]
    assert fields["total_marks"].confidence >= 0.99  # three sources agree
    assert not warnings
    assert list(fields) == cert.FIELD_NAMES


def test_title_overrides_hint():
    fields, warnings, meta, _ = cert.extract(make_page(fbise_boxes(level="intermediate")), level_hint="matric")
    assert meta["level"] == "intermediate"
    assert fields["exam"].value == "HSSC"
    assert any("parsed as intermediate" in w for w in warnings)


def test_disagreeing_totals_flagged():
    fields, warnings, _, _ = cert.extract(make_page(fbise_boxes(total_ob="307", words="Three Hundred Eight")))
    assert fields["total_marks"].status == FieldStatus.LOW_CONFIDENCE
    assert any("could not be confirmed" in w for w in warnings)
    assert any("failed validation" in w for w in warnings)


def test_two_sources_agree_without_words():
    boxes = [b for b in fbise_boxes() if b.text not in ("(Marks in words)", "Three Hundred Six")]
    fields, _, _, _ = cert.extract(make_page(boxes))
    assert fields["total_marks"].value == "306" and fields["total_marks"].confidence >= 0.9


def test_max_marks_disagreement_is_low_confidence():
    fields, _, _, _ = cert.extract(make_page(fbise_boxes(total_max="9100")))
    assert fields["max_marks"].value == "9100"
    assert fields["max_marks"].status == FieldStatus.LOW_CONFIDENCE


def test_reread_repairs_bad_cell():
    subjects = [
        ("ENGLISH (COMPULSORY)", "150", "118"),
        ("URDU (COMPULSORY)", "150", "O86"),
        ("MATHEMATICS", "150", "102"),
    ]
    page = make_page(fbise_boxes(subjects=subjects), rereads={"*": ("", 0.0)})
    fields, _, _, rows = cert.extract(page)
    assert rows[1]["obtained_marks"] == 86  # O read as 0
    assert fields["total_marks"].value == "306"


def test_board_fallback_from_certificate_number_format():
    fields, _, meta, _ = cert.extract(make_page(fbise_boxes(title_board=False)))
    assert meta["board"] == "FBISE" and fields["board"].confidence == pytest.approx(0.7)


def test_missing_dob_and_grade():
    fields, _, _, _ = cert.extract(make_page(fbise_boxes(dob=False, grade="")))
    assert fields["date_of_birth"].value is None
    assert fields["grade"].value is None and "grade" in fields["grade"].reason


def test_empty_page():
    fields, warnings, meta, rows = cert.extract(make_page([box("nothing useful here", 10, 10)]))
    assert rows == [] and "marks table not found" in warnings
    assert fields["board"].value is None
    assert fields["total_marks"].value is None and fields["max_marks"].value is None
    assert fields["year"].value is None


def test_garbled_name_label_uses_line_above_father():
    boxes = [b for b in fbise_boxes() if b.text != "Certified that"]
    boxes.append(box("eedha", 90, 500, h=26))
    fields, _, _, _ = cert.extract(make_page(boxes))
    assert fields["student_name"].value == "ALI HASSAN KHAN"
    assert fields["student_name"].status == FieldStatus.LOW_CONFIDENCE


def test_group_with_glued_noise():
    boxes = [box("pSCIENCE", b.x0, b.y0, b.width, b.height) if b.text == "SCIENCE" else b for b in fbise_boxes()]
    fields, _, _, _ = cert.extract(make_page(boxes))
    assert fields["group"].value == "SCIENCE"


def test_numeric_reread_disagreement():
    page = make_page(fbise_boxes(), rereads={"*": ("999999", 0.99)})
    page.boxes = [box(b.text, b.x0, b.y0, b.width, b.height, conf=0.5) for b in page.boxes]
    fields, _, _, _ = cert.extract(page)
    assert fields["roll_number"].status == FieldStatus.LOW_CONFIDENCE


@pytest.mark.parametrize(
    "text,board",
    [
        ("FEDERAL BOARD OF INTERMEDIATE AND SECONDARY EDUCATION", "FBISE"),
        ("BOARD OF INTERMEDIATE AND SECONDARY EDUCATION, LAHORE", "BISE Lahore"),
        ("Board of Intermediate & Secondary Education Dera Ghazi Khan", "BISE Dera Ghazi Khan"),
        ("BOARD OF INTERMEDIATE AND SECONDARY EDUCATION", "BISE"),
        ("BOARD OF INTERMEDIATE EDUCATION KARACHI", "BIEK Karachi"),
        ("Aga Khan University Examination Board", "AKU-EB"),
        ("some other text", None),
    ],
)
def test_detect_board(text, board):
    assert cert.detect_board(text) == board


@pytest.mark.parametrize(
    "text,level",
    [
        ("SECONDARY SCHOOL CERTIFICATE EXAMINATION", "matric"),
        ("HIGHER SECONDARY SCHOOL CERTIFICATE EXAMINATION", "intermediate"),
        ("Intermediate Part-II Examination", "intermediate"),
        ("hello", None),
    ],
)
def test_detect_level(text, level):
    assert cert.detect_level(text) == level


def test_non_fbise_board_warns():
    boxes = [
        box("BOARD OF INTERMEDIATE AND SECONDARY EDUCATION, LAHORE", b.x0, b.y0, b.width, b.height)
        if b.text.startswith("FEDERAL")
        else b
        for b in fbise_boxes()
    ]
    _, warnings, meta, _ = cert.extract(make_page(boxes))
    assert meta["board"] == "BISE Lahore"
    assert any("not been verified" in w for w in warnings)


def test_assign_columns_without_headers():
    nums = [box("150", 800, 10), box("118", 1000, 10)]
    assert cert._assign_columns(nums, None, None) == (150, 118)
    assert cert._assign_columns([box("150", 800, 10)], None, None) == (None, None)
    assert cert._assign_columns([], 800, 1000) == (None, None)
    assert cert._assign_columns([box("150", 800, 10)], 800, 1000) == (150, None)
    assert cert._assign_columns([box("118", 1000, 10)], 800, 1000) == (None, 118)
