"""LLM package exports with lazy loading to avoid import cycles."""

from __future__ import annotations

from ...domain.chat import ClarificationResult, ClarifiedTask, DialogueMessage

__all__ = [
    "LLMDecider",
    "TaskClarifier",
    "DialogueMessage",
    "ClarificationResult",
    "ClarifiedTask",
]


def __getattr__(name: str):
    if name == "LLMDecider":
        from .decider import LLMDecider

        return LLMDecider
    if name == "TaskClarifier":
        from .task_clarifier import TaskClarifier

        return TaskClarifier
    raise AttributeError(name)
