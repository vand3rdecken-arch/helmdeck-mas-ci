"""Deal-Radar, Firmen-Teil (Altersnachfolge): oeffentliche nexxt-change-Inserate.

Nur lesend, ohne Login, kein Suchprofil wird gespeichert (die Suche ist ein
oeffentliches POST-Formular; Abo/Konto-Formulare werden nie angefasst).
Zwei Profile (Owner-Vorgabe 2026-10-08): IT bundesweit, alle Branchen Hessen.

    py -3.12 ops/tools/deal_radar_firms.py [--top 5] [--json]
"""
import argparse
import html
import json
import re
import sys

import requests

BASE = "https://www.nexxt-change.org"
FORM = BASE + "/SiteGlobals/Forms/Verkaufsangebot_Suche/Verkaufsangebotssuche_Formular"
UA = {"User-Agent": "Mozilla/5.0"}

# Werte = interne Rubrik-Pfade aus den <option value> des Suchformulars.
PROFILES = {
    "IT, ganz Deutschland": {"ad_nace": "[8,32]"},  # Information und Kommunikation > Dienstleistungen der IT
    "Alle Branchen, Hessen": {"ad_nuts": "[7]"},  # Hessen > Alle Regionen
}


def _txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def search(session, extra):
    page = session.get(FORM + ".html", headers=UA, timeout=30).text
    form = re.search(r'<form name="VerkaufsangebotsSuche".*?</form>', page, re.S).group(0)
    data = {}
    for tag in re.findall(r'<input[^>]*type="hidden"[^>]*>', form):
        n, v = re.search(r'name="([^"]*)"', tag), re.search(r'value="([^"]*)"', tag)
        data[n.group(1)] = v.group(1) if v else ""
    data.update(extra)
    t = session.post(FORM, data=data, headers=UA, timeout=30).text
    hits = int(re.search(r'id="hits-count">(\d+)', t).group(1))
    items = []
    for li in re.findall(r'<li class="inserat-list-item">(.*?)</li>', t, re.S):
        a = re.search(r'<a href="([^"]+adId=\d+)">(.*?)</a>', li, re.S)
        tops = [_txt(x) for x in re.findall(r'card-topline--secondary">(.*?)</p>', li, re.S)]
        items.append({
            "titel": _txt(a.group(2)), "link": html.unescape(a.group(1)),
            "datum": _txt(re.search(r'class="date">(.*?)<', li).group(1)),
            "branche": tops[0] if tops else "", "ort": tops[-1] if len(tops) > 1 else "",
        })
    return hits, items


def detail(session, item):
    t = session.get(item["link"], headers=UA, timeout=30).content.decode("utf-8", "replace")
    for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", t, re.S):
        k, v = _txt(dt).rstrip(" :"), _txt(dd)
        if re.search(r"Umsatz|Preis", k, re.I) and v:
            item.setdefault("finanz", {})[k] = v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    s = requests.Session()
    out = {}
    for name, extra in PROFILES.items():
        hits, items = search(s, extra)
        items = items[: a.top]  # Liste ist nach Datum, neueste zuerst
        for it in items:
            detail(s, it)
        out[name] = {"treffer": hits, "top": items}
    if a.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
        return
    for name, r in out.items():
        print(f"\n## {name}: {r['treffer']} Treffer")
        for i, it in enumerate(r["top"], 1):
            fin = "; ".join(f"{k}: {v}" for k, v in it.get("finanz", {}).items()) or "keine Angabe"
            print(f"{i}. {it['titel']} ({it['datum']})\n   Branche: {it['branche']} | Ort: {it['ort']} | {fin}\n   {it['link']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
