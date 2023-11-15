from pathlib import Path, PurePath
from typing import Awaitable, Callable, Optional

from PFERD.crawl.ilias.kit_ilias_html import IliasElementType
from PFERD.logging import log
from PFERD.utils import fmt_path
from slugify import slugify

from .ilias_action import IliasInteractor
from .ilias_html import ExtendedIliasPage
from .spec import IliasTest, TestQuestion, filter_with_glob


async def add_test(interactor: IliasInteractor, folder: ExtendedIliasPage, test: IliasTest, indent: str = ""):
    log.status("[cyan]", "Create", f"{indent}Creating Ilias object")
    test_page = await interactor.create_test(
        folder,
        test.title,
        test.description
    )
    log.status("[cyan]", "Create", f"{indent}Fetching settings")
    tab_page = await interactor.select_tab(test_page, "Einstellungen")
    log.status("[cyan]", "Create", f"{indent}Configuring")
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
        log.status("[bold cyan]", "Create", f"{indent}Adding question {index + 1}", f"[bright_black]({question.title!r})")
        await interactor.add_question(tab_page, question)

    log.explain("Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, "Fragen")

    log.status("[cyan]", "Create", f"{indent}Reordering questions")
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
            tests.append(properties_page.get_test_reconstruct_from_properties(questions))
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


async def ilias_glob(
    interactor: IliasInteractor, root: ExtendedIliasPage, glob: str
) -> list[tuple[PurePath, ExtendedIliasPage]]:
    """Returns all elements matching the given glob pattern, starting at the given root."""
    urls_to_page = {}
    for path, page in await _find_matching_elements(interactor, root, PurePath("."), glob):
        urls_to_page[page.url()] = (path, page)

    return list(urls_to_page.values())


async def _find_matching_elements(
    interactor: IliasInteractor, root: ExtendedIliasPage, root_path: PurePath, glob: Optional[str]
) -> list[tuple[PurePath, ExtendedIliasPage]]:
    # foo/*/bar
    # .
    #  `- foo
    #    `- hey
    #      `- bar
    #    `- baz
    #      `- bar
    # try current_glob (foo) against "foo" -> pass
    #   try current_glob (*) against "hey" -> pass
    #     try current_glob (bar) against "bar" -> pass
    #       try None against "bar" -> return bar

    if not glob:
        return [(root_path, root)]

    current_glob, next_glob = _strip_first_path_segment(glob)
    matching = []

    # Filter all before so the log output is nicer
    for child in [child for child in root.get_child_elements() if _matches_glob_part(child.name, glob)]:
        child_page = await interactor.select_page(child.url)
        child_path = root_path / _sanitize_path_name(child.name)
        matching.extend(await _find_matching_elements(interactor, child_page, child_path, next_glob))

    return matching


def _matches_glob_part(to_test: str, glob: str):
    glob_start_segment, _ = _strip_first_path_segment(glob)
    return filter_with_glob(to_test, glob_start_segment)


def _strip_first_path_segment(path_string: str) -> tuple[str, Optional[str]]:
    if "/" in path_string:
        slash_index = path_string.find("/")
        return path_string[:slash_index], path_string[slash_index + 1:]
    return path_string, None


def _sanitize_path_name(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-").strip()
