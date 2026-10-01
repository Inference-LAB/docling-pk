## What does this PR do?
<!-- One or two sentences. -->

## Modules touched
<!-- Files changed and why. -->

## How was it tested?
<!-- pytest summary; coverage. -->

## Benchmark impact
<!-- Required if extraction logic changed: paste the OVERALL / per-type lines from
     `python benchmarks/run_benchmark.py tests/fixtures/synthetic/labels.json`,
     before and after. Real-sample numbers: aggregates only. -->

## Edge cases handled
<!-- What inputs could break this and how they behave now. -->

## Checklist
- [ ] `ruff check`, `ruff format --check`, `mypy src` pass
- [ ] Tests added or updated; `pytest` passes
- [ ] No field can come back `ok` with a guessed value (fallbacks are `low_confidence` with a reason)
- [ ] Docstrings on new public functions (parameters, returns, example)
- [ ] README / CHANGELOG updated if behaviour or the public API changed
- [ ] **No real documents or personal data** in code, fixtures, logs or this description
