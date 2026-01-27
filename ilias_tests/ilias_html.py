import datetime
import random
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TypeVar, cast, Callable, Awaitable

import bs4
from PFERD.crawl import CrawlError
from PFERD.crawl.ilias.kit_ilias_html import IliasPage, IliasSoup
from PFERD.logging import log
from PFERD.utils import soupify

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
    ProgrammingQuestionAnswer,
)

T = TypeVar("T")


def _(value: Optional[T]) -> T:
    """
    Unwrap an optional value, crashing if it's None.
    Named `_` for minimal verbosity: `_(soup.find(...))`.
    Use for BeautifulSoup optionals where we don't care about handling None.
    """
    assert value is not None
    return value


def __(value: None | str | bs4.element.AttributeValueList) -> str:
    """
    Unwrap an attribute value list to a string.
    Named `__` for minimal verbosity: `__(tag["class"])`.
    Use for BeautifulSoup attribute values where we don't care about handling lists.
    """
    assert value is not None
    if isinstance(value, list):
        return " ".join(value)
    return value


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
    def __init__(self, soup: IliasSoup):
        super().__init__(soup, None)

    def url(self):
        return self._page_url

    def normalized_url(self):
        return self._page_url.lower()

    def is_test_page(self):
        log.explain_topic("Verifying page is a test")
        # use classes here that are plausible for copy-pasted links
        possible_cmdclasses = (
            "cmdclass=iltestscreengui",
            "cmdclass=ilobjtestgui",
            "cmdclass=ilparticipantstestresultsgui",
            "cmdclass=iltestscoringbyquestionsgui",
        )
        for cmdclass in possible_cmdclasses:
            if cmdclass in self.normalized_url():
                log.explain("Page matched test url fragment")
                return True
        header = self._soup.find(id="headerimage")
        if not header:
            log.explain("Could not find headerimage")
            return False
        if __(header.get("alt", "")).lower() == "symbol test":
            log.explain("Alt text in header matched")
            return True
        log.explain("Alt text did not match")
        return False

    def is_test_create_page(self):
        return "cmd=create" in self.normalized_url() and "new_type=tst" in self.normalized_url()

    def is_test_question_edit_page(self):
        return "cmd=editquestion" in self.normalized_url()

    def get_test_create_url(self) -> Optional[str]:
        return self._abs_url_from_link(_(self._soup.find(id="tst")))

    def get_test_create_submit_url(self) -> tuple[str, str]:
        if not self.is_test_create_page():
            raise CrawlError("Not on test create page")
        save_button = _(self._soup.find(attrs={"name": "cmd[save]"}))
        form = _(save_button.find_parent(name="form"))
        return self._abs_url_from_relative(__(form["action"])), __(save_button["value"])

    def get_test_tabs(self) -> dict[str, str]:
        tab = self._soup.find(id="ilTab")
        if not tab:
            return {}

        result = {}
        for tab_list in _(tab.find_all(name="li")):
            if not __(tab_list["id"]).startswith("tab_"):
                continue
            link = _(tab_list.find(name="a"))

            # https://github.com/ILIAS-eLearning/ILIAS/commit/514a820e681d6f6ee66646930b7e1db1533e5141
            # added accessibility info spans of the form "(Selected)" inside the link text, remove them
            # We do not lose selection information, as that is solved via a css class on the `a` tag.
            for accHidden in link.find_all(class_="ilAccHidden"):
                accHidden.decompose()

            result[link.getText().strip()] = self._abs_url_from_link(link)

        return result

    def get_test_settings_change_data(self) -> tuple[str, set[ExtraFormData]]:
        form = self._soup.select_one("form.il-standard-form")
        if not form:
            raise CrawlError("Could not find properties page. Is this a settings page?")

        extra_values = self._get_extra_form_values(form)
        return self._abs_url_from_relative(__(form["action"])), extra_values

    def get_test_add_question_url(self):
        """Add a question to a test."""
        button = self._soup.find(attrs={"onclick": lambda x: x is not None and "cmd=addQuestion" in x})
        if not button:
            raise CrawlError("Could not find add question button")
        on_click = __(button["onclick"])
        start = on_click.find("'")
        end = on_click.rfind("'")
        return self._abs_url_from_relative(on_click[start + 1 : end])

    def get_test_question_create_url(self) -> str:
        """Enter question editor by selecting its type and information."""
        return self._form_target_from_button("cmd[executeCreateQuestion]")[0]

    def get_test_question_finalize_data(self) -> tuple[str, set[ExtraFormData]]:
        """Url for finalizing the question creation."""
        url, btn, form = self._form_target_from_button("cmd[saveReturn]")
        form_values = self._get_extra_form_values(form)
        if filehash := self._soup.find(id="ilfilehash"):
            form_values.add(ExtraFormData(name="ilfilehash", value=__(filehash.get("value")), disabled=False))
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
                    name=__(inpt["name"]),
                    value=__(inpt.get("value", "")),
                    disabled=inpt.get("disabled", None) is not None,
                )
            )
        for inpt in form.find_all(name="textarea", attrs={"required": "required"}):
            extra_values.add(
                ExtraFormData(
                    name=__(inpt["name"]),
                    value=__(inpt.get("value", "")),
                    disabled=inpt.get("disabled", None) is not None,
                )
            )
        for select in form.find_all(name="select"):
            extra_values.add(
                ExtraFormData(
                    name=__(select["name"]),
                    value=__(_(select.find(name="option", attrs={"selected": "selected"})).get("value", "")),
                    disabled=select.get("disabled", None) is not None,
                )
            )

        for inpt in form.find_all(name="input", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=__(inpt["name"]), value="", disabled=True))
        for select in form.find_all(name="select", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=__(select["name"]), value="", disabled=True))
        for select in form.find_all(name="textarea", attrs={"disabled": "disabled"}):
            extra_values.add(ExtraFormData(name=__(select["name"]), value="", disabled=True))

        return extra_values

    def _form_target_from_button(self, button_name: str):
        btn = self._soup.find(attrs={"name": button_name})
        if not btn:
            raise CrawlError(f"Could not find {button_name!r} button")
        form = _(btn.find_parent(name="form"))
        return self._abs_url_from_relative(__(form["action"])), btn, form

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
        table = self._soup.find(name="table", id=lambda x: x is not None and x.startswith("tst_qst_lst"))
        if not table:
            raise CrawlError("Did not find questions table")
        result = []
        for row in _(table.find(name="tbody")).find_all(name="tr"):
            if len(row.find_all(name="td")) == 1:
                # probably "no questions" row
                log.explain(f"Skipping row with single td: {row}")
                continue

            order_td = row.find(name="td", attrs={"name": lambda x: x is not None and x.startswith("order[")})
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
            "cmd[saveOrderAndObligations]": "Sortierung+abspeichern",
        }
        for question_id, value in question_to_position.items():
            data[f"order[{question_id}]"] = value
        log.explain(f"Setting order {data}")
        return url, data

    def get_test_question_listing(self) -> list[tuple[str, str]]:
        """Returns [(title, url)] for all questions in a test."""
        result = []
        for _, link in self._get_test_question_ids_and_links():
            result.append((link.getText().strip(), self._abs_url_from_link(link)))
        return result

    def get_test_question_edit_url(self):
        return self._abs_url_from_link(
            _(self._soup.find(name="a", attrs={"href": lambda x: x is not None and "cmd=editQuestion" in x}))
        )

    def get_test_question_reconstruct_from_edit(self, page_design: list[PageDesignBlock]):
        if "cmd=editquestion" not in self.normalized_url():
            raise CrawlError("Not on question edit page")
        title = _norm(__(_(self._soup.find(id="title"))["value"]).strip())
        author = _norm(__(_(self._soup.find(id="author"))["value"]).strip())
        comment = self._soup.find(id="comment")
        summary = _norm(__(comment.get("value", "") if comment else "").strip())
        question = self._soup.find(id="question")
        question_html = _norm(question.getText().strip() if question else "")

        if "asstextquestiongui" in self.normalized_url():
            # free from text
            points = float(__(_(self._soup.find(id="non_keyword_points"))["value"]).strip())
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
            max_size_bytes = int(__(_(self._soup.find(id="maxsize")).get("value", "2097152")).strip())
            allowed_extensions = __(_(self._soup.find(id="allowedextensions")).get("value", "")).strip().split(",")
            points = float(__(_(self._soup.find(id="points"))["value"]).strip())
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
            shuffle = True if _(self._soup.find(id="shuffle")).get("checked", None) else False
            answer_table = _(
                self._soup.find(name="table", attrs={"class": lambda x: x is not None and "singlechoicewizard" in x})
            )
            answers = []
            for inpt in answer_table.find_all(
                name="input", id=lambda x: x is not None and x.startswith("choice[answer]")
            ):
                answer_value = _norm(__(inpt.get("value", "")))
                answer_points = float(
                    __(_(answer_table.find(id=__(inpt["id"]).replace("answer", "points"))).get("value", "0")).strip()
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
            shuffle = True if _(self._soup.find(id="shuffle")).get("checked", None) else False
            selection_limit = _(self._soup.find(id="selection_limit")).get("value", None)
            if selection_limit is not None:
                selection_limit = int(__(selection_limit))
            answer_table = _(
                self._soup.find(name="table", attrs={"class": lambda x: x is not None and "multiplechoicewizard" in x})
            )
            answers = []
            for inpt in answer_table.find_all(
                name="input", id=lambda x: x is not None and x.startswith("choice[answer]")
            ):
                answer_value = _norm(__(inpt.get("value", "")))
                answer_points_checked = float(
                    __(_(answer_table.find(id=__(inpt["id"]).replace("answer", "points"))).get("value", "0")).strip()
                )
                answer_points_unchecked = float(
                    __(
                        _(answer_table.find(id=__(inpt["id"]).replace("answer", "points_unchecked"))).get("value", "0")
                    ).strip()
                )
                answers.append(
                    QuestionMultipleChoice.Answer(answer_value, answer_points_checked, answer_points_unchecked)
                )

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
        button = self._soup.find(
            attrs={"data-action": lambda x: x is not None and "cmdclass=ilassquestionpagegui" in x.lower()}
        )
        if not button:
            raise CrawlError("Could not find page edit button")
        return self._abs_url_from_relative(__(button.get("data-action")))

    def get_test_question_design_post_url(self) -> tuple[str, str]:
        """
        Returns the post endpoint from the 'Design page' page.
        First url is the base for text and images, the second for e.g. code
        """
        init_el = _(self._soup.find(id="il-copg-init"))
        base_url = __(init_el.get("data-endpoint"))
        post_url = self._abs_url_from_relative(__(init_el.get("data-formaction")))
        return base_url, post_url

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
            child_classes = cast(list[str], child.get("class", []))  # type: ignore

            if "ilc_page_title_PageTitle" in cast(list[str], child_classes):
                after_start = True
                continue
            if not after_start:
                continue
            if "ilc_Paragraph" in child_classes:
                log.explain("Found text block")
                blocks.append(PageDesignBlockText(_normalize_tag_for_design_block(child)))
                continue
            if "ilc_Code" in child_classes:
                log.explain("Found code block")
                code = _(child.select_one("table .ilc_Sourcecode .ilc_code_block_Code"))
                for br in code.find_all(name="br"):
                    br.replace_with("\n")
                download_link = child.find(
                    name="a", attrs={"href": lambda x: x is not None and "cmd=download_paragraph" in x}
                )
                name = "unknown.c"
                if download_link:
                    if match := re.search(r"downloadtitle=([^&]+)", __(download_link["href"])):
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
                path = await downloader(__(_(img)["src"]))
                blocks.append(PageDesignBlockImage(image_path=path))
                continue
            if "ilc_question_" in str(child_classes):
                break

            log.warn(f"Found unknown design block: {child_classes!r}")

        return blocks

    def get_test_reconstruct_from_properties(self, questions: list[TestQuestion]) -> IliasTest:
        title_elem = self._get_form_input_by_label_prefix("Titel*")
        description_elem = self._get_form_input_by_label_prefix("Zusammenfassung")
        # intro_elem = self._get_form_input_by_label_prefix("Zusammenfassung")
        starting_time_elem = self._get_form_input_by_label_prefix("Start", ".il-section-input > .form-group > label")
        ending_time_elem = self._get_form_input_by_label_prefix("Ende", ".il-section-input > .form-group > label")
        number_of_tries_elem = self._get_form_input_by_label_prefix("Maximale Anzahl von Testdurchläufen")
        return IliasTest(
            title=_norm(__(title_elem.get("value", ""))),
            description=_norm("".join([str(x) for x in _(description_elem).contents])),
            intro_text=_norm("".join([str(x) for x in _(description_elem).contents])),
            starting_time=_parse_time(_(starting_time_elem)),
            ending_time=_parse_time(_(ending_time_elem)),
            number_of_tries=int(__(_(number_of_tries_elem).get("value", "100"))),
            questions=questions,
        )

    def _get_form_input_by_label_prefix(self, label_prefix: str, selector: str = "label") -> bs4.Tag:
        candidates = []
        for label in self._soup.select(selector):
            text = label.get_text().strip()
            if text.startswith(label_prefix):
                input_id = label.get("for", None)
                if not input_id:
                    raise CrawlError(f"Label for {label_prefix!r} has no 'for' attribute")
                input_element = self._soup.find(id=input_id)
                if not input_element:
                    raise CrawlError(f"Could not find input element with id {input_id!r} for label {label_prefix!r}")
                candidates.append(input_element)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise CrawlError(f"Found multiple candidates for label with prefix {label_prefix!r}")
        raise CrawlError(f"Could not find label with prefix {label_prefix!r}")

    def get_form_input_from_label_path(
        self, label_match: str | re.Pattern, section_title: str | None = None, selector: str = "label"
    ):
        match_source: bs4.Tag
        if section_title is not None:
            for title in self._soup.select(".il-section-input-header > h2"):
                if title.get_text().strip() == section_title:
                    match_source = _(title.find_parent(class_="il-section-input"))
                    break
            else:
                raise CrawlError(f"Could not find section with title {section_title!r}")
        else:
            match_source = self._soup

        candidates = []
        for label in match_source.select(selector):
            text = label.get_text().strip()
            if isinstance(label_match, str):
                matches = text == label_match
            else:
                matches = re.match(label_match, text) is not None
            if not matches:
                continue
            input_id = label.get("for", None)
            if not input_id:
                log.explain(f"Label {text!r} has no 'for' attribute, skipping")
                continue
            input_element = self._soup.find(id=input_id)
            if not input_element:
                log.explain(f"Could not find input element with id {input_id!r} for label {text!r}, skipping")
                continue
            candidates.append(input_element)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise CrawlError(f"Found multiple candidates for label with match {label_match!r}")
        raise CrawlError(f"Could not find label with match {label_match!r}")

    def get_test_question_design_last_component_id(self) -> str:
        editor = self._soup.find(id="ilEditorTD")
        if not editor:
            raise CrawlError("Could not find editor")
        candidates: list[bs4.Tag] = list(editor.find_all(name="div", id=lambda x: x is not None and x.startswith("pc")))
        # question is always last, so return the one before it :)
        if len(candidates) >= 2:
            last = candidates[-2]
            return __(last["id"]).removeprefix("pc")
        return ""

    def get_scoring_settings_url(self):
        link = self._soup.find(
            name="a",
            attrs={"href": lambda x: x is not None and "ilobjtestsettingsscoringresultsgui" in x.lower()},
        )
        if not link:
            raise CrawlError("Could not find scoring settings url on test page")
        return self._abs_url_from_link(link)

    def get_test_scoring_settings_change_data(self) -> tuple[str, set[ExtraFormData]]:
        form = self._soup.select_one("form.il-standard-form")
        if not form:
            raise CrawlError("Could not find scoring form. Is this a settings (scoring) page?")

        extra_values = self._get_extra_form_values(form)
        return self._abs_url_from_relative(__(form["action"])), extra_values

    def get_test_scoring_name_for_label(self, label_regex: str) -> list[str]:
        results = []
        for inp in self._soup.find_all(name="input"):
            input_id = inp.get("id", "")
            label = self._soup.find("label", attrs={"for": input_id})  # type: ignore
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
        link = self._soup.find(
            name="a", attrs={"href": lambda x: x is not None and "cmd=showManScoringParticipantsTable" in x}
        )
        if link is not None:
            return self._abs_url_from_link(link)
        return None

    def get_manual_grading_filter_url(self):
        link = _(self._soup.find(id="manScorePartTable")).get("action")
        return self._abs_url_from_relative(__(link))

    def get_manual_grading_participant_infos(self) -> list[ManualGradingParticipantInfo]:
        participants = []
        table = _(self._soup.find(name="table", id="manScorePartTable"))
        rows = list(table.select("tbody > tr"))

        # No participant results, only a single row with a single td containing the text "no results"
        if len(rows) == 1 and len(rows[0].select("td")) == 1:
            log.explain("Participant table had no results")
            return []

        for row in rows:
            cols = list(row.select("td"))
            last_name = cols[0].getText().strip()
            first_name = cols[1].getText().strip()
            email = cols[2].getText().strip()
            username = email.split("@")[0]
            detail_link = self._abs_url_from_link(_(cols[3].select_one("a")))
            participants.append(ManualGradingParticipantInfo(last_name, first_name, email, username, detail_link))
        return participants

    def get_manual_grading_participant_results(
        self, participant: ManualGradingParticipantInfo
    ) -> ManualGradingParticipantResults:
        questions: list[ManualGradingGradedQuestion] = []
        for question in self._soup.find_all(name="h2", string=re.compile("Frage:")):  # type: ignore
            match = re.compile(r"\[ID: (\d+)]").search(question.getText())
            question_id = match.group(1)  # type: ignore
            answer_type, answer_value = self._get_manual_grading_participant_answer(
                _(question.find_next(id="il_prop_cont_"))
            )  # type: ignore
            points = _(self._soup.select_one(f"#il_prop_cont_question__{question_id}__points input")).get("value", "0")
            max_points = _(self._soup.select_one(f"#question__{question_id}__maxpoints")).getText().strip()
            feedback_element = _(self._soup.select_one(f"[name=question__{question_id}__feedback]"))

            match feedback_element.name:
                # The feedback hasn't been finalized yet => It is represented as a text area
                case "textarea":
                    feedback = feedback_element.getText().strip()
                case "input":
                    feedback = cast(str | None, feedback_element.get("value"))
                case _:
                    # Should be unreachable, until ILIAS decides to toss things up
                    raise CrawlError(f"Unknown feedback element type: {feedback_element.name}")

            if feedback == "":
                feedback = None

            is_final_feedback = feedback_element.name == "input"

            questions.append(
                ManualGradingGradedQuestion(
                    ManualGradingQuestion(question_id, question.getText().strip(), float(max_points), answer_type),
                    answer_value,
                    float(__(points)),
                    feedback,
                    is_final_feedback,
                )
            )
        return ManualGradingParticipantResults(participant, questions)

    @staticmethod
    def _get_manual_grading_participant_answer(
        user_answer: bs4.Tag,
    ) -> Optional[tuple[ManualGradingQuestionType, str | list[ProgrammingQuestionAnswer]]]:
        if text_answer := user_answer.select_one(".ilc_question_TextQuestion"):
            text_answer = text_answer.select_one(".ilc_qanswer_Answer")
            if text_answer:
                return "freeform_text", text_answer.decode_contents()
        elif file_answer := user_answer.select_one(".ilc_question_FileUpload"):
            downloadables = [(file.getText().strip(), __(file["href"])) for file in file_answer.select('[download=""]')]
            return "file_upload", [ProgrammingQuestionAnswer(name, uri) for name, uri in downloadables]
        return None

    def get_manual_grading_save_url(self):
        return self._form_target_from_button("cmd[saveManScoringParticipantScreen]")[0]

    @staticmethod
    def page_has_success_alert(page: "ExtendedIliasPage") -> bool:
        if ExtendedIliasPage.page_has_failure_alert(page):
            return False
        for alert in page._soup.find_all(attrs={"role": ["status", "alert"]}):
            if "alert-success" in __(alert.get("class", "")):
                return True
        return False

    @staticmethod
    def page_has_failure_alert(page: "ExtendedIliasPage") -> bool:
        has_danger_alert = False
        for alert in page._soup.find_all(attrs={"role": ["alert", "status"]}):
            if "alert-danger" in __(alert.get("class", "")):
                log.warn("Got danger alert")
                log.warn_contd("  " + alert.getText().strip())
                has_danger_alert = True
        return has_danger_alert

    def get_test_dashboard_end_all_passes_url(self) -> Optional[str]:
        link = self._soup.find(
            name="button", attrs={"data-action": lambda x: x is not None and "cmd=finishalluserpasses" in x.lower()}
        )
        if not link:
            return None
        return self._abs_url_from_relative(__(link.get("data-action")))

    def get_test_dashboard_end_all_passes_confirm_url(self):
        return self._form_target_from_button("cmd[confirmFinishTestPassForAllUser]")[0]

    def get_intro_text_page_url(self) -> str:
        if link := self._soup.select_one("#subtab_edit_introduction a"):
            return self._abs_url_from_link(link)

        raise CrawlError("Could not find intro text page link")

    def get_intro_text_design_url(self) -> str:
        btn = self._soup.find(
            "button",
            attrs={"data-action": lambda x: x is not None and "cmd=edit" in x.lower()},
        )
        if not btn:
            raise CrawlError("Could not find intro text design button")
        return self._abs_url_from_relative(__(btn.get("data-action")))


def _parse_time(time_input: bs4.Tag) -> Optional[datetime.datetime]:
    time_str = time_input.get("value", None)
    if not time_str:
        return None
    return datetime.datetime.strptime(cast(str, time_str), "%Y-%m-%d %H:%M")


def random_ilfilehash() -> str:
    return "".join(random.choice(string.ascii_lowercase + "0123456789") for _ in range(32))


def _norm(inpt: str) -> str:
    return inpt.strip().replace("\u00a0", " ").replace("\r\n", "\n")


def _normalize_tag_for_design_block(element: bs4.Tag):
    # remove class from <code> as ILIAS crashes otherwise
    for elem in element.find_all(name="code"):
        del elem["class"]

    for comment in element.find_all(text=lambda text: isinstance(text, bs4.Comment)):
        comment.extract()

    for emph in element.find_all("em"):
        emph.name = "span"
        classes = emph.get_attribute_list("class")
        if "ilc_em_Emph" in classes:
            classes.remove("ilc_em_Emph")
        classes.append("ilc_text_inline_Emph")
        emph["class"] = classes

    for strong in element.find_all("strong"):
        strong.name = "span"
        classes = strong.get_attribute_list("class")
        if "ilc_strong_Strong" in classes:
            classes.remove("ilc_strong_Strong")
        classes.append("ilc_text_inline_Strong")
        strong["class"] = classes

    return _norm(element.decode_contents())


def raw_html_to_page_design(html: str) -> list[PageDesignBlock]:
    soup = soupify(html.encode())
    blocks = []

    headings = {
        "h1": PageDesignBlockText.Characteristic.Heading1,
        "h2": PageDesignBlockText.Characteristic.Heading2,
        "h3": PageDesignBlockText.Characteristic.Heading3,
    }

    for elem in soup.children:
        if not isinstance(elem, bs4.Tag):
            log.explain(f"Skipping non-tag element {repr(elem)}")
            continue
        if elem.name in headings:
            blocks.append(
                PageDesignBlockText(_normalize_tag_for_design_block(elem), characteristic=headings[elem.name])
            )
            continue
        blocks.append(PageDesignBlockText(_normalize_tag_for_design_block(elem)))

    return blocks
