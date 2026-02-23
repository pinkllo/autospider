import asyncio

async def test():
    from autospider.common.browser import BrowserSession, shutdown_browser_engine
    
    session = BrowserSession(headless=False)
    await session.start()
    
    try:
        print('navigating...')
        await session.page.goto('https://ygp.gdzwfw.gov.cn/#/44/jygg', wait_until='networkidle')
        await session.page.wait_for_timeout(2000)
        print('url before:', session.page.url)
        
        # We need to click '交通运输工程' and see if URL changes
        loc = session.page.locator("text='交通运输工程'").first
        if await loc.count() > 0:
            print('Clicking 交通运输工程...')
            await loc.click()
            await session.page.wait_for_timeout(2000)
            print('url after:', session.page.url)
        else:
            print('Element not found')
            
    except Exception as e:
        print(e)
    finally:
        await session.stop()
        await shutdown_browser_engine()

if __name__ == '__main__':
    asyncio.run(test())
