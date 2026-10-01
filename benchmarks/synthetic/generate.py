"""
Synthetic document generator for tests and the public benchmark.

Real CNICs and certificates contain personal data and must never be
committed, so the repository's fixtures are generated here instead. Every
image is fabricated from random data and stamped "SYNTHETIC SPECIMEN"; the
layouts reproduce *field positions and label wording* (what the parsers
depend on), not official artwork: there are no emblems, seals, photos,
holograms or security patterns that could make an image pass as a real
document.

    python benchmarks/synthetic/generate.py            # writes tests/fixtures/synthetic
    python benchmarks/synthetic/generate.py --seed 7 --out /tmp/synth --count 40

Requires Pillow and a TrueType font (Arial on Windows, DejaVu/Liberation on
Linux, Helvetica on macOS). Output is deterministic for a given seed and font.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "synthetic"

FIRST = [
    "Muhammad",
    "Ahmed",
    "Ali",
    "Usman",
    "Bilal",
    "Hamza",
    "Hassan",
    "Zain",
    "Fahad",
    "Imran",
    "Ayesha",
    "Fatima",
    "Zainab",
    "Maryam",
    "Hira",
    "Sana",
    "Amna",
    "Iqra",
    "Mahnoor",
    "Rabia",
]
LAST = [
    "Khan",
    "Ahmed",
    "Hussain",
    "Iqbal",
    "Raza",
    "Shah",
    "Malik",
    "Butt",
    "Chaudhry",
    "Qureshi",
    "Siddiqui",
    "Abbasi",
    "Javed",
    "Rehman",
    "Akram",
    "Aslam",
    "Nawaz",
    "Saleem",
    "Tariq",
    "Yousaf",
]
SCHOOLS = [
    "MODEL HIGH SCHOOL, SECTOR G-7, ISLAMABAD",
    "CITY PUBLIC SCHOOL, SADDAR, RAWALPINDI",
    "GOVT BOYS COLLEGE, MALL ROAD, LAHORE",
    "FG GIRLS COLLEGE, CANTT, PESHAWAR",
]
SUBJECTS_SSC = [
    "ENGLISH (COMPULSORY)",
    "URDU (COMPULSORY)",
    "ISLAMIYAT (COMPULSORY)",
    "PAKISTAN STUDIES",
    "MATHEMATICS",
    "PHYSICS",
    "CHEMISTRY",
    "BIOLOGY",
]
MAX_SSC = [150, 150, 100, 100, 150, 150, 150, 150]
SUBJECTS_HSSC = [
    "ENGLISH (COMPULSORY)",
    "URDU (COMPULSORY)",
    "ISLAMIC EDUCATION",
    "PAKISTAN STUDIES",
    "MATHEMATICS",
    "PHYSICS",
    "CHEMISTRY",
]
MAX_HSSC = [200, 200, 50, 50, 200, 200, 200]
ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

STAMP = "SYNTHETIC SPECIMEN - NOT A REAL DOCUMENT"


def find_font(bold: bool = False) -> str:
    candidates = (
        [
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for c in candidates:
        if Path(c).exists():
            return c
    raise SystemExit("No TrueType font found; install DejaVu or Liberation fonts.")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(find_font(bold), size)


def number_words(n: int) -> str:
    parts = []
    if n >= 1000:
        parts += [ONES[n // 1000], "Thousand"]
        n %= 1000
    if n >= 100:
        parts += [ONES[n // 100], "Hundred"]
        n %= 100
    if n >= 20:
        parts.append(TENS[n // 10])
        n %= 10
    if n:
        parts.append(ONES[n])
    return " ".join(p for p in parts if p)


def person(rng: random.Random, female: bool = False) -> Tuple[str, str]:
    first = rng.choice(FIRST[10:] if female else FIRST[:10])
    return f"{first} {rng.choice(LAST)}", f"{rng.choice(FIRST[:10])} {rng.choice(LAST)}"


def rand_date(rng: random.Random, y0: int, y1: int) -> dt.date:
    start = dt.date(y0, 1, 1).toordinal()
    return dt.date.fromordinal(rng.randint(start, dt.date(y1, 12, 28).toordinal()))


def cnic_number(rng: random.Random, female: bool) -> str:
    digits = [str(rng.randint(1, 7))] + [str(rng.randint(0, 9)) for _ in range(11)]
    last = rng.choice("2468" if female else "13579")
    d = "".join(digits) + last
    return f"{d[:5]}-{d[5:12]}-{d[12]}"


# --------------------------------------------------------------- renderers


def render_cnic_front(rng: random.Random) -> Tuple[Image.Image, Dict[str, str]]:
    female = rng.random() < 0.4
    name, father = person(rng, female)
    number = cnic_number(rng, female)
    dob = rand_date(rng, 1950, 2006)
    doi = rand_date(rng, max(dob.year + 18, 2012), 2025)
    doe = doi.replace(year=doi.year + rng.choice([5, 7, 10]))
    W, H = 1000, 630
    img = Image.new("RGB", (W, H), (222, 240, 214))
    d = ImageDraw.Draw(img)
    for y in range(0, H, 6):  # faint background lines, not a security pattern
        d.line([(0, y), (W, y)], fill=(214, 233, 207))
    d.text((240, 30), "PAKISTAN", font=font(46, True), fill=(30, 40, 50))
    d.text((520, 42), "National Identity Card", font=font(30, True), fill=(30, 40, 50))
    d.text((240, 88), "ISLAMIC REPUBLIC OF PAKISTAN", font=font(14, True), fill=(40, 50, 60))
    d.rectangle([760, 150, 960, 400], outline=(150, 160, 150), width=2)  # photo placeholder (empty)
    d.text((790, 265), "NO PHOTO", font=font(20), fill=(150, 160, 150))
    lab, val = font(19), font(31)

    def field(x, y, label, value):
        d.text((x, y), label, font=lab, fill=(60, 70, 80))
        d.text((x + 8, y + 24), value, font=val, fill=(20, 20, 20))

    field(270, 125, "Name", name)
    field(270, 225, "Father Name", father)
    field(270, 330, "Gender", "F" if female else "M")
    field(400, 330, "Country of Stay", "Pakistan")
    field(270, 410, "Identity Number", number)
    field(570, 410, "Date of Birth", dob.strftime("%d.%m.%Y"))
    field(270, 490, "Date of Issue", doi.strftime("%d.%m.%Y"))
    field(570, 490, "Date of Expiry", doe.strftime("%d.%m.%Y"))
    d.text((760, 560), "Holder's Signature", font=font(16), fill=(60, 70, 80))
    d.text((20, H - 32), STAMP, font=font(16, True), fill=(200, 60, 60))
    expected = {
        "name": name,
        "father_name": father,
        "gender": "F" if female else "M",
        "country_of_stay": "Pakistan",
        "cnic_number": number,
        "date_of_birth": dob.strftime("%d-%m-%Y"),
        "date_of_issue": doi.strftime("%d-%m-%Y"),
        "date_of_expiry": doe.strftime("%d-%m-%Y"),
    }
    return img, expected


def render_cnic_back(rng: random.Random) -> Tuple[Image.Image, Dict[str, str]]:
    number = cnic_number(rng, rng.random() < 0.4)
    W, H = 1000, 630
    img = Image.new("RGB", (W, H), (228, 242, 220))
    d = ImageDraw.Draw(img)
    d.text((660, 30), number, font=font(34), fill=(20, 20, 20))
    d.rectangle([700, 100, 920, 320], outline=(40, 40, 40), width=3)  # QR placeholder
    d.text((720, 340), str(rng.randint(10**11, 10**12 - 1)), font=font(22), fill=(30, 30, 30))
    d.text((40, 420), "Registrar General of Pakistan", font=font(18), fill=(60, 60, 60))
    d.text((20, H - 32), STAMP, font=font(16, True), fill=(200, 60, 60))
    return img, {"cnic_number": number}


def render_certificate(rng: random.Random, level: str) -> Tuple[Image.Image, Dict]:
    female = rng.random() < 0.5
    name, father = person(rng, female)
    name, father = name.upper(), father.upper()
    subjects = SUBJECTS_SSC if level == "matric" else SUBJECTS_HSSC
    maxes = MAX_SSC if level == "matric" else MAX_HSSC
    obtained = [rng.randint(int(m * 0.4), m) for m in maxes]
    total_max, total_ob = sum(maxes), sum(obtained)
    year = rng.randint(2015, 2025)
    dob = rand_date(rng, year - 18, year - 15)
    serial = str(rng.randint(10**6, 10**7 - 1))
    roll = str(rng.randint(10**5, 10**7 - 1))
    reg = str(rng.randint(10**9, 10**10 - 1))
    cert = f"{rng.randint(10**8, 10**9 - 1)}/{rng.randint(10**5, 10**6 - 1)}"
    grade = rng.choice(["A1", "A", "B", "C"])
    group = rng.choice(["SCIENCE", "GENERAL"]) if level == "matric" else rng.choice(["PRE-MEDICAL", "PRE-ENGINEERING"])
    school = rng.choice(SCHOOLS)
    title = (
        "SECONDARY SCHOOL CERTIFICATE EXAMINATION"
        if level == "matric"
        else "HIGHER SECONDARY SCHOOL CERTIFICATE EXAMINATION"
    )
    award = "Secondary School Certificate" if level == "matric" else "Higher Secondary School Certificate"

    W, H = 1240, 1700
    img = Image.new("RGB", (W, H), (250, 250, 246))
    d = ImageDraw.Draw(img)
    f, fb, fs = font(24), font(24, True), font(20)
    d.text(
        (W // 2, 70),
        "FEDERAL BOARD OF INTERMEDIATE AND SECONDARY EDUCATION",
        font=font(34),
        fill=(20, 20, 20),
        anchor="mm",
    )
    d.text((W // 2, 115), "ISLAMABAD", font=font(32), fill=(20, 20, 20), anchor="mm")
    d.text((90, 190), "Serial No.", font=f, fill=(30, 30, 30))
    d.text((230, 185), serial, font=font(28), fill=(170, 40, 40))
    d.text((760, 190), "Certificate No.", font=f, fill=(30, 30, 30))
    d.text((950, 190), cert, font=f, fill=(20, 20, 20))
    d.text((90, 260), "Roll No.", font=f, fill=(30, 30, 30))
    d.text((230, 260), roll, font=fb, fill=(20, 20, 20))
    d.text((760, 260), "Registration No.", font=f, fill=(30, 30, 30))
    d.text((970, 260), reg, font=f, fill=(20, 20, 20))
    d.text((90, 330), "Group", font=f, fill=(30, 30, 30))
    d.text((230, 330), group, font=f, fill=(20, 20, 20))
    d.text((760, 330), "Attempt(s)", font=f, fill=(30, 30, 30))
    d.text((970, 330), "FIRST", font=f, fill=(20, 20, 20))
    d.text((W // 2, 420), title, font=fb, fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 455), f"ANNUAL {year}", font=fb, fill=(20, 20, 20), anchor="mm")
    y = 520
    lines = [
        ("Certified that", name),
        ("Son / Daughter of", father),
        ("whose date of birth is", dob.strftime("%d-%m-%Y")),
        ("has qualified for award of", award),
        ("at the examination held in the month(s) of", "March / April  as a Regular Candidate from"),
    ]
    for label, value in lines:
        d.text((90, y), label, font=f, fill=(30, 30, 30))
        lw = d.textlength(label + "  ", font=f)
        d.text((90 + lw, y), value, font=fb if value.isupper() else f, fill=(20, 20, 20))
        y += 48
    d.text((90, y), school, font=f, fill=(20, 20, 20))
    y += 48
    d.text((90, y), f"as per statement of marks given below and has obtained grade {grade}", font=f, fill=(30, 30, 30))
    y += 70
    d.text((W // 2, y), "SUBJECT-WISE STATEMENT OF MARKS", font=fb, fill=(20, 20, 20), anchor="mm")
    y += 40
    x_sn, x_sub, x_max, x_ob, x_end = 80, 170, 760, 960, 1160
    d.rectangle([x_sn, y, x_end, y + 70], outline=(20, 20, 20), width=2)
    d.text((x_sn + 15, y + 22), "S.No.", font=fb, fill=(20, 20, 20))
    d.text((x_sub + 200, y + 22), "Subject(s)", font=fb, fill=(20, 20, 20))
    d.text((x_max + 50, y + 5), "MARKS", font=fb, fill=(20, 20, 20))
    d.text((x_max + 20, y + 38), "Maximum", font=fs, fill=(20, 20, 20))
    d.text((x_ob + 30, y + 38), "Obtained", font=fs, fill=(20, 20, 20))
    y += 70
    for i, (s, m, o) in enumerate(zip(subjects, maxes, obtained), 1):
        d.rectangle([x_sn, y, x_end, y + 46], outline=(20, 20, 20), width=1)
        d.text((x_sn + 25, y + 11), str(i), font=fs, fill=(20, 20, 20))
        d.text((x_sub + 10, y + 11), s, font=fs, fill=(20, 20, 20))
        d.text((x_max + 50, y + 11), f"{m:03d}", font=fs, fill=(20, 20, 20))
        d.text((x_ob + 50, y + 11), f"{o:03d}", font=fs, fill=(20, 20, 20))
        y += 46
    d.rectangle([x_sn, y, x_end, y + 50], outline=(20, 20, 20), width=2)
    d.text((x_sub + 250, y + 12), "TOTAL", font=fb, fill=(20, 20, 20))
    d.text((x_max + 45, y + 12), str(total_max), font=fb, fill=(20, 20, 20))
    d.text((x_ob + 50, y + 12), str(total_ob), font=fb, fill=(20, 20, 20))
    y += 90
    d.text((90, y), "(Marks in words)", font=f, fill=(30, 30, 30))
    d.text((310, y), number_words(total_ob), font=fb, fill=(20, 20, 20))
    y += 60
    issued = rand_date(rng, year, year)
    d.text(
        (90, y),
        f"Islamabad Dated   {MONTHS[issued.month - 1]} {issued.day:02d}, {issued.year}",
        font=f,
        fill=(30, 30, 30),
    )
    d.text((40, H - 40), STAMP, font=font(20, True), fill=(200, 60, 60))
    expected = {
        "board": "FBISE",
        "serial_number": serial,
        "roll_number": roll,
        "registration_number": reg,
        "certificate_number": cert,
        "group": group,
        "year": str(year),
        "grade": grade,
        "student_name": name,
        "father_name": father,
        "date_of_birth": dob.strftime("%d-%m-%Y"),
        "institute": school,
        "max_marks": str(total_max),
        "total_marks": str(total_ob),
        "subjects": [[s, m, o] for s, m, o in zip(subjects, maxes, obtained)],
    }
    return img, expected


def render_degree(rng: random.Random) -> Tuple[Image.Image, Dict]:
    female = rng.random() < 0.5
    name, father = person(rng, female)
    rel = "d/o" if female else "s/o"
    degree = rng.choice(
        [
            "Bachelor of Science in Computer Science",
            "Bachelor of Science in Electrical Engineering",
            "Master of Business Administration",
            "Bachelor of Science in Artificial Intelligence",
        ]
    )
    uni = rng.choice(["Example University of Technology", "Sample Institute of Engineering and Technology"])
    year = rng.randint(2015, 2025)
    issued = rand_date(rng, year, year)
    serial = str(rng.randint(10**5, 10**6 - 1))
    reg = f"EX/SP{year % 100 - 4:02d}-BCS-{rng.randint(1, 199):03d}"
    cgpa = f"{rng.uniform(2.0, 4.0):.2f}"
    W, H = 1400, 1000
    img = Image.new("RGB", (W, H), (252, 250, 240))
    d = ImageDraw.Draw(img)
    d.text((80, 80), f"Serial No: {serial}", font=font(24), fill=(150, 40, 40))
    d.text((900, 80), f"Registration No: {reg}", font=font(22), fill=(30, 30, 30))
    d.text((W // 2, 200), uni, font=font(50, True), fill=(40, 40, 40), anchor="mm")
    d.text((W // 2, 320), f"{name.upper()} {rel} {father.upper()}", font=font(32, True), fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 390), "has been conferred upon the degree of", font=font(26), fill=(30, 30, 30), anchor="mm")
    d.text((W // 2, 460), degree, font=font(38, True), fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 530), f"with CGPA {cgpa}", font=font(26), fill=(30, 30, 30), anchor="mm")
    d.text(
        (180, 640),
        f"Date of Issuance: {issued.day} {MONTHS[issued.month - 1]} {issued.year}",
        font=font(26),
        fill=(30, 30, 30),
    )
    d.text((40, H - 40), STAMP, font=font(20, True), fill=(200, 60, 60))
    expected = {
        "institution": uni,
        "student_name": name.upper(),
        "father_name": father.upper(),
        "degree": degree,
        "serial_number": serial,
        "registration_number": reg,
        "cgpa": cgpa,
        "date_of_issue": issued.strftime("%d-%m-%Y"),
        "year": str(issued.year),
    }
    return img, expected


# ----------------------------------------------------------- augmentations


def place_on_background(rng: random.Random, img: Image.Image, pad: float = 0.25) -> Image.Image:
    W, H = img.size
    bw, bh = int(W * (1 + pad)), int(H * (1 + pad))
    base = rng.choice([(90, 90, 100), (140, 120, 100), (200, 200, 205)])
    bg = Image.new("RGB", (bw, bh), base)
    d = ImageDraw.Draw(bg)
    for x in range(0, bw, 40):  # striped cloth, like the real sample backgrounds
        d.rectangle([x, 0, x + 18, bh], fill=tuple(max(0, c - 35) for c in base))
    bg.paste(img, ((bw - W) // 2, (bh - H) // 2))
    return bg


def augment(rng: random.Random, img: Image.Image, kind: str) -> Image.Image:
    if kind == "clean":
        return img
    if kind == "rotated90":
        return img.rotate(90, expand=True)
    if kind == "rotated270":
        return img.rotate(-90, expand=True)
    if kind == "upside_down":
        return img.rotate(180, expand=True)
    if kind == "skewed":
        return place_on_background(rng, img).rotate(rng.choice([-6, -4, 4, 6]), expand=True, fillcolor=(90, 90, 100))
    if kind == "photo":
        out = place_on_background(rng, img).rotate(rng.uniform(-2, 2), expand=True, fillcolor=(90, 90, 100))
        arr = np.asarray(out).astype(np.float32)
        h, w = arr.shape[:2]
        grad = np.linspace(0.8, 1.1, w)[None, :, None]  # uneven lighting
        arr = np.clip(arr * grad + np.random.default_rng(rng.randint(0, 9999)).normal(0, 6, arr.shape), 0, 255)
        return Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    if kind == "low_res":
        w, h = img.size
        return img.resize((w * 45 // 100, h * 45 // 100), Image.BILINEAR)
    if kind == "blurry":
        return img.filter(ImageFilter.GaussianBlur(1.6))
    if kind == "very_blurry":
        return img.filter(ImageFilter.GaussianBlur(7))
    raise ValueError(kind)


def occlude(img: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    out = img.copy()
    ImageDraw.Draw(out).ellipse(box, fill=(70, 70, 160))  # an ink stamp over the field
    return out


# ------------------------------------------------------------------- main


PLAN: List[Tuple[str, str]] = [
    ("cnic_front", "clean"),
    ("cnic_front", "clean"),
    ("cnic_front", "rotated90"),
    ("cnic_front", "rotated270"),
    ("cnic_front", "upside_down"),
    ("cnic_front", "skewed"),
    ("cnic_front", "photo"),
    ("cnic_front", "photo"),
    ("cnic_front", "low_res"),
    ("cnic_front", "blurry"),
    ("cnic_front", "very_blurry"),
    ("cnic_front", "occluded_name"),
    ("cnic_back", "clean"),
    ("cnic_back", "photo"),
    ("matric", "clean"),
    ("matric", "rotated90"),
    ("matric", "photo"),
    ("matric", "low_res"),
    ("intermediate", "clean"),
    ("intermediate", "skewed"),
    ("intermediate", "photo"),
    ("degree", "clean"),
    ("degree", "photo"),
]


def generate(out: Path, seed: int, count: int) -> Path:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    plan = (PLAN * (count // len(PLAN) + 1))[:count]
    for i, (doc, kind) in enumerate(plan):
        if doc == "cnic_front":
            img, exp = render_cnic_front(rng)
            dtype = "cnic"
        elif doc == "cnic_back":
            img, exp = render_cnic_back(rng)
            dtype = "cnic"
        elif doc in ("matric", "intermediate"):
            img, exp = render_certificate(rng, doc)
            dtype = doc
        else:
            img, exp = render_degree(rng)
            dtype = "degree"
        expect_missing: List[str] = []
        if kind == "occluded_name":
            img = occlude(img, (250, 140, 640, 215))
            expect_missing = ["name"]
            exp = {k: v for k, v in exp.items() if k != "name"}
            kind_applied = "clean"
        else:
            kind_applied = kind
        img = augment(rng, img, kind_applied)
        name = f"{i:02d}_{doc}_{kind}.jpg"
        img.save(out / name, quality=rng.choice([72, 80, 85]))
        case = {"id": f"{i:02d}_{doc}_{kind}", "image": name, "doc_type": dtype, "tags": [doc, kind], "expected": exp}
        if expect_missing:
            case["expect_missing"] = expect_missing
        if kind == "very_blurry":
            case["tags"].append("unreadable")
        cases.append(case)
    labels = out / "labels.json"
    labels.write_text(
        json.dumps(
            {"_note": "Synthetic data. Generated by benchmarks/synthetic/generate.py", "seed": seed, "cases": cases},
            indent=1,
        ),
        encoding="utf-8",
    )
    return labels


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--count", type=int, default=len(PLAN))
    args = ap.parse_args()
    print(f"Wrote {generate(args.out, args.seed, args.count)}")


if __name__ == "__main__":
    main()
