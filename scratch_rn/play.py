import asyncio,json,re,sys,urllib.request
from cdp import T
JS=r"""(()=>{const h=document.documentElement.innerHTML;
const em=[...new Set((h.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g)||[]))].filter(e=>!/google|gstatic|example|sentry|schema|w3\.org|\.png|\.jpg|\.webp|\.js$/i.test(e));
const t=document.body.innerText;
const g=(re)=>{const m=t.match(re);return m?m[1]:null};
return JSON.stringify({title:(document.querySelector('h1')||{}).innerText,emails:em.slice(0,4),
installs:g(/([\d.,]+[KMB]?\+)\s*\n?\s*Downloads/),updated:g(/Updated on\s*\n?\s*([A-Za-z]{3} \d+, \d{4})/),
cat:g(/(Health & Fitness|Medical|Productivity|Business|Tools|Lifestyle|Finance|Education|Social|Travel & Local|Shopping|Food & Drink|Music & Audio|Entertainment|Communication|Maps & Navigation|Sports|News & Magazines|Books & Reference|Auto & Vehicles|House & Home|Photography|Personalization|Events|Art & Design|Video Players & Editors|Dating|Parenting|Beauty|Weather)/),
dev:(document.querySelector('a[href*="/store/apps/dev"]')||{}).innerText,gone:/not found|isn't available|We're sorry/.test(t.slice(0,600)),
head:t.slice(0,60).replace(/\n/g,' ')})})()"""
async def main(ids,outf):
    t=T(); await t.open(); await t.cmd("Page.bringToFront"); res={}
    try:
        for i in ids:
            await t.go("https://play.google.com/store/apps/details?id=%s&hl=en&gl=DE"%i,3)
            v=await t.ev(JS)
            try: res[i]=json.loads(v)
            except Exception: res[i]={"err":str(v)[:100]}
            json.dump(res,open(outf,"w",encoding="utf-8"),ensure_ascii=False)
    finally: await t.close()
    print(len(res))
if __name__=="__main__":
    ids=open(sys.argv[1]).read().split()
    asyncio.run(main(ids,sys.argv[2]))
