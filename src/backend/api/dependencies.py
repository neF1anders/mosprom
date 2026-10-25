from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..container import Container


def container(request: Request) -> Container:
    return request.app.state.container


def user(request: Request) -> str:
    """Пользователь из cookie сессии."""
    return request.state.user_id


Services = Annotated[Container, Depends(container)]
User = Annotated[str, Depends(user)]
