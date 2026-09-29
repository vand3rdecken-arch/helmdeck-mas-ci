import asyncio, json, re, urllib.request, urllib.parse, sys
import websockets
def new_tab():
    r=urllib.request.Request("http://127.0.0.1:9222/json/new?about:blank",method="PUT")
    return json.load(urllib.request.urlopen(r))
def close_tab(i): urllib.request.urlopen("http://127.0.0.1:9222/json/close/"+i).read()
class T:
    async def open(s):
        s.t=new_tab(); s.ws=await websockets.connect(s.t["webSocketDebuggerUrl"],max_size=None); s.n=0
    async def cmd(s,m,**p):
        s.n+=1; i=s.n
        await s.ws.send(json.dumps({"id":i,"method":m,"params":p}))
        while True:
            d=json.loads(await s.ws.recv())
            if d.get("id")==i: return d
    async def ev(s,js):
        d=await s.cmd("Runtime.evaluate",expression=js,returnByValue=True,awaitPromise=True)
        return d.get("result",{}).get("result",{}).get("value")
    async def go(s,u,wait=6):
        await s.cmd("Page.navigate",url=u); await asyncio.sleep(wait)
    async def close(s):
        await s.ws.close(); close_tab(s.t["id"])
