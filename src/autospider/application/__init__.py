"""应用层 use case 入口。"""

from .aggregation import AggregateResultsUseCase
from .collection import BatchCollectUrlsUseCase, CollectUrlsUseCase, GenerateCollectionConfigUseCase
from .dispatch import DispatchResult, DispatchUseCase
from .execution import ExecutePipelineUseCase
from .field_extraction import ExtractFieldsUseCase
from .planning import PlanUseCase

__all__ = [
    "AggregateResultsUseCase",
    "BatchCollectUrlsUseCase",
    "CollectUrlsUseCase",
    "DispatchResult",
    "DispatchUseCase",
    "ExecutePipelineUseCase",
    "ExtractFieldsUseCase",
    "GenerateCollectionConfigUseCase",
    "PlanUseCase",
]
