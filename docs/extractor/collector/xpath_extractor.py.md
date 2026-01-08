# xpath_extractor.py - XPath 提取器

xpath_extractor.py 模块提供 XPath 提取和模式分析功能。

---

## 📁 文件路径

```
src/autospider/extractor/collector/xpath_extractor.py
```

---

## 📑 函数目录

### 🚀 核心类
- `XPathExtractor` - XPath 提取器主类

### 🔧 主要方法
- `extract_common_xpath()` - 从探索记录中提取公共 xpath

---

## 🚀 核心功能

### XPathExtractor

XPath 提取器，负责从访问记录中提取公共 xpath。

```python
from autospider.extractor.collector.xpath_extractor import XPathExtractor

# 创建 XPath 提取器
extractor = XPathExtractor()

# 从探索记录中提取公共 xpath
common_xpath = extractor.extract_common_xpath(detail_visits)

if common_xpath:
    print(f"公共 xpath: {common_xpath}")
else:
    print("未能提取公共 xpath")
```

---

## 💡 特性说明

### 公共模式提取

从多次访问中提取公共 xpath 模式：

```python
# 找出公共模式
common_pattern = self._find_common_xpath_pattern(xpaths)

if common_pattern:
    print(f"公共 xpath 模式: {common_pattern}")
```

---

## 🔧 使用示例

### 基本使用

```python
from autospider.extractor.collector.xpath_extractor import XPathExtractor

# 创建 XPath 提取器
extractor = XPathExtractor()

# 从探索记录中提取公共 xpath
common_xpath = extractor.extract_common_xpath(detail_visits)

print(f"公共 xpath: {common_xpath}")
```

---

## 📚 方法参考

### XPathExtractor 方法

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `extract_common_xpath()` | detail_visits | str \| None | 从探索记录中提取公共 xpath |

---

*最后更新: 2026-01-08*
