from __future__ import annotations

from dataclasses import dataclass

from .model import ClarifiedTask


@dataclass(frozen=True, slots=True)
class TaskClarified:
    session_id: str
    task: ClarifiedTask
