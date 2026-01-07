# URL Collector 模块重构说明

## 重构概述

原 `url_collector.py` 文件（约1900行）已被拆分成多个解耦的模块，提高了代码的可维护性和可测试性。

## 模块结构

### collector/ 包

```
collector/
├── __init__.py                 # 包导出
├── models.py                   # 数据模型定义
├── page_utils.py               # 页面操作工具
├── xpath_extractor.py          # XPath 提取器
├── llm_decision.py             # LLM 决策制定
├── url_extractor.py            # URL 提取器
├── navigation_handler.py       # 导航处理器
└── pagination_handler.py       # 分页处理器
```

### 模块职责

#### 1. **models.py** (数据模型)
- `DetailPageVisit` - 详情页访问记录
- `CommonPattern` - 公共模式
- `URLCollectorResult` - 收集结果

#### 2. **page_utils.py** (页面工具)
- `is_at_page_bottom()` - 检测页面底部
- `smart_scroll()` - 智能滚动

#### 3. **xpath_extractor.py** (XPath提取)
- `XPathExtractor` - 从访问记录中提取公共XPath模式

#### 4. **llm_decision.py** (LLM决策)
- `LLMDecisionMaker` - 调用LLM进行决策
  - `ask_for_decision()` - 询问LLM如何获取详情页URL
  - `extract_pagination_with_llm()` - 使用LLM识别分页控件

#### 5. **url_extractor.py** (URL提取)
- `URLExtractor` - 从页面元素提取URL
  - `extract_from_element()` - 从元素提取URL（优先href）
  - `click_and_get_url()` - 点击元素获取URL
  - `click_element_and_get_url()` - 点击locator获取URL

#### 6. **navigation_handler.py** (导航处理)
- `NavigationHandler` - 导航阶段处理器
  - `run_navigation_phase()` - 执行导航阶段
  - `replay_nav_steps()` - 重放导航步骤

#### 7. **pagination_handler.py** (分页处理)
- `PaginationHandler` - 分页处理器
  - `extract_pagination_xpath()` - 提取分页控件XPath
  - `find_and_click_next_page()` - 查找并点击下一页
  - `find_next_page_with_llm()` - 使用LLM识别下一页

### 主文件

#### url_collector.py (主协调器)
- `URLCollector` - 主收集器类（约700行，较原文件减少63%）
  - 协调各个模块完成URL收集流程
  - 保留了原有的公共接口，确保向后兼容

## 重构优势

### 1. **单一职责原则**
每个模块只负责一项具体功能，易于理解和维护

### 2. **降低耦合**
模块之间通过清晰的接口交互，减少了相互依赖

### 3. **提高可测试性**
每个模块都可以独立测试

### 4. **更好的代码组织**
相关功能集中在一起，便于查找和修改

### 5. **保持兼容性**
主文件保留了原有的接口，确保现有代码无需修改

## 使用方式

使用方式与原来完全相同：

```python
from autospider.url_collector import URLCollector, collect_detail_urls

# 方式 1: 使用类
collector = URLCollector(
    page=page,
    list_url="https://example.com/list",
    task_description="收集招标公告",
    explore_count=3,
)
result = await collector.run()

# 方式 2: 使用便捷函数
result = await collect_detail_urls(
    page=page,
    list_url="https://example.com/list",
    task_description="收集招标公告",
    explore_count=3,
)
```

## 备份文件

原文件已备份为：`url_collector_backup.py`

## 注意事项

1. 所有配置仍然在 config 文件中管理
2. 废弃的函数已被移除，不会造成困扰
3. 所有模块文档和注释均使用中文
