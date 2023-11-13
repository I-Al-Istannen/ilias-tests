import argparse
import asyncio
import configparser
import sys
from pathlib import Path

from PFERD.auth import KeyringAuthenticator, KeyringAuthSection, SimpleAuthenticator, SimpleAuthSection
from PFERD.logging import log
from PFERD.utils import fmt_path

from .automation import slurp_tests_from_folder, add_test
from .ilias_action import IliasInteractor
from .spec import load_spec_from_file, dump_tests_to_yml


def load_interactor(args: argparse.Namespace):
    log.output_explain = args.explain
    log.output_report = False

    username = args.user
    password = args.password

    parser = configparser.ConfigParser(interpolation=None)
    parser["auth:ilias"] = {"username": username}
    if password:
        parser["auth:ilias"]["password"] = password

    if args.keyring:
        log.explain_topic("Using keyring authenticator")
        log.explain(f"Using username {username}")
        authenticator = KeyringAuthenticator(name="PFERD", section=KeyringAuthSection(parser["auth:ilias"]))
    else:
        log.explain_topic("Using simple authenticator")
        log.explain(f"Using username {username}")
        if password:
            log.explain("Password was given on CLI")
        else:
            log.explain("Password will be read from stdin")
        authenticator = SimpleAuthenticator(name="PFERD", section=SimpleAuthSection(parser["auth:ilias"]))

    return IliasInteractor(authenticator=authenticator, cookie_file=args.cookies)


async def run_slurp(interactor: IliasInteractor, args: argparse.Namespace):
    url: str = args.url
    data_path: Path = args.data_dir

    log.status("[bold magenta]", "Setup", "Setting up data")
    if not data_path.exists():
        data_path.mkdir(parents=True)

    log.status("[bold cyan]", "Slurp", "Starting")
    tests = await slurp_tests_from_folder(interactor, url, data_path)

    spec_path = data_path / "spec.yml"
    log.status("[cyan]", "Slurp", f"Writing spec to {fmt_path(spec_path)}")
    with open(spec_path, "w") as file:
        file.write(dump_tests_to_yml(tests))


async def run_upload(interactor: IliasInteractor, args: argparse.Namespace):
    spec_path: Path = args.spec
    if not spec_path.exists():
        log.print(f"[bold red]Spec file {fmt_path(spec_path)} does not exist")
        exit(1)
    ilias_folder: str = args.ilias_folder

    log.status("[bold magenta]", "Setup", "Loading spec")
    log.explain(f"Loading spec from {fmt_path(spec_path)}")
    spec = load_spec_from_file(spec_path)

    log.status("[bold cyan]", "Create", f"Create {len(spec.tests)} tests")

    for index, test in list(enumerate(spec.tests)):
        log.status("[bold cyan]", "Create", f"Adding test {index + 1}")
        await add_test(
            interactor,
            ilias_folder,
            test
        )


def main():
    parser = argparse.ArgumentParser(description='The forgotten ILIAS Test API', prog="ilias-tests")
    parser.add_argument(
        "--no-keyring", help="Do not use the system keyring to store credentials", action='store_false', dest="keyring"
    )
    parser.add_argument("--user", type=str, required=True, help="The name of the Shibboleth user")
    parser.add_argument("--password", type=str, help="The user's password (interactive input preferred)", default=None)
    parser.add_argument("--explain", help="Shows more debug information", action='store_true')
    parser.add_argument("--cookies", type=Path, help="Location of cookies file", default=Path(".cookies"))

    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand")

    slurp = subparsers.add_parser("slurp", help="Converts an ilias test/folder to yml")
    slurp.add_argument("url", metavar="URL", type=str, help="The URL to slurp")
    slurp.add_argument("data_dir", metavar="PATH", type=Path, help="The output directory. Will be created")

    create = subparsers.add_parser("create", help="Creates tests in ILIAS based on a yml spec")
    create.add_argument("spec", metavar="FILE", type=Path, help="The spec file to use")
    create.add_argument("ilias_folder", metavar="URL", type=str, help="The folder to place the test in")

    args = parser.parse_args()

    # show usage if no subcommand was picked
    if len(sys.argv) <= 1:
        parser.print_help()
        exit(1)

    match args.subcommand:
        case "slurp":
            run_command = run_slurp
        case "create":
            run_command = run_upload
        case _:
            parser.print_help()
            exit(1)

    async def run():
        async with load_interactor(args) as interactor:
            await run_command(interactor, args)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.explain_topic("Interrupted, exiting immediately")


if __name__ == "__main__":
    main()
