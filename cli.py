"""
Command line interface for docling-pk.

Skeleton only, per this week's scope: commands are wired up and return
placeholder output shaped like the real schema, but do not call any
real extraction logic yet. That gets connected once preprocessor.py,
ocr.py, and the parsers are all merged.
"""

import json
import typer

app = typer.Typer(help="Extract structured data from Pakistani identity and education documents.")


def _placeholder_result(document_type: str) -> dict:
    return {
        "document_type": document_type,
        "fields": {},
        "confidence": 0.0,
        "warnings": ["not implemented yet, this is placeholder output"],
        "raw_text": None,
    }


@app.command()
def cnic(image_path: str = typer.Argument(..., help="Path to a CNIC image file.")):
    """Extract fields from a CNIC image."""
    result = _placeholder_result("cnic")
    typer.echo(json.dumps(result, indent=2))


@app.command()
def matric(image_path: str = typer.Argument(..., help="Path to a Matric certificate image file.")):
    """Extract fields from a Matric certificate image."""
    result = _placeholder_result("matric")
    typer.echo(json.dumps(result, indent=2))


@app.command()
def intermediate(image_path: str = typer.Argument(..., help="Path to an Intermediate certificate image file.")):
    """Extract fields from an Intermediate certificate image."""
    result = _placeholder_result("intermediate")
    typer.echo(json.dumps(result, indent=2))


@app.command()
def degree(image_path: str = typer.Argument(..., help="Path to a Degree/Transcript image file.")):
    """Extract fields from a Degree/Transcript image."""
    result = _placeholder_result("degree")
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()