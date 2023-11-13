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
    log.status("[cyan]", "Create", f"Navigating to folder {fmt_path(test.path)}")
    root_page = await interactor.navigate_to_folder(base_folder_url, test.path)

    log.status("[cyan]", "Create", "Creating Ilias object")
    test_page = await interactor.create_test(
        root_page.url(),
        test.title,
        test.description
    )
    log.status("[cyan]", "Create", "Fetching settings")
    tab_page = await interactor.select_tab(test_page, "Einstellungen")
    log.status("[cyan]", "Create", "Configuring")
    tab_page = await interactor.configure_test(
        tab_page,
        test.title,
        test.description,
        test.intro_text,
        test.starting_time,
        test.ending_time,
        test.number_of_tries
    )
    log.explain_topic("Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, "Fragen")

    log.explain_topic("Adding questions")
    for index, question in enumerate(test.questions):
        log.status("[bold cyan]", "Create", f"Adding question {index + 1}", f"[bright_black]({question.title!r})")
        await interactor.add_question(tab_page, question)

    log.explain("Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, "Fragen")

    log.status("[cyan]", "Create", "Reordering questions")
    await interactor.reorder_questions(tab_page, [q.title for q in test.questions])


async def slurp_tests_from_folder(interactor: IliasInteractor, folder_url: str, aux_path: Path) -> list[IliasTest]:
    log.status("[cyan]", "Slurp", "Crawling folder")
    page = await interactor.select_page(folder_url)

    tests = []
    for child in page.get_child_elements():
        if child.type == IliasElementType.TEST:
            log.explain(f"Child {child.name!r} is a test, slurping")
            log.status("[bold cyan]", "Slurp", f"Test: {child.name!r}")
            test_page = await interactor.select_page(child.url)
            properties_page = await interactor.select_tab(test_page, "Einstellungen")

            questions = await slurp_questions_from_test(interactor, test_page, aux_path)

            log.explain_topic("Converting settings page to test")
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
        log.status("[cyan]", "Slurp", "Question ", f"[bright_black]{title!r}")
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
        log.explain_topic(f"Downloading file from {url} to folder {fmt_path(aux_path)}")
        log.explain(f"Current counter: {counter}")

        path = await interactor.download_file(url, aux_path, slugify(f"{title}-{counter}") + "-")

        log.explain(f"Downloaded to {fmt_path(path)}")
        counter += 1
        return path

    return inner
