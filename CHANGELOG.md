# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10

First release on PyPI. Field accuracy on 16 real document photos went from
34.9% (v0.1) to 94.4%, with 99.2% of fields marked `ok` correct.

### Added
- `extract()` public API accepting paths, bytes, NumPy arrays, PIL images,
  PDFs and lists (CNIC front + back merged into one result).
- `document_type="auto"` detection; aliases `ssc`, `hssc`, `fsc`, `inter`, `transcript`.
- Degree and transcript extraction.
- Per-field `status` and `reason`; `FieldResult.as_date()`; `DocumentResult.to_json()`
  and dict-style access; marks table in `result.tables["subjects"]`.
- RapidOCR backend (new default) and pluggable `OCRBackend` interface.
- Cross-engine verification of CNIC numbers, dates, marks and IDs (with the `urdu` extra).
- CNIC: label-geometry parsing, chronological date assignment, gender vs CNIC
  parity check, back-side support, experimental Urdu address with normalization
  and lexicon correction.
- Certificates: column-aligned marks table validated against the TOTAL row,
  subject sums and "marks in words"; board detection for FBISE and other boards.
- Orientation (0/90/180/270) and skew correction that work on cluttered backgrounds.
- Image-quality warnings (blur, exposure, glare, resolution).
- CLI: `extract`, `batch`, `info`, `--version`, table output.
- Synthetic document generator, 23 committed fixtures, benchmark runner and report.
- Test suite (253 tests, 92% coverage), CI on Python 3.9–3.12 / Linux, Windows,
  macOS, clean-install check, PyPI trusted-publishing release workflow.

### Changed
- EasyOCR moved to the optional `urdu` extra; the core install no longer needs PyTorch.
- Blurry images produce warnings and partial results instead of being rejected.
- Package moved to a `src/` layout; the CLI entry point is `docling_pk.cli:app`.

### Fixed
- `docling_pk.extractor` could not be imported (`from __future__` after other imports).
- `from docling_pk import extract` did not exist.
- The installed `docling-pk` command pointed to a module that was not packaged.
- Orientation selection preferred Urdu-script noise on sideways reads, so the
  cleanest CNIC photo extracted 0 of 8 fields.
- Deskew was a no-op (or wrong) on OpenCV ≥ 4.5.
- "Father Name" label minus "Father" was returned as the father's name ("Name").
- Images with non-ASCII paths failed to load on Windows.

## [0.1.0] - 2026-09

Fellowship prototype: EasyOCR + regex CNIC parser, Federal Board certificate
parser, CLI skeleton returning placeholder output.
