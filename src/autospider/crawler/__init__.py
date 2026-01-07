"""Crawler模块 - 批量爬取执行

该模块负责：
- 基于已知规则执行批量爬取
- URL收集和去重
- 检查点管理和断点续传
- 速率控制和反反爬
"""

__all__ = ["BatchCollector", "URLCollector"]
