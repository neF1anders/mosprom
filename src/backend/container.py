from __future__ import annotations

import asyncio
from functools import cached_property

from .agents.assistant import Assistant
from .agents.events import Narrator
from .agents.runner import AgentRunner
from .agents.stage1 import Stage1, Stage1Settings
from .agents.tools import ToolBox
from .config import Settings
from .domain.catalog import Catalog
from .domain.model_settings import ModelSettings
from .infrastructure.catalog import load_catalog, load_requirement_keys
from .infrastructure.database import database
from .infrastructure.files import LocalFiles
from .infrastructure.model_settings import ModelSettingsFile
from .infrastructure.notifier import Notifier
from .infrastructure.queue import STAGE1_TASK, STAGE2_TASK, STEER_TASK, TaskRunner
from .infrastructure.qwen import QwenClient
from .infrastructure.results import LocalResultFolders
from .infrastructure.slicer import McpSlicer, SlicerSettings, gcode_facts
from .pipeline.parameters import ParameterPipeline, PipelineSettings
from .services.answers import AnswerService
from .services.artifacts import ArtifactService
from .services.commands import Commands
from .services.control import ControlService
from .services.jobs import JobService
from .services.messages import MessageService
from .services.queued import QueuedService
from .services.reports import Reports
from .services.sessions import SessionService
from .services.steering import Steering
from .services.uploads import UploadService
from .slicing import check_gcode
from .tuning.select import select_parameters
from .validation import check


class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.notifier = Notifier()
        self.wake = asyncio.Event()
        self.engine, self.uow = database(settings.database_url, self.notifier, self.wake)
        self.files = LocalFiles(settings.data_dir, limits=settings.limits)
        self.model_settings = ModelSettingsFile(
            settings.data_dir,
            ModelSettings(settings.qwen_base_url, settings.qwen_model, settings.qwen_api_key),
        )
        self.model = QwenClient(self.model_settings.current, max_tokens=settings.qwen_max_tokens)
        self.requirement_keys = load_requirement_keys(settings.requirement_keys_path)
        commands = Commands(self.uow)
        self.jobs = JobService(self.uow, self.notifier)
        self.sessions = SessionService(self.uow, settings.session_secret)
        self.messages = MessageService(commands)
        self.answers = AnswerService(commands)
        self.control = ControlService(commands)
        self.queued = QueuedService(commands)
        self.uploads = UploadService(commands, self.files, self.uow, settings.limits)
        self.result_folders = LocalResultFolders(
            settings.slicer_folder, settings.slicer_host_folder
        )
        self.artifacts = ArtifactService(self.uow, self.files, self.result_folders)
        # общий исполнитель
        runner = AgentRunner(
            self.model,
            ToolBox(self.files),
            self.uow,
            lambda: self.model_settings.current().model,
            narrate=Narrator(self.model) if settings.narrate_reasoning else None,
        )
        self.assistant = Assistant(runner, self.uow, self.files)
        self.steering = Steering(self.uow, self.assistant)
        self.reports = Reports(
            self.uow,
            self.assistant,
            self.files,
            self.result_folders,
        )
        self.stage1 = Stage1(
            self.uow,
            self.files,
            runner,
            Stage1Settings(
                timeout_seconds=settings.stage1_timeout_seconds,
                job_images=settings.limits.job_images,
            ),
            self.requirement_keys,
            safe_point=self.steering.deliver,
        )

    @cached_property
    def runner(self) -> TaskRunner:
        async def stage1(
            job_id: str,
            revision: int,
            start: bool = False,
            correction: bool = False,
            typed: list[str] | None = None,
        ) -> None:
            await self.stage1.run(job_id, revision, start, correction, typed or [])

        async def parameters(job_id: str, revision: int) -> None:
            await self.pipeline.run(job_id, revision)

        async def steer(job_id: str) -> None:
            await self.steering.deliver(job_id, force=True)

        return TaskRunner(
            self.uow,
            self.wake,
            {STAGE1_TASK: stage1, STAGE2_TASK: parameters, STEER_TASK: steer},
            self.settings.worker_concurrency,
        )

    @cached_property
    def catalog(self) -> Catalog:
        """Каталог читается при первом обращении."""
        return load_catalog(self.settings.build_dir, self.settings.printer)

    @cached_property
    def slicer(self) -> McpSlicer:
        settings = self.settings
        return McpSlicer(
            self.files,
            SlicerSettings(
                settings.slicer_folder,
                settings.slicer_host_folder,
                settings.slicer_host,
                settings.slicing_timeout_seconds,
            ),
        )

    @cached_property
    def pipeline(self) -> ParameterPipeline:
        """Подбор, проверка и нарезка."""
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
            PipelineSettings(timeout_seconds=self.settings.parameters_timeout_seconds),
            safe_point=self.steering.deliver,
            report=self.reports.post,
        )

    async def close(self) -> None:
        await self.runner.stop()
        await self.model.close()
        await self.engine.dispose()
