import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import RunCLI
from .stack import Ilias
from .test_workflows import url


@pytest.fixture
def finished_participant(ilias: Ilias, workspace: dict[str, int]) -> dict[str, Any]:
    return ilias.run_php("participant.php", str(workspace["test"]), "finished")


def test_results(
    ilias: Ilias, workspace: dict[str, int], finished_participant: dict[str, Any], run_cli: RunCLI, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "results.json"
    run_cli("results", url(ilias, workspace["test"], "tst"), output)
    results = json.loads(output.read_text())
    assert list(results) == ["test"]
    assert len(results["test"]) == 1
    participant = results["test"][0]
    assert participant["participant"]["email"] == finished_participant["email"]
    assert participant["participant"]["username"] == finished_participant["login"].split("@")[0]
    assert len(participant["answers"]) == 1
    answer = participant["answers"][0]
    assert answer["question"]["id"] == str(finished_participant["question_id"])
    assert answer["question"]["max_points"] == 4.0
    assert answer["question"]["question_type"] == "freeform_text"
    assert "My independently seeded answer." in answer["answer"]
    assert answer["points"] == 1.5
    assert answer["final_feedback"] is False


def test_grading_round_trip(
    ilias: Ilias, workspace: dict[str, int], finished_participant: dict[str, Any], run_cli: RunCLI, tmp_path: Path
) -> None:
    target = url(ilias, workspace["test"], "tst")
    active_id = str(finished_participant["active_id"])
    before = ilias.run_php("inspect_participant.php", active_id)
    assert before["points"] == 1.5
    assert before["grading_done"] is False
    storage = tmp_path / "grading"
    run_cli("grading", target, storage, "--download-state")
    markdown = storage / f"{finished_participant['question_id']}.md"
    assert list(storage.glob("*.md")) == [markdown]
    content = markdown.read_text()
    assert finished_participant["email"] in content
    assert "My independently seeded answer." in content
    assert "### Answer 1.5 / 4.0" in content
    markdown.write_text(content.replace("### Answer 1.5 / 4.0", "### Answer 3.5 / 4.0") + "Well **explained**.\n")
    run_cli("grading", target, storage, "--upload-state", "--mark-done")

    after = ilias.run_php("inspect_participant.php", active_id)
    assert after["question_points"] == 3.5
    assert after["points"] == 3.5
    assert after["grading_done"] is True
    downloaded = tmp_path / "graded"
    run_cli("grading", target, downloaded, "--download-state")
    updated = (downloaded / markdown.name).read_text()
    assert "### Answer 3.5 / 4.0" in updated
    assert "Well **explained**." in updated


def test_end_open_pass(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI) -> None:
    participants = [ilias.run_php("participant.php", str(workspace["test"]), "open") for _ in range(2)]
    finished = ilias.run_php("participant.php", str(workspace["test"]), "finished")
    finished_before = ilias.run_php("inspect_participant.php", str(finished["active_id"]))
    for participant in participants:
        before = ilias.run_php("inspect_participant.php", str(participant["active_id"]))
        assert before["submitted"] is False
        assert before["last_finished_pass"] is None
        assert before["points"] == 1.5
    run_cli("passes", url(ilias, workspace["test"], "tst"), "--end-passes")
    for participant in participants:
        after = ilias.run_php("inspect_participant.php", str(participant["active_id"]))
        assert after["submitted"] is True
        assert after["last_finished_pass"] == 0
        assert after["finalized_by"] == "finished_by_administrator"
        assert after["points"] == after["question_points"] == 1.5
    assert ilias.run_php("inspect_participant.php", str(finished["active_id"])) == finished_before
    log = run_cli("passes", url(ilias, workspace["test"], "tst"), "--end-passes")
    assert "No active test passes to end" in log
