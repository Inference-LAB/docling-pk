# docling-pk

**Structured data extraction from Pakistani identity and education documents.**
Give it a photo of a CNIC, a Matric or Intermediate certificate, or a university
degree / transcript, and get back typed fields with confidence scores, plus a
reason for every field it could not read.

[![CI](https://github.com/Inference-LAB/docling-pk/actions/workflows/ci.yml/badge.svg)](https://github.com/Inference-LAB/docling-pk/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

```python
from docling_pk import extract

result = extract("cnic_front.jpg", document_type="cnic")
print(result.to_json())
```

```json
{
  "document_type": "cnic",
  "fields": {
    "name":           {"value": "Muhammad Ali",    "confidence": 0.99, "status": "ok"},
    "father_name":    {"value": "Muhammad Akram",  "confidence": 0.99, "status": "ok"},
    "gender":         {"value": "M",               "confidence": 1.0,  "status": "ok"},
    "country_of_stay":{"value": "Pakistan",        "confidence": 1.0,  "status": "ok"},
    "cnic_number":    {"value": "35202-1234567-9", "confidence": 1.0,  "status": "ok"},
    "date_of_birth":  {"value": "01-01-1995",      "confidence": 1.0,  "status": "ok"},
    "date_of_issue":  {"value": "15-03-2020",      "confidence": 1.0,  "status": "ok"},
    "date_of_expiry": {"value": "15-03-2030",      "confidence": 1.0,  "status": "ok"},
    "address":        {"value": null, "confidence": 0.0, "status": "not_applicable",
                       "reason": "printed on the back of the card; pass the back image too"},
    "permanent_address": {"value": null, "confidence": 0.0, "status": "not_applicable", "reason": "..."}
  },
  "confidence": 0.99,
  "warnings": [],
  "metadata": {"ocr_backend": "rapidocr", "sides": ["front"], "pages": [{"rotation_degrees": 90, "skew_degrees": 0.0}]}
}
```

## Why it is built this way

- **It does not return a wrong value as `ok`.** On the synthetic benchmark, every
  field reported with status `ok` was correct; on 16 real photos, 99.2% were.
  When a field cannot be read reliably, `value` is `None` and the result says
  why (`not_found`, `invalid`, `low_confidence`, `not_applicable`). A blank
  goes to a human. A wrong CNIC digit would quietly change someone's identity.
- **Cross-checks, not just OCR.** CNIC numbers and dates are re-read from a
  tight crop by a second OCR engine. The three CNIC dates must satisfy
  birth < issue < expiry. The CNIC's last digit must match the printed gender
  (odd = male). Marks are checked against the TOTAL row, the subject rows'
  sum, and the "marks in words" line.
- **Real phone photos.** It detects and fixes 90/180/270-degree rotation and
  skew, filters security-paper micro-text, and warns about blur, glare and low
  resolution instead of rejecting the image.
- **Light install.** The default engine is RapidOCR (PP-OCR models on ONNX
  Runtime): about 370 MB installed, CPU-only, around 2.5 s per document. No
  PyTorch is needed unless you want the Urdu address.

## Installation

```bash
pip install docling-pk                 # CNIC front, certificates, degrees (CPU, ~370 MB)
pip install "docling-pk[urdu]"         # + Urdu address on CNIC backs, + second-engine verification (EasyOCR/PyTorch)
pip install "docling-pk[pdf]"          # + PDF input (PyMuPDF)
pip install "docling-pk[all]"
```

Python 3.9 to 3.12 on Linux, Windows and macOS. Models are bundled with or
downloaded by the OCR engines on first use; nothing is sent to any server.
On minimal Linux images (e.g. `python:3.x-slim` in Docker), OpenCV needs two
system libraries: `apt-get install -y libgl1 libglib2.0-0`.

## Usage

### Python

```python
from docling_pk import extract

# CNIC: pass front and back together to also get the address
r = extract(["cnic_front.jpg", "cnic_back.jpg"], document_type="cnic")
r.fields["cnic_number"].value         # '35202-1234567-9'
r.fields["date_of_birth"].as_date()   # datetime.date(1995, 1, 1)
r["fields"]["name"]["value"]          # dict-style access mirrors the JSON

# Board certificate: subject-wise marks come back as a table
r = extract("matric.jpg", document_type="matric")
r.fields["total_marks"].value          # '787'
r.tables["subjects"][0]                # {'subject': 'ENGLISH (COMPULSORY)', 'max_marks': 150, 'obtained_marks': 118}

# Let it figure out the document type
r = extract("unknown_scan.png")        # document_type="auto"
r.document_type                        # 'intermediate'

# Inputs: path, bytes, NumPy array (BGR), PIL image, PDF, or a list of these
r = extract(open("card.jpg", "rb").read(), "cnic")

# Acting only on fields that passed every check
trusted = {k: f.value for k, f in r.fields.items() if f.status == "ok"}
needs_review = {k: f.reason for k, f in r.fields.items() if f.status != "ok"}
```

Options: `backend="auto" | "rapidocr" | "easyocr"` (or your own
`OCRBackend`), `verify=True` (second-engine re-reads when EasyOCR is
installed), `urdu=True`, `gpu=None` (auto), `auto_rotate=True`,
`include_raw_text=True`.

### Command line

```bash
docling-pk extract cnic_front.jpg cnic_back.jpg --type cnic           # JSON to stdout
docling-pk extract certificate.jpg --type auto --output table         # readable table
docling-pk extract transcript.pdf --type degree --out result.json
docling-pk batch ./scans --type matric --out results.jsonl            # a folder, one JSON line per file
docling-pk info                                                       # engines installed, GPU
```

Exit codes: `0` success, `1` processed but nothing could be extracted, `2` bad
input (missing file, unreadable image, unknown type).

## Supported documents

| `document_type` | Fields | Verified on real samples |
|---|---|---|
| `cnic` | `name`, `father_name`, `gender`, `country_of_stay`, `cnic_number`, `date_of_birth`, `date_of_issue`, `date_of_expiry`, `address`, `permanent_address` | Current green CNIC / SNIC, front and back |
| `matric` (`ssc`) | `student_name`, `father_name`, `date_of_birth`, `roll_number`, `registration_number`, `serial_number`, `certificate_number`, `board`, `exam`, `year`, `session`, `group`, `institute`, `grade`, `total_marks`, `max_marks`, plus `tables["subjects"]` | FBISE |
| `intermediate` (`hssc`, `fsc`, `inter`) | Same as matric | FBISE |
| `degree` (`transcript`) | `student_name`, `father_name`, `degree`, `institution`, `campus`, `registration_number`, `serial_number`, `cgpa`, `division`, `date_of_birth`, `date_of_issue`, `year` | COMSATS degree and transcript |

Every field key is always present for its document type. Matric and
intermediate are confirmed against the certificate title, which wins if it
disagrees with `document_type` (a warning says so). Other boards (BISE
Lahore, Rawalpindi, Karachi, Peshawar...) are detected and parsed with the
same label vocabulary, but come with a warning because their layouts have
not been verified on real samples yet.

## Accuracy

Exact-match field accuracy. *Precision* is the share of returned values that
are correct; *ok-precision* is the same restricted to fields with status
`ok`, which is the number that matters if your system auto-accepts them.

| Dataset | Accuracy | Precision | ok-precision | Marks rows | Time / doc |
|---|---|---|---|---|---|
| 16 real photos, original v0.1 pipeline | 34.9% | n/a | n/a | 0 / 30 | n/a |
| 16 real photos, v1 (`pip install docling-pk`) | **94.4%** | 97.1% | 98.5% | 30 / 30 | 3.7 s |
| 16 real photos, v1 with the `urdu` extra | **94.4%** | 96.4% | **99.2%** | 30 / 30 | 3.7 s |
| 23 synthetic fixtures (committed) | **96.2%** | 100% | **100%** | 53 / 53 | 2.5 s (CPU) |

By document type on real photos: CNIC 91.2%, Matric 96.4%, Intermediate
100%, Degree 100%, Transcript 90%. Every date and gender on the real CNICs was
correct. The misses: the Urdu address (both cards), three fields on a
motion-blurred photo (left blank, plus a misspelled name flagged
`low_confidence`), one father's name on a small soft-focus photo (left
blank), one registration number with an I/l confusion (flagged
`low_confidence`) and one dropped space in a school name. Full methodology
and per-field numbers:
[docs/benchmark.md](https://github.com/Inference-LAB/docling-pk/blob/main/docs/benchmark.md). The real photos contain personal data
and are not published; only aggregate counts are
([benchmarks/results/real_samples_summary.json](https://github.com/Inference-LAB/docling-pk/blob/main/benchmarks/results/real_samples_summary.json)).

Reproduce the public benchmark:

```bash
python benchmarks/run_benchmark.py tests/fixtures/synthetic/labels.json
```

## Known limitations

- **Urdu address (CNIC back) is experimental.** Nastaliq OCR with EasyOCR
  averages about 49% character error on real cards, even after Urdu
  normalization and lexicon correction of address words and district names.
  It is always returned as `low_confidence`. UTRNet, the strongest open Urdu
  recognizer we evaluated, is licensed CC BY-NC-SA (non-commercial), so it
  cannot ship in an MIT library.
- **Handwritten fields, heavily damaged documents, and stamps covering more
  than ~30% of a field** are out of scope (per the v1 brief). They return
  `None` with a reason; they do not crash.
- **Old (pre-2012) Urdu-only CNICs**: numbers and dates are read; Urdu-only
  names are not.
- **Board layouts other than FBISE** are parsed best-effort and flagged.
- **Severe motion blur** loses fields. The result is a blur warning and blank
  fields, never invented values.
- **No NADRA verification.** docling-pk reads documents; it does not check
  that they are genuine.

## Privacy

Processing is fully local. `DocumentResult.to_dict()` and the CLI leave out
the raw OCR text by default, because it can contain personal data that is not
part of any extracted field (`include_raw=True` / `--raw` to include it). The
repository's test images are synthetic and stamped "SYNTHETIC SPECIMEN".

## How it works

```
image/PDF ─► load (Unicode paths, EXIF, PDF pages) ─► quality checks (blur, glare, exposure)
          ─► orientation (0/90/180/270 by Latin-text score × box shape) ─► deskew from text-line angles
          ─► OCR with positions (RapidOCR / EasyOCR) ─► micro-text filter (+ ink-only re-read if needed)
          ─► per-type parser: labels found by fuzzy match, values by position
          ─► validation & cross-checks (second engine, CNIC structure, date order, marks sums)
          ─► DocumentResult (value, confidence, status, reason per field)
```

Details and the decisions behind them, including the measurements that
replaced the brief's EasyOCR default: [docs/design_doc.md](https://github.com/Inference-LAB/docling-pk/blob/main/docs/design_doc.md).

## Development

```bash
pip install -e ".[dev,pdf]"
pytest -m "not ocr"            # 211 fast tests, no models needed
pytest                          # + end-to-end OCR tests on synthetic fixtures
ruff check . && ruff format --check . && mypy src
python benchmarks/synthetic/generate.py   # regenerate the synthetic fixtures
```

See [CONTRIBUTING.md](https://github.com/Inference-LAB/docling-pk/blob/main/CONTRIBUTING.md). Releases are published to PyPI from
version tags by GitHub Actions (trusted publishing).

## License

MIT. See [LICENSE](https://github.com/Inference-LAB/docling-pk/blob/main/LICENSE). Built at [INFERENCE Lab](https://inference-lab.org)
as part of Engineering Fellowship Cohort 01.
