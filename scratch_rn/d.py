import asyncio
from cdp import T
import up_js
async def m():
    t=T(); await t.open()
    try:
        await t.cmd("Page.bringToFront")
        await t.go("https://www.upwork.com/nx/search/jobs/?q=react%20native%20upgrade&sort=recency&per_page=50&page=1",9)
        print(await t.ev("document.querySelectorAll('article').length"))
        d=await t.cmd("Runtime.evaluate",expression=up_js.JS,returnByValue=True); print(str(d)[:500])
    finally: await t.close()
asyncio.run(m())
