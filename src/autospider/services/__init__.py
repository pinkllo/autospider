"""Service package exports."""

from __future__ import annotations

__all__ = [
    "PlanMutationService",
    "RuntimeExpansionService",
]


def __getattr__(name: str):
    if name == "PlanMutationService":
        from .plan_mutation_service import PlanMutationService

        return PlanMutationService
    if name == "RuntimeExpansionService":
        from .runtime_expansion_service import RuntimeExpansionService

        return RuntimeExpansionService
    raise AttributeError(f"module 'autospider.services' has no attribute {name!r}")
