"""Collection application exports."""

from autospider.contexts.collection.application.use_cases import (
    DetailPageWorker,
    DetailPageWorkerResult,
    NavigationHandler,
    PaginationHandler,
    ReplayNavigationResult,
    ResultAggregator,
    ScriptGenerator,
    URLCollector,
    URLExtractor,
    build_navigation_task_plan,
    collect_detail_urls,
    generate_crawler_script,
    run_field_pipeline,
)

__all__ = [
    "DetailPageWorker",
    "DetailPageWorkerResult",
    "NavigationHandler",
    "PaginationHandler",
    "ReplayNavigationResult",
    "ResultAggregator",
    "ScriptGenerator",
    "URLCollector",
    "URLExtractor",
    "build_navigation_task_plan",
    "collect_detail_urls",
    "generate_crawler_script",
    "run_field_pipeline",
]
