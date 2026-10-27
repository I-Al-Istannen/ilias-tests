import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

import aiohttp
import pytest
from PFERD.crawl.ilias.kit_ilias_html import IliasPage, IliasSoup
from PFERD.utils import soupify

from . import stack
from .stack import Ilias


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(__file__).parent in item.path.parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def ilias() -> Iterator[Ilias]:
    yield stack.get_or_start()


@pytest.fixture
def workspace(ilias: Ilias) -> dict[str, int]:
    return ilias.run_php("workspace.php", uuid.uuid4().hex)


async def _login(ilias: Ilias, cookie_file: Path) -> None:
    # Authenticate locally, then use the CLI's existing --cookies option. This avoids
    # needing KIT Shibboleth or adding a test-only login mode to production code.
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{ilias.base_url}/login.php", params={"client_id": "default", "cmd": "force_login"}
        ) as response:
            page = soupify(await response.read())
        form = page.find("form", attrs={"name": "login_form"})
        assert form is not None, "ILIAS did not show a local login form"
        async with session.post(
            urljoin(ilias.base_url, str(form["action"])),
            data={
                "login_form/input_3/input_4": ilias.seed["login"],
                "login_form/input_3/input_5": ilias.seed["password"],
            },
        ) as response:
            soup = IliasSoup(soupify(await response.read()), str(response.url))
            assert IliasPage.is_logged_in(soup), "Local ILIAS login failed"
        cookie_file.write_text(
            "\n".join(f"Set-Cookie: {cookie.OutputString()}" for cookie in session.cookie_jar) + "\n"
        )


class RunCLI(Protocol):
    def __call__(self, *args: str | Path, expected_exit_code: int = 0) -> str: ...


@pytest.fixture
def run_cli(ilias: Ilias, tmp_path: Path) -> RunCLI:
    cookies = tmp_path / "cookies.txt"
    asyncio.run(_login(ilias, cookies))

    def run(*args: str | Path, expected_exit_code: int = 0) -> str:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ilias_tests",
                "--no-keyring",
                "--user",
                ilias.seed["login"],
                "--password",
                ilias.seed["password"],
                "--cookies",
                str(cookies),
                *map(str, args),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "NO_COLOR": "1", "TERM": "dumb"},
        )
        log = result.stdout + result.stderr
        assert result.returncode == expected_exit_code, log
        return log

    return run
