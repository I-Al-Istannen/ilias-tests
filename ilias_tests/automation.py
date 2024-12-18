from pathlib import Path, PurePath
from typing import Awaitable, Callable, Optional, Any
from dataclasses import asdict

from PFERD.crawl.ilias.kit_ilias_html import IliasElementType
from PFERD.logging import log
from PFERD.utils import fmt_path
from slugify import slugify

from .ilias_action import IliasInteractor
from .ilias_html import ExtendedIliasPage
from .spec import (
    IliasTest,
    TestQuestion,
    filter_with_regex,
    TestTab,
    manual_grading_write_question_md,
    ManualGradingParticipantResults,
    load_manual_grading_results_from_md,
)


async def add_test(interactor: IliasInteractor, folder: ExtendedIliasPage, test: IliasTest, indent: str = ""):
    log.status("[cyan]", "Create", f"{indent}Creating Ilias object")
    test_page = await interactor.create_test(folder, test.title, test.description)
    log.status("[cyan]", "Create", f"{indent}Fetching settings")
    tab_page = await interactor.select_tab(test_page, TestTab.SETTINGS)
    log.status("[cyan]", "Create", f"{indent}Configuring")
    tab_page = await interactor.configure_test(
        tab_page,
        test.title,
        test.description,
        test.intro_text,
        test.starting_time,
        test.ending_time,
        test.number_of_tries,
    )
    # Somehow ILIAS needs this twice to actually fill out the intro text...
    tab_page = await interactor.configure_test(
        tab_page,
        test.title,
        test.description,
        test.intro_text,
        test.starting_time,
        test.ending_time,
        test.number_of_tries,
    )
    log.status("[cyan]", "Create", f"{indent}Configure scoring settings so people see their results")
    tab_page = await interactor.configure_test_scoring(tab_page)
    log.explain_topic("Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, TestTab.QUESTIONS)

    log.explain_topic("Adding questions")
    for index, question in enumerate(test.questions):
        log.status(
            "[bold cyan]", "Create", f"{indent}Adding question {index + 1}", f"[bright_black]({question.title!r})"
        )
        await interactor.add_question(tab_page, question)

    log.explain("Navigating to questions")
    tab_page = await interactor.select_tab(tab_page, TestTab.QUESTIONS)

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
            properties_page = await interactor.select_tab(test_page, TestTab.SETTINGS)

            questions = await slurp_questions_from_test(interactor, test_page, aux_path)

            log.explain_topic("Converting settings page to test")
            tests.append(properties_page.get_test_reconstruct_from_properties(questions))
        else:
            log.explain(f"Skipping child ({child.name!r}) of wrong type {child.type!r}")

    return tests


async def slurp_questions_from_test(
    interactor: IliasInteractor, test_page: ExtendedIliasPage, data_path: Path
) -> list[TestQuestion]:
    question_tab = await interactor.select_tab(test_page, TestTab.QUESTIONS)

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


async def slurp_grading_state_to_md(
    interactor: IliasInteractor, test_page: ExtendedIliasPage, output_dir: Path
) -> None:
    participant_results = await slurp_participant_results(interactor, test_page)
    questions = set([answer.question for res in participant_results for answer in res.answers])
    for question in questions:
        with open(output_dir / f"{question.id}.md", "w") as f:
            f.write(manual_grading_write_question_md(participant_results, question))


async def slurp_participant_results(
    interactor: IliasInteractor, test_page: ExtendedIliasPage
) -> list[ManualGradingParticipantResults]:
    log.explain_topic("Slurping test results")
    log.explain("Navigating to manual grading tab")
    tab_page = await interactor.select_tab(test_page, TestTab.MANUAL_GRADING)

    log.explain("Navigating to manual grading per participant")
    tab_page = await interactor.select_page(tab_page.get_manual_grading_per_participant_url())

    log.explain("Showing all participants")
    page = await interactor.set_manual_grading_filter_show_all(tab_page)

    participant_results = []
    participant_infos = page.get_manual_grading_participant_infos()

    log.status("[bold cyan]", "Slurp", f"Slurping {len(participant_infos)} participants(s)")

    for index, participant in enumerate(participant_infos):
        log.status(
            "[cyan]",
            "Slurp",
            f"  Participant {index + 1:-2}",
            f"[link={participant.detail_link}][bright_black]{participant.format_name()!r}[/link]",
        )
        participant_page = await interactor.select_page(participant.detail_link)
        participant_result = participant_page.get_manual_grading_participant_results(participant)
        for answer in participant_result.answers:
            question = answer.question
            if question.question_type == "file_upload":
                for file in answer.answer:
                    await file.download(interactor)
        participant_results.append(participant_result)
    return participant_results


async def upload_grading_state(
    interactor: IliasInteractor,
    test_page: ExtendedIliasPage,
    input_dir: Path,
    mark_done: bool = False,
    notify_users: bool = False,
) -> None:
    log.explain_topic("Uploading grading results")

    log.status("[bold cyan]", "Grading", f"Parsing saved data from {input_dir}")
    results_by_mail = load_manual_grading_results_from_md(input_dir)

    log.explain("Navigating to manual grading tab")
    tab_page = await interactor.select_tab(test_page, TestTab.MANUAL_GRADING)

    log.explain("Navigating to manual grading per participant")
    tab_page = await interactor.select_page(tab_page.get_manual_grading_per_participant_url())

    log.explain("Showing all participants")
    page = await interactor.set_manual_grading_filter_show_all(tab_page)

    participant_urls = page.get_manual_grading_participant_infos()
    for index, participant in enumerate(participant_urls):
        log.status(
            "[cyan]",
            "Grading",
            f"  Updating participant {index + 1:-2}",
            f"[link={participant.detail_link}][bright_black]{participant.format_name()!r}[/link]",
        )
        page = await interactor.select_page(participant.detail_link)
        await interactor.upload_manual_grading_result(
            page, results_by_mail[participant.email], mark_done=mark_done, notify_users=notify_users
        )


async def ilias_glob_regex(
    interactor: IliasInteractor, root: ExtendedIliasPage, regex: str
) -> list[tuple[PurePath, ExtendedIliasPage]]:
    """
    Returns all elements matching the given hierarchical regex pattern, starting at the given root.
    The pattern must be glob-like, i.e. 'top_level/second_level/third/...'. Each time a directory is entered, the next
    pattern is picked. For example: The pattern 'foo/bar' matches the file 'bar' in folder 'foo'.
    """
    urls_to_page = {}
    for path, page in await _find_matching_elements(interactor, root, PurePath("."), regex):
        urls_to_page[page.url()] = (path, page)

    return list(urls_to_page.values())


async def _find_matching_elements(
    interactor: IliasInteractor, root: ExtendedIliasPage, root_path: PurePath, regex: Optional[str]
) -> list[tuple[PurePath, ExtendedIliasPage]]:
    # foo/*/bar
    # .
    #  `- foo
    #    `- hey
    #      `- bar
    #    `- baz
    #      `- bar
    # try current_regex (foo) against "foo" -> pass
    #   try current_regex (*) against "hey" -> pass
    #     try current_regex (bar) against "bar" -> pass
    #       try None against "bar" -> return bar

    if not regex:
        return [(root_path, root)]

    current_regex, next_glob = _strip_first_path_segment(regex)
    matching = []

    # Filter all before so the log output is nicer
    for child in [child for child in root.get_child_elements() if _matches_regex_part(child.name, regex)]:
        child_page = await interactor.select_page(child.url)
        child_path = root_path / _sanitize_path_name(child.name)
        matching.extend(await _find_matching_elements(interactor, child_page, child_path, next_glob))

    return matching


def _matches_regex_part(to_test: str, glob_regex: str):
    regex_start_segment, _ = _strip_first_path_segment(glob_regex)
    return filter_with_regex(to_test, regex_start_segment)


def _strip_first_path_segment(path_string: str) -> tuple[str, Optional[str]]:
    if "/" in path_string:
        slash_index = path_string.find("/")
        return path_string[:slash_index], path_string[slash_index + 1 :]
    return path_string, None


def _sanitize_path_name(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-").strip()
