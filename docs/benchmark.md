# Benchmark report (v1.0.0)

## Method

`benchmarks/run_benchmark.py` runs `extract()` on every case in a labels file
and compares each field to the hand-labelled value after light normalization
(case, spacing, punctuation; dates compared as `DD-MM-YYYY`). It reports:

- **accuracy**: correct / all labelled fields (a missing value counts as wrong)
- **coverage**: fields that got any value
- **precision**: correct / returned values
- **ok-precision**: correct / values returned with status `ok`, the figure to use if a system auto-accepts `ok` fields
- **CER**: character error rate on free-text fields
- **subjects**: marks-table rows with subject, maximum and obtained marks all correct

## Datasets

| Set | Images | Fields | Where |
|---|---|---|---|
| Real photos | 16 (8 CNIC fronts, 2 CNIC backs, 2 Matric, 2 Intermediate, 1 degree, 1 transcript) | 146 + 30 marks rows | Private (personal data). Aggregates in [`benchmarks/results/real_samples_summary.json`](../benchmarks/results/real_samples_summary.json) |
| Synthetic | 23 (clean, rotated 90/180/270, skewed, photo-on-cloth, low-res, blurry, very blurry, occluded name, CNIC back, Matric, Intermediate, degree) | 213 + 53 marks rows | [`tests/fixtures/synthetic`](../tests/fixtures/synthetic), report in [`tests/benchmark_report.json`](../tests/benchmark_report.json) |

Real-photo conditions: clean phone photos, 90/270° rotations, skew on striped
cloth, a plastic sleeve with glare, a small soft-focus card, motion blur, a
flatbed scan, and a digital certificate on micro-text security paper.

## Results

### Overall

| Dataset / configuration | Accuracy | Coverage | Precision | ok-precision | Marks rows | s / doc |
|---|---|---|---|---|---|---|
| Real, v0.1 (original pipeline) | 34.9% | n/a | n/a | n/a | 0/30 | n/a |
| Real, v1 core (RapidOCR, CPU) | 94.4% | 97.2% | 97.1% | 98.5% | 30/30 | 3.7 |
| Real, v1 + `urdu` extra (EasyOCR verifier) | 94.4% | 97.9% | 96.4% | **99.2%** | 30/30 | 3.7 |
| Synthetic, v1 core (CPU only) | 96.2% | 96.2% | 100% | **100%** | 53/53 | 2.5 |
| Synthetic, v1 + `urdu` extra | 96.2% | 96.2% | 100% | **100%** | 53/53 | 2.6 |

The full install's precision is slightly lower than the core's only because
it *attempts* the Urdu address (always flagged `low_confidence`); the core
install leaves it blank.

### By document type (real photos)

| Type | v0.1 | v1 |
|---|---|---|
| CNIC | 35.3% | 91.2% |
| Matric | 63.3% | 96.4% |
| Intermediate | 27.6% | 100% |
| Degree | 0% (unsupported) | 100% |
| Transcript | 0% (unsupported) | 90.0% |

### CNIC fields (real photos, v1)

| Field | Accuracy | Notes |
|---|---|---|
| cnic_number | 90% (9/10) | every returned value correct; the miss (motion blur) was left blank |
| date_of_birth / issue / expiry | 100% (8/8 each) | |
| gender | 100% | |
| name / father_name | 87.5% | misses: motion blur, soft focus |
| country_of_stay | 87.5% | |
| address (Urdu) | 0% exact, CER ≈ 0.49 | experimental, always `low_confidence` |

Certificates: every field except one school name (a dropped space) was
correct, and all 30 subject rows (subject, maximum, obtained) were exact.

## What moved the numbers

Each step was measured on the real set (accuracy after the change):

| Change | Accuracy |
|---|---|
| v0.1 baseline | 34.9% |
| Layout-aware parsers, new orientation scoring, quality warnings instead of rejection (EasyOCR) | 59.9% |
| RapidOCR engine + raised detector candidate cap + box-shape orientation | 80.3% |
| Cross-engine digit re-reads, garbled-number recovery | 83.8% |
| Positional/format fallbacks for unreadable labels, blackletter-tolerant degree patterns | 90.8% |
| Ink-only re-read for micro-text paper | 93.0% |
| Precision fixes (verifier on IDs, confidence floors) | 94.4% |

## Caveats

16 real images is a small sample; per-type figures on 1–2 documents are
indicative, not statistically strong. The synthetic set controls for privacy
and covers the brief's required conditions, but its layouts are simpler than
real cards. The most useful next step is more real, consented samples,
especially from Punjab, Sindh and KP boards.

## Reproduce

```bash
python benchmarks/run_benchmark.py tests/fixtures/synthetic/labels.json --out report.json
python benchmarks/run_benchmark.py path/to/private/labels.json --backend rapidocr
```
