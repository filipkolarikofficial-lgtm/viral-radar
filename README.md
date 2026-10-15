# Viral radar – týdenní přehled YouTube Shorts

Každé pondělí stáhne z oficiálního YouTube Data API krátká hudební videa
z posledních 14 dní, která mají výrazně víc zhlédnutí než odběratelů autora,
a publikuje je jako webovou stránku (GitHub Pages) s výběrem a poznámkami.

## Nastavení (jednorázově, ~15 minut)

1. **YouTube API klíč** (zdarma): console.cloud.google.com → nový projekt →
   „APIs & Services" → povolit **YouTube Data API v3** → „Credentials" → „Create API key".
2. **GitHub repozitář**: vytvoř nový (může být veřejný) a nahraj do něj obsah této složky
   (včetně skryté složky `.github`).
3. **Secret**: repo → Settings → Secrets and variables → Actions → New repository secret,
   název `YOUTUBE_API_KEY`, hodnota je tvůj klíč.
4. **GitHub Pages**: Settings → Pages → Source „Deploy from a branch", branch `main`, složka `/docs`.
5. **První běh**: záložka Actions → „Týdenní přehled" → Run workflow.
   Za minutu je stránka na `https://<uživatel>.github.io/<repo>/`.

Dál běží samo každé pondělí.

## Ladění

Vše se nastavuje v `config.json` (dotazy, stáří videí, limit odběratelů, minimální poměr).
Test vzhledu bez klíče: `python3 fetch.py --mock` (ukázková data, nepublikovat).

## Omezení

- Jen YouTube Shorts. TikTok, Instagram a Facebook zde nejsou.
- Autoři, kteří skrývají počet odběratelů, se vynechají.
- Kvóta: jeden běh spotřebuje zhruba 1 500 z 10 000 denních jednotek.
- Výběr a poznámky na stránce se ukládají jen v prohlížeči, ve kterém je strejda udělal.
