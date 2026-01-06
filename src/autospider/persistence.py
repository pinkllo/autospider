"""持久化配置管理

用于保存和读取导航步骤、XPath等配置信息
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CollectionConfig:
    """URL收集过程的配置信息"""

    # 导航步骤
    nav_steps: list[dict[str, Any]] = field(default_factory=list)

    # 详情页公共 xpath
    common_detail_xpath: str | None = None

    # 分页控件 xpath
    pagination_xpath: str | None = None

    # 任务信息
    list_url: str = ""
    task_description: str = ""

    # 元信息
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "nav_steps": self.nav_steps,
            "common_detail_xpath": self.common_detail_xpath,
            "pagination_xpath": self.pagination_xpath,
            "list_url": self.list_url,
            "task_description": self.task_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectionConfig":
        """从字典创建"""
        return cls(
            nav_steps=data.get("nav_steps", []),
            common_detail_xpath=data.get("common_detail_xpath"),
            pagination_xpath=data.get("pagination_xpath"),
            list_url=data.get("list_url", ""),
            task_description=data.get("task_description", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ConfigPersistence:
    """配置持久化管理器"""

    def __init__(self, config_dir: str | Path = "output"):
        """初始化

        Args:
            config_dir: 配置文件存放目录
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "collection_config.json"

    def save(self, config: CollectionConfig) -> None:
        """保存配置

        Args:
            config: 要保存的配置
        """
        # 更新时间戳
        if not config.created_at:
            config.created_at = datetime.now().isoformat()
        config.updated_at = datetime.now().isoformat()

        # 保存到文件
        data = config.to_dict()
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[持久化] 配置已保存到: {self.config_file}")

    def load(self) -> CollectionConfig | None:
        """加载配置

        Returns:
            加载的配置，如果文件不存在则返回 None
        """
        if not self.config_file.exists():
            print(f"[持久化] 配置文件不存在: {self.config_file}")
            return None

        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            config = CollectionConfig.from_dict(data)
            print(f"[持久化] 配置已加载: {self.config_file}")
            return config
        except Exception as e:
            print(f"[持久化] 加载配置失败: {e}")
            return None

    def exists(self) -> bool:
        """检查配置文件是否存在

        Returns:
            配置文件是否存在
        """
        return self.config_file.exists()
