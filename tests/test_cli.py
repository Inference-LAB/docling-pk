"""
Tests for the CLI skeleton: command registration, placeholder JSON
shape, and exit code behavior. Real extraction logic is not tested
here since it is not implemented yet, only the CLI's own contract.
"""

import json
import pytest
from typer.testing import CliRunner

from cli import app

runner = CliRunner()

COMMANDS = ["cnic", "matric", "intermediate", "degree"]


@pytest.mark.parametrize("command", COMMANDS)
def test_command_registered(command):
    """Each of the four document commands exists and shows help."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("command", COMMANDS)
def test_valid_path_returns_placeholder_json_and_exits_nonzero(command, tmp_path):
    """
    A valid but unimplemented command returns placeholder JSON
    matching the schema shape, and exits non-zero, since the result
    is not real output and callers should not treat it as success.
    """
    fake_image = tmp_path / "fake.jpg"
    fake_image.write_bytes(b"not a real image, just needs to exist")

    result = runner.invoke(app, [command, str(fake_image)])

    assert result.exit_code == 1
    output = json.loads(result.stdout)
    assert output["document_type"] == command
    assert output["fields"] == {}
    assert output["confidence"] == 0.0
    assert "not implemented" in output["warnings"][0]
    assert output["raw_text"] is None


@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_path_exits_with_error_code(command):
    """A path that does not exist exits with a distinct error code, not the placeholder code."""
    result = runner.invoke(app, [command, "this/path/does/not/exist.jpg"])
    assert result.exit_code == 2
    assert "does not exist" in result.stderr