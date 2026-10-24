"""Composition root: the only place that binds infrastructure to application ports."""

from __future__ import annotations

from functools import cached_property

from .agents.runner import AgentRunner
from .agents.stage1 import Stage1, Stage1Settings
from .agents.tools import ToolBox
from .config import Settings
from .domain.catalog import Catalog
from .infrastructure.catalog import load_catalog, load_requirement_keys
from .infrastructure.database import database
from .infrastructure.files import LocalFiles
from .infrastructure.notifier import PostgresNotifier
from .infrastructure.queue import queue_app
from .infrastructure.qwen import QwenClient
from .infrastructure.slicer import McpSlicer, SlicerSettings, gcode_facts
from .pipeline.parameters import ParameterPipeline, PipelineSettings
from .services.answers import AnswerService
from .services.artifacts import ArtifactService
from .services.commands import Commands
from .services.control import ControlService
from .services.jobs import JobService
from .services.messages import MessageService
from .services.sessions import SessionService
from .services.uploads import UploadService
from .slicing import check_gcode
from .tuning.select import select_parameters
from .validation import check


class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.queue = queue_app(settings.database_url)
        self.engine, self.uow = database(settings.database_url, self.queue)
        self.files = LocalFiles(settings.data_dir, limits=settings.limits)
        self.model = QwenClient(
            settings.qwen_base_url,
            settings.qwen_model,
            settings.qwen_api_key,
            max_tokens=settings.qwen_max_tokens,
        )
        self.notifier = PostgresNotifier(settings.database_url)
        self.requirement_keys = load_requirement_keys(settings.requirement_keys_path)
        commands = Commands(self.uow)
        self.jobs = JobService(self.uow, self.notifier)
        self.sessions = SessionService(self.uow, settings.session_secret)
        self.messages = MessageService(commands)
        self.answers = AnswerService(commands)
        self.control = ControlService(commands)
        self.uploads = UploadService(commands, self.files, self.uow, settings.limits)
        self.artifacts = ArtifactService(self.uow, self.files)
        tools = ToolBox(self.files)
        self.stage1 = Stage1(
            self.uow,
            self.files,
            AgentRunner(self.model, tools, self.uow, settings.qwen_model),
            Stage1Settings(
                model=settings.qwen_model,
                timeout_seconds=settings.stage1_timeout_seconds,
                job_images=settings.limits.job_images,
            ),
            self.requirement_keys,
        )

    @cached_property
    def catalog(self) -> Catalog:
        """Read on first use: only the worker selects and checks parameters."""
        return load_catalog(self.settings.build_dir, self.settings.printer)

    @cached_property
    def slicer(self) -> McpSlicer:
        settings = self.settings
        return McpSlicer(
            self.files,
            SlicerSettings(
                settings.slicer_folder, settings.slicer_host_folder, settings.slicer_host
            ),
        )

    @cached_property
    def pipeline(self) -> ParameterPipeline:
        """Selection, its check, slicing and the G-code check, bound to the build catalog."""
        catalog, keys, files = self.catalog, self.requirement_keys, self.files
        return ParameterPipeline(
            self.uow,
            catalog,
            lambda card, feedback: select_parameters(card, catalog, keys, feedback),
            lambda parameter_set: check(parameter_set, catalog),
            self.slicer,
            lambda key, parameter_set, iteration: check_gcode(
                gcode_facts(files, key), parameter_set, catalog, iteration
            ),
            PipelineSettings(
                timeout_seconds=self.settings.parameters_timeout_seconds,
                slicing_timeout_seconds=self.settings.slicing_timeout_seconds,
            ),
        )

    async def close(self) -> None:
        await self.notifier.close()
        await self.model.close()
        await self.engine.dispose()
