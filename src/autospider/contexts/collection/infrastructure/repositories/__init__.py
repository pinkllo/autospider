"""Collection infrastructure repositories."""

from .config_repository import (
    CollectionConfig,
    CollectionConfigLoadError,
    ConfigPersistence,
    coerce_collection_config,
    load_collection_config,
)
from .field_xpath_repository import (
    FieldXPathQueryService,
    FieldXPathWriteService,
    normalize_xpath_domain,
)
from .page_result_repository import PageResultRepository
from .progress_repository import (
    CollectionProgress,
    ProgressPersistence,
    coerce_collection_progress,
)
from .run_repository import RunRepository, TaskRunPayload

__all__ = [
    "CollectionConfig",
    "CollectionConfigLoadError",
    "CollectionProgress",
    "ConfigPersistence",
    "FieldXPathQueryService",
    "FieldXPathWriteService",
    "PageResultRepository",
    "ProgressPersistence",
    "RunRepository",
    "TaskRunPayload",
    "coerce_collection_config",
    "coerce_collection_progress",
    "load_collection_config",
    "normalize_xpath_domain",
]
