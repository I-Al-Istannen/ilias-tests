import abc
from enum import Enum


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
