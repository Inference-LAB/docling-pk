# docling-pk Design Document

## 1. Project Summary

docling-pk is a Python library that reads Pakistani documents (CNIC, Matric,
Intermediate certificates) from a photo and returns structured data as JSON.
No cloud API needed. Built for KYC, admissions, and HR use cases in Pakistan.

## 2. Problem Statement

Document data entry in Pakistan is manual today. Banks, universities, and HR
teams type data from CNIC and certificate photos by hand. This is slow and
causes real errors. No open source tool exists for Pakistani document formats
specifically. docling-pk fills that gap.

## 3. Technical Approach

**Owner:** Abdul Moiz Muhammad

### Stack

- OCR: EasyOCR (chosen in the brief, supports Arabic script for Urdu labels,
  no system install needed)
- Preprocessing: OpenCV (blur check, deskew, denoise, threshold)
- Parsing: regex based field extraction

### What works (tested on 4 real CNIC photos)

- Name, father name, CNIC number, all 3 dates: reliable
- Gender: works on some cards, fails on others (depends on print format)
- Address: not on the front of a Smart CNIC, out of scope unless back images
  are added

### Key fixes made during testing

| Problem | Fix |
|---|---|
| Photo shot sideways | Try OCR at all 4 rotations, keep the best result |
| Blurry photo returns garbage | Detect blur early (Laplacian variance), reject with a clear message instead of guessing |
| Date labels and values not next to each other in OCR output | Match dates by format, assign by fixed order (birth, issue, expiry) |
| CNIC number separator misread (colon, underscore, backtick) | Normalize all variants to a dash before matching |
| 2x image upscaling (tested) | Made results worse, not better. Not used. |

### Known limitations

- Deskew fails when the background is cluttered (tested, confirmed on a
  tilted photo against striped fabric). Works only with a plain background.
- Gender and multi-line names are not reliably extracted with the current
  full page OCR plus regex method.
- A better approach would crop each field to its own region before OCR,
  instead of reading the whole card at once. Being explored separately.

## 4. Module Ownership

All modules currently owned by Abdul Moiz Muhammad (solo).

| Module | Purpose |
|---|---|
| `preprocessor.py` | Load, blur check, deskew, denoise, threshold |
| `ocr.py` | EasyOCR wrapper with rotation correction |
| `parsers/cnic.py` | CNIC field extraction |
| `parsers/matric.py` | Matric extraction (not started) |
| `parsers/intermediate.py` | Intermediate extraction (not started) |
| `schema.py` | Output data structures |
| `extractor.py` | Main `extract()` function |
| `cli.py` | Command line interface |
| `pyproject.toml` | Packaging |

## 5. Evaluation Plan

- Test each document type against real sample photos: clean, blurry, rotated,
  partially obscured.
- Track per-field success, not one overall accuracy number. Some fields
  (gender, address) need separate tracking since they fail differently.
- Confidence score reflects extraction completeness across all fields, not
  just the fields that succeeded.

## 6. Known Risks

- Blur and rotation handling calibrated on very few real samples so far.
- Matric and Intermediate parsers not started yet.
- Degree/Transcript scope is unclear: RoleGuide lists it, the Brief's
  required feature list does not. Needs confirmation.

## 7. Definition of Done (v1)

- [ ] CNIC, Matric, Intermediate extraction working
- [ ] `extract()` function and CLI both working
- [ ] Confidence score and warnings on every result
- [ ] Blurry or unreadable images fail with a clear message, not a crash
- [ ] pytest suite, 90%+ coverage
- [ ] README with install steps, usage, and known limitations
- [ ] `pip install docling-pk` works in a clean Python 3.9+ environment