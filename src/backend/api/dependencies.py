from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..container import Container


def container(request: Request) -> Container:
    return request.app.state.container


Services = Annotated[Container, Depends(container)]
