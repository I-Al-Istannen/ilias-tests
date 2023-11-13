import abc
import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath, Path
from typing import Optional, Any

import yaml
from PFERD.crawl import CrawlError
from slugify import slugify


class QuestionType(Enum):
    SINGLE_CHOICE = 1
    FREE_FORM_TEXT = 8
    FILE_UPLOAD = 14


def str_presenter(dumper, data):
    """
    Configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data
    Ref: https://github.com/yaml/pyyaml/issues/240#issuecomment-1096224358
    """
    if data.count('\n') > 0 or data.count("<p>") > 0:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dum


def load_freeform_question(
    title: str,
    author: str,
    summary: str,
    question_html: str,
    page_design: list['PageDesignBlock'],
    yml: dict[Any, Any]
):
    return QuestionFreeFormText(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        page_design=page_design,
        points=yml["points"]
    )


def load_upload_file_question(
    title: str,
    author: str,
    summary: str,
    question_html: str,
    page_design: list['PageDesignBlock'],
    yml: dict[Any, Any]
):
    return QuestionUploadFile(
        title=title,
        author=author,
        summary=summary,
        question_html=question_html,
        page_design=page_design,
        points=yml["points"],
        allowed_extensions=yml["allowed_filetypes"],
        max_size_bytes=eval(yml["max_bytes"])
    )


def load_single_choice_question(
    title: str,
    author: str,
    summary: str,
    question_html: str,
    page_design: list['PageDesignBlock'],
    yml: dict[Any, Any]
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
        answers=answers
    )


class PageDesignBlock(abc.ABC):

    @abc.abstractmethod
    def serialize(self) -> dict[str, Any]:
        ...

    @staticmethod
    def deserialize(yml: dict[str, Any]):
        if "type" not in yml:
            raise CrawlError("Could not find 'type' for block")
        if yml["type"] == "text":
            return PageDesignBlockText.deserialize(yml)
        elif yml["type"] == "image":
            return PageDesignBlockImage.deserialize(yml)
        else:
            raise CrawlError(f"Unknown type {yml['type']!r}")


class PageDesignBlockText(PageDesignBlock):
    def __init__(self, text_html: str):
        self.text_html = text_html

    def serialize(self):
        return {"text": self.text_html, "type": "text"}

    @staticmethod
    def deserialize(yml: dict[str, Any]) -> 'PageDesignBlockText':
        return PageDesignBlockText(yml["text"])


class PageDesignBlockImage(PageDesignBlock):
    def __init__(self, image_path: Path):
        self.image = image_path

    def serialize(self) -> dict[str, Any]:
        return {"path": str(self.image), "type": "image"}

    @staticmethod
    def deserialize(yml: dict[str, Any]) -> 'PageDesignBlockImage':
        return PageDesignBlockImage(Path(yml["path"]))


class TestQuestion(abc.ABC):
    def __init__(
        self, title: str, author: str, summary: str, question_html: str, question_type: QuestionType,
        page_design: list[PageDesignBlock]
    ):
        self.title = title
        self.author = author
        self.summary = summary
        self.question_html = question_html
        self.question_type = question_type
        self.page_design = page_design

    def get_options(self) -> dict[str, str]:
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
            "page_design": [block.serialize() for block in self.page_design]
        }

    @staticmethod
    def deserialize(yml: dict[Any, Any]) -> 'TestQuestion':
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
        self, title: str, author: str, summary: str, question_html: str, points: float,
        page_design: list[PageDesignBlock]
    ):
        super().__init__(title, author, summary, question_html, QuestionType.FREE_FORM_TEXT, page_design)
        self.points = points

    def get_options(self) -> dict[str, str]:
        return {
            **super().get_options(),
            "scoring_mode": "non",  # manual
            "non_keyword_points": str(self.points),
            "all_keyword_points": str(self.points),
            "one_keyword_points": str(self.points),
        }

    def serialize(self) -> dict[str, Any]:
        return {
            **super().serialize(),
            "points": self.points,
            "type": "freeform_text"
        }


class QuestionUploadFile(TestQuestion):

    def __init__(
        self,
        title: str, author: str, summary: str, question_html: str, page_design: list[PageDesignBlock],
        points: float, allowed_extensions: list[str], max_size_bytes: int
    ):
        super().__init__(title, author, summary, question_html, QuestionType.FILE_UPLOAD, page_design)
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

    def serialize(self) -> dict[str, Any]:
        return {
            **super().serialize(),
            "allowed_filetypes": self.allowed_extensions,
            "max_bytes": self.max_size_bytes,
            "points": self.points,
            "type": "file_upload"
        }


class QuestionSingleChoice(TestQuestion):

    def __init__(
        self,
        title: str, author: str, summary: str, question_html: str, page_design: list[PageDesignBlock],
        shuffle: bool, answers: list[tuple[str, float]]
    ):
        super().__init__(title, author, summary, question_html, QuestionType.SINGLE_CHOICE, page_design)
        self.shuffle = shuffle
        self.answers = answers

    def get_options(self) -> dict[str, str]:
        # choice[answer][0]
        # choice[image][0]"; filename="", octet-stream
        # choice[points][0]
        answer_options = {}
        for index, (answer, points) in enumerate(self.answers):
            answer_options[f"choice[answer][{index}]"] = answer
            answer_options[f"choice[image][{index}]"] = Path("")
            answer_options[f"choice[points][{index}]"] = str(points)

        return {
            **super().get_options(),
            **answer_options,
            "shuffle": "1" if self.shuffle else "0",
            "types": "0",  # single line answers for now
            "thumb_size": "",  # image preview size. Not supported for now.
        }

    def serialize(self) -> dict[str, Any]:
        answers = []
        for title, points in self.answers:
            answers.append({"answer": title, "points": points})

        return {
            **super().serialize(),
            "answers": answers,
            "shuffle": self.shuffle,
            "type": "single_choice"
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

    @staticmethod
    def deserialize(yml: dict[str, Any], test_questions: list[TestQuestion]):
        return IliasTest(
            path=PurePath(yml["path"]),
            title=yml["title"],
            description=yml["description"],
            intro_text=yml["intro_text"],
            starting_time=eval(yml["starting_time"]),
            ending_time=eval(yml["ending_time"]),
            numer_of_tries=yml["numer_of_tries"],
            questions=test_questions
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


def dump_questions_to_yml(questions: list[TestQuestion]) -> str:
    outer = {}
    for question in questions:
        slug = slugify(question.title)
        yml_dict = question.serialize()
        outer[slug] = yml_dict
    return yaml.safe_dump({"questions": outer}, indent=2, allow_unicode=True)
