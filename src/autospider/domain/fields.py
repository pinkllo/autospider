"""字段领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FieldDefinition:
    """字段定义。

    该模型属于跨模块共享的领域对象，不应隶属于 field 或 common 基础设施层。
    """

    name: str
    description: str
    required: bool = True
    data_type: str = "text"
    example: str | None = None
    extraction_source: str | None = None
    fixed_value: str | None = None

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        """提供与 Pydantic 模型兼容的最小序列化接口。"""
        _ = mode
        return asdict(self)
