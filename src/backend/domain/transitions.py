from __future__ import annotations

from .errors import AppError
from .models import Status

TRANSITIONS = {
    Status.DRAFT: {Status.QUEUED, Status.STOPPED},
    Status.QUEUED: {Status.RUNNING, Status.STOPPED, Status.QUEUED},
    Status.RUNNING: {
        Status.QUEUED,
        Status.WAITING,
        Status.FAILED,
        Status.STOPPING,
        Status.COMPLETED,
    },
    Status.WAITING: {Status.QUEUED, Status.STOPPED},
    Status.FAILED: {Status.QUEUED, Status.STOPPED},
    Status.STOPPING: {Status.STOPPED, Status.QUEUED},
    Status.STOPPED: {Status.QUEUED},
    Status.COMPLETED: {Status.QUEUED, Status.STOPPED},
}


def transition(current: Status, target: Status) -> Status:
    if target == current or target in TRANSITIONS[current]:
        return target
    raise AppError("Недопустимый переход состояния", "invalid_transition", 409)
