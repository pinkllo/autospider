"""Collection application exports."""

from autospider.contexts.collection.application.use_cases import (
    CollectionExploreDependencies,
    DetailPageWorker,
    DetailPageWorkerResult,
    NavigationHandler,
    PaginationHandler,
    ReplayNavigationResult,
    ResultAggregator,
    ScriptGenerator,
    URLCollector,
    URLExtractor,
    build_collection_explore_dependencies,
    build_navigation_task_plan,
    collect_detail_urls,
    generate_crawler_script,
    run_field_pipeline,
)

__all__ = [
    "CollectionExploreDependencies",
    "DetailPageWorker",
    "DetailPageWorkerResult",
    "NavigationHandler",
    "PaginationHandler",
    "ReplayNavigationResult",
    "ResultAggregator",
    "ScriptGenerator",
    "URLCollector",
    "URLExtractor",
    "build_collection_explore_dependencies",
    "build_navigation_task_plan",
    "collect_detail_urls",
    "generate_crawler_script",
    "run_field_pipeline",
]
