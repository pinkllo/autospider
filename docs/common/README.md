# Common 模块

Common 模块提供 AutoSpider 项目的基础设施和公共工具，包括配置管理、类型定义、浏览器操作、SoM 标注系统和存储管理。

---

## 📁 模块结构

```
common/
├── __init__.py              # 模块导出
├── config.py                # 配置管理（Pydantic 模型）
├── types.py                 # 核心数据类型定义
├── channel/                 # URL 传输通道 (memory/file/redis)
├── llm/                     # LLM 解析、决策与规划
├── browser/                 # 浏览器操作
│   ├── actions.py          # 动作执行器
│   └── session.py          # 浏览器会话管理
├── som/                    # Set-of-Mark 标注系统
│   ├── api.py              # SoM Python API
│   ├── mark_id_validator.py# Mark ID 验证
│   └── text_first.py       # 文本优先解析逻辑
├── storage/                # 持久化存储
│   ├── persistence.py      # 持久化基类
│   └── redis_manager.py    # Redis 队列管理器 (Stream ACK)
└── utils/                  # 内部工具
    ├── delay.py            # 延迟控制
    ├── fuzzy_search.py     # 模糊搜索
    └── paths.py            # 路径管理
```

---

## 🚀 核心组件

- **`config.py`**: 全局配置中心，支持环境变量覆盖。
- **`types.py`**: 基于 Pydantic 的核心数据模型。
- **`channel/`**: 实现解耦的 URL 生产-消费通道。
- **`llm/`**: 封装模型决策逻辑，支持不同任务类型的 Prompt 编排。
- **`browser/actions.py`**: 基于 `GuardedPage` 的安全动作执行引擎。
- **`storage/redis_manager.py`**: 基于 Redis Stream 的可靠消息交换系统。

---

*最后更新: 2026-01-27*
