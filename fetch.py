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


CZ_CHARS = set("ěščřžťďňůĚŠČŘŽŤĎŇŮ")
CZ_WORDS = {"je", "se", "na", "že", "jsme", "jsem", "kapela", "koncert", "zkouška", "píseň", "písnička",
            "nová", "nový", "máme", "tak", "ale", "jako", "pro", "když", "naše", "zpěvák", "zpěvačka", "klip"}


def is_czech(snippet):
    if snippet.get("defaultAudioLanguage", "").startswith("cs") or snippet.get("defaultLanguage", "").startswith("cs"):
        return True
    text = (snippet.get("title", "") + " " + snippet.get("description", "")[:300]).lower()
    if sum(1 for c in text if c in CZ_CHARS) >= 2:
        return True
    return len(set(re.findall(r"\w+", text)) & CZ_WORDS) >= 2


def why(r, title):
    t = title.lower()
    parts = []
    if re.search(r"who sang|better|vs\.?|which|rate|\?", t):
        parts.append("hook ve formě otázky nebo srovnání, který láká k odpovědi v komentářích")
    if re.search(r"rehears|practice|zkou|backstage|bts|zákulis", t):
        parts.append("zákulisí nebo zkouška: působí autenticky a nepotřebuje produkci")
    if re.search(r"cover|předělávk", t):
        parts.append("cover známé písně, kterou lidi aktivně hledají")
    if re.search(r"live|koncert|concert|solo", t):
        parts.append("živý záběr nebo sólo, hlavní je výkon")
    if re.search(r"😂|funny|meme|vtip|🤣", t):
        parts.append("humor, který se snadno sdílí")
    if r["views"] and r["likes"] is not None and r["likes"] / r["views"] > 0.06:
        parts.append("nadprůměrný poměr lajků (%d %%) – diváci video opravdu přijali" % round(100 * r["likes"] / r["views"]))
    if r["comments"] is not None and r["views"] and r["comments"] / r["views"] > 0.004:
        parts.append("hodně komentářů, video vyvolává reakce")
    if not parts:
        parts.append("důvod z názvu nepoznám, podívej se na prvních 3 sekundy videa")
    return "; ".join(parts[:3]).capitalize() + "."


FORMATS = [
    ("Srovnání / otázka", r"who sang|better|vs\.?|which|rate|\?|choose|pick",
     "Zahrajte nebo zazpívejte stejnou pasáž dvěma způsoby (např. česky a anglicky, akusticky a naplno) a zeptejte se, která verze je lepší. Výhoda: komentáře."),
    ("Zkouška / zákulisí", r"rehears|practice|backstage|bts|soundcheck|behind the scenes|tour bus|before the show",
     "Natočte 15–20 s ze zkoušky nebo zákulisí: jeden konkrétní okamžik (chyba, smích, nový nápad), ne celou písničku. Telefon na stativ, bez střihu."),
    ("Cover", r"cover|acoustic|unplugged",
     "Vezměte známou písničku a udělejte ji ve stylu Fate Magazine (pop-rock aranž, duet, jiný jazyk). Prvních 2 s musí být refrén nebo hlavní hook."),
    ("Živě / sólo", r"live|concert|solo|stage|festival|gig",
     "Vyberte 15 s z koncertu s největší energií (refrén, sólo, reakce publika). Titulek s jednou větou, co se tam stalo."),
    ("Humor / situace", r"😂|🤣|funny|meme|relatable|pov|when ",
     "Krátká vtipná scénka z života kapely (POV: zkouška, cesta na koncert, technika). Postačí jedna replika a reakce."),
]


def fmt_tag(title):
    t = title.lower()
    for name, pat, idea in FORMATS:
        if re.search(pat, t):
            return name, idea
    return "Jiné", "Podívejte se na prvních 3 sekundy: co dělá hook? Zkuste stejný princip s vlastní písničkou."


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def collect(cfg):
    after = (datetime.now(timezone.utc) - timedelta(days=cfg["days_back"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = {}  # video_id -> region label
    for region in cfg["regions"]:
        for q in cfg["queries"][region["queries"]]:
            params = dict(part="id", type="video", videoDuration="short", order=region.get("order", "viewCount"),
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

    seed_ids = set()
    for ref in cfg.get("seed_channels", []):
        p = dict(part="contentDetails", forHandle=ref) if ref.startswith("@") else dict(part="contentDetails", id=ref)
        try:
            res = api("channels", **p)
            for ch in res.get("items", []):
                pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
                items = api("playlistItems", part="contentDetails", playlistId=pl, maxResults=15).get("items", [])
                for it in items:
                    if it["contentDetails"].get("videoPublishedAt", "9999") >= after:
                        ids.setdefault(it["contentDetails"]["videoId"], "Sledované")
                        seed_ids.add(it["contentDetails"]["videoId"])
        except Exception as e:
            print("seed kanál selhal %s: %s" % (ref, e), file=sys.stderr)

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

    cz_found = [v for v in videos.values() if is_czech(v["snippet"])]
    print("Diagnostika: kandidátů %d, z toho česky %d" % (len(videos), len(cz_found)))
    for v in cz_found[:15]:
        st = v.get("statistics", {})
        ch = channels.get(v["snippet"]["channelId"], {})
        print("  CZ kandidát: %s views=%s subs=%s dur=%s" % (v["snippet"]["title"][:40], st.get("viewCount"), ch.get("subscriberCount"), v["contentDetails"]["duration"]))
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
        lim = {r["label"]: r for r in cfg["regions"]}.get(ids[vid], {})
        min_views = lim.get("min_views", cfg["min_views"])
        min_ratio = lim.get("min_ratio", cfg["min_ratio"])
        if views < min_views:
            continue
        seed = vid in seed_ids
        if subs is None or (subs > cfg["max_subscribers"] and not seed):
            continue
        ratio = views / max(subs, 1)
        if ratio < min_ratio and not seed:
            continue
        low = (v["snippet"]["title"] + " " + v["snippet"]["channelTitle"]).lower()
        if any(w in low for w in cfg.get("exclude_words", [])):
            continue
        czech = is_czech(v["snippet"])
        if cfg.get("czech_only_for_cz") and ids[vid] == "CZ" and not czech:
            continue
        row = {
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
            "market": "Sledované" if seed else ("CZ" if czech else "Svět"),
            "fetched": fetched,
        }
        row["why"] = why(row, v["snippet"]["title"])
        row["format"], row["idea"] = fmt_tag(v["snippet"]["title"])
        rows.append(row)
    rows.sort(key=lambda r: r["ratio"], reverse=True)
    out, per = [], {}
    for r in rows:
        if per.get(r["author_url"], 0) >= cfg.get("max_per_channel", 2):
            continue
        per[r["author_url"]] = per.get(r["author_url"], 0) + 1
        out.append(r)
    return out[:cfg["max_rows"]]


def mock_rows():
    return [{
        "id": "MOCK%d" % i, "url": "https://www.youtube.com/shorts/MOCK%d" % i,
        "title": "UKÁZKOVÁ DATA %d (není skutečné video)" % i, "author": "Ukázkový autor",
        "author_url": "#", "subscribers": 1200 * i, "views": 250000 // i, "likes": 9000 // i,
        "comments": 300 // i, "published": datetime.now().strftime("%Y-%m-%d"), "duration": 30,
        "ratio": round((250000 // i) / (1200 * i), 1), "market": "CZ" if i % 2 else "Svět",
        "fetched": "mock", "why": "Ukázkový text.", "format": "Cover", "idea": "Ukázka.",
    } for i in range(1, 7)]


def fmt(n):
    return "–" if n is None else "{:,}".format(n).replace(",", " ")


def render(rows, cfg):
    trs = []
    for r in rows:
        trs.append(
            '<tr data-id="{id}"><td><input type="checkbox" class="pick" aria-label="Vybrat"></td>'
            '<td class="vid"><a href="{url}" target="_blank" rel="noopener"><img src="https://i.ytimg.com/vi/{id}/mqdefault.jpg" alt="" loading="lazy"></a>'
            '<div><a href="{url}" target="_blank" rel="noopener">{title}</a><div class="sub">{published} · <span class="tag">{format}</span></div></div></td>'
            '<td><a href="{author_url}" target="_blank" rel="noopener">{author}</a></td>'
            '<td class="n">{subs}</td><td class="n">{views}</td><td class="n">{likes}</td><td class="n">{comments}</td>'
            '<td class="n"><b>{ratio}×</b></td><td class="why">{why}</td><td class="why idea">{idea}</td>'
            '<td><input type="text" class="note" placeholder="poznámka…"></td></tr>'.format(
                id=html.escape(r["id"]), url=html.escape(r["url"]), title=html.escape(r["title"]),
                published=r["published"], market=html.escape(r["market"]),
                author_url=html.escape(r["author_url"]), author=html.escape(r["author"]),
                subs=fmt(r["subscribers"]), views=fmt(r["views"]), likes=fmt(r["likes"]),
                comments=fmt(r["comments"]), ratio=r["ratio"], why=html.escape(r.get("why", "")), format=html.escape(r.get("format", "")), idea=html.escape(r.get("idea", ""))))
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
table{border-collapse:collapse;width:100%;min-width:1180px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--acc)}.sub{color:var(--mut);font-size:12px}
tr.sel{background:color-mix(in srgb,var(--acc) 12%,transparent)}
.note{width:100%;min-width:130px;font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:transparent;color:var(--fg)}
.vid{display:flex;gap:10px;min-width:300px}.vid img{width:96px;height:54px;object-fit:cover;border-radius:4px;flex:none;background:var(--line)}.tag{background:var(--line);padding:1px 6px;border-radius:10px}.idea{min-width:260px;color:var(--fg)}.why{font-size:13px;color:var(--mut);min-width:220px}.foot{color:var(--mut);font-size:13px;margin-top:16px}
</style></head><body><main>
<h1>Virální krátká videa (YouTube Shorts)</h1>
<p class="meta">Aktualizováno: %%UPDATED%% · %%COUNT%% videí z posledních %%DAYS%% dní · zahraniční autoři do %%MAXSUBS%% odběratelů · řazeno podle poměru zhlédnutí ku odběratelům</p>
<div class="bar"><button id="only">Jen vybraná</button><button id="all">Všechna</button>
<a href="videos.csv">Stáhnout CSV</a><span id="cnt" class="sub"></span></div>
<div class="wrap"><table><thead><tr><th></th><th>Video</th><th>Autor</th><th class="n">Odběratelé</th>
<th class="n">Zhlédnutí</th><th class="n">Lajky</th><th class="n">Komentáře</th><th class="n">Poměr</th><th>Proč to (asi) funguje</th><th>Jak na to s Fate Magazine</th><th>Poznámka</th></tr></thead>
<tbody>
%%ROWS%%
</tbody></table></div>
<p class="foot">Čísla pocházejí z oficiálního YouTube Data API v době aktualizace. Výběr a poznámky se ukládají jen v tomto prohlížeči.
„Proč to funguje“ je automatický odhad podle názvu a čísel, ne ověřený fakt. „Poměr“ = zhlédnutí ÷ odběratelé autora; vysoký poměr naznačuje, že video funguje díky nápadu, ne velkému účtu.</p>
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
