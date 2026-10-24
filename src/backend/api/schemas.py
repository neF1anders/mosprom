from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AnswerText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class CreateJob(Command):
    title: str = Field(default="Новое задание", min_length=1, max_length=200)


class RenameJob(Command):
    title: str = Field(min_length=1, max_length=80)


class SendMessage(Command):
    text: str = Field(min_length=1, max_length=30000)


class Answers(Command):
    expected_revision: int = Field(ge=0)
    answers: dict[str, AnswerText] = Field(min_length=1, max_length=100)


class Launch(BaseModel):
    token: str = Field(min_length=1, max_length=1000)
