"""CNIC parsing on constructed OCR layouts (no OCR models needed)."""

from conftest import box, cnic_front_boxes, make_page
from docling_pk.parsers import cnic
from docling_pk.schema import FieldResult, FieldStatus


def _extract(boxes, rereads=None):
    fields, warnings, meta = cnic.extract(make_page(boxes, rereads))
    return fields, warnings, meta


def test_clean_front_extracts_every_front_field():
    fields, warnings, meta = _extract(cnic_front_boxes())
    assert meta["side"] == "front"
    assert fields["name"].value == "Muhammad Ali"
    assert fields["father_name"].value == "Muhammad Akram"
    assert fields["gender"].value == "M"
    assert fields["country_of_stay"].value == "Pakistan"
    assert fields["cnic_number"].value == "35202-1234567-9"
    assert fields["date_of_birth"].value == "01-01-1995"
    assert fields["date_of_issue"].value == "15-03-2020"
    assert fields["date_of_expiry"].value == "14-03-2030"
    assert not warnings
    for name in cnic.FRONT_FIELDS:
        assert fields[name].status == FieldStatus.OK, name


def test_back_fields_are_not_applicable_on_front():
    fields, _, _ = _extract(cnic_front_boxes())
    assert fields["address"].status == FieldStatus.NOT_APPLICABLE
    assert "back" in fields["address"].reason


def test_every_field_key_always_present():
    fields, _, _ = _extract([box("random text", 10, 10)])
    assert list(fields) == cnic.FIELD_NAMES


def test_ocr_box_order_does_not_matter():
    """The original parser assumed labels precede values in OCR order."""
    fields, _, _ = _extract(cnic_front_boxes(shuffle_dates=True))
    assert fields["date_of_birth"].value == "01-01-1995"
    assert fields["date_of_issue"].value == "15-03-2020"
    assert fields["date_of_expiry"].value == "14-03-2030"
    assert fields["name"].value == "Muhammad Ali"


def test_dates_assigned_chronologically_even_if_layout_scrambled():
    boxes = cnic_front_boxes(dob="14.03.2030", doe="01.01.1995")  # values in wrong slots
    fields, _, _ = _extract(boxes)
    assert fields["date_of_birth"].value == "01-01-1995"
    assert fields["date_of_expiry"].value == "14-03-2030"


def test_father_label_does_not_steal_name():
    """Old bug: 'Father Name' minus 'Father' left 'Name' as the father's name."""
    fields, _, _ = _extract(cnic_front_boxes())
    assert fields["father_name"].value != "Name"


def test_misread_labels_still_match():
    boxes = cnic_front_boxes()
    renamed = {"Father Name": "Fathgr Namg", "Gender": "GenUer", "Date of Birth": "Date 0/ 8irth"}
    boxes = [box(renamed.get(b.text, b.text), b.x0, b.y0, b.width, b.height, b.confidence) for b in boxes]
    fields, _, _ = _extract(boxes)
    assert fields["father_name"].value == "Muhammad Akram"
    assert fields["gender"].value == "M"


def test_cnic_number_separator_misread():
    fields, _, _ = _extract(cnic_front_boxes(number="35202-1234567.9"))
    assert fields["cnic_number"].value == "35202-1234567-9"


def test_gender_inferred_from_cnic_when_letter_unreadable():
    fields, _, _ = _extract(cnic_front_boxes(gender=None, number="35202-1234567-4"))
    g = fields["gender"]
    assert g.value == "F"
    assert g.status == FieldStatus.LOW_CONFIDENCE
    assert "inferred" in g.reason


def test_gender_conflict_with_cnic_is_flagged():
    fields, _, _ = _extract(cnic_front_boxes(gender="F", number="35202-1234567-9"))
    assert fields["gender"].value == "F"
    assert fields["gender"].status == FieldStatus.LOW_CONFIDENCE
    assert "disagrees" in fields["gender"].reason


def test_matching_gender_raises_confidence():
    fields, _, _ = _extract(cnic_front_boxes())
    assert fields["gender"].confidence > 0.95


def test_reread_agreement_raises_confidence():
    fields, _, _ = _extract(cnic_front_boxes(), rereads={"*": ("35202-1234567-9", 0.9)})
    assert fields["cnic_number"].confidence > 0.99


def test_reread_disagreement_is_flagged():
    fields, _, _ = _extract(cnic_front_boxes(), rereads={"*": ("35202-1234568-9", 0.99)})
    f = fields["cnic_number"]
    assert f.status == FieldStatus.LOW_CONFIDENCE
    assert "disagree" in f.reason


def test_invalid_region_digit_reported_as_invalid():
    fields, _, _ = _extract(cnic_front_boxes(number="05202-1234567-9"))
    f = fields["cnic_number"]
    assert f.value is None and f.status == FieldStatus.INVALID
    assert f.raw == "05202-1234567-9"


def test_missing_cnic_number_reason():
    boxes = [b for b in cnic_front_boxes() if b.text != "35202-1234567-9"]
    fields, _, _ = _extract(boxes)
    assert fields["cnic_number"].value is None
    assert "13-digit" in fields["cnic_number"].reason


def test_cnic_split_across_boxes():
    boxes = [b for b in cnic_front_boxes() if b.text != "35202-1234567-9"]
    boxes += [box("35202-", 345, 605, h=30), box("1234567-9", 460, 605, h=30)]
    fields, _, _ = _extract(boxes)
    assert fields["cnic_number"].value == "35202-1234567-9"


def test_impossible_date_order_warns():
    boxes = cnic_front_boxes(dob="01.01.1995", doi="15.03.2020", doe="15.03.2020")
    fields, warnings, _ = _extract(boxes)
    # only two distinct dates -> label geometry assignment, then logic check
    assert any("not before" in w for w in warnings)


def test_two_dates_assigned_by_label_geometry():
    boxes = [b for b in cnic_front_boxes() if b.text != "14.03.2030"]
    fields, _, _ = _extract(boxes)
    assert fields["date_of_birth"].value == "01-01-1995"
    assert fields["date_of_issue"].value == "15-03-2020"
    assert fields["date_of_expiry"].value is None


def test_husband_name_label():
    boxes = [
        box("Husband Name", b.x0, b.y0, None, b.height) if b.text == "Father Name" else b for b in cnic_front_boxes()
    ]
    fields, _, _ = _extract(boxes)
    assert fields["father_name"].value == "Muhammad Akram"
    assert "Husband" in fields["father_name"].reason


def test_value_in_same_box_as_label():
    boxes = [b for b in cnic_front_boxes() if b.text not in ("Gender", "M")]
    boxes.append(box("Gender M", 335, 470, h=18))
    fields, _, _ = _extract(boxes)
    assert fields["gender"].value == "M"


def test_detect_side_back():
    boxes = [
        box("35202-1234567-1", 900, 30),
        box("موجودہ پتہ : مکان نمبر B-12", 150, 60),
        box("تحصیل کامونکی، ضلع گوجرانوالہ", 300, 120),
        box("100000000001", 970, 400),
    ]
    assert cnic.detect_side(boxes) == "back"


def test_back_without_urdu_backend_explains():
    boxes = [box("35202-1234567-1", 900, 30), box("موجودہ پتہ مکان نمبر", 150, 60), box("ضلع گوجرانوالہ", 300, 120)]
    fields, _, meta = _extract(boxes)
    assert meta["side"] == "back"
    assert fields["cnic_number"].value == "35202-1234567-1"
    assert fields["name"].status == FieldStatus.NOT_APPLICABLE
    assert "Urdu" in fields["address"].reason


def test_back_with_urdu_backend_reads_address():
    from conftest import FakeBackend

    urdu = FakeBackend(
        [
            box("موجودہ پتہ : مکان نمبر B-12، محلہ نوری", 150, 60, w=700),
            box("کینٹ، تحصیل کامونکی، ضلع گوجرانوالہ", 350, 120, w=500),
            box("مستقل پتہ : مکان نمبر B-12، محلہ نوری", 150, 280, w=700),
            box("کینٹ، تحصیل کامونکی", 350, 340, w=400),
            box("گمشدہ کارڈ ملنے پر قریبی لیٹر بکس میں ڈال دیں", 200, 600, w=800),
        ]
    )
    page = make_page([box("35202-1234567-1", 900, 30), box("مکان نمبر", 150, 60), box("ضلع گوجرانوالہ", 300, 120)])
    fields, _, _ = cnic.extract(page, urdu_backend=urdu)
    addr = fields["address"]
    assert addr.value and "مکان نمبر B-12" in addr.value and "گوجرانوالہ" in addr.value
    assert "موجودہ" not in addr.value
    assert addr.status == FieldStatus.LOW_CONFIDENCE
    assert fields["permanent_address"].value and "کامونکی" in fields["permanent_address"].value
    assert "لیٹر" not in (addr.value + fields["permanent_address"].value)


def test_unknown_document_warns():
    fields, warnings, meta = _extract([box("hello world", 10, 10)])
    assert meta["side"] == "unknown"
    assert warnings


def test_merge_front_and_back():
    front, _, _ = _extract(cnic_front_boxes())
    back = {n: FieldResult.missing("x", status=FieldStatus.NOT_APPLICABLE) for n in cnic.FIELD_NAMES}
    back["cnic_number"] = FieldResult("35202-1234567-9", 0.9)
    back["address"] = FieldResult("مکان نمبر 1", 0.4, FieldStatus.LOW_CONFIDENCE)
    merged = cnic.merge_sides([front, back])
    assert merged["name"].value == "Muhammad Ali"
    assert merged["address"].value == "مکان نمبر 1"
    assert merged["cnic_number"].confidence > front["cnic_number"].confidence


def test_merge_conflicting_numbers_flagged():
    a = {"cnic_number": FieldResult("35202-1234567-9", 0.9)}
    b = {"cnic_number": FieldResult("35202-1234567-8", 0.8)}
    m = cnic.merge_sides([a, b])
    assert m["cnic_number"].status == FieldStatus.LOW_CONFIDENCE
    assert "differ" in m["cnic_number"].reason


def test_merge_prefers_higher_confidence_and_found_values():
    a = {"name": FieldResult.missing("x"), "father_name": FieldResult("A", 0.5)}
    b = {"name": FieldResult("Ali", 0.7), "father_name": FieldResult("B", 0.9)}
    m = cnic.merge_sides([a, b])
    assert m["name"].value == "Ali" and m["father_name"].value == "B"
