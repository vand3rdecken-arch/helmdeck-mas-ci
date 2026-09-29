import json,sys,datetime as D
r=json.load(open(sys.argv[1],encoding="utf-8"))
cut=D.datetime(2025,9,29)
n=0
for k,v in r.items():
    if v.get("gone") or "err" in v or not v.get("title"): print("GONE/ERR",k,v.get("head")); continue
    try: u=D.datetime.strptime(v["updated"],"%b %d, %Y")
    except Exception: u=None
    print("STALE" if u and u<cut else "fresh" ,k,"|",v["title"][:30],"|",v["installs"],"|",v["updated"],"|",v["cat"],"|",v["dev"],"|",v["emails"][:2])
