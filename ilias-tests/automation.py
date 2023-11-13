from pathlib import Path, PurePath
from typing import Awaitable, Callable

from PFERD.crawl.ilias.kit_ilias_html import IliasElementType
from PFERD.logging import log
from PFERD.utils import fmt_path
from slugify import slugify

from .ilias_action import IliasInteractor
from .ilias_html import ExtendedIliasPage
from .spec import IliasTest, TestQuestion


async def add_test(interactor: IliasInteractor, base_folder_url: str, test: IliasTest):
    log.status("[bold cyan]", "Creating", f"Navigating to folder {fmt_path(test.path)}")
    root_page = await interactor.navigate_to_folder(base_folder_url, test.path)

    log.status("[bold cyan]", "Creating", "Ilias object")
    test_page = await interactor.create_test(
        root_page.url(),
        test.title,
        test.description
    )
    log.status("[bold cyan]", "Creating", "Fetching settings")
    tab_page = await interactor.select_tab(test_page, "Einstellungen")
    log.status("[bold cyan]", "Creating", "Configuring")
    tab_page = await interactor.configure_test(
        tab_page,
        test.title,
        test.description,
        test.intro_text,
        test.starting_time,
        test.ending_time,
        test.number_of_tries
    )
    log.status("[bold cyan]", "Creating", "Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, "Fragen")

    log.status("[bold cyan]", "Creating", "Adding questions")
    for index, question in enumerate(test.questions):
        log.status("[bold cyan]", "Creating", f"Adding question {index + 1}")
        await interactor.add_question(tab_page, question)

    log.status("[bold cyan]", "Creating", "Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, "Fragen")

    log.status("[bold cyan]", "Creating", "Reordering questions")
    await interactor.reorder_questions(tab_page, [q.title for q in test.questions])


async def slurp_tests_from_folder(interactor: IliasInteractor, folder_url: str) -> list[IliasTest]:
    log.status("[bold cyan]", "Slurping", "Crawling folder")
    page = await interactor.select_page(folder_url)
    tests = []

    for child in page.get_child_elements():
        if child.type == IliasElementType.TEST:
            log.status("[bold cyan]", "Slurping", f"Slurping {child.name!r}")
            test_page = await interactor.select_page(child.url)
            properties_page = await interactor.select_tab(test_page, "Einstellungen")

            questions = await slurp_questions_from_test(interactor, test_page, Path("aux"))

            tests.append(properties_page.get_test_reconstruct_from_properties(PurePath("."), questions))
        else:
            log.explain(f"Skipping child ({child.name!r}) of wrong type {child.type!r}")

    return tests


async def slurp_questions_from_test(
    interactor: IliasInteractor, test_page: ExtendedIliasPage, data_path: Path
) -> list[TestQuestion]:
    question_tab = await interactor.select_tab(test_page, "Fragen")

    elements = question_tab.get_test_question_listing()
    questions: list[TestQuestion] = []
    for title, url in elements:
        log.status("[bold bright_black]", "Slurping", "", f"[bright_black]({title!r})")
        question_page = await interactor.select_page(url)
        page_design = await question_page.get_test_question_design_blocks(
            downloader=_download_files(interactor, title, data_path)
        )
        edit_page = await interactor.select_page(question_page.get_test_question_edit_url())
        questions.append(edit_page.get_test_question_reconstruct_from_edit(page_design))

    return questions


def _download_files(interactor: IliasInteractor, title: str, aux_path: Path) -> Callable[[str], Awaitable[Path]]:
    counter = 0

    async def inner(url: str) -> Path:
        nonlocal counter
        path = await interactor.download_file(url, aux_path, slugify(f"{title}-{counter}") + "-")
        counter += 1
        return path

    return inner
