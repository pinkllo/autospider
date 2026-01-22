# script_generator.py - 爬虫脚本生成器

script_generator.py 模块提供爬虫脚本生成功能，从探索记录中分析共同模式，生成 Scrapy + scrapy-playwright 爬虫脚本。

---

## 📁 文件路径

```
src/autospider/extractor/output/script_generator.py
```

---

## 📑 函数目录

### 🚀 核心类
- `ScriptGenerator` - 爬虫脚本生成器主类

### 🔧 主要方法
- `generate_scrapy_playwright_script()` - 生成 Scrapy + scrapy-playwright 爬虫脚本

---

## 🚀 核心功能

### ScriptGenerator

爬虫脚本生成器，从探索记录中分析共同模式，生成 Scrapy + scrapy-playwright 爬虫脚本。

```python
from autospider.extractor.output.script_generator import ScriptGenerator

# 创建脚本生成器
generator = ScriptGenerator(output_dir="output")

# 生成爬虫脚本
script = await generator.generate_scrapy_playwright_script(
    list_url="https://example.com/list",
    task_description="收集商品详情页链接",
    detail_visits=detail_visits,
    nav_steps=nav_steps,
    collected_urls=collected_urls,
    common_detail_xpath=common_detail_xpath
)

print(f"生成的脚本:\n{script}")
```

---

## 💡 特性说明

### LLM 驱动的脚本生成

使用 LLM 分析探索记录并生成脚本：

```python
# 使用模板引擎加载和渲染 prompt
system_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="system_prompt",
)

user_prompt = render_template(
    PROMPT_TEMPLATE_PATH,
    section="user_prompt",
    variables={
        "list_url": list_url,
        "task_description": task_description,
        "detail_visits": json.dumps(detail_visits, ensure_ascii=False),
        "nav_steps": json.dumps(nav_steps, ensure_ascii=False),
        "common_detail_xpath": common_detail_xpath or "未提取",
    }
)

# 调用 LLM 生成脚本
response = await self.llm.ainvoke(messages)
script = response.content
```

---

## 🔧 使用示例

### 基本使用

```python
import asyncio
from autospider.extractor.output.script_generator import ScriptGenerator

async def generate_script():
    # 创建脚本生成器
    generator = ScriptGenerator(output_dir="output")

    # 生成爬虫脚本
    script = await generator.generate_scrapy_playwright_script(
        list_url="https://example.com/list",
        task_description="收集商品详情页链接",
        detail_visits=detail_visits,
        nav_steps=nav_steps,
        collected_urls=collected_urls,
        common_detail_xpath=common_detail_xpath
    )

    # 保存脚本
    script_file = Path("output/spider.py")
    script_file.write_text(script, encoding="utf-8")

    print(f"脚本已保存到: {script_file}")
    print(f"运行方式: scrapy runspider {script_file} -o output.json")

# 运行
asyncio.run(generate_script())
```

---

## 📝 最佳实践

### 脚本生成

1. **提供详细的探索记录**：提供详细的探索记录帮助 LLM 理解
2. **包含导航步骤**：包含导航步骤使脚本更完整
3. **验证脚本质量**：验证生成的脚本是否可以正常运行

### 脚本使用

1. **测试脚本**：在实际运行前测试脚本
2. **优化性能**：根据实际需求优化脚本性能
3. **处理异常**：添加适当的异常处理

---

## 🔍 故障排除

### 常见问题

1. **脚本生成失败**
   - 检查探索记录是否完整
   - 验证导航步骤是否正确
   - 确认 LLM 响应是否有效

2. **脚本无法运行**
   - 检查脚本语法是否正确
   - 验证依赖是否安装
   - 确认配置是否正确

---

## 📚 方法参考

### ScriptGenerator 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `generate_scrapy_playwright_script()` | list_url, task_description, detail_visits, nav_steps, collected_urls, common_detail_xpath | str | 生成 Scrapy + scrapy-playwright 爬虫脚本 |

---

## 📄 脚本示例

### Scrapy + scrapy-playwright 脚本

```python
import scrapy
from scrapy_playwright.page import PageMethod

class ProductSpider(scrapy.Spider):
    name = 'products'
    start_urls = ['https://example.com/list']
    
    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                meta={
                    'playwright': True,
                    'playwright_page_methods': [
                        PageMethod('wait_for_selector', '//a[@class="product-link"]')
                    ]
                }
            )
    
    def parse(self, response):
        # 提取商品链接
        product_links = response.xpath('//a[@class="product-link"]/@href').getall()
        
        for link in product_links:
            yield response.follow(link, callback=self.parse_product)
    
    def parse_product(self, response):
        # 提取商品信息
        yield {
            'url': response.url,
            'title': response.xpath('//h1/text()').get(),
            'price': response.xpath('//span[@class="price"]/text()').get(),
        }
```

---

*最后更新: 2026-01-08*
