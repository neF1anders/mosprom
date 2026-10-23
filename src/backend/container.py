"""Composition root: the only place that binds infrastructure to application ports."""

from __future__ import annotations

from .config import Settings
from .infrastructure.database import database
from .infrastructure.files import LocalFiles
from .infrastructure.handoff import HttpHandoff
from .infrastructure.qwen import QwenClient
from .services.answers import AnswerService
from .services.artifacts import ArtifactService
from .services.commands import Commands
from .services.control import ControlService
from .services.extraction import ExtractionService
from .services.geometry import GeometryService
from .services.jobs import JobService
from .services.knowledge import KnowledgeService
from .services.messages import MessageService
from .services.pipeline import Pipeline
from .services.preparation import PreparationService
from .services.sessions import SessionService
from .services.tools import ToolService
from .services.uploads import UploadService


class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine, self.uow = database(settings.database_url)
        self.files = LocalFiles(settings.data_dir, limits=settings.limits)
        self.model = QwenClient(settings.qwen_base_url, settings.qwen_model, settings.qwen_api_key)
        commands = Commands(self.uow)
        self.jobs = JobService(self.uow)
        self.sessions = SessionService(self.uow, settings.session_secret)
        self.messages = MessageService(commands)
        self.answers = AnswerService(commands)
        self.control = ControlService(commands)
        self.uploads = UploadService(commands, self.files, self.uow, settings.limits)
        self.artifacts = ArtifactService(self.uow, self.files)
        self.knowledge = KnowledgeService(self.uow)
        geometry = GeometryService(self.uow, self.files)
        tools = ToolService(geometry, self.knowledge)
        extraction = ExtractionService(self.uow, self.model, tools, settings.qwen_model)
        self.pipeline = Pipeline(
            self.uow,
            PreparationService(self.uow, self.files),
            geometry,
            extraction,
            HttpHandoff(settings.handoff_url),
        )

    async def close(self):
        await self.model.close()
        await self.engine.dispose()
