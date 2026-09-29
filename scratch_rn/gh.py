import json,re,urllib.request,urllib.parse,time,concurrent.futures as cf
H={"User-Agent":"Mozilla/5.0","Accept":"application/vnd.github+json"}
def get(u,raw=False):
    try:
        return urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=20).read().decode("utf-8","replace")
    except Exception as e: return ""
qs=['topic:react-native "play.google.com" in:readme pushed:<2025-09-01 fork:false',
    'topic:expo "play.google.com" in:readme pushed:<2025-09-01 fork:false',
    '"react native" "play.google.com" in:readme pushed:<2025-09-01 fork:false',
    '"expo" "play.google.com" in:readme pushed:<2025-09-01 fork:false']
repos={}
for q in qs:
    for p in range(1,6):
        d=get("https://api.github.com/search/repositories?q=%s&per_page=100&page=%d"%(urllib.parse.quote(q),p))
        try: items=json.loads(d).get("items",[])
        except Exception: items=[]
        print(q[:30],p,len(items),flush=True)
        for i in items: repos[i["full_name"]]=i["pushed_at"]
        if len(items)<100: break
        time.sleep(7)
    time.sleep(7)
print("repos",len(repos))
def readme(r):
    for n in ("README.md","readme.md","Readme.md"):
        t=get("https://raw.githubusercontent.com/%s/HEAD/%s"%(r,n))
        if t: return r,t
    return r,""
ids={}
with cf.ThreadPoolExecutor(8) as ex:
    for r,t in ex.map(readme,repos):
        for m in set(re.findall(r"play\.google\.com/store/apps/details\?id=([A-Za-z0-9_.]+)",t)):
            ids.setdefault(m,r)
json.dump(ids,open("ids2.json","w"))
print("ids",len(ids))
