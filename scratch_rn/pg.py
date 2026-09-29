import asyncio,sys
from cdp import T
async def m(url,n=3000,js=None):
    t=T(); await t.open()
    try:
        await t.cmd("Page.bringToFront"); await t.go(url,8)
        v=await t.ev(js or "document.title+' || '+document.body.innerText.slice(0,%d)"%n)
        print(v)
    finally: await t.close()
asyncio.run(m(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 3000, sys.argv[3] if len(sys.argv)>3 else None))
