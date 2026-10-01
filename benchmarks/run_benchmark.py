"""
Accuracy benchmark for docling-pk.

    python benchmarks/run_benchmark.py benchmarks/synthetic/labels.json
    python benchmarks/run_benchmark.py path/to/private/labels.json --backend rapidocr

A labels file is JSON: ``{"cases": [{"id", "image", "doc_type", "expected":
{field: value, "subjects": [[name, max, obtained], ...]}, "tags": [...]}]}``
with ``image`` relative to the labels file. ``image`` may also be a list
(e.g. CNIC front and back).

Metrics, per field and overall:

* **accuracy**  exact match after normalization, over all expected fields.
  A missing value counts as wrong.
* **coverage**  fraction of expected fields that got any value.
* **precision** of the values that were returned, how many were right.
  For KYC this matters more than accuracy: a ``None`` is safe (a human
  looks at it), a wrong value is not.
* **ok-precision** precision restricted to fields with status ``ok``; the
  number to quote if a pipeline auto-accepts ``ok`` fields.
* **CER** character error rate for free-text fields (names, addresses).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docling_pk import extract  # noqa: E402

TEXT_FIELDS = {
    "name",
    "father_name",
    "student_name",
    "address",
    "permanent_address",
    "institute",
    "institution",
    "degree",
}


def norm(field: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    v = unicodedata.normalize("NFKC", str(value)).strip()
    if field.startswith("date"):
        m = re.search(r"(\d{1,2})\D+(\d{1,2})\D+(\d{4})", v)
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}-{m.group(3)}" if m else v
    if field in ("total_marks", "max_marks") or field.endswith("_number"):
        v = re.sub(r"\s+", "", v)
    v = re.sub(r"[\s,.]+", " ", v).upper().strip()
    v = v.replace("،", " ").replace("۔", " ")
    return re.sub(r"\s+", " ", v)


def cer(expected: str, actual: Optional[str]) -> float:
    e = norm("x", expected) or ""
    a = norm("x", actual) or ""
    return Levenshtein.distance(e, a) / max(len(e), 1)


def score_subjects(expected: List, actual: List[Dict]) -> Dict[str, int]:
    got = {}
    for r in actual or []:
        got.setdefault(re.sub(r"[^A-Z]", "", str(r.get("subject", "")).upper()), r)
    correct = 0
    for name, mx, ob in expected:
        key = re.sub(r"[^A-Z]", "", name.upper())
        r = got.get(key)
        if r is None:
            # fuzzy subject name match
            best = min(got, key=lambda k: Levenshtein.distance(k, key), default=None)
            if best is not None and Levenshtein.distance(best, key) <= max(2, len(key) // 6):
                r = got[best]
        if r is not None and r.get("max_marks") == mx and r.get("obtained_marks") == ob:
            correct += 1
    return {"rows_correct": correct, "rows_expected": len(expected), "rows_returned": len(actual or [])}


def run(labels_path: Path, backend: str, out: Optional[Path], limit_tags: Optional[str]) -> Dict:
    data = json.loads(labels_path.read_text(encoding="utf-8"))
    base = labels_path.parent
    rows = []
    subj_tot = defaultdict(int)
    timings = []
    per_case = []
    for case in data["cases"]:
        if limit_tags and not set(limit_tags.split(",")) & set(case.get("tags", [])):
            continue
        imgs = case["image"] if isinstance(case["image"], list) else [case["image"]]
        paths = [str(base / p) for p in imgs]
        t0 = time.perf_counter()
        try:
            result = extract(paths if len(paths) > 1 else paths[0], document_type=case["doc_type"], backend=backend)
            fields = {k: v for k, v in result.fields.items()}
            tables = result.tables
            err = None
        except Exception as exc:  # report, keep going
            fields, tables, err = {}, {}, f"{type(exc).__name__}: {exc}"
        dt = time.perf_counter() - t0
        timings.append(dt)
        case_ok = 0
        for fname, exp in case["expected"].items():
            if fname == "subjects":
                s = score_subjects(exp, tables.get("subjects", []))
                for k, v in s.items():
                    subj_tot[k] += v
                continue
            f = fields.get(fname)
            got = f.value if f is not None else None
            status = f.status.value if f is not None else "absent"
            correct = norm(fname, got) == norm(fname, exp)
            case_ok += correct
            rows.append(
                {
                    "case": case["id"],
                    "doc_type": case["doc_type"],
                    "field": fname,
                    "expected": exp,
                    "actual": got,
                    "status": status,
                    "correct": correct,
                    "confidence": f.confidence if f is not None else 0.0,
                    "cer": cer(exp, got) if fname in TEXT_FIELDS else None,
                    "tags": case.get("tags", []),
                    "error": err,
                }
            )
        n = len([k for k in case["expected"] if k != "subjects"])
        per_case.append((case["id"], case_ok, n, dt, err))
        print(f"{case['id']:32s} {case_ok:>3}/{n:<3} {dt:6.1f}s {err or ''}", flush=True)

    def summarize(rs):
        n = len(rs)
        returned = [r for r in rs if r["actual"] is not None]
        okr = [r for r in rs if r["status"] == "ok"]
        return {
            "n": n,
            "accuracy": sum(r["correct"] for r in rs) / n if n else 0.0,
            "coverage": len(returned) / n if n else 0.0,
            "precision": (sum(r["correct"] for r in returned) / len(returned)) if returned else None,
            "ok_precision": (sum(r["correct"] for r in okr) / len(okr)) if okr else None,
            "ok_count": len(okr),
        }

    report: Dict[str, Any] = {
        "labels": str(labels_path.name),
        "backend": backend,
        "overall": summarize(rows),
        "by_doc_type": {},
        "by_field": {},
        "subjects": dict(subj_tot),
        "seconds_per_document": {
            "mean": statistics.mean(timings) if timings else 0,
            "max": max(timings) if timings else 0,
        },
        "cases": [
            {"id": c, "correct": k, "total": n, "seconds": round(t, 2), "error": e} for c, k, n, t, e in per_case
        ],
    }
    by_type = defaultdict(list)
    by_field = defaultdict(list)
    for r in rows:
        by_type[r["doc_type"]].append(r)
        by_field[f"{r['doc_type']}.{r['field']}"].append(r)
    report["by_doc_type"] = {k: summarize(v) for k, v in sorted(by_type.items())}
    report["by_field"] = {k: summarize(v) for k, v in sorted(by_field.items())}
    text_cer = [r["cer"] for r in rows if r["cer"] is not None]
    report["mean_cer_text_fields"] = statistics.mean(text_cer) if text_cer else None

    o = report["overall"]
    print(
        f"\nOVERALL  accuracy {o['accuracy']:.1%}  coverage {o['coverage']:.1%}  "
        f"precision {o['precision'] or 0:.1%}  ok-precision {o['ok_precision'] or 0:.1%} (n_ok={o['ok_count']})"
    )
    for k, v in report["by_doc_type"].items():
        print(f"  {k:14s} accuracy {v['accuracy']:.1%}  precision {v['precision'] or 0:.1%}  (n={v['n']})")
    if subj_tot:
        print(f"  subjects rows correct {subj_tot['rows_correct']}/{subj_tot['rows_expected']}")
    print("\nPer field:")
    for k, v in report["by_field"].items():
        print(
            f"  {k:40s} {v['accuracy']:6.1%}  prec {v['precision'] if v['precision'] is not None else float('nan'):6.1%}  n={v['n']}"
        )
    if out:
        report["rows"] = rows
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("labels", type=Path)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--out", type=Path, default=None, help="Write the full JSON report here.")
    ap.add_argument("--tags", default=None, help="Only cases with any of these comma-separated tags.")
    args = ap.parse_args()
    run(args.labels, args.backend, args.out, args.tags)


if __name__ == "__main__":
    main()
