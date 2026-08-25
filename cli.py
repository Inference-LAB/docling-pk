"""
Command line interface for docling-pk.

Real extraction is not wired in yet. Every command validates that the
given image path actually exists, then returns a placeholder result
with a non-zero exit code, so callers (and CI) can tell "not
implemented" apart from "succeeded", rather than a silent success on
input that was never read.
"""

import json
import sys
from pathlib import Path
import typer

app = typer.Typer(help="Extract structured data from Pakistani identity and education documents.")

NOT_IMPLEMENTED_EXIT_CODE = 1


def _placeholder_result(document_type: str) -> dict:
    return {
        "document_type": document_type,
        "fields": {},
        "confidence": 0.0,
        "warnings": ["not implemented yet, this is placeholder output"],
        "raw_text": None,
    }


def _run_placeholder(document_type: str, image_path: str) -> None:
    path = Path(image_path)
    if not path.exists():
        typer.echo(f"Error: image path does not exist: {image_path}", err=True)
        raise typer.Exit(code=2)

    result = _placeholder_result(document_type)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)


@app.command()
def cnic(image_path: str = typer.Argument(..., help="Path to a CNIC image file.")):
    """Extract fields from a CNIC image. Not implemented yet, exits non-zero."""
    _run_placeholder("cnic", image_path)


@app.command()
def matric(image_path: str = typer.Argument(..., help="Path to a Matric certificate image file.")):
    """Extract fields from a Matric certificate image. Not implemented yet, exits non-zero."""
    _run_placeholder("matric", image_path)


@app.command()
def intermediate(image_path: str = typer.Argument(..., help="Path to an Intermediate certificate image file.")):
    """Extract fields from an Intermediate certificate image. Not implemented yet, exits non-zero."""
    _run_placeholder("intermediate", image_path)


@app.command()
def degree(image_path: str = typer.Argument(..., help="Path to a Degree/Transcript image file.")):
    """Extract fields from a Degree/Transcript image. Not implemented yet, exits non-zero."""
    _run_placeholder("degree", image_path)


if __name__ == "__main__":
    app()