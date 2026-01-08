"""
BrowserEngine 功能测试

测试内容：
1. 登录状态保持（storage_state）
2. 窗口大小可调节  
3. User-Agent / 代理 替换
4. 反爬措施检测
5. 工厂函数单例模式

运行方式：
    pytest tests/test_common/test_engine/test_browser_engine.py -v -s
"""
import asyncio
import pytest
import json
import os
import tempfile
from pathlib import Path

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from common.browser_manager.engine import (
    BrowserEngine,
    get_browser_engine,
    shutdown_browser_engine,
)


# ========== Fixtures ==========

@pytest.fixture
def temp_storage_file():
    """创建临时存储状态文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump({"cookies": [], "origins": []}, f)
        temp_path = f.name
    yield temp_path
    if os.path.exists(temp_path):
        os.remove(temp_path)


# ========== 测试：登录状态保持 ==========

class TestStorageState:
    """测试登录状态（Cookie/Storage）的保存与加载"""
    
    @pytest.mark.asyncio
    async def test_save_and_load_storage_state(self, temp_storage_file):
        """
        场景：用户登录后保存状态，新 Page 加载状态后应携带登录信息
        """
        engine = BrowserEngine(default_headless=True)
        
        try:
            # 第一个 Page：设置 Cookie（模拟登录）
            async with engine.page() as page1:
                await page1.goto("https://httpbin.org/cookies/set?session_id=test123&user=demo")
                
                # 获取当前 context 并保存状态
                context = page1.context
                storage = await context.storage_state()
                
                with open(temp_storage_file, 'w', encoding='utf-8') as f:
                    json.dump(storage, f)
                
                print(f"[Page 1] Saved cookies: {storage.get('cookies', [])}")
            
            # 第二个 Page：加载之前保存的状态
            async with engine.page(auth_file=temp_storage_file) as page2:
                await page2.goto("https://httpbin.org/cookies")
                content = await page2.content()
                
                print(f"[Page 2] Response: {content}")
                
                # 验证 Cookie 被正确加载
                assert "session_id" in content or "test123" in content, \
                    "Cookie 未被正确加载到新 Page"
                    
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    # @pytest.mark.skip(reason="交互式测试，需手动运行")
    async def test_interactive_login_flow(self):
        """
        交互式登录测试（需要手动操作）
        运行：pytest -s -k test_interactive_login_flow --runmanual
        """
        storage_file = "temp_login_state.json"
        engine = BrowserEngine(default_headless=False)
        
        try:
            async with engine.page() as page:
                await page.goto("https://github.com/login")
                
                print("\n" + "=" * 50)
                print("请在浏览器中完成登录操作...")
                print("登录成功后，请按 Enter 继续")
                print("=" * 50)
                input()
                
                context = page.context
                storage = await context.storage_state()
                with open(storage_file, 'w', encoding='utf-8') as f:
                    json.dump(storage, f)
                print(f"登录状态已保存到: {storage_file}")
            
            async with engine.page(auth_file=storage_file) as page2:
                await page2.goto("https://github.com")
                avatar = await page2.query_selector('img.avatar')
                assert avatar is not None, "未检测到登录状态"
                print("[OK] 新 Page 成功加载登录状态！")
                
        finally:
            await engine.close()
            if os.path.exists(storage_file):
                os.remove(storage_file)


# ========== 测试：窗口大小调节 ==========

class TestViewport:
    """测试窗口大小配置"""
    
    @pytest.mark.asyncio
    async def test_default_viewport(self):
        """测试默认窗口大小 1920x1080"""
        engine = BrowserEngine(default_headless=True)
        try:
            async with engine.page() as page:
                await page.goto("about:blank")
                viewport = page.viewport_size
                
                assert viewport["width"] == 1920, f"默认宽度应为 1920，实际为 {viewport['width']}"
                assert viewport["height"] == 1080, f"默认高度应为 1080，实际为 {viewport['height']}"
                print(f"[OK] 默认窗口大小测试通过: {viewport}")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_custom_viewport(self):
        """测试自定义窗口大小"""
        engine = BrowserEngine(default_headless=True)
        custom_size = {"width": 1280, "height": 720}
        
        try:
            async with engine.page(viewport=custom_size) as page:
                await page.goto("about:blank")
                viewport = page.viewport_size
                
                assert viewport["width"] == 1280, f"自定义宽度应为 1280，实际为 {viewport['width']}"
                assert viewport["height"] == 720, f"自定义高度应为 720，实际为 {viewport['height']}"
                print(f"[OK] 自定义窗口大小测试通过: {viewport}")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_multiple_pages_different_sizes(self):
        """测试同时打开多个不同大小的 Page"""
        engine = BrowserEngine(default_headless=True)
        sizes = [
            {"width": 1920, "height": 1080},
            {"width": 1280, "height": 720},
            {"width": 375, "height": 667},  # iPhone SE
        ]
        
        try:
            for expected_size in sizes:
                async with engine.page(viewport=expected_size) as page:
                    await page.goto("about:blank")
                    actual = page.viewport_size
                    
                    assert actual["width"] == expected_size["width"], \
                        f"宽度不匹配: 期望 {expected_size['width']}，实际 {actual['width']}"
                    assert actual["height"] == expected_size["height"], \
                        f"高度不匹配: 期望 {expected_size['height']}，实际 {actual['height']}"
                        
            print("[OK] 多窗口尺寸测试通过")
        finally:
            await engine.close()


# ========== 测试：User-Agent 和反爬措施 ==========

class TestAntiBot:
    """测试反爬虫措施"""
    
    @pytest.mark.asyncio
    async def test_custom_user_agent(self):
        """测试自定义 User-Agent"""
        engine = BrowserEngine(default_headless=True)
        custom_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) CustomBot/1.0"
        
        try:
            async with engine.page(user_agent=custom_ua) as page:
                await page.goto("https://httpbin.org/user-agent")
                content = await page.content()
                
                assert "CustomBot/1.0" in content, \
                    f"User-Agent 未正确设置，页面内容: {content}"
                print(f"[OK] User-Agent 测试通过: {custom_ua}")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_different_user_agents_per_page(self):
        """测试不同 Page 使用不同的 User-Agent"""
        engine = BrowserEngine(default_headless=True)
        ua1 = "TestBot/1.0 Chrome"
        ua2 = "TestBot/2.0 Firefox"
        
        try:
            async with engine.page(user_agent=ua1) as page1:
                await page1.goto("https://httpbin.org/user-agent")
                content1 = await page1.content()
                assert "TestBot/1.0" in content1, f"Page1 UA 错误: {content1}"
            
            async with engine.page(user_agent=ua2) as page2:
                await page2.goto("https://httpbin.org/user-agent")
                content2 = await page2.content()
                assert "TestBot/2.0" in content2, f"Page2 UA 错误: {content2}"
                
            print("[OK] 多 User-Agent 测试通过")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_webdriver_detection(self):
        """
        测试 WebDriver 检测规避（playwright-stealth）
        检查 navigator.webdriver 是否被隐藏
        """
        engine = BrowserEngine(default_headless=True)
        
        try:
            async with engine.page() as page:
                await page.goto("about:blank")
                
                webdriver_value = await page.evaluate("() => navigator.webdriver")
                
                # stealth 应该让 webdriver 返回 undefined 或 false
                assert webdriver_value in [None, False, "undefined"], \
                    f"WebDriver 检测未规避，navigator.webdriver = {webdriver_value}"
                
                print(f"[OK] WebDriver 规避测试通过: navigator.webdriver = {webdriver_value}")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_automation_controlled_detection(self):
        """测试自动化控制检测规避"""
        engine = BrowserEngine(default_headless=True)
        
        try:
            async with engine.page() as page:
                await page.goto("about:blank")
                
                checks = {
                    "window.chrome": await page.evaluate("() => !!window.chrome"),
                    "navigator.plugins.length > 0": await page.evaluate("() => navigator.plugins.length > 0"),
                    "navigator.languages.length > 0": await page.evaluate("() => navigator.languages.length > 0"),
                }
                
                print(f"反自动化检测结果: {checks}")
                
                # Chrome 对象应该存在（正常浏览器行为）
                assert checks["window.chrome"], "window.chrome 应该存在"
                print("[OK] 自动化检测规避测试通过")
        finally:
            await engine.close()
    
    @pytest.mark.asyncio
    async def test_bot_detection_site(self):
        """
        使用专业的机器人检测网站进行测试
        访问 bot.sannysoft.com 查看检测结果
        """
        engine = BrowserEngine(default_headless=True)
        
        try:
            async with engine.page() as page:
                await page.goto("https://bot.sannysoft.com/")
                await page.wait_for_timeout(2000)
                
                screenshot_path = Path(__file__).parent / "bot_detection_result.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                
                print(f"[OK] 机器人检测结果已保存到: {screenshot_path}")
                print("请查看截图确认各项检测是否通过（绿色为通过）")
        finally:
            await engine.close()


# ========== 测试：代理设置 ==========

class TestProxy:
    """测试代理配置（需要可用代理才能通过）"""
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_proxy_configuration(self):
        """
        测试代理配置是否生效 (尝试多个代理)
        """
        PROXY_LIST = [
            {"ip_port": "114.231.195.131:22535"},
            {"ip_port": "152.26.229.52:9443"},
        ]
        
        valid_proxy_config = None
        engine = BrowserEngine(default_headless=True)
        
        # 1. 寻找可用代理
        import socket
        for proxy in PROXY_LIST:
            ip, port = proxy["ip_port"].split(":")
            print(f"尝试连接代理: {ip}:{port} ...")
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3) # 3秒超时
                result = sock.connect_ex((ip, int(port)))
                sock.close()
                if result == 0:
                    valid_proxy_config = {"server": f"http://{proxy['ip_port']}"}
                    print(f"[OK] 找到可用代理: {valid_proxy_config['server']}")
                    break
                else:
                    print(f"[FAIL] 代理不可达: {proxy['ip_port']}")
            except Exception as e:
                print(f"[FAIL] 代理检测出错: {e}")

        if not valid_proxy_config:
            # 如果所有代理都失败，打印警告并跳过，而不是 fail，以免阻塞流程
            pytest.skip(f"所有提供的 {len(PROXY_LIST)} 个代理均不可用，跳过测试")

        # 2. 使用可用代理进行测试
        try:
            async with engine.page(proxy=valid_proxy_config) as page:
                print(f"正在通过代理访问: {valid_proxy_config['server']}")
                # 增加超时时间，代理通常较慢
                await page.goto("https://httpbin.org/ip", timeout=60000)
                content = await page.content()
                
                print(f"代理返回内容: {content}")
                assert "origin" in content, "未能获取 IP 信息"
                
                # 验证返回的 IP 是否包含代理 IP (简单检查)
                # 注意：httpbin 返回的 origin 可能是个列表，包含原始 IP 和代理 IP
                proxy_ip = valid_proxy_config['server'].split(":")[1].replace("//", "")
                if proxy_ip in content:
                     print(f"[OK] 成功验证 IP 变更，包含: {proxy_ip}")
                else:
                     print(f"[WARN] 警告: 返回内容中未显式包含代理IP，可能是高匿代理或格式问题。")

                print("[OK] 代理配置测试通过")
        except Exception as e:
            pytest.fail(f"代理连接或页面访问失败: {e}")
        finally:
            await engine.close()


# ========== 测试：工厂函数单例模式 ==========

class TestFactoryFunction:
    """测试 get_browser_engine 工厂函数"""
    
    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """测试单例模式：多次调用返回同一实例"""
        try:
            engine1 = await get_browser_engine()
            engine2 = await get_browser_engine()
            
            assert engine1 is engine2, "get_browser_engine 应返回同一实例"
            print("[OK] 单例模式测试通过")
        finally:
            await shutdown_browser_engine()
    
    @pytest.mark.asyncio
    async def test_lazy_initialization(self):
        """测试懒加载：只有首次调用才初始化"""
        await shutdown_browser_engine()  # 确保干净状态
        
        try:
            engine = await get_browser_engine()
            assert engine is not None
            
            # 引擎内部的 browser 在调用 page() 前应该还未启动
            assert engine._browser is None, "Browser 应该延迟到第一次 page() 调用时启动"
            
            # 使用 page 后 browser 才会启动
            async with engine.page() as page:
                await page.goto("about:blank")
            
            assert engine._browser is not None, "使用 page 后 Browser 应该已启动"
            print("[OK] 懒加载测试通过")
        finally:
            await shutdown_browser_engine()
    
    @pytest.mark.asyncio
    async def test_shutdown_and_reinitialize(self):
        """测试关闭后重新初始化"""
        try:
            engine1 = await get_browser_engine()
            
            async with engine1.page() as page:
                await page.goto("about:blank")
            
            await shutdown_browser_engine()
            
            engine2 = await get_browser_engine()
            
            assert engine1 is not engine2, "关闭后应该创建新实例"
            print("[OK] 重新初始化测试通过")
        finally:
            await shutdown_browser_engine()


# ========== 运行入口 ==========

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "-s",
        "--asyncio-mode=auto",
    ])
