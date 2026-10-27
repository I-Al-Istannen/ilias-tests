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


def test_answer_types(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    seeded = ilias.run_php("answer_types.php", str(workspace["course"]))
    participant = ilias.run_php("participant.php", str(seeded["test"]), "finished")
    active_id = str(participant["active_id"])
    target = url(ilias, seeded["test"], "tst")
    output = tmp_path / "results.json"
    run_cli("results", target, output)
    answers = {answer["question"]["id"]: answer for answer in json.loads(output.read_text())["test"][0]["answers"]}
    single, multiple, upload = (answers[str(seeded[key])] for key in ("single", "multiple", "upload"))
    assert single["question"]["question_type"] == "single_choice"
    assert single["answer"] == "<ul><li>No</li></ul>"
    assert single["points"] == 2.0
    assert multiple["question"]["question_type"] == "multiple_choice"
    assert multiple["answer"] == "<ul><li>First</li><li>Second</li></ul>"
    assert multiple["points"] == 1.0
    assert upload["question"]["question_type"] == "file_upload"
    assert [(file["file_name"], file["file_content"]) for file in upload["answer"]] == [
        ("solution.c", "int main(void) {\n    return 0;\n}\n")
    ]
    assert upload["points"] == 0.5

    storage = tmp_path / "grading"
    run_cli("grading", target, storage, "--download-state")
    assert "* No" in (storage / f"{seeded['single']}.md").read_text()
    content = (storage / f"{seeded['multiple']}.md").read_text()
    assert "* First\n* Second" in content
    assert "Third" not in content
    assert "file_upload" in (storage / f"{seeded['upload']}.md").read_text()

    grades = {"single": ("2.0", "1.0"), "multiple": ("1.0", "2.0"), "upload": ("0.5", "2.5")}
    for key, (old, new) in grades.items():
        markdown = storage / f"{seeded[key]}.md"
        content = markdown.read_text()
        maximum = content.split(f"### Answer {old} / ")[1].split("\n")[0]
        markdown.write_text(
            content.replace(f"### Answer {old} / {maximum}", f"### Answer {new} / {maximum}")
            + f"Feedback for **{key}**.\n"
        )
    expected = {
        str(seeded[key]): {
            "points": float(new),
            "feedback": f"<p>Feedback for <strong>{key}</strong>.</p>\n",
            "final": False,
        }
        for key, (_, new) in grades.items()
    }

    run_cli("grading", target, storage, "--upload-state")
    after = ilias.run_php("inspect_participant.php", active_id)
    assert after["questions"] == expected
    assert after["points"] == 5.5
    assert after["grading_done"] is False
    assert after["mails"] == []

    run_cli("grading", target, storage, "--upload-state", "--mark-done", "--notify-users")
    done = ilias.run_php("inspect_participant.php", active_id)
    assert done["questions"] == expected
    assert done["grading_done"] is True
    # The notification is an internal ILIAS mail, so it does not leave the instance
    assert done["mails"] == ["Manuelle Bewertung für Test „Answer Types“ erfolgt"]


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


def test_replicate_results_and_passes(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    seeded = ilias.run_php("answer_types.php", str(workspace["course"]))
    tests = {"Source/Seeded Test": workspace["test"], "Answer Types/Answer Types": seeded["test"]}
    participants = {path: ilias.run_php("participant.php", str(ref), "open") for path, ref in tests.items()}
    course = url(ilias, workspace["course"], "crs")
    selector = "(Source|Answer Types)/.*"

    run_cli("passes", course, "--replicate", selector, "--end-passes")
    for participant in participants.values():
        assert ilias.run_php("inspect_participant.php", str(participant["active_id"]))["submitted"] is True

    output = tmp_path / "results.json"
    run_cli("results", course, output, "--replicate", selector)
    results = json.loads(output.read_text())
    assert sorted(results) == sorted(tests)
    for path, participant in participants.items():
        assert [result["participant"]["email"] for result in results[path]] == [participant["email"]]
