import re
exec(open("an.py",encoding="utf-8").read().split("for q,rows in d.items():")[0])
print("=== detail")
for q in ["expo sdk upgrade","target api 35"]:
    for r in d[q]:
        if age(r["t"])<=7: print(q,"|",age(r["t"]),"|",title(r["t"])[:100],"|",price(r["t"]))
print("--- existing/maintain/fix in RN upgrade+new arch")
seen=set()
for q in ["react native upgrade","react native new architecture"]:
    for r in d[q]:
        t=title(r["t"])
        if age(r["t"])<=7 and t not in seen and re.search(r"existing|maintain|fix|update|bug|rescue|rebuild|legacy|publish|release|store",r["t"][:400],re.I):
            seen.add(t); print(age(r["t"]),"|",t[:95],"|",price(r["t"]))
u=set()
for q in d:
    for r in d[q]:
        if age(r["t"])<=7: u.add(r["h"])
print("unique jobs across terms in 7d:",len(u))
