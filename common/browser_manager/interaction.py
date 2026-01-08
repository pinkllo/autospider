"""
人工交互工具模块

提供自动化流程中人工介入的辅助功能，例如等待人工登录。
"""
import asyncio
import os
from typing import Optional, Set
from playwright.async_api import Page
from loguru import logger


# 浏览器内提示 UI 的 CSS 样式和 HTML 模板
_OVERLAY_STYLE = """
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    z-index: 2147483647;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    text-align: center;
    padding: 15px 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    box-sizing: border-box;
"""

_BUTTON_STYLE = """
    margin-left: 20px;
    padding: 8px 24px;
    font-size: 14px;
    font-weight: bold;
    color: white;
    background-color: #28a745;
    border: none;
    border-radius: 5px;
    cursor: pointer;
    transition: background-color 0.2s;
"""


async def handle_human_login(
    page: Page, 
    auth_file: str = "auth.json",
    success_selector: Optional[str] = None,
    target_url_contains: Optional[str] = None,
    wait_url_change: bool = True,
    wait_cookie_change: bool = True,
    poll_interval: int = 1000,
    timeout: int = 300000 
) -> Page:
    """
    暂停自动化流程，等待人工在浏览器中完成登录，并自动保存状态。
    
    该函数提供多种登录成功检测策略，按优先级依次使用：
    1. 若指定了 `success_selector`，等待该元素出现。
    2. 若指定了 `target_url_contains`，等待 URL 包含该字符串。
    3. 若 `wait_url_change=True`（默认），监测 URL 是否发生变化。
    4. 若 URL 未变化且 `wait_cookie_change=True`（默认），监测 Cookie 是否发生变化。
    5. 若以上均未触发，在页面上显示确认按钮，等待用户手动点击确认。
    
    Args:
        page: 当前活动的 Playwright 页面对象。
        auth_file: 登录状态保存路径（json 文件），支持相对或绝对路径。
        success_selector: (可选) 登录成功后出现的元素选择器，如 ".user-avatar"。
        target_url_contains: (可选) 登录成功后 URL 应包含的字符串，如 "/dashboard"。
        wait_url_change: 是否启用 URL 变化检测（默认 True）。
        wait_cookie_change: 是否启用 Cookie 变化检测（默认 True）。
        poll_interval: 变化检测的轮询间隔（毫秒），默认 1000ms。
        timeout: 等待登录的超时时间（毫秒），默认 300,000ms (5分钟)。

    Returns:
        Page: 处理完登录后的页面对象（引用相同，但状态已保存）。
    
    Examples:
        # 方式1：自动监测 URL 或 Cookie 变化（最通用，推荐）
        await handle_human_login(page, auth_file="cookies.json")
        
        # 方式2：指定登录成功后出现的元素
        await handle_human_login(page, success_selector="img.avatar")
        
        # 方式3：禁用所有自动检测，纯手动确认（在页面上点击按钮）
        await handle_human_login(page, wait_url_change=False, wait_cookie_change=False)
    """
    initial_url = page.url
    initial_cookies = await _get_cookie_names(page)
    
    logger.warning(">>> 触发人工接管模式 <<<")
    logger.info(f">>> 当前页面: {initial_url}")
    logger.info(f">>> 当前 Cookie 数量: {len(initial_cookies)}")
    
    try:
        # 尝试将浏览器窗口带到前台，并显示提示
        try:
            await page.bring_to_front()
        except Exception:
            pass
        
        # 在页面上显示等待登录的提示横幅
        await _show_login_prompt(page, "请在此页面完成登录操作，系统将自动检测登录状态...")

        # ========== 策略1：等待指定元素 ==========
        if success_selector:
            logger.info(f">>> [策略: 元素检测] 等待元素出现: '{success_selector}'")
            await page.wait_for_selector(success_selector, timeout=timeout, state="visible")
            logger.success(">>> 检测到目标元素，判定为登录成功！")
        
        # ========== 策略2：等待目标 URL ==========
        elif target_url_contains:
            logger.info(f">>> [策略: URL 匹配] 等待 URL 包含: '{target_url_contains}'")
            await _wait_for_url_contains(page, target_url_contains, timeout, poll_interval)
            logger.success(f">>> URL 已匹配目标，判定为登录成功！当前 URL: {page.url}")
        
        # ========== 策略3+4：监测 URL 或 Cookie 变化 ==========
        elif wait_url_change or wait_cookie_change:
            strategies = []
            if wait_url_change:
                strategies.append("URL变化")
            if wait_cookie_change:
                strategies.append("Cookie变化")
            logger.info(f">>> [策略: {' / '.join(strategies)}] 开始监测...")
            
            detected = await _wait_for_url_or_cookie_change(
                page, 
                initial_url, 
                initial_cookies,
                wait_url_change,
                wait_cookie_change,
                timeout, 
                poll_interval
            )
            
            if detected == "url":
                logger.success(f">>> URL 已变化，判定为登录成功！新 URL: {page.url}")
            elif detected == "cookie":
                new_cookies = await _get_cookie_names(page)
                added = new_cookies - initial_cookies
                logger.success(f">>> Cookie 已变化，判定为登录成功！新增 Cookie: {added}")
            else:
                # 都没变化，显示确认按钮让用户手动确认
                logger.warning(">>> URL 和 Cookie 均未发生变化，等待用户手动确认...")
                await _wait_for_manual_confirm_in_browser(page, timeout)
        
        # ========== 策略5：直接手动确认 ==========
        else:
            await _wait_for_manual_confirm_in_browser(page, timeout)

        # ========== 移除提示并保存状态 ==========
        await _remove_overlay(page)
        
        save_dir = os.path.dirname(auth_file)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir)

        await page.context.storage_state(path=auth_file)
        logger.info(f">>> 登录状态已保存至: {os.path.abspath(auth_file)}")
        
    except asyncio.TimeoutError:
        await _remove_overlay(page)
        logger.error(f">>> 等待登录超时 ({timeout / 1000}秒)")
        raise
    except Exception as e:
        await _remove_overlay(page)
        logger.error(f">>> 人工登录等待失败: {e}")
        raise

    logger.info(">>> 恢复自动化流程...")
    return page


async def _show_login_prompt(page: Page, message: str) -> None:
    """在页面顶部显示登录提示横幅"""
    js_code = f"""
    () => {{
        // 移除旧的提示（如果有）
        const old = document.getElementById('__human_login_overlay__');
        if (old) old.remove();
        
        // 创建提示横幅
        const overlay = document.createElement('div');
        overlay.id = '__human_login_overlay__';
        overlay.style.cssText = `{_OVERLAY_STYLE} background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;`;
        
        const textSpan = document.createElement('span');
        textSpan.innerText = '{message}';
        textSpan.style.fontSize = '16px';
        overlay.appendChild(textSpan);
        
        // 确保页面内容不被遮挡
        document.body.style.marginTop = '60px';
        document.body.insertBefore(overlay, document.body.firstChild);
    }}
    """
    try:
        await page.evaluate(js_code)
    except Exception:
        pass  # 页面可能已跳转，忽略错误


async def _show_confirm_button(page: Page) -> None:
    """在页面顶部显示确认按钮"""
    js_code = f"""
    () => {{
        // 移除旧的提示（如果有）
        const old = document.getElementById('__human_login_overlay__');
        if (old) old.remove();
        
        // 创建提示横幅
        const overlay = document.createElement('div');
        overlay.id = '__human_login_overlay__';
        overlay.style.cssText = `{_OVERLAY_STYLE} background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white;`;
        
        const textSpan = document.createElement('span');
        textSpan.innerText = '如果您已完成登录，请点击右侧按钮确认 →';
        textSpan.style.fontSize = '16px';
        overlay.appendChild(textSpan);
        
        // 创建确认按钮
        const btn = document.createElement('button');
        btn.id = '__human_login_confirm_btn__';
        btn.innerText = '✓ 登录完成';
        btn.style.cssText = `{_BUTTON_STYLE}`;
        btn.onmouseover = () => btn.style.backgroundColor = '#218838';
        btn.onmouseout = () => btn.style.backgroundColor = '#28a745';
        overlay.appendChild(btn);
        
        document.body.style.marginTop = '60px';
        document.body.insertBefore(overlay, document.body.firstChild);
    }}
    """
    try:
        await page.evaluate(js_code)
    except Exception:
        pass


async def _remove_overlay(page: Page) -> None:
    """移除页面上的提示横幅"""
    js_code = """
    () => {
        const overlay = document.getElementById('__human_login_overlay__');
        if (overlay) overlay.remove();
        document.body.style.marginTop = '';
    }
    """
    try:
        await page.evaluate(js_code)
    except Exception:
        pass


async def _wait_for_manual_confirm_in_browser(page: Page, timeout: int) -> None:
    """
    在页面上显示确认按钮，等待用户点击。
    """
    await _show_confirm_button(page)
    logger.info(">>> [策略: 手动确认] 等待用户在浏览器中点击确认按钮...")
    
    try:
        # 等待按钮被点击
        await page.wait_for_selector(
            "#__human_login_confirm_btn__:not(:visible)", 
            timeout=timeout,
            state="hidden"  # 当按钮消失时说明被点击了
        )
    except Exception:
        # 如果按钮选择器方法失败，改用点击事件监听
        pass
    
    # 备用方案：直接等待按钮点击事件
    await page.evaluate("""
        () => new Promise((resolve) => {
            const btn = document.getElementById('__human_login_confirm_btn__');
            if (btn) {
                btn.addEventListener('click', () => resolve(true), { once: true });
            } else {
                resolve(true); // 按钮不存在，直接继续
            }
        })
    """)
    
    logger.info(">>> 用户已确认登录完成。")


async def _get_cookie_names(page: Page) -> Set[str]:
    """获取当前页面所有 Cookie 的名称集合"""
    cookies = await page.context.cookies()
    return {c["name"] for c in cookies}


async def _wait_for_url_or_cookie_change(
    page: Page, 
    initial_url: str, 
    initial_cookies: Set[str],
    check_url: bool,
    check_cookie: bool,
    timeout: int, 
    poll_interval: int
) -> Optional[str]:
    """
    轮询检测 URL 或 Cookie 是否发生变化。
    
    Returns:
        "url" - URL 发生变化
        "cookie" - Cookie 发生变化
        None - 超时，均未变化
    """
    elapsed = 0
    while elapsed < timeout:
        await asyncio.sleep(poll_interval / 1000)
        elapsed += poll_interval
        
        # 检查 URL 变化
        if check_url:
            current_url = page.url
            if current_url != initial_url:
                return "url"
        
        # 检查 Cookie 变化（新增 Cookie）
        if check_cookie:
            current_cookies = await _get_cookie_names(page)
            if current_cookies != initial_cookies:
                return "cookie"
        
        # 每 10 秒输出一次等待状态
        if elapsed % 10000 == 0:
            logger.debug(f">>> 仍在等待变化... ({elapsed // 1000}s / {timeout // 1000}s)")
    
    return None


async def _wait_for_url_contains(
    page: Page, 
    target: str, 
    timeout: int, 
    poll_interval: int
) -> None:
    """
    轮询检测 URL 是否包含指定字符串。
    
    Raises:
        asyncio.TimeoutError: 超时未匹配。
    """
    elapsed = 0
    while elapsed < timeout:
        if target in page.url:
            return
        
        await asyncio.sleep(poll_interval / 1000)
        elapsed += poll_interval
        
        if elapsed % 10000 == 0:
            logger.debug(f">>> 仍在等待 URL 匹配 '{target}'... ({elapsed // 1000}s / {timeout // 1000}s)")
    
    raise asyncio.TimeoutError(f"等待 URL 包含 '{target}' 超时")
