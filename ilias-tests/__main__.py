import asyncio
import configparser
from pathlib import Path

from PFERD.auth import KeyringAuthenticator, KeyringAuthSection
from PFERD.logging import log

from .ilias_action import IliasInteractor


def load_interactor():
    log.output_report = False
    log.output_explain = False

    parser = configparser.ConfigParser(interpolation=None)
    parser["auth:ilias"] = {"username": "uxxxx"}

    authenticator = KeyringAuthenticator(name="PFERD", section=KeyringAuthSection(parser["auth:ilias"]))

    return IliasInteractor(authenticator=authenticator, cookie_file=Path(".cookies"))


if __name__ == "__main__":
    async def foo():
        async with load_interactor() as interactor:
            await interactor.hello()


    asyncio.run(foo())
