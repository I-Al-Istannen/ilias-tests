import datetime
import random
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, cast, Callable, Awaitable

import bs4
from PFERD.crawl import CrawlError
from PFERD.crawl.ilias.kit_ilias_html import IliasPage
from PFERD.logging import log
from bs4 import BeautifulSoup

from .spec import (
    QuestionUploadFile,
    QuestionFreeFormText,
    QuestionSingleChoice,
    QuestionMultipleChoice,
    PageDesignBlock,
    PageDesignBlockText,
    PageDesignBlockImage,
    PageDesignBlockCode,
    IliasTest,
    TestQuestion,
    ManualGradingParticipantInfo,
    ManualGradingGradedQuestion,
    ManualGradingParticipantResults,
    ManualGradingQuestion,
    ManualGradingQuestionType,
)


@dataclass
class ExtraFormData:
    name: str
    value: str
    disabled: bool

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.name == other.name


class ExtendedIliasPage(IliasPage):
    def __init__(self, soup: BeautifulSoup, _page_url: str):
        super().__init__(soup, _page_url, None)

    def url(self):
        return self._page_url

    def normalized_url(self):
        return self._page_url.lower()

    def is_test_page(self):
        log.explain_topic("Verifying page is a test")
        if "cmdclass=ilobjtestgui" in self.normalized_url():
            log.explain("Page matched test url fragment")
            return True
        header = self._soup.find(id="headerimage")
        if not header:
            log.explain("Could not find headerimage")
            return False
        if header.get("alt", "").lower() == "symbol test":
            log.explain("Alt text in header matched")
            return True
        log.explain("Alt text did not match")
        return False

    def is_test_create_page(self):
        return "cmd=create" in self.normalized_url() and "new_type=tst" in self.normalized_url()

    def is_test_question_edit_page(self):
        return "cmd=editquestion" in self.normalized_url()

    def get_test_create_url(self) -> Optional[str]:
        return self._abs_url_from_link(self._soup.find(id="tst"))

    def get_test_create_submit_url(self) -> tuple[str, str]:
        if not self.is_test_create_page():
            raise CrawlError("Not on test create page")
        save_button = self._soup.find(attrs={"name": "cmd[save]"})
        form = save_button.find_parent(name="form")
        return self._abs_url_from_relative(form["action"]), save_button["value"]

    def get_test_tabs(self) -> dict[str, str]:
        tab = self._soup.find(id="ilTab")
        if not tab:
            return {}

        result = {}
        for tab_list in tab.find_all(name="li"):
            if not tab_list["id"].startswith("tab_"):
                continue
            link = tab_list.find(name="a")
            result[link.getText().strip()] = self._abs_url_from_link(link)

        return result

    def get_test_settings_change_data(self) -> tuple[str, set[ExtraFormData]]:
        form = self._soup.find(id="form_test_properties")
        if not form:
            raise CrawlError("Could not find properties page. Is this a settings page?")

        extra_values = self._get_extra_form_values(form)
        extra_values.add(ExtraFormData(name="ilfilehash", value=form.find(id="ilfilehash")["value"], disabled=False))
        return self._abs_url_from_relative(form["action"]), extra_values

    def get_test_add_question_url(self):
        """Add a question to a test."""
        button = self._soup.find(attrs={"onclick": lambda x: x and "cmd=addQuestion" in x})
        if not button:
            raise CrawlError("Could not find add question button")
        start = button["onclick"].find("'")
        end = button["onclick"].rfind("'")
        return self._abs_url_from_relative(button["onclick"][start + 1 : end])

    def get_test_question_create_url(self) -> str:
        """Enter question editor by selecting its type and information."""
        return self._form_target_from_button("cmd[executeCreateQuestion]")[0]

    def get_test_question_finalize_data(self) -> tuple[str, set[ExtraFormData]]:
        """Url for finalizing the question creation."""
        url, btn, form = self._form_target_from_button("cmd[saveReturn]")
        form_values = self._get_extra_form_values(form)
        if filehash := self._soup.find(id="ilfilehash"):
            form_values.add(ExtraFormData(name="ilfilehash", value=filehash.get("value"), disabled=False))
        return url, form_values

    def get_test_question_design_code_submit_url(self):
        """Url for submitting a code block."""
        return self._form_target_from_button("cmd[create_src]")[0]

    @staticmethod
    def _get_extra_form_values(form: bs4.Tag) -> set[ExtraFormData]:
        extra_values = set()
        for inpt in form.find_all(name="input", attrs={"required": "required"}):
            extra_values.add(
                ExtraFormData(
                    name=inpt["name"],
                    value=inpt.get("value", ""),
                    disabled=inpt.get("disabled", None) is not None,
                )
            )
        for inpt in form.find_all(name="textarea", attrs={"required": "required"}):
            extra_values.add(
                ExtraFormData(
                    name=inpt["name"],
                    value=inpt.get("value", ""),
                    disabled=inpt.get("disabled", None) is not None,
                )
            )
        for select in form.find_all(name="select"):
            extra_values.add(
                ExtraFormData(
                    name=select["name"],
                    value=select.find(name="option", attrs={"selected": "selected"}).get("value", ""),
                    disabled=select.get("disabled", None) is not None,
                )
            )

        for inpt in form.find_all(name="input", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=inpt["name"], value="", disabled=True))
        for select in form.find_all(name="select", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=select["name"], value="", disabled=True))
        for select in form.find_all(name="textarea", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=select["name"], value="", disabled=True))

        return extra_values

    def _form_target_from_button(self, button_name: str):
        btn = self._soup.find(attrs={"name": button_name})
        if not btn:
            raise CrawlError(f"Could not find {button_name!r} button")
        form = btn.find_parent(name="form")
        return self._abs_url_from_relative(form["action"]), btn, form

    def get_test_question_after_values(self) -> dict[str, str]:
        position_select = self._soup.find(id="position")
        if not position_select:
            raise CrawlError("Could not find element")
        results = {}
        for select in position_select.find_all("option"):
            text: str = select.getText().strip()
            if "Nach" in text:
                title = text[len("Nach") : text.rfind("[")].strip()
                results[title] = select["value"]
        return results

    def get_test_question_ids(self) -> dict[str, str]:
        """Returns { title -> question_id }"""
        ids = {}
        for question_id, title_link in self._get_test_question_ids_and_links():
            ids[title_link.getText().strip()] = question_id

        return ids

    def _get_test_question_ids_and_links(self) -> list[tuple[str, bs4.Tag]]:
        """Returns [(id, link tag for title)]"""
        if "cmd=questions" not in self.normalized_url() or "ilobjtestgui" not in self.normalized_url():
            raise CrawlError("Not on test question page")
        table = self._soup.find(name="table", id=lambda x: x and x.startswith("tst_qst_lst"))
        if not table:
            raise CrawlError("Did not find questions table")
        result = []
        for row in table.find(name="tbody").find_all(name="tr"):
            order_td = row.find(name="td", attrs={"name": lambda x: x and x.startswith("order[")})
            if not order_td:
                alert_message = ""
                for alert in self._soup.select(".alert"):
                    alert_message += alert.getText().strip()
                raise CrawlError(f"Could not find order column. Page-Alerts: {alert_message}")
            question_id = cast(str, order_td["name"]).replace("order[", "").replace("]", "").strip()
            result.append((question_id, row.find(name="a")))

        return result

    def get_test_question_save_order_data(self, question_to_position: dict[str, str]) -> tuple[str, dict[str, str]]:
        url, _, _ = self._form_target_from_button("cmd[saveOrderAndObligations]")
        data = {
            "cmd[saveOrderAndObligations]": "Sortierung abspeichern",
        }
        for question_id, value in question_to_position.items():
            data[f"order[q_{question_id}]"] = value
        return url, data

    def get_test_question_listing(self) -> list[tuple[str, str]]:
        """Returns [(title, url)] for all questions in a test."""
        result = []
        for _, link in self._get_test_question_ids_and_links():
            result.append((link.getText().strip(), self._abs_url_from_link(link)))
        return result

    def get_test_question_edit_url(self):
        return self._abs_url_from_link(
            self._soup.find(name="a", attrs={"href": lambda x: x and "cmd=editQuestion" in x})
        )

    def get_test_question_reconstruct_from_edit(self, page_design: list[PageDesignBlock]):
        if "cmd=editquestion" not in self.normalized_url():
            raise CrawlError("Not on question edit page")
        title = _norm(self._soup.find(id="title")["value"].strip())
        author = _norm(self._soup.find(id="author")["value"].strip())
        summary = _norm(self._soup.find(id="comment").get("value", "").strip())
        question_html = _norm(self._soup.find(id="question").getText().strip())

        if "asstextquestiongui" in self.normalized_url():
            # free from text
            points = float(self._soup.find(id="non_keyword_points")["value"].strip())
            return QuestionFreeFormText(
                title=title,
                author=author,
                summary=summary,
                question_html=question_html,
                page_design=page_design,
                points=points,
            )
        elif "cmdclass=assfileuploadgui" in self.normalized_url():
            # file upload
            max_size_bytes = int(self._soup.find(id="maxsize").get("value", "2097152").strip())
            allowed_extensions = self._soup.find(id="allowedextensions").get("value", "").strip().split(",")
            points = float(self._soup.find(id="points")["value"].strip())
            return QuestionUploadFile(
                title=title,
                author=author,
                summary=summary,
                question_html=question_html,
                page_design=page_design,
                points=points,
                allowed_extensions=allowed_extensions,
                max_size_bytes=max_size_bytes,
            )
        elif "cmdclass=asssinglechoicegui" in self.normalized_url():
            shuffle = True if self._soup.find(id="shuffle").get("checked", None) else False
            answer_table = self._soup.find(name="table", attrs={"class": lambda x: x and "singlechoicewizard" in x})
            answers = []
            for inpt in answer_table.find_all(name="input", id=lambda x: x and x.startswith("choice[answer]")):
                answer_value = _norm(inpt.get("value", ""))
                answer_points = float(
                    answer_table.find(id=inpt["id"].replace("answer", "points")).get("value", "0").strip()
                )
                answers.append((answer_value, answer_points))

            return QuestionSingleChoice(
                title=title,
                author=author,
                summary=summary,
                question_html=question_html,
                page_design=page_design,
                shuffle=shuffle,
                answers=answers,
            )
        elif "cmdclass=assmultiplechoicegui" in self.normalized_url():
            shuffle = True if self._soup.find(id="shuffle").get("checked", None) else False
            selection_limit = self._soup.find(id="selection_limit").get("value", None)
            if selection_limit is not None:
                selection_limit = int(selection_limit)
            answer_table = self._soup.find(name="table", attrs={"class": lambda x: x and "multiplechoicewizard" in x})
            answers = []
            for inpt in answer_table.find_all(name="input", id=lambda x: x and x.startswith("choice[answer]")):
                answer_value = _norm(inpt.get("value", ""))
                answer_points_checked = float(
                    answer_table.find(id=inpt["id"].replace("answer", "points")).get("value", "0").strip()
                )
                answer_points_unchecked = float(
                    answer_table.find(id=inpt["id"].replace("answer", "points_unchecked")).get("value", "0").strip()
                )
                answers.append((answer_value, answer_points_checked, answer_points_unchecked))

            return QuestionMultipleChoice(
                title=title,
                author=author,
                summary=summary,
                question_html=question_html,
                page_design=page_design,
                shuffle=shuffle,
                answers=answers,
                selection_limit=selection_limit,
            )
        else:
            raise CrawlError(f"Unknown question type at '{self.url()}'")

    def get_test_question_design_page_url(self):
        link = self._soup.find(attrs={"href": lambda x: x and "cmdclass=ilassquestionpagegui" in x.lower()})
        if not link:
            raise CrawlError("Could not find page edit button")
        return self._abs_url_from_link(link)

    def get_test_question_design_post_url(self) -> tuple[str, str]:
        """
        Returns the post endpoint from the 'Design page' page.
        First url is the base for text and images, the second for e.g. code
        """
        for script in self._soup.find_all(name="script"):
            if not isinstance(script, bs4.Tag):
                continue
            text = "".join([str(x) for x in script.contents])
            if "il.copg.editor.init" in text:
                candidates = [line.strip() for line in text.splitlines() if "il.copg.editor.init" in line]
                if not candidates:
                    raise CrawlError("Found no init call candidate")
                init_call = candidates[0]
                match = re.search(r"\('([^']+)','([^']+)'", init_call)
                if not match:
                    raise CrawlError(f"Editor init call has unknown format: {candidates[0]!r}")
                return match.group(1), self._abs_url_from_relative(match.group(2))
        raise CrawlError("Could not find copg editor base url")

    async def get_test_question_design_blocks(
        self, downloader: Callable[[str], Awaitable[Path]]
    ) -> list[PageDesignBlock]:
        log.explain_topic(f"Fetching page design blocks for '{self.url()}'")
        form = self._soup.find(name="form", attrs={"name": "ilAssQuestionPreview"})
        if not form:
            raise CrawlError("Could not find question preview form")
        after_start = False
        blocks: list[PageDesignBlock] = []

        for child in form.children:
            if not isinstance(child, bs4.Tag):
                continue
            if "ilc_page_title_PageTitle" in child.get("class", []):
                after_start = True
                continue
            if not after_start:
                continue
            child_classes = child.get("class", [])
            if "ilc_Paragraph" in child_classes:
                log.explain("Found text block")
                blocks.append(PageDesignBlockText(_normalize_tag_for_design_block(child)))
                continue
            if "ilc_Code" in child_classes:
                log.explain("Found code block")
                code = child.select_one("table .ilc_Sourcecode .ilc_code_block_Code")
                for br in code.find_all(name="br"):
                    br.replace_with("\n")
                download_link = child.find(name="a", attrs={"href": lambda x: x and "cmd=download_paragraph" in x})
                name = "unknown.c"
                if download_link:
                    if match := re.search(r"downloadtitle=([^&]+)", download_link["href"]):
                        name = match.group(1)

                blocks.append(
                    PageDesignBlockCode(
                        code=_norm(code.getText().strip()),
                        language="c",  # guess
                        name=_norm(name),
                    )
                )
                continue
            if media_container := child.select_one(".ilc_media_cont_MediaContainer"):
                log.explain("Found image block")
                img = media_container.find(name="img")
                if not img:
                    img = media_container.find(name="embed")
                path = await downloader(img["src"])
                blocks.append(PageDesignBlockImage(image_path=path))
                continue
            if "ilc_question_" in str(child_classes):
                break

            log.warn(f"Found unknown design block: {child_classes!r}")

        return blocks

    def get_test_reconstruct_from_properties(self, questions: list[TestQuestion]) -> IliasTest:
        return IliasTest(
            title=_norm(self._soup.find(id="title").get("value", "")),
            description=_norm("".join([str(x) for x in self._soup.find(id="description").contents])),
            intro_text=_norm("".join([str(x) for x in self._soup.find(id="introduction").contents])),
            starting_time=_parse_time(self._soup.find(id="starting_time")),
            ending_time=_parse_time(self._soup.find(id="ending_time")),
            number_of_tries=int(self._soup.find(id="nr_of_tries").get("value", "100")),
            questions=questions,
        )

    def get_test_question_design_last_component_id(self) -> str:
        editor = self._soup.find(id="ilEditorTD")
        if not editor:
            raise CrawlError("Could not find editor")
        candidates: list[bs4.Tag] = list(editor.find_all(name="div", id=lambda x: x and x.startswith("pc")))
        # question is always last, so return the one before it :)
        if len(candidates) >= 2:
            last = candidates[-2]
            return last["id"].removeprefix("pc")
        return ""

    def get_scoring_settings_url(self):
        link = self._soup.find(
            name="a",
            attrs={"href": lambda x: x and "ilobjtestsettingsscoringresultsgui" in x.lower()},
        )
        if not link:
            raise CrawlError("Could not find scoring settings url on test page")
        return self._abs_url_from_link(link)

    def get_test_scoring_settings_change_data(self) -> tuple[str, set[ExtraFormData]]:
        form = self._soup.select_one("form.il-standard-form")
        if not form:
            raise CrawlError("Could not find scoring form. Is this a settings (scoring) page?")

        extra_values = self._get_extra_form_values(form)
        return self._abs_url_from_relative(form["action"]), extra_values

    def get_test_scoring_name_for_label(self, label_regex: str) -> list[str]:
        results = []
        for inp in self._soup.find_all(name="input"):
            input_id = inp.get("id", "")
            label = self._soup.find("label", attrs={"for": input_id})
            if not label or not input_id:
                continue
            if re.match(label_regex, label.getText().strip(), re.IGNORECASE):
                results.append(inp.get("name", ""))
        return results

    def get_test_scoring_dates(self) -> list[str]:
        names = []
        for inputs in self._soup.select(".date.il-input-datetime input"):
            names.append(inputs["name"])
        return names

    def get_manual_grading_per_participant_url(self):
        link = self._soup.find(name="a", attrs={"href": lambda x: x and "cmd=showManScoringParticipantsTable" in x})
        if link is not None:
            return self._abs_url_from_link(link)
        return None

    def get_manual_grading_filter_url(self):
        link = self._soup.find(id="manScorePartTable").get("action")
        return self._abs_url_from_relative(link)

    def get_manual_grading_participant_infos(self) -> list[ManualGradingParticipantInfo]:
        participants = []
        table = self._soup.find(name="table", id="manScorePartTable")
        for row in table.select("tbody > tr"):
            cols = list(row.select("td"))
            last_name = cols[0].getText().strip()
            first_name = cols[1].getText().strip()
            email = cols[2].getText().strip()
            detail_link = self._abs_url_from_link(cols[3].select_one("a"))
            participants.append(ManualGradingParticipantInfo(last_name, first_name, email, detail_link))
        return participants

    def get_manual_grading_participant_results(
        self, participant: ManualGradingParticipantInfo
    ) -> ManualGradingParticipantResults:
        questions: list[ManualGradingGradedQuestion] = []
        for question in self._soup.find_all(name="h2", string=re.compile("Frage:")):
            match = re.compile(r"\[ID: (\d+)]").search(question.getText())
            question_id = match.group(1)
            answer_type, answer_text = self._get_manual_grading_participant_answer(
                question.find_next(id="il_prop_cont_")
            )
            points = self._soup.select_one(f"#il_prop_cont_question__{question_id}__points input").get("value", "0")
            max_points = self._soup.select_one(f"#question__{question_id}__maxpoints").getText().strip()
            feedback = self._soup.select_one(f"#question__{question_id}__feedback").getText().strip()
            questions.append(
                ManualGradingGradedQuestion(
                    ManualGradingQuestion(question_id, question.getText().strip(), float(max_points), answer_type),
                    answer_text,
                    float(points),
                    feedback,
                )
            )
        return ManualGradingParticipantResults(participant, questions)

    @staticmethod
    def _get_manual_grading_participant_answer(user_answer: bs4.Tag) -> Optional[tuple[ManualGradingQuestionType, str]]:
        if text_answer := user_answer.select_one(".ilc_question_TextQuestion"):
            text_answer = text_answer.select_one(".solutionbox")
            if text_answer:
                return "freeform_text", text_answer.decode_contents()
        elif user_answer.select_one(".ilc_question_FileUpload") is not None:
            return "file_upload", "file_upload"
        return None

    def get_manual_grading_save_url(self):
        return self._form_target_from_button("cmd[saveManScoringParticipantScreen]")[0]

    @staticmethod
    def page_has_success_alert(page: "ExtendedIliasPage") -> bool:
        if ExtendedIliasPage.page_has_failure_alert(page):
            return False
        for alert in page._soup.find_all(attrs={"role": ["status", "alert"]}):
            if "alert-success" in alert.get("class", ""):
                return True
        return False

    @staticmethod
    def page_has_failure_alert(page: "ExtendedIliasPage") -> bool:
        has_danger_alert = False
        for alert in page._soup.find_all(attrs={"role": ["alert", "status"]}):
            if "alert-danger" in alert.get("class", ""):
                log.warn("Got danger alert")
                log.warn_contd("  " + alert.getText().strip())
                has_danger_alert = True
        return has_danger_alert

    def get_test_dashboard_end_all_passes_url(self) -> Optional[str]:
        link = self._soup.find(name="a", attrs={"href": lambda x: x and "cmd=finishAllUserPasses" in x})
        if not link:
            return None
        return self._abs_url_from_link(link)

    def get_test_dashboard_end_all_passes_confirm_url(self):
        return self._form_target_from_button("cmd[confirmFinishTestPassForAllUser]")[0]


def _parse_time(time_input: bs4.Tag) -> Optional[datetime.datetime]:
    time_str = time_input.get("value", None)
    if not time_str:
        return None
    return datetime.datetime.strptime(time_str, "%d.%m.%Y %H:%M")


def random_ilfilehash() -> str:
    return "".join(random.choice(string.ascii_lowercase + "0123456789") for _ in range(32))


def _norm(inpt: str) -> str:
    return inpt.strip().replace("\u00a0", " ").replace("\r\n", "\n")


def _normalize_tag_for_design_block(element: bs4.Tag):
    # remove class from <code> as ILIAS crashes otherwise
    for elem in element.find_all(name="code"):
        del elem["class"]

    for comment in element.findAll(text=lambda text: isinstance(text, bs4.Comment)):
        comment.extract()

    return _norm(element.decode_contents())
