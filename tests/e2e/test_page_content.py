from pathlib import Path

from bs4 import BeautifulSoup, Comment

from ilias_tests.spec import (
    PageDesignBlockCode,
    PageDesignBlockImage,
    PageDesignBlockText,
    dump_tests_to_yml,
    load_spec_from_file,
)

from .conftest import RunCLI
from .stack import Ilias
from .test_workflows import url


def test_page_content_round_trip(ilias: Ilias, workspace: dict[str, int], run_cli: RunCLI, tmp_path: Path) -> None:
    fixtures = Path(__file__).parent / "fixtures"
    original = load_spec_from_file(fixtures / "page_content.yml").tests[0]
    image = original.questions[0].page_design[2]
    assert isinstance(image, PageDesignBlockImage)
    image.image = fixtures / "diagram.png"
    spec = tmp_path / "input.yml"
    spec.write_text(dump_tests_to_yml([original]))
    run_cli("create", spec, url(ilias, workspace["target"]), "--replicate", "")
    output = tmp_path / "export"
    run_cli("slurp", url(ilias, workspace["target"]), output)
    exported = load_spec_from_file(output / "spec.yml").tests
    assert len(exported) == 1
    test = exported[0]
    assert test.description == original.description
    intro = BeautifulSoup(test.intro_text, "html.parser")
    assert intro.h1 is not None
    assert intro.h1.get_text() == "Before you begin"
    assert intro.get_text(" ", strip=True) == "Before you begin Read these instructions & explain why ."
    assert len(test.questions) == 1
    question = test.questions[0]
    assert question.question_html == original.questions[0].question_html
    blocks = question.page_design
    assert [type(block) for block in blocks] == [
        PageDesignBlockText,
        PageDesignBlockCode,
        PageDesignBlockImage,
        PageDesignBlockText,
    ]
    text, code, downloaded_image, trailing_text = blocks
    assert isinstance(text, PageDesignBlockText)
    markup = BeautifulSoup(text.text_html, "html.parser")
    assert markup.get_text() == "Read carefully and explain x < 3."
    assert markup.select_one("span.ilc_text_inline_Strong") is not None
    assert markup.select_one("span.ilc_text_inline_Emph") is not None
    assert not markup.select("strong, em, code[class]")
    assert not markup.find_all(string=lambda value: isinstance(value, Comment))
    assert isinstance(code, PageDesignBlockCode)
    assert code.serialize() == original.questions[0].page_design[1].serialize()
    assert isinstance(downloaded_image, PageDesignBlockImage)
    assert downloaded_image.image.parent == output
    assert downloaded_image.image.suffix == ".png"
    assert downloaded_image.image.read_bytes() == image.image.read_bytes()
    assert isinstance(trailing_text, PageDesignBlockText)
    assert trailing_text.text_html == "This paragraph belongs after the image."

    # Publishing must preserve the introduction's enabled state and its content.
    run_cli("configure", url(ilias, workspace["target"]), "--replicate", "Page content", "--publish")
    published = tmp_path / "published"
    run_cli("slurp", url(ilias, workspace["target"]), published)
    assert load_spec_from_file(published / "spec.yml").tests[0].intro_text == test.intro_text

    # The exported spec and downloaded assets must also be usable for a new import.
    run_cli("create", output / "spec.yml", url(ilias, workspace["other"]), "--replicate", "")
    second_output = tmp_path / "reexport"
    run_cli("slurp", url(ilias, workspace["other"]), second_output)
    second = load_spec_from_file(second_output / "spec.yml").tests[0]
    assert second.intro_text == test.intro_text
    assert second.description == test.description
    expected = question.serialize()
    actual = second.questions[0].serialize()
    second_image = second.questions[0].page_design[2]
    assert isinstance(second_image, PageDesignBlockImage)
    assert second_image.image.read_bytes() == image.image.read_bytes()
    expected["page_design"][2].pop("path")
    actual["page_design"][2].pop("path")
    assert actual == expected
