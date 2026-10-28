# How this site is built

`src/site.html` is the ONE file to edit (all images inlined as base64).
The files the website actually serves are generated from it:

    python3 tools/build.py                       # rebuild everything
    (the live address https://gurgaoncentral.in/ is built in; it adds canonical tags, sitemap.xml and robots.txt)

Generated (do not edit by hand): `index.html`, `<tab>/index.html`,
`<tab>/<item>/index.html` (one per card on Shopping, Food, Education, Hidden Gems, Events, Sidequests, Travel), `assets/`.

After every change to `src/site.html`: run the build, then commit `src/` plus the generated files together.
Needs Python 3 and Playwright (Chromium).

## Events expire by themselves
Every dated event in `src/site.html` (Events page) carries an `end:'YYYY-MM-DD'` field. The page hides an event
automatically once that date has passed (India time), so nothing has to be removed by hand. When adding a new
dated event, always include `end`. Undated cards ("Concert season", "Theatre and stage shows") have no `end`.
