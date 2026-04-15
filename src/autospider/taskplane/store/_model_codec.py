from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def encode_model(model: BaseModel) -> str:
    return json.dumps(dump_model(model), ensure_ascii=True, separators=(",", ":"))


def decode_model(model_type: type[ModelT], raw: str | None) -> ModelT | None:
    if not raw:
        return None
    return model_type.model_validate(json.loads(raw))
