from typing import Optional, cast

import bs4
from PFERD.crawl import CrawlError
from PFERD.crawl.ilias.kit_ilias_html import IliasPage
from PFERD.logging import log
from bs4 import BeautifulSoup


class ExtendedIliasPage(IliasPage):
    def __init__(self, soup: BeautifulSoup, _page_url: str):
        super().__init__(soup, _page_url, None)

    def url(self):
        return self._page_url

    def is_test_create_page(self):
        return "cmd=create" in self._page_url and "new_type=tst" in self._page_url

    def is_test_question_edit_page(self):
        return "cmd=editQuestion" in self._page_url

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

    def get_test_settings_change_data(self) -> tuple[str, dict[str, str]]:
        form = self._soup.find(id="form_test_properties")
        if not form:
            raise CrawlError("Could not find properties page. Is this a settings page?")

        extra_values = self._get_extra_form_values(form)
        extra_values["ilfilehash"] = form.find(id="ilfilehash")["value"]
        return self._abs_url_from_relative(form["action"]), extra_values

    def get_test_add_question_url(self):
        """Add a question to a test."""
        button = self._soup.find(attrs={"onclick": lambda x: x and "cmd=addQuestion" in x})
        if not button:
            raise CrawlError("Could not find add question button")
        start = button["onclick"].find("'")
        end = button["onclick"].rfind("'")
        return self._abs_url_from_relative(button["onclick"][start + 1:end])

    def get_test_question_create_url(self) -> str:
        """Enter question editor by selecting its type and information."""
        return self._form_target_from_button("cmd[executeCreateQuestion]")[0]

    def get_test_question_finalize_data(self) -> tuple[str, dict[str, str]]:
        """Url for finalizing the question creation."""
        url, btn, form = self._form_target_from_button("cmd[saveReturn]")
        return url, self._get_extra_form_values(form)

    @staticmethod
    def _get_extra_form_values(form: bs4.Tag):
        extra_values = {}
        for inpt in form.find_all(name="input", attrs={"required": "required"}):
            extra_values[inpt["name"]] = inpt.get("value", "")
        for select in form.find_all(name="select"):
            extra_values[select["name"]] = select.find(name="option", attrs={"selected": "selected"}).get("value", "")
        return extra_values

    def _form_target_from_button(self, button_name: str):
        btn = self._soup.find(attrs={"name": button_name})
        if not btn:
            raise CrawlError("Could not find create button")
        form = btn.find_parent(name="form")
        return self._abs_url_from_relative(form["action"]), btn, form

    def get_test_question_after_values(self):
        position_select = self._soup.find(id="position")
        if not position_select:
            raise CrawlError("Could not find element")
        results = {}
        for select in position_select.find_all("option"):
            text: str = select.getText().strip()
            if "Nach" in text:
                title = text[len("Nach"):text.rfind("[")].strip()
                results[title] = select["value"]
        return results

    def get_test_question_ids(self) -> dict[str, str]:
        if "cmd=questions" not in self._page_url or "ilobjtestgui" not in self._page_url:
            raise CrawlError("Not on test question page")
        table = self._soup.find(name="table", id=lambda x: x and x.startswith("tst_qst_lst"))
        if not table:
            raise CrawlError("Did not find questions table")
        ids = {}
        for row in table.find(name="tbody").find_all(name="tr"):
            order_td = row.find(name="td", attrs={"name": lambda x: x and x.startswith("order[")})
            question_id = cast(str, order_td["name"]).replace("order[", "").replace("]", "").strip()
            title = row.find(name="a").getText().strip()
            ids[title] = question_id

        return ids

    def get_test_question_save_order_data(self, question_to_position: dict[str, str]) -> tuple[str, dict[str, str]]:
        url, _, _ = self._form_target_from_button("cmd[saveOrderAndObligations]")
        data = {
            "cmd[saveOrderAndObligations]": "Sortierung abspeichern",
        }
        for question_id, value in question_to_position.items():
            data[f"order[q_{question_id}]"] = value
        return url, data

    @staticmethod
    def page_has_success_alert(page: 'ExtendedIliasPage') -> bool:
        for alert in page._soup.find_all(attrs={"role": "alert"}):
            if "alert-danger" in alert.get("class", ""):
                log.warn("Got danger alert")
                log.warn_contd(alert.getText().strip())
                return False
        for alert in page._soup.find_all(attrs={"role": "alert"}):
            if "alert-success" in alert.get("class", ""):
                return True
        return False
