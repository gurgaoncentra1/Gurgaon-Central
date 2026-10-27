# How this site is built

`src/site.html` is the ONE file to edit (all images inlined as base64).
The files the website actually serves are generated from it:

    python3 tools/build.py                       # rebuild everything
    python3 tools/build.py --site-url https://YOUR-LIVE-URL/   # also writes sitemap.xml + robots.txt

Generated (do not edit by hand): `index.html`, `<tab>/index.html`,
`shopping/<place>/index.html`, `assets/`.

After every change to `src/site.html`: run the build, then commit `src/` plus the generated files together.
Needs Python 3 and Playwright (Chromium).
