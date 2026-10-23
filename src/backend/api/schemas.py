from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class CreateJob(Command):
    title: str = Field(default="Новое задание", min_length=1, max_length=200)


class SendMessage(Command):
    text: str = Field(min_length=1, max_length=30000)
    intent: Literal["message", "status", "edit"] = "message"


class Answers(Command):
    expected_revision: int = Field(ge=0)
    answers: dict[str, str] = Field(min_length=1, max_length=50)


class Launch(BaseModel):
    token: str = Field(min_length=1, max_length=1000)
