import datetime
from pathlib import Path

import pytest

from ilias_tests.spec import dump_tests_to_yml, load_spec_from_file

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


def test_slurp_test_with_participants(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    # ILIAS refuses to show the question settings once a test has participant data. Its alert explains why.
    ilias.run_php("participant.php", str(workspace["test"]), "finished")
    log = run_cli("slurp", url(ilias, workspace["source"]), tmp_path / "export", expected_exit_code=1)
    assert "Der Test enthält bereits Teilnehmerdatensätze" in " ".join(log.split())


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
    assert exported[0].intro_text == original.intro_text
    assert exported[0].number_of_tries == original.number_of_tries
    assert [q.serialize() for q in exported[0].questions] == [q.serialize() for q in original.questions]


@pytest.mark.parametrize("replicate", [False, True], ids=["direct", "folder"])
def test_publish_and_unpublish(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, replicate: bool) -> None:
    target = url(ilias, workspace["source"]) if replicate else url(ilias, workspace["test"], "tst")
    options = ["--replicate", "Seeded Test"] if replicate else []
    # The seeded test was not created by the CLI, so its settings differ from the CLI's defaults
    settings = ilias.run_php("inspect_settings.php", str(workspace["test"]))
    for option, online in [("--unpublish", False), ("--publish", True)]:
        run_cli("configure", target, option, *options)
        assert ilias.run_php("inspect.php", str(workspace["source"])) == [
            {"title": "Seeded Test", "online": online, "questions": 1}
        ]
        assert ilias.run_php("inspect_settings.php", str(workspace["test"])) == {**settings, "online": online}


def test_fix_result_viewing(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI) -> None:
    before = ilias.run_php("scoring.php", str(workspace["test"]), "reset")
    assert before == {key: 0 if key == "reporting" else False for key in before}
    run_cli("configure", url(ilias, workspace["test"], "tst"), "--fix-result-viewing")
    after = ilias.run_php("scoring.php", str(workspace["test"]))
    assert after == {
        "reporting": 1,
        "grade": True,
        "passed": True,
        "details": True,
        "printview": True,
        "feedback": True,
        "hide_page_contents": False,
        "suggested_content": False,
        "best_solution": True,
    }


def test_dates_and_online_switch(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    test = load_spec_from_file(Path(__file__).parent / "fixtures" / "spec.yml").tests[0]
    test.title = "Dated"
    test.questions = test.questions[:1]
    test.starting_time = datetime.datetime(2030, 1, 2, 8, 15)
    test.ending_time = datetime.datetime(2030, 7, 9, 23, 45)
    spec = tmp_path / "dated.yml"
    spec.write_text(dump_tests_to_yml([test]))
    run_cli("create", spec, url(ilias, workspace["target"]), "--replicate", "")

    def check(online: bool) -> None:
        # The times are local (German) time, i.e. CET in January and CEST in July
        assert ilias.run_php("inspect_dates.php", str(workspace["target"])) == [
            {
                "title": "Dated",
                "online": online,
                "start_enabled": True,
                "start": "2030-01-02 07:15",
                "end_enabled": True,
                "end": "2030-07-09 21:45",
                "availability": False,
            }
        ]
        output = tmp_path / f"export-{online}"
        run_cli("slurp", url(ilias, workspace["target"]), output)
        exported = load_spec_from_file(output / "spec.yml").tests
        assert [(t.starting_time, t.ending_time) for t in exported] == [(test.starting_time, test.ending_time)]

    check(False)
    for option, online in [("--publish", True), ("--unpublish", False)]:
        run_cli("configure", url(ilias, workspace["target"]), "--replicate", "Dated", option)
        check(online)


def test_configure_keeps_settings(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    test = load_spec_from_file(Path(__file__).parent / "fixtures" / "page_content.yml").tests[0]
    test.title = "Configured"
    test.number_of_tries = 3
    test.starting_time = datetime.datetime(2030, 1, 2, 8, 15)
    test.ending_time = datetime.datetime(2030, 7, 9, 23, 45)
    # Only the settings matter here, the page content has its own round trip test
    test.questions[0].page_design = []
    spec = tmp_path / "configured.yml"
    spec.write_text(dump_tests_to_yml([test]))
    run_cli("create", spec, url(ilias, workspace["target"]), "--replicate", "")
    [ref] = ilias.run_php("children.php", str(workspace["target"]))

    created = ilias.run_php("inspect_settings.php", str(ref))
    assert created == {
        "title": "Configured",
        "description": "This description is not the introduction.",
        "online": False,
        "availability": False,
        "question_set_type": "FIXED_QUEST_SET",
        "anonymity": False,
        "intro_enabled": True,
        "intro_text": "Before you begin Read these instructions &amp; explain why .",
        "start": "2030-01-02 07:15",
        "end": "2030-07-09 21:45",
        "number_of_tries": 3,
        "title_output": 0,
        "lock_answer_on_feedback": False,
        "lock_answer_on_next": False,
        "autosave": False,
        "use_previous_answers": True,
        "suspend": True,
        "postponed_to_end": False,
        "question_list": True,
        "pass_overview": True,
        "pass_overview_at_end": True,
        "pass_overview_descriptions": True,
        "question_marking": False,
        "answer_overview": True,
    }
    for option, online in [("--publish", True), ("--unpublish", False), ("--fix-result-viewing", False)]:
        run_cli("configure", url(ilias, ref, "tst"), option)
        assert ilias.run_php("inspect_settings.php", str(ref)) == {**created, "online": online}, option
