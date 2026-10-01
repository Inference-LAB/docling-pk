"""Format validators and OCR-error normalization."""

import datetime as dt

import pytest

from docling_pk.validation.cnic import check_cnic, find_cnic, format_cnic, gender_from_cnic
from docling_pk.validation.dates import find_dates, parse_date, to_date
from docling_pk.validation.marks import agree, check_subjects, words_to_number
from docling_pk.validation.text import digits_only, eastern_to_ascii_digits, fix_digits


class TestFindCnic:
    @pytest.mark.parametrize(
        "text",
        [
            "35202-1234567-1",
            "Identity Number 35202-1234567-1",
            "35202_1234567_1",  # underscore misread (seen in real output)
            "35202-1234567.1",  # dot misread (seen in real output)
            "35202:1234567:1",  # colon misread
            "35202 1234567 1",  # dashes dropped
            "3520212345671",  # all 13 digits run together
            "352O2-l234567-l",  # letter-for-digit misreads
            "35202 - 1234567 - 1",
        ],
    )
    def test_tolerates_real_ocr_misreads(self, text):
        assert find_cnic(text) == "35202-1234567-1"

    @pytest.mark.parametrize("text", ["", "no digits here", "35202-123456-1", "13.07.2012", "352021234567123"])
    def test_rejects_non_cnic(self, text):
        assert find_cnic(text) is None

    def test_does_not_accept_arabic_indic_digits_as_ascii_silently(self):
        # Eastern digits are converted deliberately, then validated as usual.
        assert find_cnic("٣٥٢٠٢-١٢٣٤٥٦٧-١") == "35202-1234567-1"

    def test_format(self):
        assert format_cnic("3520212345679") == "35202-1234567-9"


class TestCheckCnic:
    def test_valid(self):
        c = check_cnic("35202-1234567-9")
        assert c.valid and c.region == "Punjab" and c.gender_digit == "9"

    def test_bad_region_digit(self):
        c = check_cnic("05202-1234567-9")
        assert not c.valid
        assert "region" in c.problems[0]

    def test_wrong_length(self):
        assert not check_cnic("3520-1234567-9").valid

    def test_missing(self):
        assert check_cnic(None).problems == ("missing",)

    @pytest.mark.parametrize(
        "num,gender", [("35202-1234567-9", "M"), ("35202-1234567-4", "F"), ("bad", None), (None, None)]
    )
    def test_gender_from_last_digit(self, num, gender):
        assert gender_from_cnic(num) == gender


class TestDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("14.02.2004", "14-02-2004"),
            ("14,02.2004", "14-02-2004"),
            ("Date of Birth 11.10.1988", "11-10-1988"),
            ("22-07-1998(Twenty Second July", "22-07-1998"),
            ("14-Feb-2004", "14-02-2004"),
            ("20-Jul-2026", "20-07-2026"),
            ("February 22, 2022", "22-02-2022"),
            ("Feb 01, 2024", "01-02-2024"),
            ("November 08, 2019", "08-11-2019"),
            ("20th July 2026", "20-07-2026"),
            ("6th July 2026", "06-07-2026"),
            ("Novembr 08, 2019", "08-11-2019"),  # OCR typo in month name
            ("17.O5.2O24", "17-05-2024"),  # letter O for zero
        ],
    )
    def test_formats(self, text, expected):
        assert parse_date(text) == expected

    @pytest.mark.parametrize("text", ["31.02.2003", "00.01.2000", "12.13.2000", "01.01.1800", "hello", ""])
    def test_invalid(self, text):
        assert parse_date(text) is None

    def test_find_all_in_order(self):
        assert find_dates("18.06.2023 then 18.06.2033") == ["18-06-2023", "18-06-2033"]

    def test_duplicates_removed(self):
        assert find_dates("01.01.2000 01.01.2000") == ["01-01-2000"]

    def test_to_date(self):
        assert to_date("14-02-2004") == dt.date(2004, 2, 14)
        assert to_date(None) is None
        assert to_date("garbage") is None


class TestText:
    def test_fix_digits_only_in_numeric_tokens(self):
        assert fix_digits("6543O1") == "654301"
        assert fix_digits("Name") == "Name"
        assert fix_digits("") == ""

    def test_digits_only(self):
        assert digits_only("O98") == "098"
        assert digits_only("1,100") == "1100"

    def test_eastern_digits(self):
        assert eastern_to_ascii_digits("۱۲۳٤") == "1234"


class TestMarks:
    @pytest.mark.parametrize(
        "text,n",
        [
            ("Seven Hundred Eighty Seven", 787),
            ("EIGHT HUNDRED EIGHTY-TWO", 882),
            ("Five Hundred Fifty Four", 554),
            ("Eight Hundred Sixty Nine", 869),
            ("One Thousand and Twenty", 1020),
            ("Five Hundred Fiffy Four", 554),  # OCR typo
            ("Nine Hundred", 900),
            ("Ninety", 90),
        ],
    )
    def test_words_to_number(self, text, n):
        assert words_to_number(text) == n

    def test_words_to_number_none(self):
        assert words_to_number("no number words") is None
        assert words_to_number("") is None

    def test_check_subjects_consistent(self):
        rows = [("ENGLISH", 150, 118), ("URDU", 150, 86)]
        assert check_subjects(rows, 300, 204) == (True, [])

    def test_check_subjects_sum_mismatch(self):
        ok, problems = check_subjects([("ENGLISH", 150, 118), ("URDU", 150, 86)], 300, 205)
        assert not ok and "obtained marks add up to 204" in problems[0]

    def test_check_subjects_obtained_exceeds_max(self):
        ok, problems = check_subjects([("ENGLISH", 50, 98)], None, None)
        assert not ok and "exceeds" in problems[0]

    def test_check_subjects_incomplete(self):
        ok, problems = check_subjects([("ENGLISH", None, 98)], None, None)
        assert not ok and "incomplete" in problems[0]

    def test_check_subjects_empty(self):
        assert check_subjects([], 1100, 787)[0] is False

    def test_agree(self):
        assert agree([787, 787, None]) == 787
        assert agree([787, 788]) is None
        assert agree([None]) is None
