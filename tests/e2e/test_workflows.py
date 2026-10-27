from pathlib import Path

import pytest

from ilias_tests.spec import load_spec_from_file

from .conftest import RunCLI
from .stack import Ilias


def url(ilias: Ilias, ref_id: int, kind: str = "fold") -> str:
    return f"{ilias.base_url}/goto.php?target={kind}_{ref_id}"


def test_slurp_seeded_test(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    output = tmp_path / "export"
    run_cli("slurp", url(ilias, workspace["source"]), output)

    tests = load_spec_from_file(output / "spec.yml").tests
    assert len(tests) == 1
    test = tests[0]
    assert test.title == "Seeded Test"
    assert test.description == "A fixture created independently of the CLI"
    assert len(test.questions) == 1
    question = test.questions[0].serialize()
    assert question["type"] == "freeform_text"
    assert question["title"] == "Explain"
    assert question["author"] == "E2E Author"
    assert question["points"] == 4.0
    assert "Explain your answer." in question["question_html"]


def test_slurp_empty_folder(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    output = tmp_path / "nested" / "export"
    run_cli("slurp", url(ilias, workspace["target"]), output)
    assert load_spec_from_file(output / "spec.yml").tests == []


def test_create_and_export(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    spec = Path(__file__).parent / "fixtures" / "spec.yml"
    run_cli("create", spec, url(ilias, workspace["course"], "crs"), "--replicate", "Target", "--tests", "Practice")

    assert ilias.run_php("inspect.php", str(workspace["target"])) == [
        {"title": "Practice", "online": False, "questions": 4}
    ]
    assert ilias.run_php("inspect.php", str(workspace["other"])) == []
    output = tmp_path / "export"
    run_cli("slurp", url(ilias, workspace["target"]), output)
    original = load_spec_from_file(spec).tests[0]
    exported = load_spec_from_file(output / "spec.yml").tests
    assert len(exported) == 1
    assert exported[0].title == original.title
    assert exported[0].description == original.description
    assert exported[0].number_of_tries == original.number_of_tries
    assert [q.serialize() for q in exported[0].questions] == [q.serialize() for q in original.questions]


@pytest.mark.parametrize("replicate", [False, True], ids=["direct", "folder"])
def test_publish_and_unpublish(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, replicate: bool) -> None:
    target = url(ilias, workspace["source"]) if replicate else url(ilias, workspace["test"], "tst")
    options = ["--replicate", "Seeded Test"] if replicate else []
    for option, online in [("--unpublish", False), ("--publish", True)]:
        run_cli("configure", target, option, *options)
        assert ilias.run_php("inspect.php", str(workspace["source"])) == [
            {"title": "Seeded Test", "online": online, "questions": 1}
        ]
