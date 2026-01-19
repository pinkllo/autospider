# AutoSpider 项目流程图

## 1. 整体架构

```mermaid
graph TD
    subgraph 核心模块
        A[AutoSpider主入口]
        B[Common模块] -- 提供基础设施 --> A
        C[Crawler模块] -- 批量数据采集 --> A
        D[Extractor模块] -- 智能规则发现 --> A
        E[Prompts模块] -- 提示词管理 --> A
    end
    
    subgraph 工具模块
        F[Utils工具集] -- 通用工具 --> B
        G[Browser Manager] -- 浏览器管理 --> C
    end
    
    subgraph 输入输出
        H[用户输入] -- 任务描述+起始URL --> A
        I[生成的配置文件] -- 输出 --> A
        J[可执行爬虫脚本] -- 输出 --> A
    end
```

## 2. 核心工作流程

```mermaid
graph TD
    A[用户输入] -- 任务描述+起始URL --> B[ConfigGenerator]
    B --> C{生成配置}
    C --> |需要收集URL| D[URLCollector]
    D --> E{三阶段探索}
    E --> |1. 探索阶段| F[访问详情页样本]
    E --> |2. 收集阶段| G[批量收集URL]
    E --> |3. 分析阶段| H[提取公共XPath]
    H --> I[生成公共XPath模式]
    C --> |已有URL列表| J[生成XPath脚本]
    I --> J
    J --> K[生成最终配置]
    K --> L[输出配置文件]
    K --> M[输出可执行脚本]
```

## 3. URLCollector工作流程

```mermaid
graph TD
    A[URLCollector初始化] --> B[检查点恢复]
    B --> |有检查点| C[从检查点继续]
    B --> |无检查点| D[从头开始]
    C --> E[探索阶段]
    D --> E
    E --> |访问N个详情页| F[分析页面结构]
    F --> G[收集阶段]
    G --> |批量收集URL| H[分页处理]
    H --> |下一页| I[判断是否完成]
    I --> |未完成| G
    I --> |完成| J[分析阶段]
    J --> |提取公共XPath| K[生成common_detail_xpath]
    K --> L[保存检查点]
    L --> M[返回收集结果]
```

## 4. ConfigGenerator工作流程

```mermaid
graph TD
    A[ConfigGenerator初始化] --> B[接收任务]
    B --> C[调用URLCollector]
    C --> D[收集详情页URL]
    D --> E[调用LLM生成XPath脚本]
    E --> F[生成爬虫配置]
    F --> G[返回配置和脚本]
```

## 5. Extractor Field模块工作流程

```mermaid
graph TD
    A[FieldExtractor初始化] --> B[接收字段定义]
    B --> C[导航到目标页面]
    C --> D[页面加载完成]
    D --> E{字段提取}
    E --> |单个字段| F[导航到字段区域]
    F --> G[使用SoM标注]
    G --> H[调用LLM识别字段]
    H --> I[执行字段提取]
    I --> J[生成XPath表达式]
    J --> K[验证提取结果]
    K --> L[保存提取结果]
    L --> E
    E --> |所有字段完成| M[返回提取结果]
```

## 6. Common SOM模块工作流程

```mermaid
graph TD
    A[注入SoM脚本] --> B[扫描页面元素]
    B --> C[生成元素标注]
    C --> D[创建元素快照]
    D --> E[提供元素映射]
    E --> F{后续操作}
    F --> |截图| G[生成带标注的截图]
    F --> |获取元素| H[根据mark_id获取元素]
    F --> |构建映射| I[生成mark_id到XPath映射]
    F --> |格式化| J[生成LLM友好的标注信息]
```

## 7. 模块间依赖关系

```mermaid
graph TD
    subgraph Common
        A[browser] --> B[actions]
        A --> C[session]
        D[som] --> E[api]
        D --> F[text_first]
        G[storage] --> H[persistence]
        G --> I[redis_manager]
    end
    
    subgraph Extractor
        J[collector] --> K[url_extractor]
        J --> L[navigation_handler]
        J --> M[pagination_handler]
        N[field] --> O[field_extractor]
        N --> P[field_decider]
        N --> Q[xpath_pattern]
        R[llm] --> S[decider]
        R --> T[planner]
        R --> U[prompt_template]
    end
    
    subgraph Crawler
        V[checkpoint] --> W[resume_strategy]
        X[url_collector] --> Y[base_collector]
        Z[batch_collector] --> Y
    end
    
    X --> K
    X --> A
    X --> D
    X --> G
    O --> A
    O --> D
    O --> S
    T --> U
    S --> U
    M --> A
    L --> A
    K --> D
    J --> R
    N --> R
    V --> G
```

## 8. 数据流向图

```mermaid
graph TD
    A[用户输入] --> |任务描述+URL| B[ConfigGenerator]
    B --> |调用| C[URLCollector]
    C --> |使用| D[Browser Manager]
    D --> |返回| E[页面数据]
    E --> |处理| F[提取URL列表]
    F --> |返回| G[URLCollector结果]
    G --> |输入| H[生成XPath脚本]
    H --> |调用| I[LLM Decider]
    I --> |使用| J[Prompts模板]
    J --> |返回| K[LLM响应]
    K --> |生成| L[XPath表达式]
    L --> |组合| M[最终脚本]
    M --> |输出| N[可执行爬虫脚本]
    M --> |输出| O[配置文件]
```

## 9. 故障处理流程

```mermaid
graph TD
    A[任务执行] --> B{是否出错}
    B --> |否| C[正常完成]
    B --> |是| D{错误类型}
    D --> |网络错误| E[重试机制]
    D --> |页面结构变化| F[重新探索]
    D --> |LLM调用失败| G[备用模型]
    D --> |其他错误| H[记录日志]
    E --> |重试成功| C
    E --> |重试失败| I[保存检查点]
    F --> |重新探索成功| C
    F --> |重新探索失败| I
    G --> |备用模型成功| C
    G --> |备用模型失败| I
    H --> I
    I --> J[退出任务]
    C --> K[清理资源]
    J --> K
```

## 10. 完整系统流程图

```mermaid
graph TD
    A[用户] --> |输入任务描述+起始URL| B[AutoSpider入口]
    B --> C[ConfigGenerator]
    C --> D{生成配置}
    D --> |需要收集URL| E[URLCollector]
    E --> F[探索阶段]
    F --> |访问详情页| G[Browser Manager]
    G --> H[页面快照]
    H --> I[SoM标注]
    I --> J[LLM分析]
    J --> K[公共XPath模式]
    E --> L[收集阶段]
    K --> L
    L --> M[批量收集URL]
    M --> N[URL列表]
    D --> |生成XPath脚本| O[LLM Decider]
    N --> O
    O --> P[XPath脚本]
    P --> Q[生成配置文件]
    P --> R[生成可执行脚本]
    Q --> S[输出结果]
    R --> S
    S --> T[用户]
```

---

## 图例说明

- **矩形框**：表示模块、类或函数
- **菱形框**：表示判断或条件分支
- **箭头**：表示数据流向或调用关系
- **子图**：表示模块分组
- **虚线箭头**：表示间接依赖关系
- **实线箭头**：表示直接调用或数据传递

## 使用说明

1. 这些流程图使用Mermaid语法编写，可以直接在支持Mermaid的Markdown编辑器中查看
2. 建议使用VS Code配合Markdown Preview Mermaid Support插件查看
3. 也可以将Mermaid代码复制到[Mermaid Live Editor](https://mermaid.live/)中查看
4. 流程图展示了AutoSpider的核心架构、工作流程和模块间关系，有助于理解系统设计

## 设计原则

1. **模块化设计**：清晰的模块划分，便于维护和扩展
2. **分层架构**：核心模块、工具模块、输入输出层分离
3. **数据驱动**：以数据流向为主线，清晰展示系统运行逻辑
4. **可视化**：通过流程图直观展示复杂系统的工作原理
5. **完整性**：覆盖从用户输入到最终输出的完整流程

---

*最后更新: 2026-01-19*