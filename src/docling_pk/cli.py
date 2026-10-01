"""
Command line interface.

    docling-pk extract cnic_front.jpg cnic_back.jpg --type cnic
    docling-pk extract certificate.jpg --type auto --output table
    docling-pk batch ./scans --type matric --out results.jsonl
    docling-pk info

Exit codes: 0 success, 1 the document was processed but no field could be
extracted, 2 bad input (missing file, unreadable image, unknown type).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

import typer

from docling_pk import __version__

app = typer.Typer(
    help="Extract structured data from Pakistani identity and education documents.",
    no_args_is_help=True,
    add_completion=False,
)

EXIT_NO_FIELDS = 1
EXIT_BAD_INPUT = 2

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"docling-pk {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """docling-pk command line."""


def _print_table(result) -> None:
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    console = Console()
    table = Table(title=f"{result.document_type}  (confidence {result.confidence:.2f})")
    table.add_column("field")
    table.add_column("value")
    table.add_column("conf", justify="right")
    table.add_column("status")
    colors = {"ok": "green", "low_confidence": "yellow", "not_applicable": "dim"}
    for name, f in result.fields.items():
        c = colors.get(f.status.value, "red")
        table.add_row(
            name, "" if f.value is None else escape(f.value), f"{f.confidence:.2f}", f"[{c}]{f.status.value}[/{c}]"
        )
    console.print(table)
    rows = result.tables.get("subjects")
    if rows:
        sub = Table(title="subjects")
        for col in ("subject", "max_marks", "obtained_marks"):
            sub.add_column(col)
        for r in rows:
            sub.add_row(escape(str(r["subject"])), str(r["max_marks"]), str(r["obtained_marks"]))
        console.print(sub)
    for w in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {escape(w)}")


def _run(paths: List[Path], document_type: str, backend: str, urdu: bool, cpu: bool, raw: bool, verify: bool = True):
    from docling_pk import extract
    from docling_pk.errors import DoclingPKError

    try:
        return extract(
            [str(p) for p in paths] if len(paths) > 1 else str(paths[0]),
            document_type=document_type,
            backend=backend,
            urdu=urdu,
            verify=verify,
            gpu=False if cpu else None,
            include_raw_text=raw,
        )
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=EXIT_BAD_INPUT) from exc
    except (DoclingPKError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=EXIT_BAD_INPUT) from exc


@app.command()
def extract(
    images: List[Path] = typer.Argument(
        ..., help="Image or PDF file(s). For a CNIC, pass the front and back together."
    ),
    document_type: str = typer.Option("auto", "--type", "-t", help="cnic, matric, intermediate, degree or auto."),
    output: str = typer.Option("json", "--output", "-o", help="json or table."),
    out_file: Optional[Path] = typer.Option(None, "--out", help="Write JSON to this file instead of stdout."),
    backend: str = typer.Option("auto", "--backend", "-b", help="OCR engine: auto, rapidocr or easyocr."),
    urdu: bool = typer.Option(
        True, "--urdu/--no-urdu", help="Read the Urdu address on CNIC backs (needs the urdu extra)."
    ),
    verify: bool = typer.Option(
        True, "--verify/--no-verify", help="Cross-check key fields with a second OCR engine if installed."
    ),
    cpu: bool = typer.Option(False, "--cpu", help="Do not use a GPU even if one is available."),
    raw: bool = typer.Option(False, "--raw", help="Include raw OCR text in the JSON output."),
) -> None:
    """Extract fields from one document (one or more images of it)."""
    if output not in ("json", "table"):
        typer.echo("Error: --output must be 'json' or 'table'", err=True)
        raise typer.Exit(code=EXIT_BAD_INPUT)
    result = _run(images, document_type, backend, urdu, cpu, raw, verify)
    if output == "table" and out_file is None:
        _print_table(result)
    else:
        text = result.to_json(include_raw=raw)
        if out_file:
            out_file.write_text(text, encoding="utf-8")
            typer.echo(f"Wrote {out_file}", err=True)
        else:
            sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
            sys.stdout.flush()
    if not any(f.value is not None for f in result.fields.values()):
        raise typer.Exit(code=EXIT_NO_FIELDS)


@app.command()
def batch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of images/PDFs."),
    document_type: str = typer.Option("auto", "--type", "-t", help="cnic, matric, intermediate, degree or auto."),
    out_file: Path = typer.Option(Path("docling_pk_results.jsonl"), "--out", help="JSON Lines output file."),
    backend: str = typer.Option("auto", "--backend", "-b", help="OCR engine: auto, rapidocr or easyocr."),
    urdu: bool = typer.Option(True, "--urdu/--no-urdu"),
    cpu: bool = typer.Option(False, "--cpu"),
) -> None:
    """Extract every document in a folder (one file per document) to JSON Lines."""
    from docling_pk import extract as run_extract

    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not files:
        typer.echo(f"Error: no images found in {folder}", err=True)
        raise typer.Exit(code=EXIT_BAD_INPUT)
    ok = 0
    with out_file.open("w", encoding="utf-8") as fh:
        for i, path in enumerate(files, 1):
            try:
                result = run_extract(
                    str(path),
                    document_type=document_type,
                    backend=backend,
                    urdu=urdu,
                    gpu=False if cpu else None,
                    include_raw_text=False,
                )
                record = {"file": path.name, **result.to_dict()}
                ok += 1
            except Exception as exc:  # keep going: one bad file must not stop a batch
                record = {"file": path.name, "error": f"{type(exc).__name__}: {exc}"}
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            typer.echo(f"[{i}/{len(files)}] {path.name}", err=True)
    typer.echo(f"Processed {ok}/{len(files)} files -> {out_file}", err=True)


@app.command()
def info() -> None:
    """Show version, installed OCR backends and GPU availability."""
    import importlib.util

    typer.echo(f"docling-pk {__version__}")
    typer.echo(f"python     {sys.version.split()[0]}")
    for mod in ("easyocr", "rapidocr", "fitz"):
        label = {"fitz": "pymupdf (pdf)"}.get(mod, mod)
        typer.echo(f"{label:<14} {'installed' if importlib.util.find_spec(mod) else 'not installed'}")
    try:
        import torch

        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none (CPU mode)"
    except Exception:
        gpu = "not used (PyTorch not installed; RapidOCR runs on CPU)"
    typer.echo(f"gpu            {gpu}")


if __name__ == "__main__":  # pragma: no cover
    app()
