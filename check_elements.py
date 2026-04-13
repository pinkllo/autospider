import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = 'https://ygp.gdzwfw.gov.cn/#/44/jygg'
        await page.goto(url, wait_until='domcontentloaded')
        try:
            await page.wait_for_load_state('networkidle', timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        targets = ['招标公告及资格预审', '交通运输工程', '土地矿业', '中标结果']
        
        print('=== 初始状态 ===')
        for t in targets:
            c = await page.get_by_text(t, exact=True).count()
            print(f'  {t}: exact={c}')
        
        # 点击 "土地矿业"
        print('\n=== 点击 "土地矿业" ===')
        await page.get_by_text('土地矿业', exact=True).click()
        await page.wait_for_timeout(2000)
        for t in targets:
            c = await page.get_by_text(t, exact=True).count()
            print(f'  {t}: exact={c}')
        
        # 方案1: goto 同一 URL (当前方式 - 失败)
        print('\n=== 方案1: goto 同一 URL ===')
        await page.goto(url, wait_until='domcontentloaded')
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        for t in targets:
            c = await page.get_by_text(t, exact=True).count()
            print(f'  {t}: exact={c}')

        # 再次点击土地矿业来设置脏状态
        await page.get_by_text('土地矿业', exact=True).click()
        await page.wait_for_timeout(1000)

        # 方案2: 先到 about:blank 再回来
        print('\n=== 方案2: about:blank -> goto URL ===')
        await page.goto('about:blank', wait_until='domcontentloaded')
        await page.wait_for_timeout(500)
        await page.goto(url, wait_until='domcontentloaded')
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
        for t in targets:
            c = await page.get_by_text(t, exact=True).count()
            print(f'  {t}: exact={c}')

        # 再次点击土地矿业
        await page.get_by_text('土地矿业', exact=True).click()
        await page.wait_for_timeout(1000)

        # 方案3: page.reload()
        print('\n=== 方案3: page.reload() ===')
        await page.reload(wait_until='domcontentloaded')
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
        for t in targets:
            c = await page.get_by_text(t, exact=True).count()
            print(f'  {t}: exact={c}')

        await browser.close()

asyncio.run(main())
