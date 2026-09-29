import json,re,statistics as S
d=json.load(open("up.json",encoding="utf-8"))
def age(t):
    m=re.match(r"Posted (.*?) \|",t); a=m.group(1) if m else ""
    if "hour" in a or "minute" in a: return 0
    if a=="yesterday": return 1
    m=re.match(r"(\d+) days?",a)
    if m: return int(m.group(1))
    return 99
def price(t):
    m=re.search(r"Fixed price.*?Est\. budget: \| \$([\d,\.]+)",t)
    if m: return ("F",float(m.group(1).replace(",","")))
    m=re.search(r"Hourly: \$([\d\.]+)(?: - \$([\d\.]+))?",t)
    if m:
        a=float(m.group(1)); b=float(m.group(2) or a); return ("H",(a+b)/2,a,b)
    return None
def title(t): return t.split(" | ")[1] if " | " in t else t[:80]
KEY=re.compile(r"upgrad|migrat|new architecture|fabric|turbomodule|sdk \d|target api|api level|api 3\d|16 ?kb|page size|0\.7\d|0\.8\d|outdated|play console|google play",re.I)
for q,rows in d.items():
    r7=[r for r in rows if age(r["t"])<=7]
    F=[price(r["t"]) for r in r7]
    Fx=[p[1] for p in F if p and p[0]=="F"]; Hr=[p for p in F if p and p[0]=="H"]
    rel=[r for r in r7 if KEY.search(r["t"])]
    fs=f"med={S.median(Fx):.0f} min={min(Fx):.0f} max={max(Fx):.0f}" if Fx else ""
    hs=f"med={S.median([h[1] for h in Hr]):.1f} min={min(h[2] for h in Hr):.0f} max={max(h[3] for h in Hr):.0f}" if Hr else ""
    print(f"\n## {q}: total7={len(r7)} fixed n={len(Fx)} {fs} hourly n={len(Hr)} {hs} kw={len(rel)}")
    for r in rel[:40]:
        print("  -",age(r["t"]),"d |",title(r["t"])[:90],"|",price(r["t"]),"|",(r["h"] or "")[-24:])
