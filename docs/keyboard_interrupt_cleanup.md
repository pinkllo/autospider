# Ctrl+C 资源清理改进

## 问题描述

当用户使用 Ctrl+C 中断 AutoSpider 时，出现以下错误：

```
RuntimeError: Event loop is closed
ValueError: I/O operation on closed pipe
```

这些错误表明：
1. 事件循环在关闭时还有未完成的操作
2. Playwright 的子进程管道没有正确关闭

## 根本原因

1. **事件循环清理不完整**：`run_async_safely` 函数在关闭事件循环前没有取消所有待处理任务
2. **异步资源未完全释放**：没有调用 `shutdown_asyncgens()` 和 `shutdown_default_executor()`
3. **浏览器会话清理不完整**：在 asyncio 任务被中断时，context manager 的 `finally` 块可能没有正确执行

## 解决方案

### 1. 改进 `run_async_safely` 函数 (cli.py)

**改进内容：**

```python
def run_async_safely(coro):
    """在 CLI 同步上下文中安全执行协程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环，直接使用 asyncio.run
        try:
            return asyncio.run(coro)
        except KeyboardInterrupt:
            # Ctrl+C 中断时，asyncio.run 会自动清理
            raise

    # 已有运行中的事件循环，需要在新线程中创建新的事件循环
    result_holder: dict[str, object] = {"result": None, "error": None}

    def _runner():
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result_holder["result"] = loop.run_until_complete(coro)
        except KeyboardInterrupt:
            # Ctrl+C 中断，取消所有任务
            result_holder["error"] = KeyboardInterrupt("用户中断")
            if loop:
                # 取消所有待处理的任务
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # 等待所有任务完成取消
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            if loop:
                try:
                    # 关闭所有异步生成器
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    # 关闭所有异步 executor
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
                finally:
                    loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if result_holder["error"] is not None:
        raise result_holder["error"]
    return result_holder["result"]
```

**关键改进：**
- ✅ 捕获 `KeyboardInterrupt` 异常
- ✅ 取消所有待处理的 asyncio 任务
- ✅ 调用 `shutdown_asyncgens()` 关闭所有异步生成器
- ✅ 调用 `shutdown_default_executor()` 关闭默认执行器
- ✅ 正确关闭事件循环

### 2. 改进 `_run_config_generator` 函数

**改进内容：**

```python
async def _run_config_generator(
    list_url: str,
    task: str,
    explore_count: int,
    headless: bool,
    output_dir: str,
):
    """异步运行配置生成器"""
    from .extractor.config_generator import generate_collection_config
    
    session = None
    try:
        async with create_browser_session(headless=headless, close_engine=True) as session:
            return await generate_collection_config(
                page=session.page,
                list_url=list_url,
                task_description=task,
                explore_count=explore_count,
                output_dir=output_dir,
            )
    except (KeyboardInterrupt, asyncio.CancelledError):
        # 确保浏览器会话被正确清理
        if session:
            try:
                await session.stop()
            except Exception:
                pass
        raise KeyboardInterrupt("用户中断")
```

**关键改进：**
- ✅ 显式捕获 `KeyboardInterrupt` 和 `asyncio.CancelledError`
- ✅ 在中断时确保调用 `session.stop()` 清理浏览器资源
- ✅ 重新抛出 `KeyboardInterrupt` 让上层处理

### 3. 现有的清理机制

**`session.py` 中的 `create_browser_session`：**

```python
@asynccontextmanager
async def create_browser_session(
    headless: bool | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    close_engine: bool = False,
) -> AsyncGenerator[BrowserSession, None]:
    """创建浏览器会话的上下文管理器"""
    session = BrowserSession(...)
    try:
        await session.start()
        yield session
    finally:
        await session.stop()
        if close_engine:
            try:
                await shutdown_browser_engine()
            except Exception:
                pass
```

这个 context manager 确保即使发生异常，也会调用 `session.stop()` 和可选的 `shutdown_browser_engine()`。

## 清理流程

当用户按下 Ctrl+C 时，清理流程如下：

1. **KeyboardInterrupt 被捕获** → `run_async_safely` 的内部 `_runner` 函数
2. **取消所有待处理任务** → `task.cancel()` + `asyncio.gather(..., return_exceptions=True)`
3. **关闭异步生成器** → `loop.shutdown_asyncgens()`
4. **关闭默认执行器** → `loop.shutdown_default_executor()`
5. **关闭事件循环** → `loop.close()`
6. **浏览器会话清理** → `session.stop()` (通过 context manager 或显式调用)
7. **关闭浏览器引擎** → `shutdown_browser_engine()` (如果 `close_engine=True`)

## 验证

修改后，当用户按 Ctrl+C 时：

- ✅ 不再出现 `RuntimeError: Event loop is closed`
- ✅ 不再出现 `ValueError: I/O operation on closed pipe`
- ✅ 仅显示 `[yellow]用户中断[/yellow]` 消息
- ✅ 退出代码为 130 (标准的 SIGINT 退出码)

## 其他建议

### 对于其他 CLI 命令

建议对以下函数应用相同的改进模式：

- `_run_agent`
- `_run_batch_collector`
- `_run_collector`
- `_run_field_extractor`
- `_run_batch_xpath_extractor`

### 示例模板

```python
async def _run_xxx(...):
    session = None
    try:
        async with create_browser_session(...) as session:
            return await xxx_function(...)
    except (KeyboardInterrupt, asyncio.CancelledError):
        if session:
            try:
                await session.stop()
            except Exception:
                pass
        raise KeyboardInterrupt("用户中断")
```

## 测试方法

1. 运行任何 CLI 命令：
   ```bash
   autospider generate-config --list-url "https://example.com" --task "测试任务"
   ```

2. 在执行过程中按 Ctrl+C

3. 验证：
   - 程序立即停止
   - 只显示 "用户中断" 消息
   - 没有额外的异常堆栈信息
   - 没有资源泄漏警告
