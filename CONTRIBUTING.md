# Contributing to docling-pk

## Setup

```bash
git clone https://github.com/Inference-LAB/docling-pk.git
cd docling-pk
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,pdf]"          # add ,urdu to work on the Urdu address or verifier
```

## Before opening a PR

```bash
ruff check src tests benchmarks
ruff format src tests benchmarks
mypy src
pytest -m "not ocr"                  # fast, no OCR models
pytest                               # full suite incl. end-to-end OCR (downloads ~15 MB of models once)
python benchmarks/run_benchmark.py tests/fixtures/synthetic/labels.json
```

CI runs all of these, enforces 90% coverage, and fails if any synthetic
fixture returns a field with status `ok` and a wrong value. Paste the
benchmark summary into the PR description whenever extraction logic changes.

## Never commit real documents

Real CNICs and certificates contain personal data. Do not add them to the
repository, to issues, or to PR descriptions, even blurred. To evaluate on
real samples, keep the images and a labels file outside the repo and run
`benchmarks/run_benchmark.py /path/to/private/labels.json`; share only the
aggregate numbers. For tests, add synthetic cases to
`benchmarks/synthetic/generate.py` and regenerate the fixtures.

## Adding a board, university or document type

1. Collect a few real samples (privately) and label them.
2. Run the benchmark to see where the current parser fails.
3. Prefer **label vocabulary and validation** over coordinates: add labels to
   the parser's label lists, formats to `validation/`, and checks that can turn
   a wrong value into `low_confidence`.
4. Add constructed-layout unit tests (see `tests/conftest.py`) and, if
   possible, a synthetic fixture.
5. Values found by fallbacks must be `low_confidence` with a `reason`.

## Design rules

- A field is never filled with a guess. Return `None` with a reason instead.
- Status `ok` means it passed every check that applies to it.
- Problems with the call raise; problems with the document go in `warnings`.
- Keep the core install free of PyTorch; heavy models go in extras.
