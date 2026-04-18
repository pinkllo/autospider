from __future__ import annotations

from typing import Any


class BaseAutospiderError(Exception):
    def __init__(self, message: str, *, code: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class DomainError(BaseAutospiderError):
    pass


class InfrastructureError(BaseAutospiderError):
    pass
