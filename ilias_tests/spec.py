import abc
import datetime
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Union, Literal

import yaml
from PFERD.crawl import CrawlError
from PFERD.logging import log
from markdownify import markdownify
from slugify import slugify


class QuestionType(Enum):
    SINGLE_CHOICE = 1
    FREE_FORM_TEXT = 8
    FILE_UPLOAD = 14


class TestTab(Enum):
    SETTINGS = ("Settings", "Einstellungen")
    PARTICIPANTS = ("Participants", "Teilnehmer")
    QUESTIONS = ("Questions", "Fragen")
    MANUAL_GRADING = ("", "Manuelle Bewertung")


def str_presenter(dumper, data):
    """
    Configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data
    Ref: https://github.com/yaml/pyyaml/issues/240#issuecomment-1096224358
    """
    if data.count("\n") > 0 or data.count("<p>") > 0:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


def load_freeform_question(
    title: str, author: str, summary: str, question_html: str, page_design: list["PageDesignBlock"], yml: dict[Any, Any]
):
    return QuestionFreeFormText(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        page_design=page_design,
        points=yml["points"],
    )


def load_upload_file_question(
    title: str, author: str, summary: str, question_html: str, page_design: list["PageDesignBlock"], yml: dict[Any, Any]
):
    return QuestionUploadFile(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        page_design=page_design,
        points=yml["points"],
        allowed_extensions=yml["allowed_filetypes"],
        max_size_bytes=eval(str(yml["max_bytes"])),
    )


def load_single_choice_question(
    title: str, author: str, summary: str, question_html: str, page_design: list["PageDesignBlock"], yml: dict[Any, Any]
):
    answers: list[tuple[str, float]] = []
    for elem in yml["answers"]:
        answers.append((elem["answer"], elem["points"]))

    return QuestionSingleChoice(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        page_design=page_design,
        shuffle=yml["shuffle"],
        answers=answers,
    )


class PageDesignBlock(abc.ABC):
    @abc.abstractmethod
    def serialize(self) -> dict[str, Any]: ...

    @staticmethod
    def deserialize(yml: dict[str, Any]):
        if "type" not in yml:
            raise CrawlError("Could not find 'type' for block")
        if yml["type"] == "text":
            return PageDesignBlockText.deserialize(yml)
        elif yml["type"] == "image":
            return PageDesignBlockImage.deserialize(yml)
        elif yml["type"] == "code":
            return PageDesignBlockCode.deserialize(yml)
        else:
            raise CrawlError(f"Unknown type {yml['type']!r}")


class PageDesignBlockText(PageDesignBlock):
    def __init__(self, text_html: str):
        self.text_html = text_html

    def serialize(self):
        return {"text": self.text_html, "type": "text"}

    @staticmethod
    def deserialize(yml: dict[str, Any]) -> "PageDesignBlockText":
        return PageDesignBlockText(yml["text"])


class PageDesignBlockImage(PageDesignBlock):
    def __init__(self, image_path: Path):
        self.image = image_path

    def serialize(self) -> dict[str, Any]:
        return {"path": str(self.image), "type": "image"}

    @staticmethod
    def deserialize(yml: dict[str, Any]) -> "PageDesignBlockImage":
        return PageDesignBlockImage(Path(yml["path"]))


class PageDesignBlockCode(PageDesignBlock):
    def __init__(self, code: str, language: str, name: str):
        self.code = code
        self.language = language
        self.name = name

    def serialize(self) -> dict[str, Any]:
        return {"code": self.code, "language": self.language, "name": self.name, "type": "code"}

    @staticmethod
    def deserialize(yml: dict[str, Any]) -> "PageDesignBlockCode":
        return PageDesignBlockCode(yml["code"], yml["language"], yml["name"])


class TestQuestion(abc.ABC):
    def __init__(
        self,
        title: str,
        author: str,
        summary: str,
        question_html: str,
        question_type: QuestionType,
        page_design: list[PageDesignBlock],
    ):
        self.title = title
        self.author = author
        self.summary = summary
        self.question_html = question_html
        self.question_type = question_type
        self.page_design = page_design

    def get_options(self) -> dict[str, Union[str, Path]]:
        return {
            "title": self.title,
            "author": self.author,
            "comment": self.summary,
            "lifecycle": "draft",
            "question": self.question_html,
        }

    def serialize(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "summary": self.summary,
            "question_html": self.question_html,
            "page_design": [block.serialize() for block in self.page_design],
        }

    @staticmethod
    def deserialize(yml: dict[Any, Any]) -> "TestQuestion":
        str_type = yml["type"]
        title = yml["title"]
        author = yml["author"]
        summary = yml["summary"]
        question_html = yml["question_html"]
        page_design = [PageDesignBlock.deserialize(x) for x in yml["page_design"]]

        if str_type == "file_upload":
            return load_upload_file_question(title, author, summary, question_html, page_design, yml)
        elif str_type == "freeform_text":
            return load_freeform_question(title, author, summary, question_html, page_design, yml)
        elif str_type == "single_choice":
            return load_single_choice_question(title, author, summary, question_html, page_design, yml)
        else:
            raise CrawlError(f"Unknown question type {str_type}")


class QuestionFreeFormText(TestQuestion):
    def __init__(
        self,
        title: str,
        author: str,
        summary: str,
        question_html: str,
        points: float,
        page_design: list[PageDesignBlock],
    ):
        super().__init__(title, author, summary, question_html, QuestionType.FREE_FORM_TEXT, page_design)
        self.points = points

    def get_options(self) -> dict[str, Union[str, Path]]:
        return {
            **super().get_options(),
            "scoring_mode": "non",  # manual
            "non_keyword_points": str(self.points),
            "all_keyword_points": str(self.points),
            "one_keyword_points": str(self.points),
        }

    def serialize(self) -> dict[str, Any]:
        return {**super().serialize(), "points": self.points, "type": "freeform_text"}


class QuestionUploadFile(TestQuestion):
    def __init__(
        self,
        title: str,
        author: str,
        summary: str,
        question_html: str,
        page_design: list[PageDesignBlock],
        points: float,
        allowed_extensions: list[str],
        max_size_bytes: int,
    ):
        super().__init__(title, author, summary, question_html, QuestionType.FILE_UPLOAD, page_design)
        self.points = points
        self.allowed_extensions = allowed_extensions
        self.max_size_bytes = max_size_bytes

    def get_options(self) -> dict[str, Union[str, Path]]:
        return {
            **super().get_options(),
            "allowedextensions": ",".join(self.allowed_extensions),
            "maxsize": str(self.max_size_bytes),
            "points": str(self.points),
        }

    def serialize(self) -> dict[str, Any]:
        return {
            **super().serialize(),
            "allowed_filetypes": self.allowed_extensions,
            "max_bytes": self.max_size_bytes,
            "points": self.points,
            "type": "file_upload",
        }


class QuestionSingleChoice(TestQuestion):
    def __init__(
        self,
        title: str,
        author: str,
        summary: str,
        question_html: str,
        page_design: list[PageDesignBlock],
        shuffle: bool,
        answers: list[tuple[str, float]],
    ):
        super().__init__(title, author, summary, question_html, QuestionType.SINGLE_CHOICE, page_design)
        self.shuffle = shuffle
        self.answers = answers

    def get_options(self) -> dict[str, Union[str, Path]]:
        # choice[answer][0]
        # choice[image][0]"; filename="", octet-stream
        # choice[points][0]
        answer_options: dict[str, Union[str, Path]] = {}
        for index, (answer, points) in enumerate(self.answers):
            answer_options[f"choice[answer][{index}]"] = answer
            answer_options[f"choice[answer_id][{index}]"] = "-1"
            answer_options[f"choice[image][{index}]"] = Path("")
            answer_options[f"choice[points][{index}]"] = str(points)

        return {
            **super().get_options(),
            **answer_options,
            "shuffle": "1" if self.shuffle else "0",
            "types": "0",  # single line answers for now
            "thumb_size": "150",  # image preview size. Not supported for now.
        }

    def serialize(self) -> dict[str, Any]:
        answers = []
        for title, points in self.answers:
            answers.append({"answer": title, "points": points})

        return {**super().serialize(), "answers": answers, "shuffle": self.shuffle, "type": "single_choice"}


@dataclass
class IliasTest:
    title: str
    description: str
    intro_text: str
    starting_time: Optional[datetime.datetime]
    ending_time: Optional[datetime.datetime]
    number_of_tries: int

    questions: list[TestQuestion]

    def serialize(self, questions_title_to_id: dict[str, str]) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "intro_text": self.intro_text,
            "starting_time": self.starting_time,
            "ending_time": self.ending_time,
            "number_of_tries": self.number_of_tries,
            "questions": [questions_title_to_id[question.title] for question in self.questions],
        }

    @staticmethod
    def deserialize(yml: dict[str, Any], test_questions: list[TestQuestion]):
        start_time = yml["starting_time"]
        end_time = yml["ending_time"]
        return IliasTest(
            title=yml["title"],
            description=yml["description"],
            intro_text=yml["intro_text"],
            starting_time=eval(start_time) if isinstance(start_time, str) else start_time,
            ending_time=eval(end_time) if isinstance(end_time, str) else end_time,
            number_of_tries=yml["number_of_tries"],
            questions=test_questions,
        )


@dataclass
class Spec:
    tests: list[IliasTest]


def load_spec_from_file(path: Path) -> Spec:
    with open(path, "r") as file:
        data = yaml.safe_load(file)
    questions: dict[str, TestQuestion] = {}

    for key, question in data["questions"].items():
        questions[key] = TestQuestion.deserialize(question)

    tests = []
    for key, test in data["tests"].items():
        test_questions = [questions[val] for val in test["questions"]]
        tests.append(IliasTest.deserialize(test, test_questions))

    return Spec(tests=tests)


def dump_questions_to_yml_dict(questions: list[TestQuestion]) -> dict[str, Any]:
    outer = {}
    for question in questions:
        slug = slugify(question.title)
        yml_dict = question.serialize()
        outer[slug] = yml_dict
    return outer


def dump_tests_to_yml(tests: list[IliasTest]) -> str:
    questions = [question for test in tests for question in test.questions]

    question_title_to_id = {}
    for question in questions:
        question_title_to_id[question.title] = slugify(question.title)

    tests_dict = {}
    for test in tests:
        slug = slugify(test.title)
        yml_dict = test.serialize(question_title_to_id)
        tests_dict[slug] = yml_dict

    return yaml.safe_dump(
        {"tests": tests_dict, "questions": dump_questions_to_yml_dict(questions)}, indent=2, allow_unicode=True
    )


def filter_with_regex(element: str, regex: str) -> bool:
    result = re.fullmatch(regex, element) is not None
    log.explain(f"Keep {element!r} for regex {regex!r}? {'Yes' if result else 'No'}")
    return result


#  ____       _                 _                     _
# | __ )  ___| | _____      __ | |__   ___ _ __ ___  (_)___
# |  _ \ / _ \ |/ _ \ \ /\ / / | '_ \ / _ \ '__/ _ \ | / __|
# | |_) |  __/ | (_) \ V  V /  | | | |  __/ | |  __/ | \__ \
# |____/ \___|_|\___/ \_/\_/   |_| |_|\___|_|  \___| |_|___/
#
#                   _                                                 _
#   __ _  __ _ _ __| |__   __ _  __ _  ___     _   _ ___  ___    __ _| |_
#  / _` |/ _` | '__| '_ \ / _` |/ _` |/ _ \   | | | / __|/ _ \  / _` | __|
# | (_| | (_| | |  | |_) | (_| | (_| |  __/_  | |_| \__ \  __/ | (_| | |_
#  \__, |\__,_|_|  |_.__/ \__,_|\__, |\___( )  \__,_|___/\___|  \__,_|\__|
#  |___/                        |___/     |/
#                             _     _
#   _____      ___ __    _ __(_)___| | __
#  / _ \ \ /\ / / '_ \  | '__| / __| |/ /
# | (_) \ V  V /| | | | | |  | \__ \   <
#  \___/ \_/\_/ |_| |_| |_|  |_|___/_|\_\


@dataclass
class ManualGradingParticipantInfo:
    last_name: str
    first_name: str
    email: str
    detail_link: str

    def format_name(self) -> str:
        return f"{self.email} ({self.last_name}, {self.first_name})"


ManualGradingQuestionType = Literal["single_choice", "freeform_text", "file_upload"]


@dataclass(unsafe_hash=True)
class ManualGradingQuestion:
    id: str
    text: str
    max_points: float
    question_type: ManualGradingQuestionType


@dataclass
class ManualGradingGradedQuestion:
    question: ManualGradingQuestion
    answer: str
    points: float
    feedback: str


@dataclass
class ManualGradingParticipantResults:
    participant: ManualGradingParticipantInfo
    answers: list[ManualGradingGradedQuestion]

    def get_question(self, question_id: str) -> Optional[ManualGradingGradedQuestion]:
        for question in self.answers:
            if question.question.id == question_id:
                return question
        return None


def manual_grading_write_question_md(
    results: list[ManualGradingParticipantResults], question: ManualGradingQuestion, convert_to_markdown: bool = True
) -> str:
    md = f"# {question.text}\n\n"

    def convert(text: str) -> str:
        if not convert_to_markdown:
            return text
        # Remove spaces between <p> tags
        text = re.sub(r"\s+<p>", "<p>", text)
        return markdownify(text, escape_misc=False, escape_underscore=False, escape_asterisks=False).strip()

    for result in results:
        participant = result.participant
        if question_result := result.get_question(question.id):
            md += f"## {participant.format_name()}\n\n"
            md += f"### Answer {question_result.points} / {question.max_points}\n"
            md += "```\n"
            md += convert(question_result.answer)
            md += "\n```\n"
            md += "----\n"
            if question.question_type == "file_upload":
                # Already formatted
                md += f"{question_result.feedback.strip()}\n\n"
            else:
                md += f"{convert(question_result.feedback).strip()}\n\n"

    return md


class StringReader:
    underlying: str
    position: int

    def __init__(self, underlying: str):
        self.underlying = underlying
        self.position = 0

    def read_until(self, pattern: str) -> str:
        pos = self.underlying.find(pattern, self.position)
        if pos < 0:
            raise ValueError("Pattern not found")
        result = self.underlying[self.position : pos]
        self.position = pos + len(pattern)
        return result

    def read_line(self) -> str:
        return self.read_until("\n")

    def skip_blank_lines(self):
        while self.has_more() and self.underlying[self.position] == "\n":
            self.position += 1

    def read_rest(self) -> str:
        result = self.underlying[self.position :]
        self.position = len(self.underlying)
        return result

    def has_more(self):
        return self.position < len(self.underlying)

    def can_find(self, pattern: str) -> bool:
        return self.underlying.find(pattern, self.position) >= 0


def load_manual_grading_results_from_md(folder: Path) -> dict[str, ManualGradingParticipantResults]:
    participant_results = dict()
    for question_md in folder.glob("*.md"):
        question_id = str(question_md.name).replace(".md", "")
        with open(question_md, "r") as f:
            content = f.read()
        question_results = _parse_manual_grading_question_file(question_id, content)
        students = _parse_students_from_md(content)

        for email, result in question_results.items():
            if email not in participant_results:
                participant_results[email] = ManualGradingParticipantResults(students[email], [])
            participant_results[email].answers.append(result)

    return participant_results


def _parse_students_from_md(text: str):
    results = dict()
    students = [line for line in text.splitlines() if line.startswith("## ")]

    for student in students:
        student = student.replace("## ", "")
        email = student[: student.find("(")].strip()
        last_name, first_name = student[student.find("(") + 1 : student.find(")")].split(", ")
        results[email] = ManualGradingParticipantInfo(last_name, first_name, email, "")

    return results


def _parse_manual_grading_question_file(question_id: str, text: str) -> dict[str, ManualGradingGradedQuestion]:
    reader = StringReader(text)
    question_title = reader.read_line().strip().replace("# ", "")
    reader.read_until("## ")

    gradings_per_student = dict()

    while reader.has_more():
        student, graded = _parse_student_question_result(reader, question_id, question_title)
        gradings_per_student[student] = graded

        reader.skip_blank_lines()

    return gradings_per_student


def _parse_student_question_result(
    reader: StringReader, question_id: str, question_title: str
) -> tuple[str, ManualGradingGradedQuestion]:
    student_mail = reader.read_line().strip().replace("## ", "")
    student_mail = student_mail[: student_mail.find("(")].strip()

    reader.read_until("### Answer")
    points, max_points = reader.read_line().strip().split(" / ")

    reader.read_until("```\n")
    answer = reader.read_until("\n```\n")

    reader.read_until("----\n")
    if reader.can_find("## "):
        feedback = reader.read_until("## ").strip()
    else:
        feedback = reader.read_rest().strip()

    graded_question = ManualGradingGradedQuestion(
        ManualGradingQuestion(
            question_id,
            question_title,
            float(max_points),
            "file_upload" if "file\\_upload" == answer else "freeform_text",
        ),
        answer,
        float(points),
        feedback,
    )
    return student_mail, graded_question
