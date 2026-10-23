from __future__ import annotations

import hashlib
import time

from ..domain.errors import AppError
from ..domain.tokens import sign_token, verify_token
from ..ports.persistence import UowFactory

SESSION_SECONDS = 30 * 86400


class SessionService:
    def __init__(self, uow: UowFactory, secret: str):
        self.uow, self.secret = uow, secret

    async def exchange(self, token: str) -> str:
        """A launch link from the plugin works once and binds the browser to its user."""
        user_id = verify_token(self.secret, token, "launch", int(time.time()))
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.uow() as uow:
            key = "launch:" + digest
            if await uow.jobs.receipt(key, digest) is not None:
                raise AppError(
                    "Ссылка запуска уже использована, откройте новую", "used_launch_token", 401
                )
            await uow.jobs.remember(key, digest, {"used": True})
            await uow.commit()
        return sign_token(self.secret, "session", int(time.time()) + SESSION_SECONDS, user_id)
