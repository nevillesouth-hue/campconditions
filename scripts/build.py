#!/usr/bin/env python3
"""Build CampConditions.au (Victoria MVP). Python 3 stdlib only.
Sources (all fetched live; failures are recorded, never fatal):
  - DataVic Recreation Sites (DEECA, CC BY 4.0) via opendata.maps.vic.gov.au WFS — campgrounds + closure status
  - Parks Victoria / DEECA MapShare PublicAccess closures (road/seasonal/public land)
  - VicEmergency OSOM GeoJSON (State of Victoria, CC BY 3.0 AU) — warnings/incidents, fire danger ratings
  - BOM: linked only, never republished (RSS is personal/non-commercial use only)
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
OSOM = "https://emergency.vic.gov.au/public/osom-geojson.json"

rec = fetch("datavic_recreation_sites", WFS)
closures = []
for lid, lab in [(1, "Road crossing closure"), (2, "Public land road closure"), (4, "Seasonal road closure"), (6, "Public land closure")]:
    d = fetch(f"parksvic_mapshare_layer_{lid}", MS.format(lid))
    for f in (d or {}).get("features", []):
        closures.append((lab, f))
osom = fetch("vicemergency_osom", OSOM)

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

# Emergency items
emerg, fdr, emv_updated = [], {}, None
if osom:
    p = osom.get("properties", {}); emv_updated = p.get("lastUpdated")
    fdr = p.get("conditions", {}).get("fdr", {}) or {}
    for f in osom["features"]:
        q = f["properties"]
        if q.get("feedType") not in ("warning", "incident"): continue
        emerg.append({"title": f"{q.get('category1','')} – {q.get('category2','')}".strip(" –"), "status": q.get("status") or q.get("sourceTitle"),
                      "location": q.get("location"), "updated": q.get("updated"), "action": q.get("action"),
                      "url": f"https://emergency.vic.gov.au/respond/#!/warning/{q.get('id')}/moreinfo" if q.get("feedType")=="warning" else "https://emergency.vic.gov.au/respond/", "geom": f.get("geometry")})

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
    nearby_e = [{k: v for k, v in x.items() if k != "geom"} for x in emerg if x["geom"] and near((lon, lat), x["geom"], 25)]
    status = "closed" if "CLOSURE" in closed else ("check" if nearby_c or nearby_e else "open")
    camps.append({"slug": s, "id": q["serial_no"], "name": q["name"].strip(), "lat": round(lat, 6), "lon": round(lon, 6), "region": region(lon, lat),
        "status": status, "closure": {"status": q.get("clos_stat"), "desc": clean(q.get("clos_desc")), "reason": clean(q.get("clos_reas")), "start": q.get("clos_start"), "reopen": q.get("clos_open"), "outdated": bool(q.get("clos_open")) and q["clos_open"][:10] < NOW.date().isoformat()} if closed else None,
        "access": clean(q.get("access_dsc")), "about": clean(q.get("comments")), "camping": clean(q.get("camping_c")), "caravans": clean(q.get("campervan_c")),
        "site_class": q.get("site_class"), "dis_access": q.get("dis_access"), "managed_by": q.get("maintained_by"), "data_date": q.get("vers_date"),
        "nearby_closures": nearby_c[:10], "nearby_emergency": nearby_e[:10]})
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
a.btn{display:inline-block;background:var(--o);color:#fff;text-decoration:none;font-weight:600;padding:.45rem .8rem;border-radius:6px}
.leaflet-popup-content a{color:var(--g);font-weight:600}
footer{max-width:980px;margin:2rem auto;padding:1rem;font-size:.8rem;color:#555;border-top:1px solid #ddd}"""

def ld(obj): return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'
SAFETY = '<div class="warn"><strong>Not an official warning service.</strong> Always check <a href="https://emergency.vic.gov.au/">VicEmergency</a>, the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology warnings for Victoria</a> and <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> before you travel. In an emergency call 000.</div>'
def footer():
    return f"""<footer><p><strong>Data and attribution.</strong> Campground details: <a href="https://discover.data.vic.gov.au/dataset/recreation-sites">Recreation Sites</a>, Department of Energy, Environment and Climate Action (DEECA), via DataVic, licensed under CC BY 4.0. Closures: Parks Victoria / DEECA MapShare. Emergency data: source <strong>State of Victoria, Australia</strong> — <a href="https://www.emv.vic.gov.au/responsibilities/victorias-warning-system/emergency-data">licence and disclaimer notice</a> (CC BY 3.0 AU). <strong>Emergency data last received: {e(fmt(emv_updated)) if emv_updated else 'unavailable'}</strong>. Weather warnings: see the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology</a> (linked, not republished).</p>
<p>Site built {STAMP}. Conditions change quickly; information is provided as is without warranty. © CampConditions.au · <a href="/about/">About</a> · <a href="/status.json">JSON feed</a> · <a href="/llms.txt">llms.txt</a></p></footer>"""
def fmt(iso):
    try: return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).strftime("%-d %b %Y, %-I:%M %p AEDT")
    except Exception: return iso
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
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
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
def page(path, title, desc, body, extra_ld=(), head="", foot=""):
    canon = SITE + path
    h = f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{canon}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{canon}"><meta property="og:type" content="website"><meta property="og:locale" content="en_AU">
<link rel="alternate" type="application/json" href="/status.json" title="Campground status feed"><style>{CSS}</style>{head}{''.join(ld(x) for x in extra_ld)}</head><body>
<header><a href="/">⛺ CampConditions.au</a><nav><a href="/vic/">Victoria</a><a href="/#newsletter">Free digest</a><a href="/report/">Report conditions</a></nav></header>
<main>{body}</main>{footer()}{foot}</body></html>"""
    fp = os.path.join(OUT, path.lstrip("/"), "index.html") if path.endswith("/") else os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "w", encoding="utf-8").write(h)
def badge(s): return f'<span class="badge {s}">{ {"open":"No known issues","closed":"Closed","check":"Check conditions"}[s] }</span>'
def crumbs(items): return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": i+1, "name": n, "item": SITE+u} for i, (n, u) in enumerate(items)]}
NEWS = """<section class="box" id="newsletter"><h2>Get the free weekly Victoria digest</h2><p>Every Thursday: what's closed, what's flooded or burning, and what campers are reporting — region by region.</p>
<form onsubmit="event.preventDefault();this.querySelector('p').hidden=false"><input type="email" required placeholder="you@example.com" aria-label="Email address"> <button>Subscribe</button><p hidden class="muted">Thanks! Sign-ups open at launch — this form is a placeholder and nothing was sent.</p></form>
<p class="muted">Coming soon: a paid daily digest with instant alerts for camps you've saved (about $5 a month).</p></section>"""

shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
open(os.path.join(OUT, "map.js"), "w", encoding="utf-8").write(MAP_JS)
by_reg = {k: [c for c in camps if c["region"] == k] for k in REGIONS}
n_closed = sum(c["status"] == "closed" for c in camps); n_check = sum(c["status"] == "check" for c in camps)

# Home
fdr_rows = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in fdr.items())
emerg_html = "".join(f'<li><a href="{e(x["url"])}">{e(x["title"])}</a> — {e(x["location"])} <span class="muted">(updated {e(fmt(x["updated"]))})</span></li>' for x in emerg) or "<li>No current warnings or incidents in the feed.</li>"
reg_cards = "".join(f'<div class="card"><a href="/vic/{k}/">{e(n)}</a><p class="muted">{len(by_reg[k])} campgrounds · {sum(c["status"]=="closed" for c in by_reg[k])} closed · {sum(c["status"]=="check" for c in by_reg[k])} to check</p><p>{e(d)}</p></div>' for k, (n, d) in REGIONS.items())
home_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "CampConditions.au", "url": SITE + "/", "inLanguage": "en-AU", "description": "Free camp and campground conditions for Victoria, Australia."},
           {"@context": "https://schema.org", "@type": "Organization", "name": "CampConditions.au", "url": SITE + "/", "sameAs": ["https://www.youtube.com/@OptimumQuestforBigThings"]},
           {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
             {"@type": "Question", "name": "How do I know if a free camp in Victoria is open?", "acceptedAnswer": {"@type": "Answer", "text": "Each campground page shows the closure status from DEECA's Recreation Sites data, nearby Parks Victoria road and seasonal closures, and VicEmergency warnings within 25 km. Always confirm with Parks Victoria and VicEmergency before you travel."}},
             {"@type": "Question", "name": "How often is CampConditions.au updated?", "acceptedAnswer": {"@type": "Answer", "text": "The site rebuilds from official sources several times a day. Each page shows when emergency data was last received."}}]}]
page("/", "Victorian free camp conditions — closures, fire, flood | CampConditions.au", f"Is your free camp open tonight? Closures, fire and flood warnings for {len(camps)} Victorian campgrounds, updated daily.",
 f"""<h1>Is your Victorian free camp good tonight?</h1><p>Closures, fire and flood warnings and camper reports for <strong>{len(camps)}</strong> campgrounds across Victoria, pulled from official sources. Right now <span class="badge closed">{n_closed} closed</span> <span class="badge check">{n_check} to check</span>.</p>
{map_block(camps, "Map of Victorian campgrounds")}{SAFETY}<h2>Regions</h2><div class="grid">{reg_cards}</div>
<h2>Current VicEmergency warnings and incidents</h2><ul>{emerg_html}</ul><p class="muted">Emergency data last received {e(fmt(emv_updated)) if emv_updated else 'unavailable'}. Source: State of Victoria, Australia.</p>
<h2>Today's fire danger ratings</h2><table><tr><th>District</th><th>Rating</th></tr>{fdr_rows or '<tr><td colspan=2>Unavailable</td></tr>'}</table>
<p>Weather warnings: <a href="https://www.bom.gov.au/vic/warnings/">check BOM's Victorian warnings</a>.</p>{NEWS}""", home_ld, head=leaflet_head(True), foot=leaflet_foot(True))

page("/vic/", "Victoria campground conditions by region | CampConditions.au", "Browse Victorian campgrounds by region with current closures and warnings.",
     f"<h1>Victoria</h1>{map_block(camps, 'Map of Victorian campgrounds')}{SAFETY}<div class='grid'>{reg_cards}</div>", [crumbs([("Home", "/"), ("Victoria", "/vic/")])], head=leaflet_head(True), foot=leaflet_foot(True))

for k, (n, d) in REGIONS.items():
    lst = by_reg[k]
    rows = "".join(f'<tr><td><a href="/vic/camp/{c["slug"]}/">{e(c["name"])}</a></td><td>{badge(c["status"])}</td><td>{e((c["closure"] or {}).get("desc") or (str(len(c["nearby_emergency"]))+" warnings nearby" if c["nearby_emergency"] else "") or (str(len(c["nearby_closures"]))+" road closures nearby" if c["nearby_closures"] else ""))}</td></tr>' for c in sorted(lst, key=lambda c: ({"closed":0,"check":1,"open":2}[c["status"]], c["name"])))
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"Campgrounds in {n}, Victoria", "numberOfItems": len(lst), "itemListElement": [{"@type": "ListItem", "position": i+1, "url": f"{SITE}/vic/camp/{c['slug']}/", "name": c["name"]} for i, c in enumerate(lst)]}
    page(f"/vic/{k}/", f"{n} free camps and campgrounds — conditions today | CampConditions.au", f"{len(lst)} campgrounds in {n}, Victoria: closures, fire and flood warnings. {d}",
         f"<h1>{e(n)} campgrounds</h1><p>{e(d)}</p>{map_block(lst, f'Map of {n} campgrounds')}{SAFETY}<table><tr><th>Campground</th><th>Status</th><th>Notes</th></tr>{rows or '<tr><td colspan=3>No campgrounds listed.</td></tr>'}</table>{NEWS}",
         [crumbs([("Home", "/"), ("Victoria", "/vic/"), (n, f"/vic/{k}/")]), il], head=leaflet_head(True), foot=leaflet_foot(True))

for c in camps:
    rn = REGIONS[c["region"]][0]
    cl = c["closure"]; parts = []
    if cl:
        parts.append(f'<div class="warn"><strong>Closed:</strong> {e(cl["desc"] or cl["reason"] or "Full closure")} {("· Reopens "+e(cl["reopen"][:10])) if cl.get("reopen") else ""}</div>')
        if cl.get("outdated"): parts.append(f'<div class="warn"><strong>This closure record may be outdated.</strong> The listed reopening date ({e(cl["reopen"][:10])}) has passed. Check <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> or call 13 1963 before you go.</div>')
    if c["nearby_emergency"]: parts.append("<h2>VicEmergency within 25 km</h2><ul>" + "".join(f'<li><a href="{e(x["url"])}">{e(x["title"])}</a> ({e(x["status"])}) — {e(x["location"])} <span class="muted">updated {e(fmt(x["updated"]))}</span></li>' for x in c["nearby_emergency"]) + "</ul>")
    if c["nearby_closures"]: parts.append("<h2>Road and track closures within 5 km</h2><ul>" + "".join(f'<li>{e(x["type"])}{": "+e(x["name"]) if x["name"] else ""}{" — "+e(x["reason"]) if x["reason"] else ""}{" · reopens "+e(x["reopens"]) if x.get("reopens") else ""}</li>' for x in c["nearby_closures"]) + "</ul>")
    info = "".join(f"<h2>{h}</h2><p>{e(t)}</p>" for h, t in [("About", c["about"]), ("Camping", c["camping"]), ("Caravans and campervans", c["caravans"]), ("Getting there", c["access"])] if t)
    desc = f"Is {c['name']} campground open? Current status, closures and fire/flood warnings for {c['name']} in {rn}, Victoria."
    camp_ld = {"@context": "https://schema.org", "@type": "Campground", "name": c["name"], "url": f"{SITE}/vic/camp/{c['slug']}/", "description": (c["about"] or desc)[:300],
               "geo": {"@type": "GeoCoordinates", "latitude": c["lat"], "longitude": c["lon"]}, "address": {"@type": "PostalAddress", "addressRegion": "VIC", "addressCountry": "AU"},
               "containedInPlace": {"@type": "AdministrativeArea", "name": f"{rn}, Victoria"}, "publicAccess": c["status"] != "closed", "identifier": c["id"]}
    lds = [camp_ld, crumbs([("Home", "/"), ("Victoria", "/vic/"), (rn, f"/vic/{c['region']}/"), (c["name"], f"/vic/camp/{c['slug']}/")])]
    if cl or c["nearby_emergency"]:
        lds.append({"@context": "https://schema.org", "@type": "SpecialAnnouncement", "name": f"Conditions alert: {c['name']}", "text": (cl or {}).get("desc") or "Emergency warning or incident nearby — check VicEmergency.", "datePosted": NOW.isoformat(), "spatialCoverage": {"@type": "Place", "name": c["name"]}, "url": f"{SITE}/vic/camp/{c['slug']}/"})
    page(f"/vic/camp/{c['slug']}/", f"{c['name']} campground — is it open? Conditions today | CampConditions.au", desc,
     f"""<p class="muted"><a href="/vic/">Victoria</a> › <a href="/vic/{c['region']}/">{e(rn)}</a></p><h1>{e(c['name'])}</h1><p>{badge(c['status'])} <span class="muted">Checked {STAMP}</span></p>
{map_block([c], f"Map of {c['name']}", small=True)}{directions(c)}
{''.join(parts) or '<p>No closures or emergency warnings found nearby in official data.</p>'}{SAFETY}{info}
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
<h2>Sources</h2><ul><li>DEECA Recreation Sites via DataVic (CC BY 4.0)</li><li>Parks Victoria / DEECA MapShare closures</li><li>VicEmergency — State of Victoria, Australia (CC BY 3.0 AU, <a href="https://www.emv.vic.gov.au/responsibilities/victorias-warning-system/emergency-data">notice</a>)</li><li>Bureau of Meteorology — linked only</li></ul><p>We don't copy reviews from other apps. Camper reports come directly from our readers.</p>""")

# Feeds & SEO files
feed = {"name": "CampConditions.au status feed", "region": "Victoria, Australia", "generated": NOW.isoformat(), "emergency_data_last_received": emv_updated,
        "attribution": ["Recreation Sites, DEECA via DataVic, CC BY 4.0", "Parks Victoria / DEECA MapShare closures", "Emergency data: State of Victoria, Australia, CC BY 3.0 AU — https://www.emv.vic.gov.au/responsibilities/victorias-warning-system/emergency-data"],
        "disclaimer": "Not an official warning service. Check VicEmergency and BOM before travel.", "sources": SRC, "fire_danger_ratings": fdr,
        "camps": [{k: c[k] for k in ("slug", "name", "region", "lat", "lon", "status", "closure", "nearby_closures", "nearby_emergency")} | {"url": f"{SITE}/vic/camp/{c['slug']}/"} for c in camps]}
json.dump(feed, open(os.path.join(OUT, "status.json"), "w"), ensure_ascii=False, indent=1)
urls = ["/", "/vic/", "/report/", "/about/"] + [f"/vic/{k}/" for k in REGIONS] + [f"/vic/camp/{c['slug']}/" for c in camps]
open(os.path.join(OUT, "sitemap.xml"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{SITE}{u}</loc><lastmod>{NOW.date()}</lastmod></url>\n" for u in urls) + "</urlset>\n")
open(os.path.join(OUT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
open(os.path.join(OUT, "llms.txt"), "w").write(f"""# CampConditions.au

> Current conditions for {len(camps)} campgrounds and free camps in Victoria, Australia: closures, nearby road/track closures, VicEmergency fire/flood warnings and camper reports. Rebuilt several times daily from official sources. Not an official warning service.

Machine-readable status for every campground: {SITE}/status.json (includes attribution, sources and last-updated times).

## Regions
""" + "".join(f"- [{n}]({SITE}/vic/{k}/): {d}\n" for k, (n, d) in REGIONS.items()) + f"""
## Key pages
- [Victoria overview]({SITE}/vic/)
- [Report conditions]({SITE}/report/)
- [About and data sources]({SITE}/about/)

## Attribution
Campground data: DEECA Recreation Sites via DataVic (CC BY 4.0). Emergency data: State of Victoria, Australia (CC BY 3.0 AU). When citing a status, include its time and advise checking VicEmergency (emergency.vic.gov.au) and BOM (bom.gov.au).
""")
open(os.path.join(OUT, "404.html"), "w").write("<!doctype html><html lang='en-AU'><meta charset='utf-8'><title>Not found</title><p>Page not found. <a href='/'>Back to CampConditions.au</a></p></html>")
json.dump(SRC, open(os.path.join(OUT, "build-report.json"), "w"), indent=1)
print(f"Built {len(urls)} pages, {len(camps)} camps ({n_closed} closed, {n_check} check), {len(emerg)} emergency items, {len(closures)} closure features")
for k, v in SRC.items(): print(("OK  " if v["ok"] else "FAIL"), k, v.get("error", ""))
