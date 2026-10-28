import asyncio
import datetime
import http.cookies
import json
import mimetypes
import re
import ssl
from collections.abc import Callable
from pathlib import Path
from random import randint
from typing import Any, Mapping, Optional, cast

import aiohttp
import certifi
from aiohttp import ClientTimeout
from PFERD.auth import Authenticator
from PFERD.crawl import CrawlError

# noinspection PyProtectedMember
from PFERD.crawl.ilias.async_helper import _iorepeat
from PFERD.crawl.ilias.kit_ilias_html import IliasPage, IliasSoup
from PFERD.crawl.ilias.kit_ilias_web_crawler import KitIliasWebCrawler
from PFERD.crawl.ilias.shibboleth_login import ShibbolethLogin
from PFERD.logging import log
from PFERD.utils import fmt_path, soupify

from .ilias_html import ExtendedIliasPage, normalize_page_design_html, random_ilfilehash
from .spec import (
    ManualGradingParticipantResults,
    PageDesignBlock,
    PageDesignBlockCode,
    PageDesignBlockImage,
    PageDesignBlockText,
    TestQuestion,
    TestTab,
    manual_grading_feedback_md_to_html,
)


async def _request_german_pages(
    request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    # The parsers rely on German labels. ILIAS uses the "lang" parameter instead of the user's
    # language for this request. This also runs for every redirect.
    if request.url.name in ("ilias.php", "goto.php"):
        request.url = request.url.update_query(lang="de")
    return await handler(request)


class IliasInteractor:
    def __init__(
        self,
        authenticator: Authenticator,
        cookie_file: Path,
        http_timeout: int = 60,
    ) -> None:
        self._shibboleth_auth = ShibbolethLogin("https://ilias.studium.kit.edu", authenticator, None)
        self._cookie_jar = aiohttp.CookieJar()
        self._cookie_file = cookie_file
        self._authentication_id = 0
        self._authentication_lock = asyncio.Lock()
        self._request_count = 0

        self._load_cookies()

        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "Foobar"},
            cookie_jar=self._cookie_jar,
            connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
            timeout=ClientTimeout(
                # 30 minutes. No download in the history of downloads was longer than 30 minutes.
                # This is enough to transfer a 600 MB file over a 3 Mib/s connection.
                # Allowing an arbitrary value could be annoying for overnight batch jobs
                total=15 * 60,
                connect=http_timeout,
                sock_connect=http_timeout,
                sock_read=http_timeout,
            ),
            requote_redirect_url=False,
            middlewares=(_request_german_pages,),
        )

    def _load_cookies(self) -> None:
        log.explain_topic(f"Loading cookies from {fmt_path(self._cookie_file)}")
        if not Path(self._cookie_file).exists():
            log.explain("No cookie file found")
            return
        jar: Any = http.cookies.SimpleCookie()
        with open(self._cookie_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                # Names of headers are case-insensitive
                if line[:11].lower() == "set-cookie:":
                    jar.load(line[11:])
                else:
                    log.explain(f"Line {i} doesn't start with 'Set-Cookie:', ignoring it")
        self._cookie_jar.update_cookies(jar)

    def _save_cookies(self) -> None:
        log.explain_topic(f"Saving cookies to {fmt_path(self._cookie_file)}")
        jar: Any = http.cookies.SimpleCookie()
        for morsel in self._cookie_jar:
            jar[morsel.key] = morsel
        with open(self._cookie_file, "w", encoding="utf-8") as f:
            f.write(jar.output(sep="\n"))
            f.write("\n")  # A trailing newline is just common courtesy

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._save_cookies()
        return await self.session.__aexit__(exc_type, exc_val, exc_tb)

    async def create_test(self, folder: ExtendedIliasPage, title: str, description: str) -> ExtendedIliasPage:
        log.explain_topic(f"Creating test '{title}' in '{folder.url()}'")
        create_url = folder.get_test_create_url()
        if not create_url:
            raise CrawlError("Could not find test create URL")
        create_page = await self._get_extended_page(create_url)

        submit_url, post_data = create_page.get_test_create_submit_post_data(title, description)

        return await self._post_authenticated(
            submit_url,
            data=post_data,
            request_succeeded=_auth_redirected_to_test_page,
        )

    async def select_tab(self, page: ExtendedIliasPage, target_tab: TestTab):
        log.explain_topic(f"Selecting tab {target_tab.name.lower()}")
        for name, url in page.get_test_tabs().items():
            if name in target_tab.value:
                return await self.select_page(url)
        raise CrawlError(f"Could not find a match for tab {target_tab.name} in {page.get_test_tabs()}")

    async def select_page(self, url: str):
        log.explain_topic("Selecting ilias page")
        return await self._get_extended_page(url)

    def _translate_from_ilias(
        self,
        settings_page: ExtendedIliasPage,
        label_match: str | re.Pattern,
        section_title: str | None = None,
        selector: str = "label",
    ) -> str:
        return settings_page.get_form_input_from_label_path(
            label_match, section_title=section_title, selector=selector
        ).get("name")

    def _translate(self, settings_page: ExtendedIliasPage, human_name: str):
        if human_name == "title":
            return self._translate_from_ilias(settings_page, "Titel", section_title="Einstellungen des Tests")
        elif human_name == "description":
            return self._translate_from_ilias(
                settings_page, re.compile(r"^(Zusammenfassung|Beschreibung)$"), section_title="Einstellungen des Tests"
            )
        elif human_name == "question_set_type":
            return self._translate_from_ilias(
                settings_page,
                "Fest definierte Fragenauswahl",
                section_title="Einstellungen des Tests",
            )
        elif human_name == "anonymity":
            return self._translate_from_ilias(
                settings_page,
                "Testergebnisse mit Namen",
                section_title="Einstellungen des Tests",
            )
        elif human_name == "online":
            return self._translate_from_ilias(
                settings_page,
                "Online",
                section_title="Verfügbarkeit",
            )
        elif human_name == "access_period[start]":
            return self._translate_from_ilias(
                settings_page,
                "Start",
                section_title="Verfügbarkeit",
            )
        elif human_name == "access_period[end]":
            return self._translate_from_ilias(
                settings_page,
                "Ende",
                section_title="Verfügbarkeit",
            )
        elif human_name == "activation_visibility":
            return self._translate_from_ilias(
                settings_page,
                "Immer sichtbar",
                section_title="Verfügbarkeit",
            )
        elif human_name == "intro_enabled":
            return self._translate_from_ilias(
                settings_page,
                "Einleitung",
                section_title="Informationen zum Einstieg",
            )
        elif human_name == "starting_time":
            return self._translate_from_ilias(
                settings_page,
                "Start",
                section_title="Durchführung: Zugang",
            )
        elif human_name == "ending_time":
            return self._translate_from_ilias(
                settings_page,
                "Ende",
                section_title="Durchführung: Zugang",
            )
        elif human_name == "limitPasses":
            return self._translate_from_ilias(
                settings_page,
                "Anzahl von Testdurchläufen begrenzen",
                section_title="Durchführung: Steuerung Testdurchlauf",
            )
        elif human_name == "nr_of_tries":
            return self._translate_from_ilias(
                settings_page,
                "Maximale Anzahl von Testdurchläufen",
                section_title="Durchführung: Steuerung Testdurchlauf",
            )
        elif human_name == "title_output":
            return self._translate_from_ilias(
                settings_page,
                "Fragentitel und erreichbare Punkte",
                section_title="Durchführung: Verhalten der Frage",
            )
        elif human_name == "answer_fixation_handling":
            return self._translate_from_ilias(
                settings_page,
                "Antworten während des Testdurchlaufs nicht festschreiben",
                section_title="Durchführung: Verhalten der Frage",
            )
        elif human_name == "chb_use_previous_answers":
            return self._translate_from_ilias(
                settings_page,
                "Verwendung vorheriger Lösungen",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "postpone":
            return self._translate_from_ilias(
                settings_page,
                "Nicht beantwortete Fragen bleiben an ihrem Platz",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "list_of_questions":
            return self._translate_from_ilias(
                settings_page,
                "Übersicht Testdurchlauf",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "list_of_questions_show_at_end":
            return self._translate_from_ilias(
                settings_page,
                "Vor dem Ende des Test anzeigen",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "list_of_questions_show_descriptions":
            return self._translate_from_ilias(
                settings_page,
                "Fragenbeschreibungen anzeigen",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "allow_interrupt":
            return self._translate_from_ilias(
                settings_page,
                '"Test unterbrechen" anzeigen',
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "question_list":
            return self._translate_from_ilias(
                settings_page,
                "Fragenliste",
                section_title="Durchführung: Funktionen für Teilnehmer",
            )
        elif human_name == "enable_examview":
            return self._translate_from_ilias(
                settings_page,
                "Übersicht gegebener Antworten",
                section_title="Test abschließen",
            )
        elif human_name == "autosave":
            return self._translate_from_ilias(
                settings_page,
                "Automatisches Speichern",
                section_title="Durchführung: Verhalten der Frage",
            )
        elif human_name == "autosave_ival":
            return self._translate_from_ilias(
                settings_page,
                "Speicherintervall",
                section_title="Durchführung: Verhalten der Frage",
            )
        else:
            raise CrawlError(f"Unknown human name {human_name!r} for translation")

    async def configure_test(
        self,
        settings_page: ExtendedIliasPage,
        title: str,
        description: str,
        starting_time: Optional[datetime.datetime],
        ending_time: Optional[datetime.datetime],
        number_of_tries: int,
        show_intro_text: bool,
    ) -> ExtendedIliasPage:
        """Configures the base test properties."""
        log.explain_topic(f"Configuring test {title}")
        base_params = {
            "title": title,
            "description": description,
            "question_set_type": "FIXED_QUEST_SET",  # everybody gets the same questions
            "anonymity": "0",
        }
        activation_params = {
            "access_period[start]": _format_time(datetime.datetime.now()),  # start of it
            "access_period[end]": _format_time(datetime.datetime.now()),  # end of it
            "activation_visibility": "checked",  # always visible, but not take-able
        }
        intro_params = {
            "intro_enabled": "checked" if show_intro_text else None,  # show text before the test
        }
        access_params = {"starting_time": _format_time(starting_time), "ending_time": _format_time(ending_time)}
        run_test_params = {
            "limitPasses": "checked",
            "nr_of_tries": str(number_of_tries),
        }
        run_question_params = {
            "title_output": "0",  # show title and max points
            "answer_fixation_handling": "none",  # allow changing answers
        }
        run_user_params = {
            "chb_use_previous_answers": "checked",  # show answers from previous run
            "postpone": "0",  # do not move unanswered questions to the end
            "list_of_questions": "checked",  # show a list of questions in a sidebar
            "list_of_questions_show_at_end": "checked",
            "list_of_questions_show_descriptions": "checked",
            "allow_interrupt": "checked",
            "question_list": "checked",
        }
        test_finish_params = {
            "enable_examview": "checked",  # Show answers before test submission
        }
        other_params = {
            # "autosave": "checked",
            # "autosave_ival": "30",
        }

        data = {
            **base_params,
            **activation_params,
            **intro_params,
            **access_params,
            **run_test_params,
            **run_question_params,
            **run_user_params,
            **test_finish_params,
            **other_params,
        }

        data = {self._translate(settings_page, k): v for k, v in data.items() if v is not None}

        url, extra_data = settings_page.get_test_settings_change_data()

        post_data = data.copy()
        for extra in extra_data:
            if extra.disabled:
                post_data.pop(extra.name, None)
                continue
            if extra.name not in post_data:
                post_data[extra.name] = extra.value

        def build_form_data():
            form_data = aiohttp.FormData()
            for key, val in post_data.items():
                if isinstance(val, list):
                    for elem in val:
                        form_data.add_field(key, elem)
                else:
                    form_data.add_field(key, val)

            form_data.add_field(
                name="tile_image",
                value=b"",
                content_type="application/octet-stream",
                filename="",
            )
            return form_data

        return await self._post_authenticated(url=url, data=build_form_data)

    async def set_test_online(self, settings_page: ExtendedIliasPage, online: bool) -> ExtendedIliasPage:
        """Changes only the online status, submitting all other settings unchanged."""
        log.explain_topic(f"Setting test {'online' if online else 'offline'}")
        url, values = settings_page.get_test_settings_current_values()
        online_name = self._translate(settings_page, "online")
        values = [(name, value) for name, value in values if name != online_name]
        if online:
            values.append((online_name, "checked"))

        def build_form_data():
            form_data = aiohttp.FormData()
            for name, value in values:
                form_data.add_field(name, value)
            form_data.add_field(name="tile_image", value=b"", content_type="application/octet-stream", filename="")
            return form_data

        return await self._post_authenticated(url=url, data=build_form_data)

    async def configure_test_intro(self, settings_page: ExtendedIliasPage, intro: list[PageDesignBlock]):
        intro_page = await self.select_page(settings_page.get_intro_text_page_url())
        await self.design_page_add_blocks(await self.select_page(intro_page.get_intro_text_design_url()), intro)

    async def configure_test_scoring(self, settings_page: ExtendedIliasPage) -> ExtendedIliasPage:
        log.explain_topic("Configuring test scoring settings")
        page = await self._get_extended_page(settings_page.get_scoring_settings_url())

        url, extra_data = page.get_test_scoring_settings_change_data()
        label_values = {
            "(.*falsch beantwortete Fragen ergeben.*)|(.*Incomplete or Partially Incorrect.*)": "0",
            "(.*nie weniger als 0 Punkte sein)|(.*Cannot Score Negative Points.*)": "0",
            "(Letzten Durchlauf des Tests bewerten)|(Score the Last Attempt)": "0",
            "(Eigenes Testergebnis einsehen)|(Access to Test Results)": "checked",
            "(Nach Durchlauf des Tests)|(After Test Attempt Is Finished)": "1",
            "(.Bestanden. / .Nicht bestanden. anzeigen)|(Show .Passed. / .Failed. Status)": "checked",
            "(Note anzeigen)|(Show Grade)": "checked",
            "(Detaillierte Testergebnisse (anzeigen|zugänglich machen))|(Show detailed test results)": "checked",
            "(Bestmögliche Lösung)|(Best Solution)": "checked",
            "(Rückmeldungen)|(Feedback)": "checked",
            "(Druckbare Liste der Antworten)|(Additional .List of Answers. for Printing)": "checked",
            "(Länge der Bestenliste)|(Length of Top Ranking)": "0",  # not used, but required
        }
        post_data = {}

        for label, value in label_values.items():
            for name in page.get_test_scoring_name_for_label(label):
                post_data[name] = value

        for name in page.get_test_scoring_dates():
            post_data[name] = ""

        for extra in extra_data:
            if extra.disabled:
                post_data.pop(extra.name, None)
                continue
            if extra.name not in post_data:
                post_data[extra.name] = extra.value

        return await self._post_authenticated(url=url, data=post_data)

    async def add_question(self, question_page: ExtendedIliasPage, question: TestQuestion):
        log.explain_topic(f"Adding question {question.title!r}")
        url = question_page.get_test_add_question_url()
        page = await self._get_extended_page(url)

        url, data = page.get_test_question_create_url(question.question_type.value)
        edit_page = await self._post_authenticated(
            url,
            data=data,
            soup_succeeded=lambda pg: pg.is_test_question_edit_page(),
        )

        post_data = {**question.get_options(), "cmd[saveReturn]": "Speichern und zurückkehren"}
        url, defaults = edit_page.get_test_question_finalize_data()
        for extra in defaults:
            if extra.disabled:
                post_data.pop(extra.name, None)
                continue
            if extra.name not in post_data:
                post_data[extra.name] = extra.value

        def build_form_data():
            form_data = aiohttp.FormData()
            for post_key, post_val in post_data.items():
                if isinstance(post_val, Path):
                    form_data.add_field(name=post_key, value=b"", content_type="application/octet-stream", filename="")
                else:
                    form_data.add_field(post_key, post_val)

            return form_data

        question_page = await self._post_authenticated(url, data=build_form_data)
        design_page = await self.select_page(question_page.get_test_question_design_page_url())
        await self.design_page_add_blocks(design_page, question.page_design)
        return question_page

    async def reorder_questions(self, questions_tab: ExtendedIliasPage, title_order: list[str]):
        log.explain_topic("Reordering questions")
        ids = questions_tab.get_test_question_ids()
        log.explain_topic("Question ids")
        log.explain(str(ids))
        question_to_position = {}
        for index, title in enumerate(title_order):
            question_to_position[ids[title]] = str(index)

        url, data = questions_tab.get_test_question_save_order_data(question_to_position)
        await self._post_authenticated(url=url, data=data)

    async def design_page_add_blocks(self, edit_page: ExtendedIliasPage, blocks: list[PageDesignBlock]):
        log.explain_topic("Adding design blocks to page")
        current_id = ""
        for block in blocks:
            log.explain(f"Adding block {block.__class__.__name__}")
            match block:
                case PageDesignBlockImage(image=image):
                    current_id = await self.design_page_add_image_block(edit_page, path=image, after_id=current_id)
                case PageDesignBlockText(text_html=_, characteristic=_):
                    current_id = await self.design_page_add_text_block(edit_page, block=block, after_id=current_id)
                case PageDesignBlockCode(code=code, language=lang, name=name):
                    current_id = await self.design_page_add_code_block(edit_page, code, lang, name, current_id)
                case _:
                    raise CrawlError(f"Unknown page design block: {block!r}")

    async def design_page_add_text_block(
        self, edit_page: ExtendedIliasPage, block: PageDesignBlockText, after_id: str
    ) -> str:
        log.explain(f"Adding text block after {after_id}")
        post_url, _ = edit_page.get_test_question_design_post_url()
        new_id = "".join([str(randint(0, 9)) for _ in range(20)])
        resp = await self._post_authenticated_json(
            url=post_url,
            data={
                "component": "Paragraph",
                "action": "insert",
                "data": {
                    "after_pcid": after_id,
                    "pcid": new_id,
                    "content": normalize_page_design_html(block.text_html),
                    "characteristic": block.characteristic.value,
                    "fromPlaceholder": False,
                },
            },
        )
        if resp["error"]:
            raise CrawlError(f"Adding text block failed with: {resp['error']!r}")
        log.explain(f"Created block has id {new_id}")
        return new_id

    async def design_page_add_image_block(self, edit_page: ExtendedIliasPage, path: Path, after_id: str) -> str:
        log.explain(f"Adding image block after {after_id}")
        post_url, _ = edit_page.get_test_question_design_post_url()

        post_data = {
            "standard_file": path,
            "standard_type": "File",
            "standard_size": "original",
            "full_type": "None",
            "component": "MediaObject",
            "action": "insert",
            "after_pcid": after_id,
            "pcid": "",
            "ilfilehash": random_ilfilehash(),
        }

        def build_form_data():
            form_data = aiohttp.FormData()
            for post_key, post_val in post_data.items():
                if isinstance(post_val, Path):
                    form_data.add_field(
                        name=post_key,
                        value=open(post_val, "rb"),
                        content_type=mimetypes.guess_type(post_val)[0],
                        filename=str(post_val.name),
                    )
                else:
                    form_data.add_field(post_key, post_val)

            return form_data

        await self._post_authenticated(url=post_url, data=build_form_data, soup_succeeded=lambda x: True)

        edit_page = await self.select_page(edit_page.url())
        new_id = edit_page.get_test_question_design_last_component_id()
        log.explain(f"Created block has id {new_id}")
        return new_id

    async def design_page_add_code_block(
        self, edit_page: ExtendedIliasPage, code: str, language: str, file_name: str, after_id: str
    ) -> str:
        log.explain(f"Adding code block after {after_id}")
        post_url, _ = edit_page.get_test_question_design_post_url()
        new_id = "".join(str(randint(0, 9)) for _ in range(20))
        data = {
            "component": "SourceCode",
            "pcid": new_id,
            "form/input_0": "manual",
            "form/input_1": file_name,
            "form/input_2": language,
            "form/input_3": "checked",
        }
        # The current editor creates the component first, then saves its text.
        for action in ("insert", "update"):
            response = await self._post_authenticated_json(
                post_url,
                {**data, "action": action, "after_pcid": after_id, "code": code},
                as_form=True,
            )
            if response.get("error"):
                raise CrawlError(f"Adding code block failed with: {response['error']!r}")
        return new_id

    # returns data
    async def download_file_data(self, url: str) -> tuple[str, bytes] | None:
        async with self.session.get(url) as response:
            if 200 <= response.status < 300:
                disposition = response.content_disposition
                filename = (
                    response.headers.get("content-description")
                    or (disposition.filename if disposition else None)
                    or response.url.name
                    or "download"
                )
                content = await response.read()
                return filename, content
            else:
                log.explain(f"Got non 200 status code: {response.status}")
        return None

    # stores the data on disk
    async def download_file(self, url: str, output_folder: Path, prefix: str):
        log.explain_topic(f"Downloading file {prefix!r} from '{url}' to {fmt_path(output_folder)}")
        auth_id = await self._current_auth_id()
        if not output_folder.exists():
            output_folder.mkdir(parents=True, exist_ok=True)

        async def do_request():
            result = await self.download_file_data(url)
            if result is None:
                return None
            downloaded_filename, content = result
            filename = prefix + downloaded_filename
            out_path = output_folder / filename
            log.explain(f"Writing to {fmt_path(out_path)}")
            with open(out_path, "wb") as file:
                file.write(content)
            return out_path

        if output_file := await do_request():
            return output_file

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        if output_file := await do_request():
            return output_file
        raise CrawlError(f"download_file failed even after authenticating on {url!r}")

    async def end_all_user_passes(self, test_page: ExtendedIliasPage, indent: str = ""):
        dashboard = await self.select_tab(test_page, TestTab.PARTICIPANTS)
        page = await self._post_authenticated(
            dashboard.get_test_dashboard_end_all_passes_submit_url(),
            data={},
            soup_succeeded=lambda pg: pg.test_dashboard_has_no_active_passes()
            or ExtendedIliasPage.page_has_success_alert(pg),
        )
        if page.test_dashboard_has_no_active_passes():
            log.warn(f"{indent}No active test passes to end")

    async def set_manual_grading_filter_show_all(self, tab_page: ExtendedIliasPage):
        filter_url = tab_page.get_manual_grading_filter_url()
        # Show all rows of the table!
        filter_url += "&manScorePartTable_trows=800"
        data = {"participant_status": "3", "cmd[applyManScoringParticipantsFilter]": "Filter+anwenden"}

        def is_valid_page(page: ExtendedIliasPage):
            from bs4.element import Tag

            # noinspection PyProtectedMember
            participant_status = cast(Tag, page._soup.find(id="participant_status"))
            selected = cast(Tag, participant_status.find("option", selected=True))
            return selected.get("value") == "3"

        result_page = await self._post_authenticated(
            filter_url,
            data=data,
            soup_succeeded=is_valid_page,
        )

        # Try to check if the table is paginated
        # noinspection PyProtectedMember
        if page_select := result_page._soup.find(id="tab_page_sel_1", name="select"):
            log.explain(f"Element: {page_select}")
            raise CrawlError(
                "Found page selection element on manual grading table. Maybe the table is truncated? "
                "Refusing further operation."
            )

        return result_page

    async def upload_manual_grading_result(
        self,
        page: ExtendedIliasPage,
        results: ManualGradingParticipantResults,
        mark_done: bool = False,
        notify_users: bool = False,
    ):
        data = {
            "cmd[saveManScoringParticipantScreen]": "Speichern",
            "myCounter": [""] * len(results.answers),
        }

        if mark_done:
            data["manscoring_done"] = "1"
        if notify_users:
            data["manscoring_notify"] = "1"

        for answer in results.answers:
            question_id = answer.question.id
            data[f"question__{question_id}__points"] = str(answer.points)
            data[f"question__{question_id}__feedback"] = manual_grading_feedback_md_to_html(answer.feedback or "")
        save_url = page.get_manual_grading_save_url()

        return await self._post_authenticated(save_url, data)

    async def _get_extended_page(self, url: str) -> ExtendedIliasPage:
        return ExtendedIliasPage(await self._get_soup(url))

    @_iorepeat(attempts=2, name="request page", failure_is_error=True)
    async def _get_soup(self, url: str, root_page_allowed: bool = False) -> IliasSoup:
        log.explain(f"Requesting page for '{url}'")
        auth_id = await self._current_auth_id()

        async def do_request():
            async with self.session.get(url) as request:
                soup = IliasSoup(soupify(await request.read()), str(request.url))
                if IliasPage.is_logged_in(soup):
                    # noinspection PyProtectedMember
                    return KitIliasWebCrawler._verify_page(soup, url, root_page_allowed)
            return None

        if page := await do_request():
            return page

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        if page := await do_request():
            return page
        raise CrawlError(f"get_page failed even after authenticating on {url!r}")

    @_iorepeat(attempts=2, name="post authenticated", failure_is_error=True)
    async def _post_authenticated(
        self,
        url: str,
        data: Mapping[str, str | list[str]] | Callable[[], aiohttp.FormData],
        request_succeeded: Callable[[aiohttp.ClientResponse], bool] = lambda resp: 200 <= resp.status < 300,
        soup_succeeded: Callable[[ExtendedIliasPage], bool] = ExtendedIliasPage.page_has_success_alert,
    ) -> ExtendedIliasPage:
        log.explain(f"Sending post data to {url}")
        auth_id = await self._current_auth_id()

        def build_form_data():
            if isinstance(data, Callable):
                return data()
            else:
                form_data = aiohttp.FormData()
                for key, val in data.items():
                    form_data.add_field(key, val)
                return form_data

        async def do_request():
            async with self.session.post(url, data=build_form_data(), allow_redirects=True) as response:
                if request_succeeded(response):
                    my_page = ExtendedIliasPage(IliasSoup(soupify(await response.read()), str(response.url)))
                    if soup_succeeded(my_page):
                        return my_page
                    else:
                        log.warn(f"Request to '{url}' failed extended validation")
                else:
                    log.warn(f"Request to '{url}' failed")

        if page := await do_request():
            return page

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        if page := await do_request():
            return page

        raise CrawlError("post_authenticated failed even after authenticating")

    @_iorepeat(attempts=2, name="post authenticated json", failure_is_error=True)
    async def _post_authenticated_json(self, url: str, data: Any, *, as_form: bool = False) -> Any:
        log.explain(f"Sending post json data to {url}")
        auth_id = await self._current_auth_id()

        async def do_request():
            async with self.session.post(
                url,
                data=data if as_form else json.dumps(data),
                allow_redirects=True,
                headers={} if as_form else {"Content-Type": "application/json"},
            ) as response:
                log.explain_topic("Checking response")
                if 200 <= response.status < 300:
                    return json.loads(await response.read())

        if page := await do_request():
            return page

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        if page := await do_request():
            return page

        raise CrawlError("post_authenticated_json failed even after authenticating")

    async def _current_auth_id(self) -> int:
        """
        Returns the id for the current authentication, i.e. an identifier for the last
        successful call to [authenticate].

        This method must be called before any request that might authenticate is made, so the
        HttpCrawler can properly track when [authenticate] can return early and when actual
        authentication is necessary.
        """
        # We acquire the lock here to ensure we wait for any concurrent authenticate to finish.
        # This should reduce the amount of requests we make: If an authentication is in progress
        # all future requests wait for authentication to complete.
        async with self._authentication_lock:
            self._request_count += 1
            return self._authentication_id

    async def authenticate(self, caller_auth_id: int) -> None:
        """
        Starts the authentication process. The main work is offloaded to _authenticate, which
        you should overwrite in a subclass if needed. This method should *NOT* be overwritten.

        The [caller_auth_id] should be the result of a [_current_auth_id] call made *before*
        the request was made. This ensures that authentication is not performed needlessly.
        """
        async with self._authentication_lock:
            with log.show_progress():
                log.explain_topic("Authenticating")
                # Another thread successfully called authenticate in-between
                # We do not want to perform auth again, so we return here. We can
                # assume the other thread succeeded as authenticate will throw an error
                # if it failed and aborts the crawl process.
                if caller_auth_id != self._authentication_id:
                    log.explain(
                        "Authentication skipped due to auth id mismatch.A previous authentication beat us to the race."
                    )
                    return
                log.explain("Calling crawler-specific authenticate")
                await self._authenticate()
                self._authentication_id += 1
                # Saving the cookies after the first auth ensures we won't need to re-authenticate
                # on the next run, should this one be aborted or crash
                self._save_cookies()

    async def _authenticate(self) -> None:
        await self._shibboleth_auth.login(self.session)


def _auth_redirected_to_test_page(response: aiohttp.ClientResponse):
    return "cmdclass=ilias\\test\\settings\\mainsettings\\settingsmaingui" in response.url.query_string.lower()


def _format_time(time: Optional[datetime.datetime]) -> str:
    if not time:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M")
