from PFERD.crawl.ilias.kit_ilias_html import IliasElementType
from PFERD.logging import log
from PFERD.utils import fmt_path

from .ilias_action import IliasInteractor
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
        test.numer_of_tries
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


async def slurp_questions_from_folder(interactor: IliasInteractor, folder_url: str) -> list[TestQuestion]:
    log.status("[bold cyan]", "Slurping", "Crawling folder")
    questions = []
    page = await interactor.select_page(folder_url)

    for child in page.get_child_elements():
        if child.type == IliasElementType.TEST:
            log.status("[bold cyan]", "Slurping", f"Slurping {child.name!r}")
            questions.extend(await slurp_questions_from_test(interactor, child.url))
        else:
            log.explain(f"Skipping child ({child.name!r}) of wrong type {child.type!r}")

    return questions


async def slurp_questions_from_test(interactor: IliasInteractor, test_url: str) -> list[TestQuestion]:
    page = await interactor.select_page(test_url)
    question_tab = await interactor.select_tab(page, "Fragen")

    elements = question_tab.get_test_question_listing()
    questions: list[TestQuestion] = []
    for title, url in elements:
        log.status("[bold bright_black]", "Slurping", "", f"[bright_black]({title!r})")
        question_page = await interactor.select_edit_question(url)
        questions.append(question_page.get_test_question_reconstruct_from_edit())

    return questions
