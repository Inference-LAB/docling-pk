# docling-pk Design Document (v1.0)

**Owner:** Abdul Moiz Muhammad (Lead, Research/Implementation and Integration/Evaluation roles)
**Status:** implemented in v1.0.0

## 1. Project summary

docling-pk is a pip-installable Python library and CLI that turns a photo or
scan of a Pakistani document (CNIC, Matric or Intermediate certificate,
university degree or transcript) into structured, validated fields. Every
field comes with a confidence score, a status, and a plain-language reason
when it could not be read. It runs fully offline on a CPU and is meant as the
reusable foundation for KYC, admissions and HR pipelines in Pakistan.

## 2. Problem statement

Document data entry in Pakistan is manual. International OCR services return
unstructured text, do not know Pakistani layouts, and are not free or local.
The hard part is not reading characters. It is turning messy phone-photo OCR
output into the *right* value for each field and knowing when not to trust
it. A wrong CNIC digit changes a person's identity, and a wrong mark changes
an admission decision.

## 3. Public API

```python
extract(source, document_type="auto", *, backend="auto", urdu=True, verify=True,
        gpu=None, auto_rotate=True, include_raw_text=True) -> DocumentResult
```

- `source`: path (image or PDF), bytes, NumPy array, PIL image, or a list of these (e.g. CNIC front + back).
- `DocumentResult`: `document_type`, `fields: dict[str, FieldResult]`, `confidence`, `warnings`,
  `raw_text`, `tables` (marks), `metadata` (rotation, skew, quality, engines, timings), plus
  `to_dict()`, `to_json()` and dict-style access matching the brief (`result["fields"]["name"]["value"]`).
- `FieldResult`: `value` (or `None`, never a guess), `confidence`, `status`
  (`ok | low_confidence | invalid | not_found | not_applicable`), `reason`, `raw`, `as_date()`.
- Errors raise only for bad *calls*: `FileNotFoundError`, `ImageLoadError(ValueError)`,
  `UnsupportedDocumentTypeError(ValueError)`. Bad *documents* never raise.
- CLI: `docling-pk extract | batch | info | --version`.

The schema extends the brief's `FieldResult(value, confidence)` with `status`
and `reason`. The lab note's lesson was "record why a field failed, not just
that it did", and downstream systems need to tell "not printed on this side"
apart from "printed but unreadable".

## 4. Architecture and module ownership

| Module | Responsibility |
|---|---|
| `extractor.py` | `extract()`: loading, routing, merging CNIC sides, overall confidence and warnings |
| `schema.py`, `errors.py` | Public data types and exceptions |
| `vision/image_io.py` | Paths (incl. non-ASCII Windows paths), bytes, arrays, PIL, PDF pages |
| `vision/quality.py` | Blur / exposure / glare / resolution measurements, as warnings |
| `vision/geometry.py` | Resizing, right-angle rotation, deskew from text-line angles, crops |
| `pipeline.py` | Orientation detection, deskew, OCR, micro-text filtering, ink-only variant, `Page.reread` |
| `ocr/` | `OCRBackend` interface; RapidOCR and EasyOCR adapters returning positioned `TextBox`es |
| `layout.py` | Fuzzy label matching and spatial queries (below, right of, lines) |
| `parsers/cnic.py`, `certificate.py`, `degree.py` | Per-document extraction |
| `validation/` | CNIC structure, dates, OCR digit look-alikes, marks and number words |
| `urdu.py` | Urdu code-point normalization and address lexicon correction |
| `cli.py` | Typer CLI |
| `benchmarks/` | Benchmark runner and synthetic data generator |

## 5. Technical approach

### 5.1 OCR engine: measured, not assumed

The brief proposed EasyOCR. On the 16 real samples the same parsers scored
59.9% with EasyOCR and 80.3% with RapidOCR (PP-OCR v6 models on ONNX
Runtime) before engine-specific fixes. RapidOCR read a small, soft-focus CNIC
photo almost perfectly where EasyOCR returned noise. It is also ~370 MB
installed against ~2.5 GB+ for EasyOCR with PyTorch, and runs at about 2.5 s
per document on CPU.

**Decision:** RapidOCR is the default and only required engine. EasyOCR is
the optional `urdu` extra, and it earns its place twice:

1. **Urdu address.** RapidOCR's models do not cover Urdu script.
2. **Independent verification.** EasyOCR supports character allowlists, so it
   re-reads CNIC numbers, dates and marks from tight crops with digits only.
   Agreement between two *different* engines is much stronger evidence than
   one engine agreeing with itself. With it, ok-precision on real photos goes
   from 98.5% to 99.2%.

Rejected alternatives: Tesseract needs a system install, which the brief
excludes. TrOCR-Urdu was trained on handwritten single lines. Qaari /
Qwen2-VL and Qwen2.5-VL are multi-GB downloads that need a GPU, and the
earlier experiments (kept outside the library) did not yield reliable Urdu
addresses; a generative model can also produce a fluent address that is not
on the card. UTRNet is a strong published Urdu recognizer, but it is licensed
CC BY-NC-SA (non-commercial), which is incompatible with an MIT library meant
for commercial KYC use.

### 5.2 Preprocessing: what the data supported

| Step | Finding | Decision |
|---|---|---|
| Adaptive threshold (brief's default) | Lowered EasyOCR confidence on every sample (lab note A/B test) | Not used |
| Laplacian blur *rejection* (threshold 35) | Rejected perfectly readable photos (a clean CNIC back scored 15.8) | Blur measured at a fixed resolution and reported as a **warning**; the OCR result decides |
| `minAreaRect` deskew over dark pixels | Returned −90° (a no-op) on 15/16 real photos; OpenCV ≥ 4.5 also changed the angle convention | Skew estimated from the OCR engine's own text-line polygons |
| 4-rotation trial scored by `confidence × count` with an en+ur reader | Urdu-script noise on a sideways read beat the upright read, so the cleanest CNIC photo scored 0/8 | Score = confidence × Latin characters + anchor-word bonus, scaled by the share of horizontal boxes (RapidOCR rotates tall crops itself, so text alone cannot reveal a sideways page). Upright is tried first and accepted early |
| Security-paper micro-text | Merged into real lines; RapidOCR's 1000-candidate cap silently dropped the top half of one certificate | Cap raised; small low-confidence boxes filtered; if many were filtered, an *ink-only* copy (Otsu cut-off, dark pixels keep their gray levels) is re-read and kept only if it scores higher |
| Urdu | Upscaling helped (line error rate 0.4 → 0.25), ink-only hurt | Urdu read at ≥ 2048 px, no binarization |

### 5.3 Field extraction

- **Positions, not reading order.** Parsers receive `TextBox(text,
  confidence, polygon)`, not newline-joined text. A value is the box below or
  beside its fuzzy-matched label. This removes the failure in the lab note,
  where EasyOCR grouped all date labels apart from all date values.
- **CNIC dates by chronology.** With three distinct dates, birth < issue <
  expiry assigns them regardless of layout. Label geometry is the fallback.
- **CNIC structure.** 13 digits, first digit a valid region code (1–8). The
  last digit gives gender (odd = male); a printed gender that disagrees is
  flagged, and an unreadable one is inferred with `low_confidence`.
- **Marks.** The marks table is read column-aligned to the "Maximum" and
  "Obtained" headers, validated against the TOTAL row, the subject sum and
  "Marks in words" (`words_to_number`, typo-tolerant), and digit-re-read if
  inconsistent. Totals are `ok` only when two sources agree.
- **Fallbacks are always labelled.** Positional and format-based fallbacks
  (unreadable labels, FBISE certificate-number format) return
  `low_confidence` with a reason saying how the value was found.
- **Urdu.** Arabic letter forms are mapped to Urdu code points. Address tokens
  are snapped to a lexicon of address words and districts by comparing
  dot-less letter skeletons (most Nastaliq OCR errors are dot errors). Place
  names need a stronger match so that noise is never turned into a real
  district.

### 5.4 Confidence

A field's confidence starts from OCR recognition confidence. Agreeing reads
combine as `1 − Π(1 − cᵢ)`, disagreements multiply by 0.6, and failed
validation removes the value. Below 0.55 the status becomes
`low_confidence`. Document confidence is the mean over all *applicable*
fields, including missing ones, so a half-read document cannot score high
(kept from v0.1).

## 6. Evaluation plan and data ethics

- **Two datasets.** (a) 16 real photos (author-owned and publicly circulated
  samples): rotated, skewed, sleeved, soft, motion-blurred, scanned and
  watermarked. Hand-labelled, kept **outside the repository**, only aggregate
  numbers published. (b) 23 synthetic fixtures generated by
  `benchmarks/synthetic/generate.py`: fabricated data, stamped "SYNTHETIC
  SPECIMEN", no emblems, photos or seals. These are committed and drive CI.
  Real CNIC numbers must never be committed; this is a data-ethics
  requirement, not only a technical one.
- **Metrics.** Per-field exact-match accuracy, coverage, precision,
  *ok-precision*, character error rate for free text, marks-row accuracy, and
  latency.
- **Targets.** The brief's 99% CNIC-number target is interpreted as *99% of
  returned `ok` values correct*. Measured: 100% on both datasets (every
  returned CNIC number was correct; the one miss was left blank).
- **Tests.** 211 unit tests on constructed OCR layouts (run without models,
  92% branch coverage, CI gate at 90%) plus 42 end-to-end tests with real OCR
  on the synthetic fixtures. The key end-to-end test asserts that no field is
  ever returned `ok` with a wrong value.

## 7. Known risks and limitations

See the README's Known limitations. In short: Urdu address quality, board
layouts beyond FBISE, old Urdu-only CNICs, severe blur, and a small real test
set (16 images). The benchmark makes the next round of samples cheap to
evaluate: add images and labels to a private labels file and run
`benchmarks/run_benchmark.py`.

## 8. Definition of Done (v1)

- [x] CNIC, Matric, Intermediate and Degree/Transcript extraction
- [x] `extract()` and CLI (`docling-pk extract <image> --type cnic --output json`)
- [x] Confidence, status and reason on every field; warnings on every result
- [x] Graceful failure: partial results, no crash on messy input
- [x] Fixtures: clean, rotated, low-resolution, obscured field, unreadable, PDF
- [x] pytest suite, ≥ 90% coverage (92%), CI on Python 3.9–3.12 + Windows/macOS
- [x] Benchmark report (`tests/benchmark_report.json`, `docs/benchmark.md`)
- [x] README with installation, usage and known limitations
- [x] Docstrings with parameters, returns and examples on public functions
- [x] `pip install docling-pk` verified in a clean Python 3.9 virtualenv
- [ ] Publish to PyPI (release workflow ready; needs the PyPI trusted-publisher setup and a `v1.0.0` tag)
