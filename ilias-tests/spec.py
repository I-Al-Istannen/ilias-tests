import abc
import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath, Path
from typing import Optional, Any

import yaml
from PFERD.crawl import CrawlError


class QuestionType(Enum):
    FREE_FORM_TEXT = 8
    FILE_UPLOAD = 14


class TestQuestion(abc.ABC):
    def __init__(self, title: str, author: str, summary: str, question_html: str, question_type: QuestionType):
        self.title = title
        self.author = author
        self.summary = summary
        self.question_html = question_html
        self.question_type = question_type

    def get_options(self) -> dict[str, str]:
        return {
            "title": self.title,
            "author": self.author,
            "comment": self.summary,
            "lifecycle": "draft",
            "question": self.question_html,
        }


class QuestionFreeFormText(TestQuestion):
    def __init__(self, title: str, author: str, summary: str, question_html: str, points: float):
        super().__init__(title, author, summary, question_html, QuestionType.FREE_FORM_TEXT)
        self.points = points

    def get_options(self) -> dict[str, str]:
        return {
            **super().get_options(),
            "scoring_mode": "non",  # manual
            "non_keyword_points": str(self.points),
            "all_keyword_points": str(self.points),
            "one_keyword_points": str(self.points),
        }


class QuestionUploadFile(TestQuestion):

    def __init__(
        self,
        title: str, author: str, summary: str, question_html: str,
        points: float, allowed_extensions: list[str], max_size_bytes: int
    ):
        super().__init__(title, author, summary, question_html, QuestionType.FILE_UPLOAD)
        self.points = points
        self.allowed_extensions = allowed_extensions
        self.max_size_bytes = max_size_bytes

    def get_options(self) -> dict[str, str]:
        return {
            **super().get_options(),
            "allowedextensions": ",".join(self.allowed_extensions),
            "maxsize": str(self.max_size_bytes),
            "points": str(self.points),
        }


@dataclass
class IliasTest:
    path: PurePath

    title: str
    description: str
    intro_text: str
    starting_time: Optional[datetime.datetime]
    ending_time: Optional[datetime.datetime]
    numer_of_tries: int

    questions: list[TestQuestion]


@dataclass
class Spec:
    tests: list[IliasTest]


def load_spec_from_file(path: Path) -> Spec:
    with open(path, "r") as file:
        data = yaml.safe_load(file)
    questions: dict[str, TestQuestion] = {}

    for key, question in data["questions"].items():
        str_type = question["type"]
        title = question["title"]
        author = question["author"]
        summary = question["summary"]
        question_html = question["question_html"]
        if str_type == "file_upload":
            parsed = load_upload_file_question(title, author, summary, question_html, question)
        elif str_type == "freeform_text":
            parsed = load_freeform_question(title, author, summary, question_html, question)
        else:
            raise CrawlError(f"Unknown question type {str_type}")
        questions[key] = parsed

    tests = []
    for key, test in data["tests"].items():
        test_questions = [questions[val] for val in test["questions"]]
        tests.append(IliasTest(
            path=PurePath(test["path"]),
            title=test["title"],
            description=test["description"],
            intro_text=test["intro_text"],
            starting_time=eval(test["starting_time"]),
            ending_time=eval(test["ending_time"]),
            numer_of_tries=test["numer_of_tries"],
            questions=test_questions
        ))

    return Spec(tests=tests)


def load_freeform_question(
    title: str,
    author: str,
    summary: str,
    question_html: str,
    yml: dict[Any, Any]
):
    return QuestionFreeFormText(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        points=yml["points"]
    )


def load_upload_file_question(
    title: str,
    author: str,
    summary: str,
    question_html: str,
    yml: dict[Any, Any]
):
    return QuestionUploadFile(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        points=yml["points"],
        allowed_extensions=yml["allowed_filetypes"],
        max_size_bytes=eval(yml["max_bytes"])
    )
