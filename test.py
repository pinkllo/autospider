"""
南传ERP浏览器自动化爬虫 - 登录修复版
修复登录问题，增加调试信息
"""

import asyncio
from playwright.async_api import async_playwright, Route
import config
import ddddocr
import pandas as pd
import os
import time
from datetime import datetime
from typing import Optional, Dict


class AsyncNanChuanCrawler:
    """异步爬虫 - 登录修复版"""

    # 性能参数
    CLICK_DELAY = 0.2
    TAB_WAIT_TIMEOUT = 3000
    DATA_WAIT_TIMEOUT = 2000
    PAGE_LOAD_DELAY = 0.3

    def __init__(self, headless: bool = True, debug: bool = False):
        self.headless = headless
        self.debug = debug
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.current_user = None
        self.ocr = None
        self.stats = {"success": 0, "failed": 0}

    async def init_ocr(self):
        if self.ocr is None:
            loop = asyncio.get_running_loop()
            self.ocr = await loop.run_in_executor(
                None, 
                lambda: ddddocr.DdddOcr(show_ad=False)
            )

    async def get_auto_captcha(self) -> str:
        """获取验证码 - 增强调试"""
        try:
            # 等待验证码图片
            captcha_img = await self.page.wait_for_selector(
                'img[src*="/code/image"]', 
                state="visible", 
                timeout=8000
            )
            
            if not captcha_img:
                if self.debug:
                    print(f"[{self.current_user}] 验证码元素未找到")
                return ""
            
            # 等待图片加载
            await asyncio.sleep(0.5)
            
            # 检查图片尺寸
            box = await captcha_img.bounding_box()
            if self.debug:
                print(f"[{self.current_user}] 验证码尺寸: {box}")
            
            if not box or box['width'] < 20 or box['height'] < 10:
                if self.debug:
                    print(f"[{self.current_user}] 验证码图片未正确加载")
                return ""
            
            # 截图
            img_bytes = await captcha_img.screenshot()
            
            if self.debug:
                # 保存验证码图片用于调试
                os.makedirs("debug", exist_ok=True)
                with open(f"debug/captcha_{self.current_user}_{int(time.time())}.png", "wb") as f:
                    f.write(img_bytes)
            
            if len(img_bytes) < 100:
                if self.debug:
                    print(f"[{self.current_user}] 验证码截图太小: {len(img_bytes)} bytes")
                return ""
            
            # OCR识别
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, 
                lambda: self.ocr.classification(img_bytes)
            )
            
            if self.debug:
                print(f"[{self.current_user}] 验证码识别结果: {result}")
            
            return result
            
        except Exception as e:
            print(f"[{self.current_user}] 验证码识别异常: {e}")
            return ""

    async def _handle_route(self, route: Route):
        """资源拦截 - 确保验证码不被拦截"""
        request = route.request
        url = request.url.lower()
        resource_type = request.resource_type
        
        # 【关键】放行所有与验证码相关的请求
        if any(keyword in url for keyword in ["/code", "captcha", "verify", "vcode"]):
            if self.debug:
                print(f"[ROUTE] 放行验证码: {url[:80]}")
            await route.continue_()
            return
        
        # 放行关键资源类型
        if resource_type in ["document", "xhr", "fetch", "script"]:
            await route.continue_()
            return
        
        # 拦截非关键静态资源（但更保守）
        if resource_type == "font":
            await route.abort()
            return
        
        # 其他资源放行
        await route.continue_()

    async def launch(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-gpu',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security',  # 可能有助于跨域问题
            ]
        )
        
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 资源拦截
        await self.context.route("**/*", self._handle_route)
        
        self.page = await self.context.new_page()
        self.page.set_default_timeout(20000)
        self.page.set_default_navigation_timeout(30000)
        
        # 初始化OCR
        await self.init_ocr()
        
        if self.debug:
            print("[INFO] 浏览器已启动")

    async def login_workflow(self, username: str, password: str) -> bool:
        """登录流程 - 修复版"""
        self.current_user = username
        
        print(f"\n[INFO] 正在登录 [{username}]...")
        
        try:
            await self.page.goto(config.BASE_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"[{username}] 页面加载超时，尝试继续: {e}")
            # 不抛出异常，尝试继续
        
        # 等待页面稳定
        await asyncio.sleep(1)
        
        max_retries = 6
        for attempt in range(max_retries):
            try:
                print(f"[{username}] 第 {attempt + 1}/{max_retries} 次尝试...")
                
                # 刷新验证码（非首次）
                if attempt > 0:
                    try:
                        # 点击验证码图片刷新
                        captcha_img = await self.page.query_selector('img[src*="/code/image"]')
                        if captcha_img:
                            await captcha_img.click()
                            await asyncio.sleep(1)
                        else:
                            await self.page.reload(wait_until="domcontentloaded")
                            await asyncio.sleep(1.5)
                    except Exception as e:
                        if self.debug:
                            print(f"[{username}] 刷新验证码失败: {e}")

                # 清除可能的弹窗遮罩
                await self.page.evaluate("""() => {
                    document.querySelectorAll('.layui-layer-shade, .layui-layer-loading, .layui-layer').forEach(el => el.remove());
                }""")
                await asyncio.sleep(0.3)

                # 等待用户名输入框
                username_input = await self.page.wait_for_selector(
                    'input[name="username"]', 
                    state="visible", 
                    timeout=10000
                )
                
                if not username_input:
                    print(f"[{username}] 未找到用户名输入框")
                    continue

                # 【关键修复】使用 fill() 而不是 evaluate
                # fill() 会正确触发 input/change 事件
                await self.page.fill('input[name="username"]', '')
                await asyncio.sleep(0.1)
                await self.page.fill('input[name="username"]', username)
                
                await self.page.fill('input[name="password"]', '')
                await asyncio.sleep(0.1)
                await self.page.fill('input[name="password"]', password)
                
                # 获取验证码
                code = await self.get_auto_captcha()
                
                if not code:
                    print(f"[{username}] 验证码获取失败")
                    continue
                    
                if len(code) < 3:
                    print(f"[{username}] 验证码太短: {code}")
                    continue
                
                # 填写验证码
                await self.page.fill('input[name="imageCode"]', '')
                await asyncio.sleep(0.1)
                await self.page.fill('input[name="imageCode"]', code)
                
                if self.debug:
                    print(f"[{username}] 表单已填写: 用户名={username}, 验证码={code}")
                
                # 点击登录按钮
                login_clicked = await self.page.evaluate(f"""() => {{
                    let btn = document.evaluate(
                        '{config.LOGIN_BUTTON_XPATH}', 
                        document, 
                        null, 
                        XPathResult.FIRST_ORDERED_NODE_TYPE, 
                        null
                    ).singleNodeValue;
                    if (btn) {{
                        btn.click();
                        return true;
                    }}
                    // 备用：尝试找提交按钮
                    let submitBtn = document.querySelector('button[type="submit"], input[type="submit"], .login-btn, .btn-login');
                    if (submitBtn) {{
                        submitBtn.click();
                        return true;
                    }}
                    return false;
                }}""")
                
                if not login_clicked:
                    print(f"[{username}] 未找到登录按钮")
                    if self.debug:
                        await self.page.screenshot(path=f"debug/no_login_btn_{username}.png")
                    continue
                
                # 等待登录结果
                try:
                    await self.page.wait_for_url("**/manager/**", timeout=12000)
                    print(f"[✓] [{username}] 登录成功!")
                    await asyncio.sleep(1)
                    return True
                except:
                    # 检查错误提示
                    error_msg = await self.page.evaluate("""() => {
                        // 检查各种可能的错误提示
                        let selectors = [
                            '.layui-layer-content',
                            '.error-msg',
                            '.alert-danger',
                            '.login-error',
                            '#errorMsg'
                        ];
                        for (let sel of selectors) {
                            let el = document.querySelector(sel);
                            if (el && el.innerText.trim()) {
                                return el.innerText.trim();
                            }
                        }
                        return '';
                    }""")
                    
                    if error_msg:
                        print(f"[{username}] 登录错误: {error_msg}")
                    else:
                        print(f"[{username}] 登录未跳转，可能验证码错误")
                    
                    if self.debug:
                        await self.page.screenshot(path=f"debug/login_fail_{username}_{attempt}.png")
                    
            except Exception as e:
                print(f"[{username}] 登录异常: {str(e)[:100]}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                await asyncio.sleep(1)
        
        raise Exception(f"账号 [{username}] 经过 {max_retries} 次尝试后登录失败")

    async def fast_click(self, xpath: str) -> bool:
        return await self.page.evaluate("""(xpath) => {
            let el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) { el.click(); return true; }
            return false;
        }""", xpath)

    async def handle_detail_page(self, link_element) -> Optional[Dict]:
        try:
            await link_element.evaluate("el => el.click()")
            
            try:
                await self.page.wait_for_selector(
                    f"xpath={config.TAB_3_XPATH}", 
                    state="visible", 
                    timeout=self.TAB_WAIT_TIMEOUT
                )
                await self.page.click(f"xpath={config.TAB_3_XPATH}")
            except:
                pass
            
            try:
                await self.page.wait_for_selector(
                    '.layui-form-item input, .layui-form-item textarea', 
                    timeout=self.DATA_WAIT_TIMEOUT
                )
            except:
                await asyncio.sleep(0.3)
            
            data = await self.page.evaluate("""() => {
                let r = {};
                function scan(doc) {
                    if (!doc) return;
                    doc.querySelectorAll('.layui-form-item, .layui-inline').forEach(item => {
                        let lbl = item.querySelector('label');
                        if (!lbl) return;
                        let k = lbl.innerText.replace(/[:：*]/g, "").trim();
                        if (!k || k.length > 20) return;
                        let vals = Array.from(item.querySelectorAll('input:not([type="hidden"]), textarea, select'))
                            .filter(el => getComputedStyle(el).display !== 'none')
                            .map(el => el.tagName === 'SELECT' ? el.options[el.selectedIndex]?.text : el.value)
                            .map(v => (v || '').trim())
                            .filter(v => v);
                        if (vals.length) r[k] = vals.join(' ');
                    });
                    ['cipInfo', 'remarks'].forEach(id => {
                        let el = doc.getElementById(id);
                        if (el?.value) r[id] = el.value.trim();
                    });
                }
                scan(document);
                document.querySelectorAll('iframe').forEach(f => { try { scan(f.contentDocument); } catch(e){} });
                return r;
            }""")
            
            if data and len(data) >= 2:
                self.stats["success"] += 1
                return data
            
            self.stats["failed"] += 1
            return None

        except:
            self.stats["failed"] += 1
            return None

    async def fast_return_to_list(self):
        await self.page.evaluate(f"""() => {{
            let btn = document.evaluate('{config.CLOSE_TAB_XPATH}', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (btn) btn.click();
        }}""")
        await asyncio.sleep(self.CLICK_DELAY)

    async def run_steps(self):
        # 快速导航
        await self.fast_click(config.MENU_LEVEL_1)
        await asyncio.sleep(0.5)
        await self.fast_click(config.MENU_LEVEL_2)
        await asyncio.sleep(0.5)
        await self.fast_click(config.MENU_LEVEL_3)
        await asyncio.sleep(1)

        # 查找Frame
        data_frame = None
        for _ in range(20):
            for frame in self.page.frames:
                if await frame.query_selector(f"xpath={config.DETAIL_LINK_XPATH}"):
                    data_frame = frame
                    break
            if data_frame:
                break
            await asyncio.sleep(0.3)
        
        if not data_frame:
            print(f"[{self.current_user}] 未找到数据")
            return

        final_results = []
        page_num = 1
        
        while True:
            try:
                await data_frame.wait_for_selector(f"xpath={config.DETAIL_LINK_XPATH}", timeout=3000)
            except:
                pass
            
            links = await data_frame.query_selector_all(f"xpath={config.DETAIL_LINK_XPATH}")
            total = len(links)
            
            if total == 0:
                break
            
            print(f"[{self.current_user}] 第{page_num}页: {total}条", end=" → ")
            page_success = 0
            
            for i in range(total):
                current_links = await data_frame.query_selector_all(f"xpath={config.DETAIL_LINK_XPATH}")
                if i >= len(current_links):
                    continue
                
                item = await self.handle_detail_page(current_links[i])
                if item:
                    final_results.append(item)
                    page_success += 1
                
                await self.fast_return_to_list()
            
            print(f"成功{page_success}条")
            
            # 翻页
            try:
                next_btn = await data_frame.query_selector(f"xpath={config.NEXT_PAGE_XPATH}")
                if not next_btn:
                    break
                
                is_disabled = await data_frame.evaluate("el => el.classList.contains('layui-disabled')", next_btn)
                if is_disabled:
                    break
                
                first_text = await links[0].inner_text() if links else ""
                await data_frame.evaluate("el => el.click()", next_btn)
                
                for _ in range(15):
                    await asyncio.sleep(self.PAGE_LOAD_DELAY)
                    new_links = await data_frame.query_selector_all(f"xpath={config.DETAIL_LINK_XPATH}")
                    if new_links:
                        new_text = await new_links[0].inner_text()
                        if new_text != first_text:
                            break
                
                page_num += 1
                
            except:
                break
        
        print(f"\n[{self.current_user}] 总计: 成功{self.stats['success']}, 失败{self.stats['failed']}")
        self.save_excel(final_results)

    def save_excel(self, data: list):
        if not data:
            return
        try:
            os.makedirs("output", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"output/{self.current_user}_{ts}.xlsx"
            
            df = pd.DataFrame(data)
            # 将账号插入为第一列
            df.insert(0, '账号', self.current_user)
            
            df.to_excel(path, index=False)
            print(f"[{self.current_user}] ✅ 已保存 {path}")
        except Exception as e:
            print(f"保存失败: {e}")

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except:
            pass


async def process_account(account: dict, semaphore: asyncio.Semaphore, delay: float = 0):
    """处理单个账号 - 添加启动延迟防止并发风控"""
    if delay > 0:
        await asyncio.sleep(delay)
    
    async with semaphore:
        # 【调试模式】设为True可看到更多信息
        crawler = AsyncNanChuanCrawler(headless=True, debug=True)
        try:
            await crawler.launch()
            await crawler.login_workflow(account["username"], account["password"])
            await crawler.run_steps()
            return {"account": account["username"], "status": "success", "count": crawler.stats["success"]}
        except Exception as e:
            print(f"[✗] 账号 {account['username']} 失败: {e}")
            return {"account": account["username"], "status": "failed", "error": str(e)}
        finally:
            await crawler.close()


async def main():
    accounts = config.ACCOUNTS
    print(f"[启动] 账号数: {len(accounts)}")
    
    start = time.time()
    
    # 【关键】降低并发，避免风控
    MAX_CONCURRENT = 1  # 先用1测试登录是否正常
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    # 【关键】错开启动时间
    tasks = []
    for i, acc in enumerate(accounts):
        delay = i * 2  # 每个账号间隔2秒启动
        tasks.append(process_account(acc, semaphore, delay))
    
    results = await asyncio.gather(*tasks)
    
    # 统计
    total_items = sum(r.get("count", 0) for r in results if r.get("status") == "success")
    success_accounts = sum(1 for r in results if r.get("status") == "success")
    
    elapsed = time.time() - start
    
    print(f"\n{'='*50}")
    print(f"[完成] 账号: {success_accounts}/{len(accounts)}")
    print(f"[数据] 总条数: {total_items}")
    print(f"[耗时] {elapsed:.1f}秒")


if __name__ == "__main__":
    asyncio.run(main())