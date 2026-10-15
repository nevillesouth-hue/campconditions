#!/usr/bin/env python3
"""Build CampConditions.au (Victoria MVP). Python 3 stdlib only.
Sources (all fetched live; failures are recorded, never fatal):
  - DataVic Recreation Sites (DEECA, CC BY 4.0) via opendata.maps.vic.gov.au WFS — campgrounds + closure status
  - Parks Victoria / DEECA MapShare PublicAccess closures (road/seasonal/public land)
  - BOM: linked only, never republished (RSS is personal/non-commercial use only)
VicEmergency warnings are not fetched or republished. Camp pages link to emergency.vic.gov.au.
"""
import json, math, os, re, html, shutil, sys, urllib.request, gzip, datetime as dt
SITE = "https://campconditions.au"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist")
TZ = dt.timezone(dt.timedelta(hours=11))  # AEDT; good enough for display stamp
NOW = dt.datetime.now(TZ)
STAMP = NOW.strftime("%-d %B %Y, %-I:%M %p AEDT")
SRC = {}

def fetch(name, url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CampConditions.au/0.1 (+https://campconditions.au)", "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
        d = json.loads(b); SRC[name] = {"ok": True, "url": url, "fetched": NOW.isoformat()}; return d
    except Exception as e:
        SRC[name] = {"ok": False, "url": url, "error": str(e)[:200]}; print("WARN", name, e, file=sys.stderr); return None

WFS = "https://opendata.maps.vic.gov.au/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=open-data-platform:recweb_site&outputFormat=application/json&CQL_FILTER=camping='Y'"
MS = "https://corp-gis.mapshare.vic.gov.au/arcgis/rest/services/Mapshare/PublicAccess/MapServer/{}/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"

rec = fetch("datavic_recreation_sites", WFS)
closures = []
for lid, lab in [(1, "Road crossing closure"), (2, "Public land road closure"), (4, "Seasonal road closure"), (6, "Public land closure")]:
    d = fetch(f"parksvic_mapshare_layer_{lid}", MS.format(lid))
    for f in (d or {}).get("features", []):
        closures.append((lab, f))

def coords(g):
    if not g: return
    if g["type"] == "GeometryCollection":
        for x in g["geometries"]: yield from coords(x)
        return
    def walk(c):
        if isinstance(c[0], (int, float)): yield c
        else:
            for x in c: yield from walk(x)
    yield from walk(g["coordinates"])

def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 6371*2*math.asin(math.sqrt(h))

def near(pt, g, r):
    return any(km(pt, c) <= r for i, c in enumerate(coords(g)) if i % 3 == 0)

REGIONS = {
 "high-country": ("High Country", "Alpine and north-east Victoria — Mansfield, Bright, Dargo, Mitta Valley and the Ovens."),
 "gippsland": ("Gippsland", "East and West Gippsland — Erica, Heyfield, Briagolong, Orbost and the Snowy."),
 "yarra-ranges-central": ("Yarra Ranges & Central Highlands", "Marysville, Toolangi, Powelltown, Noojee and the forests east of Melbourne."),
 "goldfields-central": ("Goldfields & Central Victoria", "Bendigo, Ballarat, Daylesford, Castlemaine, Avoca and Inglewood."),
 "grampians-south-west": ("Grampians & South West", "Grampians (Gariwerd), Cavendish, Heywood, Casterton and the Wimmera."),
 "otways-surf-coast": ("Otways & Surf Coast", "Great Otway forests, Anglesea and Gellibrand."),
 "murray-mallee": ("Murray & Mallee", "Mildura, Cohuna, the Murray River and Mallee parks."),
}
def region(lon, lat):
    if lat > -35.9: return "murray-mallee"
    if lat < -38.2 and lon < 145: return "otways-surf-coast"
    if lon < 143.6: return "grampians-south-west"
    if lon < 145.3: return "goldfields-central"
    if lon >= 146.0 and lat > -37.45: return "high-country"
    if lon >= 145.9: return "gippsland"
    return "yarra-ranges-central"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
e = lambda s: html.escape(str(s or ""), quote=True)
def clean(s): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()

def msdate(v):
    try: return dt.datetime.fromtimestamp(v/1000, TZ).strftime("%-d %b %Y")
    except Exception: return ""
def closure_info(lab, p):
    name = (p.get("cross_name") or p.get("ezi_road_name_label") or p.get("name") or "").strip()
    if name.lower() == "unnamed": name = "Unnamed track"
    reason = clean(" ".join(str(x) for x in (p.get("status"), p.get("comments")) if x))
    reopen = msdate(p.get("seasonal_open_date") or p.get("reopen_date"))
    return {"type": lab, "name": name, "reason": reason, "reopens": reopen}
camps, seen = [], set()
for f in (rec or {}).get("features", []):
    q = f["properties"]; g = f.get("geometry")
    if q.get("published") != "Y" or not g: continue
    lon, lat = g["coordinates"][:2]
    s = slug(q["name"]); 
    if s in seen: s = f"{s}-{q['serial_no']}"
    seen.add(s)
    closed = (q.get("clos_stat") or "").upper()
    nearby_c = [closure_info(lab, c["properties"]) for lab, c in closures if c.get("geometry") and near((lon, lat), c["geometry"], 5)]
    status = "closed" if "CLOSURE" in closed else ("check" if nearby_c else "open")
    camps.append({"slug": s, "id": q["serial_no"], "name": q["name"].strip(), "lat": round(lat, 6), "lon": round(lon, 6), "region": region(lon, lat),
        "status": status, "closure": {"status": q.get("clos_stat"), "desc": clean(q.get("clos_desc")), "reason": clean(q.get("clos_reas")), "start": q.get("clos_start"), "reopen": q.get("clos_open"), "outdated": bool(q.get("clos_open")) and q["clos_open"][:10] < NOW.date().isoformat()} if closed else None,
        "access": clean(q.get("access_dsc")), "about": clean(q.get("comments")), "camping": clean(q.get("camping_c")), "caravans": clean(q.get("campervan_c")),
        "site_class": q.get("site_class"), "dis_access": q.get("dis_access"), "managed_by": q.get("maintained_by"), "data_date": q.get("vers_date"),
        "nearby_closures": nearby_c[:10]})
camps.sort(key=lambda c: c["name"].lower())

# ---------- rendering ----------
CSS = """:root{--g:#2f5d3a;--o:#c2571a;--bg:#fbfaf6}*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:var(--bg)}
header{background:var(--g);color:#fff;padding:.8rem 1rem}header a{color:#fff;text-decoration:none;font-weight:700;font-size:1.2rem}nav a{color:#e8f0e9;margin-left:1rem;font-size:.95rem;font-weight:400}
main{max-width:980px;margin:0 auto;padding:1rem}h1{font-size:1.7rem;margin:.6rem 0}.muted{color:#666;font-size:.9rem}
.badge{display:inline-block;padding:.1rem .55rem;border-radius:1rem;font-size:.8rem;font-weight:700;color:#fff}.open{background:#2e7d32}.closed{background:#b71c1c}.check{background:#e08a00}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:.8rem}.card{background:#fff;border:1px solid #e3e0d6;border-radius:10px;padding:.8rem}
.card a{color:var(--g);font-weight:600}table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #e3e0d6;padding:.35rem .5rem;text-align:left;font-size:.9rem}
.box{background:#fff;border:2px dashed var(--o);border-radius:10px;padding:1rem;margin:1rem 0}input,textarea,select,button{font:inherit;padding:.45rem;border:1px solid #bbb;border-radius:6px}button{background:var(--o);color:#fff;border:0;cursor:pointer}
.warn{background:#fff4e5;border-left:4px solid var(--o);padding:.6rem .8rem;margin:1rem 0}
.map{height:440px;margin:1rem 0;border:1px solid #e3e0d6;border-radius:10px;background:#e7e4da}
.map-sm{height:240px}.legend{margin:-.2rem 0 1rem;font-size:.9rem}.legend .badge{margin-right:.35rem}
.pin{background:transparent;border:none}.pin span{display:block;width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.35)}
a.btn,a.btn-alert{display:inline-block;background:var(--o);color:#fff;text-decoration:none;font-weight:600;padding:.45rem .8rem;border-radius:6px}
a.btn-alert{background:#9a3412;font-weight:700;padding:.7rem 1rem;font-size:1.05rem}
.leaflet-popup-content a{color:var(--g);font-weight:600}
footer{max-width:980px;margin:2rem auto;padding:1rem;font-size:.8rem;color:#555;border-top:1px solid #ddd}"""

def ld(obj): return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'
SAFETY = '<div class="warn"><strong>Not an official warning service.</strong> This site does not republish VicEmergency warnings. Always check <a href="https://emergency.vic.gov.au/respond/">VicEmergency</a>, the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology warnings for Victoria</a> and <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> before you travel. In an emergency call <a href="tel:000">000</a>. VicEmergency hotline <a href="tel:1800226226">1800 226 226</a>.</div>'
def footer():
    return f"""<footer><p><strong>Data and attribution.</strong> Campground details: <a href="https://discover.data.vic.gov.au/dataset/recreation-sites">Recreation Sites</a>, Department of Energy, Environment and Climate Action (DEECA), via DataVic, licensed under CC BY 4.0. Closures: Parks Victoria / DEECA MapShare. Weather warnings: see the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology</a> (linked, not republished).</p>
<p>Site built {STAMP}. Conditions change quickly; information is provided as is without warranty. © CampConditions.au · <a href="/about/">About</a> · <a href="/status.json">JSON feed</a> · <a href="/llms.txt">llms.txt</a></p></footer>"""
def vicemergency_url(lat, lon):
    # Verified against the respond app: ?bbox= is Leaflet toBBoxString order (west,south,east,north) and fitBounds centres the map on that box.
    pad = 0.2
    west, south, east, north = lon - pad, lat - pad, lon + pad, lat + pad
    return f"https://emergency.vic.gov.au/respond/?bbox={west:.5f},{south:.5f},{east:.5f},{north:.5f}"
def vicemergency_button(c):
    return f'<p><a class="btn-alert" href="{e(vicemergency_url(c["lat"], c["lon"]))}">Check VicEmergency for warnings near this camp</a></p>'
def cdn(kind, href, integrity):
    if kind == "css":
        return f'<link rel="stylesheet" href="{href}" integrity="{integrity}" crossorigin="anonymous">'
    return f'<script src="{href}" defer integrity="{integrity}" crossorigin="anonymous"></script>'
LEAFLET_CSS = cdn("css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css", "sha384-c6Rcwz4e4CITMbu/NBmnNS8yN2sC3cUElMEMfP3vqqKFp7GOYaaBBCqmaWBjmkjb")
LEAFLET_JS = cdn("js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js", "sha384-NElt3Op+9NBMCYaef5HxeJmU4Xeard/Lku8ek6hoPTvYkQPh3zLIrJP7KiRocsxO")
CLUSTER_CSS = (
    cdn("css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.min.css", "sha384-uIZNAcoEHVWMk8LrCSX95DJk6FQzH6zG00LQC9BykRY1UKKpkDzDhbDLYQ1HoRdVx8nYU4LQ5eGzI")
    + cdn("css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.min.css", "sha384-NyCa0nBOjmCqS9HwLKpE7yqy2HVG6PN/cDyAAIdPijDlUH6jCfqX6ydzXFTA/L/l")
)
CLUSTER_JS = cdn("js", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js", "sha384-SIh+qcEBNMda8tT+rx66aCBuWtVYMVzRABqhK4eeQh4pjDHoRdVx8nYU4LQ5eGzI")
def leaflet_head(cluster=False):
    return LEAFLET_CSS + (CLUSTER_CSS if cluster else "")
def leaflet_foot(cluster=False):
    return LEAFLET_JS + (CLUSTER_JS if cluster else "") + '<script src="/map.js" defer></script>'
def map_points(items):
    pts = []
    for c in items:
        cl = c.get("closure") or {}
        pts.append({"name": c["name"], "lat": c["lat"], "lon": c["lon"], "status": c["status"], "url": f"/vic/camp/{c['slug']}/",
                    "note": "Closure record may be outdated" if cl.get("outdated") else ""})
    return json.dumps(pts, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
LEGEND = '<p class="legend"><span class="badge open">No known issues</span> <span class="badge check">Check conditions</span> <span class="badge closed">Closed</span> <span class="muted">A red pin stays red when the closure record may be outdated; the note is on the marker.</span></p>'
def map_block(items, label, small=False):
    cls = "map map-sm" if small else "map"
    legend = "" if small else LEGEND
    return f'<div id="camp-map" class="{cls}" role="region" aria-label="{e(label)}"></div>{legend}<script type="application/json" id="camp-map-data">{map_points(items)}</script>'
def directions(c):
    url = f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lon']}"
    return f'<p><a class="btn" href="{e(url)}">Directions in Google Maps</a></p>'
MAP_JS = r"""(function () {
  var el = document.getElementById("camp-map");
  var raw = document.getElementById("camp-map-data");
  if (!el || !raw || typeof L === "undefined") return;
  var data = JSON.parse(raw.textContent);
  var labels = {open: "No known issues", check: "Check conditions", closed: "Closed"};
  var colours = {open: "#2e7d32", check: "#e08a00", closed: "#b71c1c"};
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
    });
  }
  function icon(status) {
    return L.divIcon({
      className: "pin",
      html: '<span style="background:' + (colours[status] || "#666") + '"></span>',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      popupAnchor: [0, -8]
    });
  }
  function popup(p) {
    var html = "<strong>" + esc(p.name) + "</strong><br>" + esc(labels[p.status] || p.status);
    if (p.note) html += '<br><span class="muted">' + esc(p.note) + "</span>";
    html += '<br><a href="' + esc(p.url) + '">Campground page</a>';
    return html;
  }
  var small = el.classList.contains("map-sm");
  var map = L.map(el, {scrollWheelZoom: false});
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
  }).addTo(map);
  var markers = data.map(function (p) {
    var title = p.name + (p.note ? " — " + p.note : "");
    return L.marker([p.lat, p.lon], {icon: icon(p.status), title: title}).bindPopup(popup(p));
  });
  if (!small && typeof L.markerClusterGroup === "function") {
    var group = L.markerClusterGroup({showCoverageOnHover: false, maxClusterRadius: 42});
    markers.forEach(function (m) { group.addLayer(m); });
    map.addLayer(group);
    if (markers.length) map.fitBounds(group.getBounds().pad(0.08));
    else map.setView([-36.8, 144.5], 6);
  } else {
    markers.forEach(function (m) { m.addTo(map); });
    if (markers.length === 1) map.setView([data[0].lat, data[0].lon], 13);
    else if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.08));
    else map.setView([-36.8, 144.5], 6);
  }
})();
"""
def external_blank(html):
    def repl(m):
        tag = m.group(0)
        if "target=" in tag: return tag
        return tag[:-1] + ' target="_blank" rel="noopener noreferrer">'
    return re.sub(r'<a\b[^>]*\bhref="https?://[^"]*"[^>]*>', repl, html)
def page(path, title, desc, body, extra_ld=(), head="", foot=""):
    canon = SITE + path
    h = f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{canon}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{canon}"><meta property="og:type" content="website"><meta property="og:locale" content="en_AU">
<link rel="alternate" type="application/json" href="/status.json" title="Campground status feed"><style>{CSS}</style>{head}{''.join(ld(x) for x in extra_ld)}</head><body>
<header><a href="/">⛺ CampConditions.au</a><nav><a href="/vic/">Victoria</a><a href="/#newsletter">Free digest</a><a href="/report/">Report conditions</a></nav></header>
<main>{body}</main>{footer()}{foot}</body></html>"""
    h = external_blank(h)
    fp = os.path.join(OUT, path.lstrip("/"), "index.html") if path.endswith("/") else os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "w", encoding="utf-8").write(h)
def badge(s): return f'<span class="badge {s}">{ {"open":"No known issues","closed":"Closed","check":"Check conditions"}[s] }</span>'
def crumbs(items): return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": i+1, "name": n, "item": SITE+u} for i, (n, u) in enumerate(items)]}
NEWS = """<section class="box" id="newsletter"><h2>Get the free weekly Victoria digest</h2><p>Every Thursday: what's closed, which roads are shut, and what campers are reporting — region by region. We'll email a confirmation link first; you're not on the list until you click it.</p>
<form id="digest-form" action="/api/subscribe" method="post"><input type="email" name="email" required placeholder="you@example.com" aria-label="Email address" autocomplete="email"> <button>Subscribe</button><p id="digest-note" class="muted" hidden></p></form>
<script>
document.getElementById("digest-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const note = document.getElementById("digest-note");
  note.hidden = false;
  note.textContent = "One moment…";
  try {
    const res = await fetch("/api/subscribe", { method: "POST", body: new FormData(ev.target), headers: { accept: "text/plain" } });
    const text = (await res.text()).replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim();
    if (res.status === 503) note.textContent = "Sign-ups open soon.";
    else if (res.ok) note.textContent = "Check your email and click the confirmation link. You won't be added until you do.";
    else note.textContent = text.slice(0, 240) || "Something went wrong. Please try again.";
  } catch (err) {
    note.textContent = "Something went wrong. Please try again.";
  }
});
</script>
<p class="muted">Coming soon: a paid daily digest with instant alerts for camps you've saved (about $5 a month).</p></section>"""

shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
open(os.path.join(OUT, "map.js"), "w", encoding="utf-8").write(MAP_JS)
by_reg = {k: [c for c in camps if c["region"] == k] for k in REGIONS}
n_closed = sum(c["status"] == "closed" for c in camps); n_check = sum(c["status"] == "check" for c in camps)

# Home
reg_cards = "".join(f'<div class="card"><a href="/vic/{k}/">{e(n)}</a><p class="muted">{len(by_reg[k])} campgrounds · {sum(c["status"]=="closed" for c in by_reg[k])} closed · {sum(c["status"]=="check" for c in by_reg[k])} to check</p><p>{e(d)}</p></div>' for k, (n, d) in REGIONS.items())
home_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "CampConditions.au", "url": SITE + "/", "inLanguage": "en-AU", "description": "Free camp and campground conditions for Victoria, Australia."},
           {"@context": "https://schema.org", "@type": "Organization", "name": "CampConditions.au", "url": SITE + "/", "sameAs": ["https://www.youtube.com/@OptimumQuestforBigThings"]},
           {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
             {"@type": "Question", "name": "How do I know if a free camp in Victoria is open?", "acceptedAnswer": {"@type": "Answer", "text": "Each campground page shows the closure status from DEECA's Recreation Sites data and nearby Parks Victoria road and seasonal closures. CampConditions.au does not republish VicEmergency warnings. Check VicEmergency, Parks Victoria and the Bureau of Meteorology before you travel. In an emergency call 000. The VicEmergency hotline is 1800 226 226."}},
             {"@type": "Question", "name": "How often is CampConditions.au updated?", "acceptedAnswer": {"@type": "Answer", "text": "The site rebuilds from DEECA and Parks Victoria sources several times a day. Each page shows when it was built. Warning information is not included."}}]}]
page("/", "Victorian free camp conditions — closures and road access | CampConditions.au", f"Is your free camp open tonight? Closure status and nearby road closures for {len(camps)} Victorian campgrounds, updated daily.",
 f"""<h1>Is your Victorian free camp good tonight?</h1><p>Closures, nearby road conditions and camper reports for <strong>{len(camps)}</strong> campgrounds across Victoria, pulled from DEECA and Parks Victoria. Right now <span class="badge closed">{n_closed} closed</span> <span class="badge check">{n_check} to check</span>.</p>
{map_block(camps, "Map of Victorian campgrounds")}{SAFETY}<h2>Regions</h2><div class="grid">{reg_cards}</div>
<p>Weather warnings: <a href="https://www.bom.gov.au/vic/warnings/">check BOM's Victorian warnings</a>. Bushfire, flood and other emergency warnings: check <a href="https://emergency.vic.gov.au/respond/">VicEmergency</a> — they are not republished here.</p>{NEWS}""", home_ld, head=leaflet_head(True), foot=leaflet_foot(True))

page("/vic/", "Victoria campground conditions by region | CampConditions.au", "Browse Victorian campgrounds by region with current closures.",
     f"<h1>Victoria</h1>{map_block(camps, 'Map of Victorian campgrounds')}{SAFETY}<div class='grid'>{reg_cards}</div>", [crumbs([("Home", "/"), ("Victoria", "/vic/")])], head=leaflet_head(True), foot=leaflet_foot(True))

for k, (n, d) in REGIONS.items():
    lst = by_reg[k]
    rows = "".join(f'<tr><td><a href="/vic/camp/{c["slug"]}/">{e(c["name"])}</a></td><td>{badge(c["status"])}</td><td>{e((c["closure"] or {}).get("desc") or (str(len(c["nearby_closures"]))+" road closures nearby" if c["nearby_closures"] else ""))}</td></tr>' for c in sorted(lst, key=lambda c: ({"closed":0,"check":1,"open":2}[c["status"]], c["name"])))
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"Campgrounds in {n}, Victoria", "numberOfItems": len(lst), "itemListElement": [{"@type": "ListItem", "position": i+1, "url": f"{SITE}/vic/camp/{c['slug']}/", "name": c["name"]} for i, c in enumerate(lst)]}
    page(f"/vic/{k}/", f"{n} free camps and campgrounds — conditions today | CampConditions.au", f"{len(lst)} campgrounds in {n}, Victoria: closures and nearby road closures. {d}",
         f"<h1>{e(n)} campgrounds</h1><p>{e(d)}</p>{map_block(lst, f'Map of {n} campgrounds')}{SAFETY}<table><tr><th>Campground</th><th>Status</th><th>Notes</th></tr>{rows or '<tr><td colspan=3>No campgrounds listed.</td></tr>'}</table>{NEWS}",
         [crumbs([("Home", "/"), ("Victoria", "/vic/"), (n, f"/vic/{k}/")]), il], head=leaflet_head(True), foot=leaflet_foot(True))

for c in camps:
    rn = REGIONS[c["region"]][0]
    cl = c["closure"]; parts = []
    if cl:
        parts.append(f'<div class="warn"><strong>Closed:</strong> {e(cl["desc"] or cl["reason"] or "Full closure")} {("· Reopens "+e(cl["reopen"][:10])) if cl.get("reopen") else ""}</div>')
        if cl.get("outdated"): parts.append(f'<div class="warn"><strong>This closure record may be outdated.</strong> The listed reopening date ({e(cl["reopen"][:10])}) has passed. Check <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> or call 13 1963 before you go.</div>')
    if c["nearby_closures"]: parts.append("<h2>Road and track closures within 5 km</h2><ul>" + "".join(f'<li>{e(x["type"])}{": "+e(x["name"]) if x["name"] else ""}{" — "+e(x["reason"]) if x["reason"] else ""}{" · reopens "+e(x["reopens"]) if x.get("reopens") else ""}</li>' for x in c["nearby_closures"]) + "</ul>")
    info = "".join(f"<h2>{h}</h2><p>{e(t)}</p>" for h, t in [("About", c["about"]), ("Camping", c["camping"]), ("Caravans and campervans", c["caravans"]), ("Getting there", c["access"])] if t)
    desc = f"Is {c['name']} campground open? Current closure status and nearby road closures for {c['name']} in {rn}, Victoria."
    camp_ld = {"@context": "https://schema.org", "@type": "Campground", "name": c["name"], "url": f"{SITE}/vic/camp/{c['slug']}/", "description": (c["about"] or desc)[:300],
               "geo": {"@type": "GeoCoordinates", "latitude": c["lat"], "longitude": c["lon"]}, "address": {"@type": "PostalAddress", "addressRegion": "VIC", "addressCountry": "AU"},
               "containedInPlace": {"@type": "AdministrativeArea", "name": f"{rn}, Victoria"}, "publicAccess": c["status"] != "closed", "identifier": c["id"]}
    lds = [camp_ld, crumbs([("Home", "/"), ("Victoria", "/vic/"), (rn, f"/vic/{c['region']}/"), (c["name"], f"/vic/camp/{c['slug']}/")])]
    if cl:
        lds.append({"@context": "https://schema.org", "@type": "SpecialAnnouncement", "name": f"Closure: {c['name']}", "text": cl.get("desc") or cl.get("reason") or "This campground is recorded as closed.", "datePosted": NOW.isoformat(), "spatialCoverage": {"@type": "Place", "name": c["name"]}, "url": f"{SITE}/vic/camp/{c['slug']}/"})
    page(f"/vic/camp/{c['slug']}/", f"{c['name']} campground — is it open? Conditions today | CampConditions.au", desc,
     f"""<p class="muted"><a href="/vic/">Victoria</a> › <a href="/vic/{c['region']}/">{e(rn)}</a></p><h1>{e(c['name'])}</h1><p>{badge(c['status'])} <span class="muted">Checked {STAMP}</span></p>
{vicemergency_button(c)}
{map_block([c], f"Map of {c['name']}", small=True)}{directions(c)}
{''.join(parts) or '<p>No closure is recorded for this campground, and no road or track closures were found within 5 km.</p>'}{SAFETY}{info}
<p class="muted">Location: {c['lat']}, {c['lon']} · <a href="https://www.google.com/maps?q={c['lat']},{c['lon']}">Open in maps</a> · <a href="https://www.bom.gov.au/vic/forecasts/">BOM forecast</a> · Campground data dated {e((c['data_date'] or '')[:10])}</p>
<div class="box"><h2>Been here recently?</h2><p><a href="/report/?camp={c['slug']}">Report conditions at {e(c['name'])}</a> — how full, road access, water, phone coverage.</p></div>{NEWS}""", lds, head=leaflet_head(False), foot=leaflet_foot(False))

page("/report/", "Report campground conditions | CampConditions.au", "Tell other campers what it's really like: how full, access, water, coverage.",
 """<h1>Report conditions</h1><p>Your report helps the next camper. Reports are checked before they're published.</p>
<form class="box" onsubmit="event.preventDefault();document.getElementById('ok').hidden=false"><p><label>Campground<br><input name="camp" id="camp" required size="40"></label></p>
<p><label>Date visited<br><input type="date" name="date" required></label></p><p><label>How full?<br><select name="full"><option>Plenty of room</option><option>About half</option><option>Nearly full</option><option>Full</option></select></label></p>
<p><label>Road access<br><select name="access"><option>2WD fine</option><option>4WD only</option><option>Closed/impassable</option></select></label></p>
<p><label>Anything else? (water, toilets, phone coverage, hazards)<br><textarea name="notes" rows="4" cols="50"></textarea></label></p><button>Send report</button>
<p id="ok" hidden class="muted">Thanks! Reports open at launch — this form is a placeholder and nothing was sent.</p></form>
<script>const p=new URLSearchParams(location.search).get('camp');if(p)document.getElementById('camp').value=p.replace(/-/g,' ');</script>""")
page("/about/", "About CampConditions.au", "Who we are and where our data comes from.",
 f"""<h1>About</h1><p>CampConditions.au is a free digest of Victorian campground conditions, built for motorhomers, caravanners and campers by the team behind the YouTube channel <a href="https://www.youtube.com/@OptimumQuestforBigThings">Optimum Quest for Big Things</a>.</p>{SAFETY}
<h2>Sources</h2><ul><li>DEECA Recreation Sites via DataVic (CC BY 4.0)</li><li>Parks Victoria / DEECA MapShare closures</li><li>Bureau of Meteorology — linked only</li></ul><p>VicEmergency warnings are not republished. Use the check button on each campground page, or call 1800 226 226. We don't copy reviews from other apps. Camper reports come directly from our readers.</p>""")

# Feeds & SEO files
feed = {"name": "CampConditions.au status feed", "region": "Victoria, Australia", "generated": NOW.isoformat(),
        "attribution": ["Recreation Sites, DEECA via DataVic, CC BY 4.0", "Parks Victoria / DEECA MapShare closures"],
        "disclaimer": "Not an official warning service. VicEmergency warnings are not included. Check VicEmergency and the Bureau of Meteorology before travel.", "sources": SRC,
        "camps": [{k: c[k] for k in ("slug", "name", "region", "lat", "lon", "status", "closure", "nearby_closures")} | {"url": f"{SITE}/vic/camp/{c['slug']}/"} for c in camps]}
json.dump(feed, open(os.path.join(OUT, "status.json"), "w"), ensure_ascii=False, indent=1)
urls = ["/", "/vic/", "/report/", "/about/"] + [f"/vic/{k}/" for k in REGIONS] + [f"/vic/camp/{c['slug']}/" for c in camps]
open(os.path.join(OUT, "sitemap.xml"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{SITE}{u}</loc><lastmod>{NOW.date()}</lastmod></url>\n" for u in urls) + "</urlset>\n")
open(os.path.join(OUT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
open(os.path.join(OUT, "llms.txt"), "w").write(f"""# CampConditions.au

> Current conditions for {len(camps)} campgrounds and free camps in Victoria, Australia: DEECA closures and nearby road/track closures. VicEmergency warnings are not republished. Rebuilt several times daily. Not an official warning service.

Machine-readable status for every campground: {SITE}/status.json (includes attribution, sources and last-updated times).

## Regions
""" + "".join(f"- [{n}]({SITE}/vic/{k}/): {d}\n" for k, (n, d) in REGIONS.items()) + f"""
## Key pages
- [Victoria overview]({SITE}/vic/)
- [Report conditions]({SITE}/report/)
- [About and data sources]({SITE}/about/)

## Attribution
Campground data: DEECA Recreation Sites via DataVic (CC BY 4.0). Closures: Parks Victoria / DEECA MapShare. When citing a status, include its time. For warnings, send people to VicEmergency (emergency.vic.gov.au) and BOM (bom.gov.au); do not treat this site as a warning feed.
""")
open(os.path.join(OUT, "404.html"), "w").write("<!doctype html><html lang='en-AU'><meta charset='utf-8'><title>Not found</title><p>Page not found. <a href='/'>Back to CampConditions.au</a></p></html>")
json.dump(SRC, open(os.path.join(OUT, "build-report.json"), "w"), indent=1)
print(f"Built {len(urls)} pages, {len(camps)} camps ({n_closed} closed, {n_check} check), {len(closures)} closure features")
for k, v in SRC.items(): print(("OK  " if v["ok"] else "FAIL"), k, v.get("error", ""))
