import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def run_cli(tmp_path: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ilias_tests",
            "--no-keyring",
            "--user",
            "unused",
            "--password",
            "unused",
            "--cookies",
            str(tmp_path / "cookies"),
            *map(str, args),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
    )


@pytest.mark.parametrize("failure", ["missing", "invalid-yaml", "unsupported-question"])
def test_create_failure_exits_nonzero(tmp_path: Path, failure: str) -> None:
    spec = tmp_path / "spec.yml"
    if failure == "invalid-yaml":
        spec.write_text("tests: [unterminated")
    elif failure == "unsupported-question":
        data = yaml.safe_load((Path(__file__).parent / "e2e/fixtures/spec.yml").read_text())
        data["questions"]["essay"]["type"] = "unsupported"
        spec.write_text(yaml.safe_dump(data))
    # Spec loading fails before any request. A local unused port also avoids external services.
    result = run_cli(tmp_path, "create", spec, "http://localhost:1/")
    assert result.returncode == 1, result.stdout + result.stderr
    if failure == "missing":
        assert "does not exist" in result.stdout
    elif failure == "unsupported-question":
        assert "Unknown question type" in result.stdout
    else:
        assert "unexpected exception" in result.stdout


def test_warning_exits_successfully(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "configure", "http://localhost:1/")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Nothing to do" in result.stdout
