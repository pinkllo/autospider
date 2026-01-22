# Crawler Checkpoint 模块

该模块负责爬虫的运行状态控制，包括自适应速率调整和断点恢复策略。

## 核心组件

### `AdaptiveRateController` ([rate_controller.py](file:///d:/autospider/src/autospider/crawler/checkpoint/rate_controller.py))
实现自适应降速与信用恢复机制，降低被反爬虫系统识别的风险。
- **指数退避算法**：遭遇错误或反爬时，按指数级增加延迟。
- **信用恢复**：连续成功抓取一定数量的页面后，逐步缩短延迟。

### `ResumeStrategy` ([resume_strategy.py](file:///d:/autospider/src/autospider/crawler/checkpoint/resume_strategy.py))
定义了多种断点恢复策略，用于在爬虫中断后快速定位到目标页码：
1. **URLPatternStrategy**：通过分析 URL 中的页码参数直接构造跳转链接。
2. **WidgetJumpStrategy**：通过操作页面上的翻页控件（如输入页码并跳转）实现定位。
3. **SmartSkipStrategy**：智能跳过策略，结合首项检测与回溯机制。

## 主要作用
- 提高爬虫的健壮性和生存能力。
- 减少因网络波动或反爬导致的抓取失败。
- 实现大规模抓取任务的高效恢复。
