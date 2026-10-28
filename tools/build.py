#!/usr/bin/env python3
"""Build the Gurgaon Central site from src/site.html.

src/site.html is the single editable source (all images inlined as base64).
Running this script (from the repo root) regenerates:
  index.html                      home page
  <tab>/index.html                one real page per tab (shopping, food, ...)
  <tab>/<item>/index.html         one real page per card (shopping, food, education, gems, events, quests, travel)
  assets/app.<hash>.js, assets/style.<hash>.css, assets/img/<hash>.<ext>
  sitemap.xml + robots.txt        only when SITE_URL is set (see below)

Usage:  python3 tools/build.py [--site-url https://example.com/base/]
Needs:  Python 3 and Playwright (Chromium) for prerendering.
"""
import hashlib, html, json, os, re, shutil, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src', 'site.html')
SITE_URL = None
if '--site-url' in sys.argv:
    SITE_URL = sys.argv[sys.argv.index('--site-url') + 1].rstrip('/') + '/'

RELATED = {'shopping': ['plan', 'food', 'events', 'quests'], 'food': ['plan', 'shopping', 'gems', 'events'], 'education': ['plan', 'travel', 'gems', 'blogs'], 'gems': ['plan', 'quests', 'food', 'travel'], 'events': ['plan', 'quests', 'food', 'shopping'], 'quests': ['plan', 'events', 'gems', 'food'], 'plan': ['shopping', 'food', 'quests', 'travel'], 'travel': ['plan', 'gems', 'shopping', 'education'], 'blogs': ['plan', 'gems', 'food', 'events'], 'tip': ['plan', 'blogs', 'gems', 'food']}

TITLES = {
    'home': ('Gurgaon Central | Your Guide to Gurgaon (Gurugram)', None),
    'shopping': ('Shopping in Gurgaon: Malls, Markets & Flea Finds | Gurgaon Central',
                 'The best malls and markets in Gurgaon (Gurugram): hours, locations and what each place is known for.'),
    'food': ('Food in Gurgaon: Street Food, Cafés & Restaurants | Gurgaon Central',
             'Where to eat in Gurgaon (Gurugram): street food, chole bhature, cafés, restaurants and markets.'),
    'education': ('Education in Gurgaon: B-Schools & Universities | Gurgaon Central',
                  'Business schools and universities in and around Gurgaon (Gurugram).'),
    'gems': ('Hidden Gems in Gurgaon: Museums, Heritage & Nature | Gurgaon Central',
             'Museums, nature parks, stepwells and old towns in Gurgaon (Gurugram) that most people skip.'),
    'events': ('Events in Gurgaon: Shows, Parties & Festivals | Gurgaon Central',
               'Upcoming events in Gurgaon (Gurugram): comedy shows, Halloween and Diwali parties, concerts and festivals.'),
    'quests': ('Sidequests in Gurgaon: Escape Rooms, Go-Karts & More | Gurgaon Central',
               'Things to do in Gurgaon (Gurugram): escape rooms, go-karts, ice skating, gaming arenas and quiet detours.'),
    'plan': ('Plan a Day in Gurgaon: One-Day Planner | Gurgaon Central',
             'Tell us your mood and we will build a one-day plan of places to visit in Gurgaon (Gurugram).'),
    'travel': ('Getting Around Gurgaon: Metro, Cabs, Buses | Gurgaon Central',
               'How to get around Gurgaon (Gurugram): metro, cabs, buses, autos and sample days.'),
    'blogs': ('Blogs: Longer Reads on Gurgaon | Gurgaon Central',
              'Longer reads about Gurgaon (Gurugram) from the Gurgaon Central blogs.'),
    'tip': ('Share a Tip: Tell Us About a Gurgaon Spot | Gurgaon Central',
            'Know a place in Gurgaon (Gurugram) we missed? Send us a tip.'),
}

img_files = {}  # filename -> bytes


def save_img(uri):
    m = re.match(r'data:image/([a-z+]+);base64,(.*)$', uri, re.S)
    ext = {'jpeg': 'jpg', 'svg+xml': 'svg'}.get(m.group(1), m.group(1))
    import base64
    raw = base64.b64decode(m.group(2))
    name = hashlib.sha1(raw).hexdigest()[:12] + '.' + ext
    img_files[name] = raw
    return name


DATA_RE = r'data:image/(?:webp|png|jpeg|gif);base64,[A-Za-z0-9+/=]{100,}'


def main():
    src = open(SRC, encoding='utf8').read()

    # ---- split the source -------------------------------------------------
    head_end = src.index('</head>')
    head = src[:head_end]
    body = src[head_end + len('</head>'):]

    styles = [m for m in re.finditer(r'<style>(.*?)</style>', src, re.S)]
    big_css = max(styles, key=lambda m: len(m.group(1)))
    css = big_css.group(1)
    scripts = [m for m in re.finditer(r'<script>(.*?)</script>', src, re.S)]
    big_js = max(scripts, key=lambda m: len(m.group(1)))
    js = big_js.group(1)

    # ---- external JS / CSS -------------------------------------------------
    js_out = re.sub("'(" + DATA_RE + ")'", lambda m: "(ROOT+'assets/img/%s')" % save_img(m.group(1)), js)
    css_out = re.sub(DATA_RE, lambda m: 'img/' + save_img(m.group(0)), css)
    app_name = 'app.%s.js' % hashlib.sha1(js_out.encode()).hexdigest()[:8]
    css_name = 'style.%s.css' % hashlib.sha1(css_out.encode()).hexdigest()[:8]

    # ---- head template (without the big style) ------------------------------
    head_t = head.replace(big_css.group(0), '') if big_css.group(0) in head else head
    FONTS = ''.join(re.findall(r'<link rel="(?:preconnect|stylesheet)" href="https://fonts[^>]*>', body))
    # small inline styles stay; the big stylesheet moves out of the body
    body_t = body.replace(big_css.group(0), '').replace(big_js.group(0), '')

    # ---- prerender every route ------------------------------------------------
    pages = {}
    tabitems = {}
    shops = []
    route_ids = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={'width': 1280, 'height': 900})
        pg.goto('file://' + SRC)
        pg.wait_for_timeout(600)
        gc = pg.evaluate('()=>({routes:window.__GC.ROUTES.map(r=>({id:r.id,label:r.label,tag:r.tag||"",blurb:r.blurb||""})),shops:window.__GC.SHOPS.map(s=>({name:s.name,img:s.img||"",imgAlt:s.imgAlt||"",tag:s.tag,area:s.area,hours:s.hours||"",text:s.text,stores:s.stores||[],addr:s.addr||"",q:s.q,links:s.links||[]}))})')
        route_ids = [r['id'] for r in gc['routes']]
        shops = gc['shops']
        for rid in route_ids:
            pg.goto('file://%s#%s' % (SRC, rid))
            pg.reload()
            pg.wait_for_timeout(500)
            pages[rid] = pg.evaluate('''()=>{
              const c=document.body.cloneNode(true);
              c.querySelectorAll('script,style,.pop-bg,link').forEach(e=>e.remove());
              c.querySelectorAll('.status').forEach(e=>e.remove());
              return c.innerHTML}''')
            tabitems[rid] = pg.evaluate('''(rid)=>(window.__GC.getTAB()[rid]||[]).map(o=>({title:o.title,tag:o.tag||"",meta:o.meta||"",text:o.text||"",stores:o.stores||[],addr:o.addr||"",href:o.href||"",cta:o.cta||"",links:o.links||[],img:o.img||"",imgAlt:o.imgAlt||"",slug:o.pop.s}))''', rid)
        br.close()
    def slug(n):
        import unicodedata
        n = ''.join(c for c in unicodedata.normalize('NFD', n) if not unicodedata.combining(c)).lower().replace('&', ' and ')
        return re.sub(r'^-+|-+$', '', re.sub(r'[^a-z0-9]+', '-', n))

    def esc(t):
        return html.escape(t, quote=True)

    def localise(htm, depth):
        root = '../' * depth
        htm = re.sub(DATA_RE, lambda m: root + 'assets/img/' + save_img(m.group(0)), htm)

        def hl(m):
            h = m.group(1)
            if h == 'home':
                return 'href="%s"' % (root or './')
            if h == 'map-section':
                return 'href="%s#map-section"' % (root or './')
            if h in route_ids:
                return 'href="%s%s/"' % (root, h)
            return m.group(0)
        return re.sub(r'href="#([a-z-]+)"', hl, htm)

    # shopping places use the same item shape as the other tabs
    tabitems['shopping'] = [{
        'title': x['name'], 'tag': x['tag'], 'meta': x['area'] + (' \u00b7 ' + x['hours'] if x['hours'] else ''),
        'text': x['text'], 'stores': x['stores'], 'addr': x['addr'], 'href': '', 'cta': '',
        'links': [['Open in Maps \u2192', 'https://www.google.com/maps/search/?api=1&query=' + x['q'].replace(' ', '+')]] + x['links'],
        'img': x['img'], 'imgAlt': x['imgAlt'], 'slug': None} for x in shops]

    labels = {r['id']: r['label'] for r in gc['routes']}
    blurbs = {r['id']: (r['blurb'] or r['tag']) for r in gc['routes']}

    def place_main(tab, it, items):
        stores = ''.join('<li>%s</li>' % esc(x) for x in it['stores'])
        others = ''.join('<li><a href="../%s/">%s</a></li>' % (o['slug'], esc(o['title'])) for o in items if o is not it)
        img = ('<img class="photo" src="%s" alt="%s" width="800" height="520">' % (it['img'], esc(it['imgAlt'] or it['title']))) if it['img'] else ''
        links = ''
        if it['href']:
            links += '<a class="more" href="%s" target="_blank" rel="noopener">%s</a>' % (esc(it['href']), esc(it['cta'] or 'Open in Maps \u2192'))
        links += ''.join('<a class="more" href="%s" target="_blank" rel="noopener">%s</a>' % (esc(l[1]), esc(l[0])) for l in it['links'] if not l[1].startswith('#'))
        rel = ''.join('<li><a href="../../%s/"><strong>%s \u2192</strong><span>%s</span></a></li>' % (k, esc(labels[k]), esc(blurbs[k])) for k in [tab] + RELATED[tab][:3])
        return ('<section class="phero" style="--pg-bg:var(--teal);--pg-fg:var(--ink)"><div class="wrap"><span class="sticker">%s</span><h1>%s</h1>'
                '<p class="tagline">%s</p></div></section><div class="wrap section"><div class="cards"><article class="card"><div class="pic">%s</div><div class="body">'
                '<p class="meta">%s</p><p>%s</p>%s%s<div class="lnks">%s</div></div></article></div>'
                '<section class="related"><h2 class="sub">More in %s</h2><ul class="mini">%s</ul></section>'
                '<section class="related"><h2 class="sub">Keep exploring</h2><ul>%s</ul></section></div>'
                ) % (esc(it['tag']), esc(it['title']), esc(it['meta']), img, esc(it['meta']), esc(it['text']),
                     ('<ul class="mini">%s</ul>' % stores) if stores else '',
                     ('<p class="addr">%s</p>' % esc(it['addr'])) if it['addr'] else '',
                     links, esc(labels[tab]), others, rel)

    def make_head(depth, title, desc, home):
        root = '../' * depth
        h = head_t
        h = re.sub(r'<title>.*?</title>', '<title>%s</title>' % esc(title), h, flags=re.S)
        if desc:
            h = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + esc(desc) + m.group(2), h)
            for k in ('og:title', 'twitter:title'):
                h = re.sub(r'(<meta (?:property|name)="%s" content=")[^"]*(")' % k, lambda m: m.group(1) + esc(title) + m.group(2), h)
            for k in ('og:description', 'twitter:description'):
                h = re.sub(r'(<meta (?:property|name)="%s" content=")[^"]*(")' % k, lambda m: m.group(1) + esc(desc) + m.group(2), h)
        if not home:
            h = re.sub(r'<meta name="keywords"[^>]*>', '', h)
            h = re.sub(r'<script type="application/ld\+json">.*?</script>', '', h, flags=re.S)
        h = h.replace('href="logo.png"', 'href="%slogo.png"' % root)
        return h

    def write(path, text):
        full = os.path.join(ROOT, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, 'w', encoding='utf8').write(text)

    # clean old generated output
    for d in route_ids + ['assets']:
        if d != 'home':
            shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    os.makedirs(os.path.join(ROOT, 'assets', 'img'), exist_ok=True)
    write('assets/' + app_name, js_out)
    write('assets/' + css_name, css_out)

    urls = []

    def page_html(depth, title, desc, home, route, place, bodyhtml):
        root = '../' * depth
        h = make_head(depth, title, desc, home)
        h += FONTS
        h += '<link rel="stylesheet" href="%sassets/%s">' % (root, css_name)
        h += '<script>var __MPA=true,__ROOT=%s,__ROUTE=%s,__PLACE=%s;</script>' % (json.dumps(root), json.dumps(route), json.dumps(place))
        h += '</head>'
        return h + bodyhtml + '<script src="%sassets/%s" defer></script>\n</body></html>\n' % (root, app_name)

    for rid in route_ids:
        depth = 0 if rid == 'home' else 1
        title, desc = TITLES.get(rid, (rid.title() + ' | Gurgaon Central', None))
        bodyhtml = localise('<body>' + pages[rid] + '</body>', depth)
        write('index.html' if rid == 'home' else rid + '/index.html', page_html(depth, title, desc, rid == 'home', rid, '', bodyhtml))
        urls.append('' if rid == 'home' else rid + '/')

    # one real page per item of every tab that has pop-up cards
    for tab, items in tabitems.items():
        if not items:
            continue
        for it in items:
            if not it['slug']:
                it['slug'] = slug(it['title'])
        for it in items:
            sl = it['slug']
            main = place_main(tab, it, items)
            shell = re.sub(r'<main id="app">.*?</main>', lambda m: '<main id="app">' + main + '</main>', '<body>' + pages[tab] + '</body>', flags=re.S)
            shell = localise(shell, 2)
            title = '%s, Gurgaon | %s | Gurgaon Central' % (it['title'], labels[tab])
            desc = (it['text'][:150].rstrip() + ('…' if len(it['text']) > 150 else ''))
            out = page_html(2, title, desc, False, tab, sl, shell)
            write('%s/%s/index.html' % (tab, sl), out)
            urls.append('%s/%s/' % (tab, sl))

    # images
    for n, raw in img_files.items():
        open(os.path.join(ROOT, 'assets', 'img', n), 'wb').write(raw)

    # sitemap + robots only when the live URL is known
    if SITE_URL:
        sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + \
             ''.join('  <url><loc>%s%s</loc></url>\n' % (SITE_URL, u) for u in urls) + '</urlset>\n'
        write('sitemap.xml', sm)
        write('robots.txt', 'User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n' % SITE_URL)

    print('built %d pages, %d images, app=%s css=%s' % (len(urls), len(img_files), app_name, css_name))


if __name__ == '__main__':
    main()
