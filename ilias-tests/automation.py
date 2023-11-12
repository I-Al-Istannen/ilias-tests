from PFERD.logging import log
from PFERD.utils import fmt_path

from .ilias_action import IliasInteractor
from .spec import IliasTest


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
