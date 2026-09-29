import asyncio, json, re, urllib.parse
from cdp import T
from up_js import JS
terms=["react native upgrade","expo sdk upgrade","react native new architecture","target api 35","16 KB page size"]
async def main():
    t=T(); await t.open(); await t.cmd("Page.bringToFront"); out={}
    try:
        for q in terms:
            rows=[]
            for n in range(1,6):
                await t.go("https://www.upwork.com/nx/search/jobs/?q=%s&sort=recency&per_page=50&page=%d"%(urllib.parse.quote(q),n),7)
                r=json.loads(await t.ev(JS) or "[]")
                if not r:
                    await asyncio.sleep(6); r=json.loads(await t.ev(JS) or "[]")
                if not r: break
                rows+=r
                old=any((m:=re.search(r"Posted (\d+) (day|week|month)",x["t"])) and (m.group(2)!="day" or int(m.group(1))>7) for x in r)
                if old or len(r)<50: break
            out[q]=rows
    finally:
        await t.close()
    json.dump(out,open("up.json","w",encoding="utf-8"),ensure_ascii=False)
    print({k:len(v) for k,v in out.items()})
asyncio.run(main())
