#!/usr/bin/env python3
"""Týdenní přehled virálních YouTube Shorts v hudební nice.

Používá oficiální YouTube Data API v3 (jen standardní knihovna Pythonu).
Klíč se čte z proměnné prostředí YOUTUBE_API_KEY.
Vše se nastavuje v config.json. Výstup: docs/data.json, docs/index.html, docs/videos.csv.

Režim bez klíče: `python fetch.py --mock` použije ukázková data (jen pro test vzhledu).
"""
import csv
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://www.googleapis.com/youtube/v3/"


def api(endpoint, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"]
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def parse_duration(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 10**6
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def collect(cfg):
    after = (datetime.now(timezone.utc) - timedelta(days=cfg["days_back"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = {}  # video_id -> region label
    for region in cfg["regions"]:
        for q in cfg["queries"][region["queries"]]:
            params = dict(part="id", type="video", videoDuration="short", order="viewCount",
                          publishedAfter=after, q=q, maxResults=cfg["results_per_query"])
            if region.get("regionCode"):
                params["regionCode"] = region["regionCode"]
            if region.get("language"):
                params["relevanceLanguage"] = region["language"]
            try:
                res = api("search", **params)
            except Exception as e:  # kvóta, síť...
                print("search selhalo pro '%s': %s" % (q, e), file=sys.stderr)
                continue
            for it in res.get("items", []):
                ids.setdefault(it["id"]["videoId"], region["label"])

    videos = {}
    for batch in chunks(ids, 50):
        res = api("videos", part="snippet,statistics,contentDetails", id=",".join(batch))
        for v in res.get("items", []):
            videos[v["id"]] = v

    channel_ids = {v["snippet"]["channelId"] for v in videos.values()}
    channels = {}
    for batch in chunks(channel_ids, 50):
        res = api("channels", part="statistics", id=",".join(batch))
        for c in res.get("items", []):
            channels[c["id"]] = c["statistics"]

    rows = []
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for vid, v in videos.items():
        dur = parse_duration(v["contentDetails"]["duration"])
        if dur > cfg["max_duration_seconds"]:
            continue
        st = v.get("statistics", {})
        views = int(st.get("viewCount", 0))
        ch = channels.get(v["snippet"]["channelId"], {})
        hidden = ch.get("hiddenSubscriberCount", False)
        subs = None if hidden or "subscriberCount" not in ch else int(ch["subscriberCount"])
        if views < cfg["min_views"]:
            continue
        if subs is None or subs > cfg["max_subscribers"]:
            continue
        ratio = views / max(subs, 1)
        if ratio < cfg["min_ratio"]:
            continue
        rows.append({
            "id": vid,
            "url": "https://www.youtube.com/shorts/" + vid,
            "title": v["snippet"]["title"],
            "author": v["snippet"]["channelTitle"],
            "author_url": "https://www.youtube.com/channel/" + v["snippet"]["channelId"],
            "subscribers": subs,
            "views": views,
            "likes": int(st["likeCount"]) if "likeCount" in st else None,
            "comments": int(st["commentCount"]) if "commentCount" in st else None,
            "published": v["snippet"]["publishedAt"][:10],
            "duration": dur,
            "ratio": round(ratio, 1),
            "market": ids[vid],
            "fetched": fetched,
        })
    rows.sort(key=lambda r: r["ratio"], reverse=True)
    return rows[:cfg["max_rows"]]


def mock_rows():
    return [{
        "id": "MOCK%d" % i, "url": "https://www.youtube.com/shorts/MOCK%d" % i,
        "title": "UKÁZKOVÁ DATA %d (není skutečné video)" % i, "author": "Ukázkový autor",
        "author_url": "#", "subscribers": 1200 * i, "views": 250000 // i, "likes": 9000 // i,
        "comments": 300 // i, "published": datetime.now().strftime("%Y-%m-%d"), "duration": 30,
        "ratio": round((250000 // i) / (1200 * i), 1), "market": "CZ" if i % 2 else "Svět",
        "fetched": "mock",
    } for i in range(1, 7)]


def fmt(n):
    return "–" if n is None else "{:,}".format(n).replace(",", " ")


def render(rows, cfg):
    trs = []
    for r in rows:
        trs.append(
            '<tr data-id="{id}"><td><input type="checkbox" class="pick" aria-label="Vybrat"></td>'
            '<td><a href="{url}" target="_blank" rel="noopener">{title}</a><div class="sub">{published} · {market}</div></td>'
            '<td><a href="{author_url}" target="_blank" rel="noopener">{author}</a></td>'
            '<td class="n">{subs}</td><td class="n">{views}</td><td class="n">{likes}</td><td class="n">{comments}</td>'
            '<td class="n"><b>{ratio}×</b></td>'
            '<td><input type="text" class="note" placeholder="poznámka…"></td></tr>'.format(
                id=html.escape(r["id"]), url=html.escape(r["url"]), title=html.escape(r["title"]),
                published=r["published"], market=html.escape(r["market"]),
                author_url=html.escape(r["author_url"]), author=html.escape(r["author"]),
                subs=fmt(r["subscribers"]), views=fmt(r["views"]), likes=fmt(r["likes"]),
                comments=fmt(r["comments"]), ratio=r["ratio"]))
    updated = rows[0]["fetched"] if rows else "–"
    page = PAGE.replace("%%ROWS%%", "\n".join(trs)).replace("%%UPDATED%%", html.escape(updated)) \
        .replace("%%COUNT%%", str(len(rows))).replace("%%MAXSUBS%%", fmt(cfg["max_subscribers"])) \
        .replace("%%DAYS%%", str(cfg["days_back"]))
    return page


PAGE = """<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Virální videa pro kapelu</title>
<style>
:root{--bg:#fafaf7;--fg:#1c1c1a;--mut:#6b6b66;--line:#e2e2dc;--card:#fff;--acc:#c2410c}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ececE6;--mut:#9a9a92;--line:#33332f;--card:#1f1f1c;--acc:#fb923c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 4px}p.meta{color:var(--mut);margin:0 0 16px}
.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
button{font:inherit;padding:6px 12px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;cursor:pointer}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--acc)}.sub{color:var(--mut);font-size:12px}
tr.sel{background:color-mix(in srgb,var(--acc) 12%,transparent)}
.note{width:100%;min-width:130px;font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:transparent;color:var(--fg)}
.foot{color:var(--mut);font-size:13px;margin-top:16px}
</style></head><body><main>
<h1>Virální krátká videa (YouTube Shorts)</h1>
<p class="meta">Aktualizováno: %%UPDATED%% · %%COUNT%% videí z posledních %%DAYS%% dní · autoři do %%MAXSUBS%% odběratelů · řazeno podle poměru zhlédnutí ku odběratelům</p>
<div class="bar"><button id="only">Jen vybraná</button><button id="all">Všechna</button>
<a href="videos.csv">Stáhnout CSV</a><span id="cnt" class="sub"></span></div>
<div class="wrap"><table><thead><tr><th></th><th>Video</th><th>Autor</th><th class="n">Odběratelé</th>
<th class="n">Zhlédnutí</th><th class="n">Lajky</th><th class="n">Komentáře</th><th class="n">Poměr</th><th>Poznámka</th></tr></thead>
<tbody>
%%ROWS%%
</tbody></table></div>
<p class="foot">Čísla pocházejí z oficiálního YouTube Data API v době aktualizace. Výběr a poznámky se ukládají jen v tomto prohlížeči.
„Poměr“ = zhlédnutí ÷ odběratelé autora; vysoký poměr naznačuje, že video funguje díky nápadu, ne velkému účtu.</p>
</main>
<script>
var K="vr-state",S={};try{S=JSON.parse(localStorage.getItem(K)||"{}")}catch(e){}
function save(){try{localStorage.setItem(K,JSON.stringify(S))}catch(e){}}
var rows=[].slice.call(document.querySelectorAll("tbody tr"));
function count(){document.getElementById("cnt").textContent=rows.filter(function(r){return r.classList.contains("sel")}).length+" vybráno"}
rows.forEach(function(r){var id=r.dataset.id,s=S[id]||{},c=r.querySelector(".pick"),n=r.querySelector(".note");
c.checked=!!s.p;n.value=s.n||"";r.classList.toggle("sel",c.checked);
c.onchange=function(){S[id]=S[id]||{};S[id].p=c.checked;r.classList.toggle("sel",c.checked);save();count()};
n.oninput=function(){S[id]=S[id]||{};S[id].n=n.value;save()}});
document.getElementById("only").onclick=function(){rows.forEach(function(r){r.hidden=!r.classList.contains("sel")})};
document.getElementById("all").onclick=function(){rows.forEach(function(r){r.hidden=false})};
count();
</script></body></html>
"""


def main():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    if "--mock" in sys.argv:
        rows = mock_rows()
    else:
        if not os.environ.get("YOUTUBE_API_KEY"):
            sys.exit("Chybí proměnná YOUTUBE_API_KEY.")
        rows = collect(cfg)
    out = os.path.join(HERE, "docs")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "data.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "videos.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(rows, cfg))
    print("Hotovo: %d videí." % len(rows))


if __name__ == "__main__":
    main()
