import asyncio
import configparser
from pathlib import Path

from PFERD.auth import KeyringAuthenticator, KeyringAuthSection
from PFERD.logging import log

from .automation import add_test, slurp_questions_from_folder
from .ilias_action import IliasInteractor
from .spec import load_spec_from_file, dump_questions_to_yml


def load_interactor():
    log.output_report = False
    log.output_explain = False

    parser = configparser.ConfigParser(interpolation=None)
    parser["auth:ilias"] = {"username": "uxxxx"}

    authenticator = KeyringAuthenticator(name="PFERD", section=KeyringAuthSection(parser["auth:ilias"]))

    return IliasInteractor(authenticator=authenticator, cookie_file=Path(".cookies"))


async def main(interactor: IliasInteractor):
    log.status("[bold green]", "Setup", "Loading spec")
    spec = load_spec_from_file(Path("tests.yml"))
    log.status("[bold green]", "Setup", "Spec loaded, creating tests")

    for index, test in enumerate(spec.tests):
        log.status("[bold green]", "Tests", f"Adding test {index + 1}")
        await add_test(
            interactor,
            "https://ilias.example.com",
            test
        )

    log.status("[bold green]", "Setup", "Slurping created tests")

    questions = await slurp_questions_from_folder(
        interactor,
        "https://ilias.example.com"
    )
    print(dump_questions_to_yml(questions))


if __name__ == "__main__":
    async def foo():
        async with load_interactor() as interactor:
            await main(interactor)


    asyncio.run(foo())
