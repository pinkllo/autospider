# Crawler Base 模块

该模块包含了爬取器的基础抽象类，为不同类型的爬取器提供公共逻辑。

## 核心组件

### `BaseCollector` 
`BaseCollector` 是一个抽象基类 (ABC)，定义了 URL 收集器的通用框架和核心属性。

#### 主要功能：
- **速率控制**：集成 `AdaptiveRateController` 实现自适应爬取频率。
- **持久化管理**：集成 `ProgressPersistence` 负责保存和恢复采集进度。
- **组件集成**：提供了 URL 提取、LLM 决策、页面导航和分页处理的统一接口。
- **路径管理**：自动创建输出目录和截图目录。
- **状态跟踪**：记录已收集的 URL、导航步骤和公共 XPath。

## 设计模式
该模块采用了**模板方法模式**，基类定义了收集流程的框架，具体的收集逻辑由子类（如 `URLCollector` 和 `BatchCollector`）实现。
