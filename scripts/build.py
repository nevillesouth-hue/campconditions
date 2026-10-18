#!/usr/bin/env python3
"""Build CampConditions.au (Victoria). Python 3 stdlib only.
Sources:
  - DataVic Recreation Sites (DEECA, CC BY 4.0) via opendata.maps.vic.gov.au WFS — campgrounds + closure status
  - Parks Victoria / DEECA MapShare PublicAccess closures (road/seasonal/public land). Applied to DataVic sites only.
  - OpenStreetMap campgrounds and towns committed in data/ (ODbL). No Parks Victoria closure data.
  - BOM: linked only, never republished (RSS is personal/non-commercial use only)
VicEmergency warnings are not fetched or republished. Camp pages link to emergency.vic.gov.au.
"""
import json, math, os, re, html, shutil, sys, urllib.request, gzip, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts
SITE = "https://campconditions.au"
CREDIT = "Campground and town data © OpenStreetMap contributors (ODbL); Campground details from DataVic and Explore Outdoors © State of Victoria (DEECA), CC BY 4.0, and Parks Victoria."
PV_LABEL = "Paid – Parks Victoria (book ahead)"
OSM_CATEGORIES = ["Free", "Camping area", "Donation", "Showground", "Council park", "Council park (leased)", "Rest area", "Pub stay", PV_LABEL]
CAT_LABEL = {"free": "Free", "donation": "Donation", "showground": "Showground", "council_park": "Council park", "council_park_leased": "Council park (leased)", "rest_area": "Rest area", "pub_stay": "Pub stay", "park_campground": PV_LABEL}
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
# A leading "12 " is an index, not part of the name, unless the next word is a
# unit or place descriptor (6 Mile Flat, 82 Bend, 14 Creek).
_KEEP_UNIT = {"mile", "miles", "bend", "bends", "km", "kms", "kilometre", "kilometres", "kilometer", "kilometers", "creek", "creeks"}
def strip_index_name(name):
    match = re.match(r"^(\d+)\s+([A-Za-z]+)", name or "")
    if not match or match.group(2).lower() in _KEEP_UNIT: return name
    return name[match.start(2):]
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
        "nearby_closures": nearby_c[:10], "source": "datavic", "category": "Park campground",
        "needs_review": False})

_FACT_PROTECTED = ("status", "closure", "nearby_closures", "id", "slug", "lat", "lon", "source", "region", "name")
def _http(value):
    text = str(value or "").strip()
    if text and not text.startswith(("http://", "https://")): text = "https://" + text
    return text
def apply_row_facts(camp, row):
    """Copy display facts onto a camp. Status, closures and identity stay as they were."""
    protected = {key: camp.get(key) for key in _FACT_PROTECTED}
    if str(row.get("suits") or "").strip():
        camp["fac_tents"], camp["fac_caravans"], camp["fac_motorhomes"] = facts.suit_flags(row.get("suits"))
    if row.get("dogs") not in (None, ""):
        dogs_text, dogs_flag = facts.dogs_fields(row.get("dogs"))
        camp["dogs_text"] = dogs_text
        camp["fac_dogs"] = dogs_flag if dogs_flag is not None else facts.yn_flag(row.get("dogs"))
    for src, dest in (("dump_point", "fac_dump"), ("dump", "fac_dump"), ("showers", "fac_showers"), ("self_contained_only", "fac_self"), ("self_contained", "fac_self")):
        if row.get(src) not in (None, ""): camp[dest] = facts.yn_flag(row.get(src))
    toilets = facts.toilet_label(row.get("toilets"))
    if toilets:
        camp["toilets_text"] = toilets
        camp["fac_toilets"] = facts.yn_flag(row.get("toilets"))
    drink_raw = row.get("drinking_water")
    if drink_raw in (None, ""): drink_raw = row.get("potable_water")
    drink = facts.drinking_label(drink_raw)
    if drink: camp["drinking_water"] = drink
    water_source = facts.scrub_money(row.get("water_source"))
    if water_source: camp["water_source"] = water_source
    water_tap = facts.yes_no_label(row.get("water_tap"))
    if water_tap: camp["water_tap"] = water_tap
    booking_raw = row.get("booking_required")
    if booking_raw in (None, ""): booking_raw = row.get("booking")
    booking = facts.booking_label(booking_raw)
    if booking: camp["booking_label"] = booking
    fee_raw = str(row.get("fee_type") or "").strip().lower()
    if fee_raw in ("free", "donation", "paid"): camp["fee_type"] = fee_raw
    fee = facts.fee_label(row.get("fee_type"), row.get("fee_note"))
    if fee: camp["fee_label"] = fee
    if row.get("max_nights") not in (None, ""):
        nights = facts.nights_from(row.get("max_nights"))
        label = facts.stay_label(row.get("max_nights"), nights)
        if label:
            camp["max_nights"] = nights
            camp["max_stay"] = label
    access_raw = row.get("access_notes")
    if access_raw in (None, ""): access_raw = row.get("access")
    access = facts.scrub_money(access_raw)
    if access and access.lower() not in ("unknown", "yes", "no"): camp["access_notes"] = access
    rubbish = facts.scrub_money(row.get("rubbish"))
    if rubbish: camp["rubbish"] = rubbish
    for src, dest in (("vehicle_notes", "vehicle_notes"), ("accessibility", "accessibility"), ("self_sufficient_note", "self_sufficient_note"), ("area", "area"), ("source_scope", "source_scope"), ("source_note", "source_note")):
        text = facts.scrub_money(row.get(src))
        if text and text.lower() != "unknown":
            if text[0].islower(): text = text[0].upper() + text[1:]
            camp[dest] = text
    description = facts.scrub_money(row.get("description"))
    if description: camp["description"] = description
    for key in ("phone", "email"):
        val = str(row.get(key) or "").strip()
        if val: camp[key] = val
    operator = str(row.get("operator") or "").strip()
    if operator:
        camp["managed_by"] = operator
        camp["overlay_operator"] = operator
    website = _http(row.get("website"))
    if website: camp["website"] = website
    source_url = _http(row.get("source_url"))
    if source_url: camp["source_url"] = source_url
    extra_url = _http(row.get("also_source_url") or row.get("source_url2"))
    if extra_url and extra_url != camp.get("source_url"): camp["source_url2"] = extra_url
    checked = facts.checked_phrase(row.get("checked_date"))
    if checked: camp["checked_line"] = checked
    for key, value in protected.items(): camp[key] = value
    return camp
def load_datavic_enrichment():
    path = os.path.join(ROOT, "data", "datavic-enrichment.json")
    if not os.path.isfile(path): return {}
    with open(path, encoding="utf-8") as handle: doc = json.load(handle)
    camps = doc.get("camps") if isinstance(doc, dict) else None
    return camps if isinstance(camps, dict) else {}
def apply_datavic_enrichment(camps):
    """Fill display facts on DataVic camps. Never changes status or closure."""
    overlay = load_datavic_enrichment()
    applied = mismatches = 0
    for camp in camps:
        if camp.get("source") != "datavic": continue
        extra = overlay.get(str(camp.get("id")))
        if not isinstance(extra, dict): continue
        want = str(extra.get("slug") or "").strip()
        if want and want != camp.get("slug"):
            mismatches += 1
            print(f"WARN datavic enrichment slug {camp.get('id')}: built {camp.get('slug')} overlay {want}", file=sys.stderr)
        apply_row_facts(camp, extra)
        camp["enriched"] = True
        applied += 1
    print(f"DataVic enrichment applied to {applied} camps, {mismatches} slug mismatches")
    return applied
def load_osm(seen):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import build_osm
    path = os.path.join(ROOT, "data", "osm-camps-vic.json")
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if isinstance(doc, dict): rows = doc.get("sites") or doc.get("camps") or []
    else: rows = doc
    rows = build_osm.apply_corrections(rows, build_osm.load_corrections())
    extra = []
    allowed = set(CAT_LABEL) | set(CAT_LABEL.values())
    for row in rows:
        name = (row.get("name") or "").strip()
        raw_cat = (row.get("category") or "").strip()
        if not name or not re.search(r"[A-Za-z0-9]", name) or raw_cat not in allowed: continue
        s = slug(name)
        if s in seen:
            tail = slug(str(row.get("osm_id") or "osm")) or "osm"
            s = f"{s}-{tail}"[:90].strip("-")
        n = 2
        base = s
        while s in seen:
            s = f"{base}-{n}"; n += 1
        seen.add(s)
        cat = CAT_LABEL.get(raw_cat, raw_cat)
        camp = {"slug": s, "id": row.get("osm_id") or s, "osm_id": row.get("osm_id") or "", "name": name,
            "lat": row["lat"], "lon": row["lon"], "region": region(row["lon"], row["lat"]),
            "status": "check", "closure": None, "access": "", "about": "", "camping": "", "caravans": "",
            "site_class": cat, "dis_access": None, "managed_by": "", "data_date": "",
            "nearby_closures": [], "source": "osm", "category": cat, "needs_review": bool(row.get("needs_review"))}
        apply_row_facts(camp, row)
        if cat == "Free" and str(row.get("fee_type") or "").strip().lower() == "paid":
            camp["category"] = "Camping area"
            camp["site_class"] = "Camping area"
        if cat == PV_LABEL and not camp.get("phone"): camp["phone"] = "13 1963"
        shown = strip_index_name(camp["name"])
        if shown != camp["name"]:
            # Slug stays on the original name so the old URL keeps working.
            camp["former_name"] = camp["name"]
            camp["name"] = shown
        extra.append(camp)
    return extra
camps.extend(load_osm(seen))
apply_datavic_enrichment(camps)
def assign_filters(camp):
    """Cost is the known fee. Type is the place filter, separate from the page label."""
    fee = str(camp.get("fee_type") or "").strip().lower()
    cat = camp.get("category") or ""
    if fee == "paid" or cat in (PV_LABEL, "Camping area"):
        camp["cost"] = "paid"
    elif fee in ("free", "donation") or cat == "Donation":
        camp["cost"] = "free"
    else:
        camp["cost"] = ""
    if cat == "Showground": camp["type_filter"] = "Showground"
    elif cat in ("Council park", "Council park (leased)"): camp["type_filter"] = "Council"
    elif cat == "Rest area": camp["type_filter"] = "Rest area"
    elif cat in ("Park campground", PV_LABEL): camp["type_filter"] = "Parks Victoria"
    else: camp["type_filter"] = ""
    return camp
for camp in camps: assign_filters(camp)
def nearest_places(camp, towns, limit=8):
    scored = []
    for town in towns:
        scored.append((km((camp["lon"], camp["lat"]), (town["lon"], town["lat"])), town["name"]))
    scored.sort()
    names, seen = [], set()
    for dist, place_name in scored:
        key = place_name.casefold()
        if key in seen: continue
        seen.add(key)
        names.append((dist, place_name))
        if len(names) >= limit: break
    return names
def assign_page_names(camps):
    """Duplicate names get a nearest-place subtitle so the title and h1 differ."""
    with open(os.path.join(ROOT, "data", "vic-towns.json"), encoding="utf-8") as handle:
        towns = json.load(handle)
    groups = {}
    for camp in camps:
        groups.setdefault(camp["name"].casefold(), []).append(camp)
    for group in groups.values():
        if len(group) < 2: continue
        choices = {id(camp): nearest_places(camp, towns) for camp in group}
        used = set()
        for camp in sorted(group, key=lambda camp: choices[id(camp)][0][0]):
            place = next((name for dist, name in choices[id(camp)] if name.casefold() not in used), choices[id(camp)][0][1])
            used.add(place.casefold())
            camp["page_name"] = f"{camp['name']}, near {place}"
        labels = {}
        for camp in group:
            labels.setdefault(camp["page_name"].casefold(), []).append(camp)
        for dupes in labels.values():
            if len(dupes) < 2: continue
            for camp in dupes:
                camp["page_name"] = f"{camp['page_name']}, {REGIONS[camp['region']][0]}"
        labels = {}
        for camp in group:
            labels.setdefault(camp["page_name"].casefold(), []).append(camp)
        for dupes in labels.values():
            if len(dupes) < 2: continue
            ordered = sorted(dupes, key=lambda camp: (camp["lat"], camp["lon"]))
            if len(ordered) == 2:
                ordered[0]["page_name"] += " (south)"
                ordered[1]["page_name"] += " (north)"
            else:
                for index, camp in enumerate(ordered, 1):
                    camp["page_name"] += f" ({index})"
assign_page_names(camps)
camps.sort(key=lambda c: c["name"].lower())

# ---------- rendering ----------
CSS = """:root{--g:#2f5d3a;--o:#c2571a;--bg:#fbfaf6}*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:var(--bg)}
header{background:var(--g);color:#fff}.banner{max-width:980px;margin:0 auto;padding:.7rem 1rem;display:flex;flex-wrap:nowrap;align-items:center;justify-content:flex-start;gap:.45rem 1.25rem}
.brand{color:#fff;text-decoration:none;font-weight:700;font-size:2.4rem;line-height:1.05;display:inline-flex;align-items:center;gap:.45rem;white-space:nowrap;max-width:100%}
.logo{width:4.8rem;height:4.8rem;flex:0 0 auto;display:block;object-fit:contain}
nav{display:flex;flex-wrap:nowrap;justify-content:flex-start;align-items:center;gap:.35rem 1.05rem}
nav a{color:#e8f0e9;text-decoration:none;font-weight:400;font-size:.95rem;white-space:nowrap}
.soon{margin:0;padding:6px 1rem;text-align:center;font-size:16px;font-weight:700;line-height:1.25;color:#fff;background:var(--o)}
.soon-sep{font-weight:700}
@media (max-width:720px){.soon{font-size:15px;padding:6px .5rem;white-space:nowrap}}
@media (max-width:360px){.soon{white-space:normal}}
@media (max-width:860px){.banner{flex-wrap:wrap;flex-direction:column;align-items:flex-start}.brand{font-size:clamp(1.05rem,5.15vw,2.4rem)}.logo{width:clamp(2.9rem,15.9vw,4.8rem);height:clamp(2.9rem,15.9vw,4.8rem)}nav{width:100%;flex-wrap:wrap;justify-content:flex-start;gap:.35rem .7rem}nav a{font-size:clamp(.8rem,3.1vw,.95rem)}}
main{max-width:980px;margin:0 auto;padding:1rem}h1{font-size:1.7rem;margin:.6rem 0}.muted{color:#666;font-size:.9rem}
.page-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.35rem .75rem;margin:.1rem 0 .15rem}
.page-head h1{margin:0;flex:1 1 auto}.head-counts{margin:0;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.badge{display:inline-block;padding:.1rem .55rem;border-radius:1rem;font-size:.8rem;font-weight:700;color:#fff}.open{background:#2e7d32}.closed{background:#b71c1c}.check{background:#e08a00}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:.8rem}.card{background:#fff;border:1px solid #e3e0d6;border-radius:10px;padding:.8rem}
.card a{color:var(--g);font-weight:600}table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #e3e0d6;padding:.35rem .5rem;text-align:left;font-size:.9rem}
.box{background:#fff;border:2px dashed var(--o);border-radius:10px;padding:1rem;margin:1rem 0}input,textarea,select,button{font:inherit;padding:.45rem;border:1px solid #bbb;border-radius:6px}button{background:var(--o);color:#fff;border:0;cursor:pointer}
a{color:var(--g)}
.signup label{display:block;font-weight:700;margin:0 0 .35rem}
.signup-row{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.signup-row input[type=email]{flex:1 1 auto;min-width:0;font-size:1.05rem;padding:.85rem .9rem;min-height:48px}
.signup-row button{font-size:1.05rem;font-weight:700;padding:.85rem 1.25rem;min-height:48px}
@media (max-width:640px){.signup-row{flex-direction:column;align-items:stretch}.signup-row input[type=email],.signup-row button{width:100%;flex:0 0 auto}}
.notice{margin:1rem 0;padding:1.15rem 1.2rem;border-radius:10px;font-size:1.35rem;font-weight:700;line-height:1.35}
.notice.ok{background:#e7f2e4;color:#1e4620;border:3px solid var(--g)}
.notice.err{background:#fde8e4;color:#7f1d1d;border:3px solid #9a3412}
.warn{background:#fff4e5;border-left:4px solid var(--o);padding:.6rem .8rem;margin:1rem 0}
.map{height:440px;margin:1rem 0;border:1px solid #e3e0d6;border-radius:10px;background:#e7e4da}
.map-sm{height:240px}.legend{margin:-.2rem 0 1rem;font-size:.9rem}.legend .badge{margin-right:.35rem}
.finder{position:relative;z-index:500;display:flex;flex-wrap:wrap;align-items:center;gap:.4rem .5rem;margin:.35rem 0 .4rem;padding:8px 0}
.town-search{position:relative;flex:1 1 14rem;min-width:9rem;margin:0}
.town-row{display:flex;flex-wrap:nowrap;gap:.4rem;align-items:center}#town-search{flex:1 1 auto;min-width:0;width:100%;font-size:1rem;padding:.4rem .7rem;min-height:44px}
#town-clear{background:#555;min-height:44px;padding:.35rem .6rem}#town-suggest{position:absolute;z-index:20;left:0;right:0;top:calc(100% + 4px);list-style:none;margin:0;padding:0;background:#fff;border:1px solid #d9d4c8;border-radius:8px;max-height:22rem;overflow:auto}
#town-suggest button,#town-suggest a{display:block;width:100%;text-align:left;background:#fff;color:#222;border:0;border-bottom:1px solid #eee;border-radius:0;padding:.65rem .8rem;font-weight:500;min-height:44px;text-decoration:none}
#town-suggest button:hover,#town-suggest button:focus,#town-suggest button[aria-selected="true"],#town-suggest a:hover,#town-suggest a:focus,#town-suggest a[aria-selected="true"]{background:#f3f1ea}
.hit-tag{display:inline-block;font-size:.72rem;font-weight:700;letter-spacing:.03em;text-transform:uppercase;border-radius:4px;padding:.05rem .4rem;margin-right:.45rem;vertical-align:middle}
.hit-tag.town{background:#f4efe4;color:#6b3e12;border:1px solid #c2571a}
.hit-tag.camp{background:#e7f2e4;color:#1e4620;border:1px solid #2f5d3a}
.hit-meta{display:block;font-weight:400;color:#555;font-size:.85rem;margin-top:.1rem}
.near-list{padding-left:1.2rem}
.filters{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem .45rem;margin:0}
.filters-all{display:none}
.filter-pop{position:relative}
.filter-btn{background:#fff;color:#222;border:1px solid #c9c3b6;border-radius:6px;min-height:44px;padding:.3rem .65rem;font-weight:600;white-space:nowrap;box-shadow:none}
.filter-btn[aria-expanded="true"]{border-color:var(--g);box-shadow:0 0 0 2px rgba(47,93,58,.2)}
.filter-caret{color:#555}
.filter-panel{position:absolute;z-index:5;top:calc(100% + 4px);left:0;min-width:15.5rem;background:#fff;border:1px solid #d9d4c8;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12);padding:.45rem .75rem .55rem}
.filter-panel-title{display:none;margin:.35rem 0 .1rem;font-weight:700}
.filter-count{margin:0;font-weight:700;font-size:.95rem;white-space:nowrap}
.filter-empty{background:#fff;border:1px solid #e3e0d6;border-radius:8px;padding:.75rem .9rem;margin:0 0 .8rem}
.filter-note{margin:0 0 .35rem;font-size:.85rem;color:#555}
.hide-closed{display:inline-flex;align-items:center;gap:.35rem;margin:0;min-height:44px;white-space:nowrap;font-weight:600}
.filter-panel .filter-row{display:flex;flex-direction:column}
.filter-panel .filter-row label{display:flex;align-items:center;gap:.4rem;margin:0;min-height:2.25rem;font-weight:500}
@media (max-width:640px){
  .filters-all{display:inline-flex;flex:0 0 auto}
  .finder{flex-wrap:nowrap}
  .filters{display:none;position:absolute;z-index:30;left:0;right:0;top:calc(100% + 6px);flex-direction:column;align-items:stretch;background:#fff;border:1px solid #d9d4c8;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12);padding:.7rem .85rem .85rem;gap:.15rem}
  .finder.filters-open .filters{display:flex}
  .filter-pop .filter-btn{display:none}
  .filter-panel{position:static;box-shadow:none;border:0;padding:0 0 .35rem;min-width:0}
  .filter-panel-title{display:block}
  .filter-count{white-space:normal}
}
.pin{background:transparent;border:none}.pin span{display:block;width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.35)}
a.btn,a.btn-alert{display:inline-block;background:var(--o);color:#fff;text-decoration:none;font-weight:600;padding:.45rem .8rem;border-radius:6px}
a.btn-alert{background:#9a3412;font-weight:700;padding:.7rem 1rem;font-size:1.05rem}
.leaflet-popup-content a{color:var(--g);font-weight:600}
footer{max-width:980px;margin:2rem auto;padding:1rem;font-size:.8rem;color:#555;border-top:1px solid #ddd}"""
BANNER = """<header><div class="banner"><a class="brand" href="/"><img class="logo" src="/assets/brand/logo-160.png" width="160" height="160" alt="CampConditions.au logo">CampConditions.au</a><nav><a href="/vic/">Victoria</a><a href="/#newsletter">Free digest</a><a href="/report/">Report conditions</a></nav></div></header><p class="soon"><span>Covering Victoria now</span><span class="soon-sep"> · </span><span>Other states coming soon</span></p>"""
ICONS = """<link rel="icon" href="/assets/brand/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/favicon-32.png"><link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png"><link rel="manifest" href="/site.webmanifest">
<meta property="og:image" content="https://campconditions.au/assets/brand/og-image.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://campconditions.au/assets/brand/og-image.png">"""

def ld(obj): return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'
SAFETY = '<div class="warn"><strong>Not an official warning service.</strong> This site does not republish VicEmergency warnings. Always check <a href="https://emergency.vic.gov.au/respond/">VicEmergency</a>, the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology warnings for Victoria</a> and <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> before you travel. In an emergency call <a href="tel:000">000</a>. VicEmergency hotline <a href="tel:1800226226">1800 226 226</a>.</div>'
def footer():
    return f"""<footer><p>{e(CREDIT)}</p>
<p><strong>Data and attribution.</strong> Campground details from DataVic (<a href="https://discover.data.vic.gov.au/dataset/recreation-sites">Recreation Sites</a> and Recreation Assets) and <a href="https://www.exploreoutdoors.vic.gov.au/">Explore Outdoors</a>, © State of Victoria (Department of Energy, Environment and Climate Action), CC BY 4.0, and Parks Victoria. Closures: Parks Victoria / DEECA MapShare. Extra campgrounds and towns: OpenStreetMap contributors (ODbL). Weather warnings: see the <a href="https://www.bom.gov.au/vic/warnings/">Bureau of Meteorology</a> (linked, not republished).</p>
<p>Site built {STAMP}. Conditions change quickly; information is provided as is without warranty. © CampConditions.au · <a href="/about/">About</a> · <a href="/privacy/">Privacy</a> · <a href="/status.json">JSON feed</a> · <a href="/llms.txt">llms.txt</a></p></footer>"""
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
    cdn("css", "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.min.css", "sha384-uIZNAcoEHVWMk8LrCSX95DJk6FQzH6zG00LQC9BykRY1UKKpkDzDhbDLYQ1Ho3mI")
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
        pt = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "status": c["status"], "url": f"/vic/camp/{c['slug']}/", "cat": c.get("category") or "", "type": c.get("type_filter") or "", "cost": c.get("cost") or ""}
        if cl.get("outdated"): pt["note"] = "Closure record may be outdated"
        for key, field in (("dogs", "fac_dogs"), ("caravans", "fac_caravans"), ("motorhomes", "fac_motorhomes")):
            value = c.get(field)
            if value is True: pt[key] = 1
            elif value is False: pt[key] = 0
        pts.append(pt)
    return json.dumps(pts, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
LEGEND = '<p class="legend"><span class="badge open">No known issues</span> <span class="badge check">Check conditions</span> <span class="badge closed">Closed</span> <span class="muted">A red pin stays red when the closure record may be outdated; the note is on the marker. Amber pins include sites where you need to check with the operator.</span></p>'
def flag_attr(c, field):
    value = c.get(field)
    if value is True: return "1"
    if value is False: return "0"
    return ""
def filters_html(items):
    costs = (("free", "Known to be free/donation"), ("paid", "Known to be paid"))
    types = ("Showground", "Council", "Rest area", "Parks Victoria")
    toggles = (("dogs", "Dogs OK"), ("caravans", "Known to suit caravans"), ("motorhomes", "Known to suit motorhomes"))
    cost_html = "".join(f'<label><input type="checkbox" name="cost" value="{key}"> {label}</label>' for key, label in costs)
    type_html = "".join(f'<label><input type="checkbox" name="type" value="{e(cat)}"> {e(cat)}</label>' for cat in types)
    flags = "".join(f'<label><input type="checkbox" data-flag="{key}"> {label}</label>' for key, label in toggles)
    total = f"{len(items):,}"
    def pop(key, title, body):
        return (f'<div class="filter-pop"><button type="button" class="filter-btn" id="filter-btn-{key}" aria-expanded="false" aria-haspopup="true" aria-controls="filter-panel-{key}">'
                f'<span class="filter-btn-label">{title}</span><span class="filter-caret" aria-hidden="true"> ▾</span></button>'
                f'<div id="filter-panel-{key}" class="filter-panel" role="group" aria-labelledby="filter-btn-{key}" hidden>'
                f'<p class="filter-panel-title">{title}</p>{body}</div></div>')
    cost_panel = f'<div class="filter-row">{cost_html}</div>'
    type_panel = f'<div class="filter-row">{type_html}</div>'
    fac_panel = f'<p class="filter-note">These filters only show sites where the detail is confirmed.</p><div class="filter-row">{flags}</div>'
    return f'''<div class="finder"><div class="town-search"><label class="sr" for="town-search">Search by town or camp name</label><div class="town-row"><input id="town-search" type="search" role="combobox" placeholder="Search by town or camp name" autocomplete="off" enterkeyhint="search" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="town-suggest" aria-expanded="false"><button type="button" id="town-clear" hidden>Clear</button></div><ul id="town-suggest" role="listbox" aria-label="Towns and camps" hidden></ul></div>
<button type="button" class="filter-btn filters-all" id="filters-all" aria-expanded="false" aria-controls="camp-filters"><span class="filter-btn-label">Filters</span></button>
<div class="filters" id="camp-filters">{pop("cost", "Cost", cost_panel)}{pop("type", "Type", type_panel)}{pop("facilities", "Facilities", fac_panel)}<label class="hide-closed"><input type="checkbox" data-flag="hide-closed"> Hide closed</label><p id="filter-count" class="filter-count" aria-live="polite">Showing {total} of {total} camps</p></div></div>
<div id="town-results" aria-live="polite"></div>'''
def map_block(items, label, small=False):
    cls = "map map-sm" if small else "map"
    legend = "" if small else LEGEND
    tools = "" if small else filters_html(items)
    empty = "" if small else '<p id="filter-empty" class="filter-empty" hidden>No camps match these filters. <a href="#camp-filters" id="filter-clear">Clear filters</a></p>'
    return f'{tools}{empty}<div id="camp-map" class="{cls}" role="region" aria-label="{e(label)}"></div>{legend}<script type="application/json" id="camp-map-data">{map_points(items)}</script>'
def directions(c):
    url = f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lon']}"
    # toiletmap.gov.au centres a map only for a facility id (/123) or a saved custom map.
    # lat/lng query strings are ignored, so this opens the Toilet Map home page.
    toilets = "https://toiletmap.gov.au/"
    return f'<p><a class="btn" href="{e(url)}">Directions in Google Maps</a> <a class="btn" href="{toilets}" target="_blank" rel="noopener noreferrer">Find nearby toilets</a></p>'
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
    if (p.cat) html += "<br>" + esc(p.cat);
    if (p.note) html += '<br><span class="muted">' + esc(p.note) + "</span>";
    html += '<br><a href="' + esc(p.url) + '">Campground page</a>';
    return html;
  }
  var small = el.classList.contains("map-sm");
  var map = L.map(el, {scrollWheelZoom: false});
  el._campMap = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
  }).addTo(map);
  var markers = data.map(function (p) {
    var title = p.name + (p.note ? " — " + p.note : "");
    return L.marker([p.lat, p.lon], {icon: icon(p.status), title: title}).bindPopup(popup(p));
  });
  if (small || typeof L.markerClusterGroup !== "function") {
    markers.forEach(function (m) { m.addTo(map); });
    if (markers.length === 1) map.setView([data[0].lat, data[0].lon], 13);
    else if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.08));
    else map.setView([-36.8, 144.5], 6);
    return;
  }
  var group = L.markerClusterGroup({showCoverageOnHover: false, maxClusterRadius: 42});
  map.addLayer(group);
  var picked = null;
  var towns = null;
  var townsPromise = null;
  function flag(obj, key) {
    var v = obj[key];
    if (v === undefined || v === null || v === "") return null;
    if (v === 1 || v === "1" || v === true) return 1;
    if (v === 0 || v === "0" || v === false) return 0;
    return null;
  }
  function selected(name) {
    var out = [];
    document.querySelectorAll('#camp-filters input[name="' + name + '"]:checked').forEach(function (box) { out.push(box.value); });
    return out;
  }
  function matches(obj) {
    var types = selected("type");
    if (types.length && types.indexOf(obj.type || "") === -1) return false;
    var costs = selected("cost");
    if (costs.length && costs.indexOf(obj.cost || "") === -1) return false;
    var hide = document.querySelector('#camp-filters input[data-flag="hide-closed"]');
    if (hide && hide.checked && obj.status === "closed") return false;
    var andFlags = ["dogs", "caravans", "motorhomes"];
    for (var i = 0; i < andFlags.length; i++) {
      var box = document.querySelector('#camp-filters input[data-flag="' + andFlags[i] + '"]');
      if (box && box.checked && flag(obj, andFlags[i]) !== 1) return false;
    }
    return true;
  }
  function kmBetween(lat1, lon1, lat2, lon2) {
    var r = Math.PI / 180;
    var dlat = (lat2 - lat1) * r, dlon = (lon2 - lon1) * r;
    var a = Math.sin(dlat / 2) * Math.sin(dlat / 2) + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dlon / 2) * Math.sin(dlon / 2);
    return 6371 * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  function fmtKm(d) {
    if (d < 10) return (Math.round(d * 10) / 10).toFixed(1) + " km";
    return Math.round(d) + " km";
  }
  function showNearest() {
    var results = document.getElementById("town-results");
    if (!picked || !results) return;
    var ranked = [];
    data.forEach(function (p) {
      if (!matches(p)) return;
      ranked.push({p: p, d: kmBetween(picked.lat, picked.lon, p.lat, p.lon)});
    });
    ranked.sort(function (a, b) { return a.d - b.d; });
    ranked = ranked.slice(0, 15);
    if (!ranked.length) {
      results.innerHTML = "<p>No camps match these filters near " + esc(picked.name) + ".</p>";
      return;
    }
    var html = "<h2>Nearest camps to " + esc(picked.name) + "</h2><ol class='near-list'>";
    ranked.forEach(function (row) {
      html += "<li><a href=\"" + esc(row.p.url) + "\">" + esc(row.p.name) + "</a> <span class='muted'>" + fmtKm(row.d);
      if (row.p.cat) html += " · " + esc(row.p.cat);
      html += "</span></li>";
    });
    results.innerHTML = html + "</ol>";
  }
  function formatCount(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  function setFilterLabel(btn, base, n) {
    var label = btn && btn.querySelector(".filter-btn-label");
    if (label) label.textContent = n ? base + " (" + n + ")" : base;
  }
  function refreshFilterButtons() {
    var fac = document.querySelectorAll("#filter-panel-facilities input:checked").length;
    [["filter-btn-cost", "Cost", selected("cost").length], ["filter-btn-type", "Type", selected("type").length], ["filter-btn-facilities", "Facilities", fac]].forEach(function (row) {
      setFilterLabel(document.getElementById(row[0]), row[1], row[2]);
    });
    setFilterLabel(document.getElementById("filters-all"), "Filters", document.querySelectorAll("#camp-filters input:checked").length);
  }
  function updateFilterStatus(shownCount) {
    var countEl = document.getElementById("filter-count");
    if (countEl) countEl.textContent = "Showing " + formatCount(shownCount) + " of " + formatCount(data.length) + " camps";
    var empty = document.getElementById("filter-empty");
    if (empty) empty.hidden = shownCount !== 0;
    refreshFilterButtons();
  }
  function redraw(fit) {
    group.clearLayers();
    var shownCount = 0;
    data.forEach(function (p, i) {
      if (!matches(p)) return;
      group.addLayer(markers[i]);
      shownCount += 1;
    });
    document.querySelectorAll("#camp-list tbody tr[data-url]").forEach(function (row) {
      row.hidden = !matches(row.dataset);
    });
    updateFilterStatus(shownCount);
    if (picked) showNearest();
    else if (fit && shownCount) {
      try { map.fitBounds(group.getBounds().pad(0.08)); } catch (err) {}
    } else if (!shownCount) map.setView([-36.8, 144.5], 6);
  }
  function loadTowns() {
    if (towns) return Promise.resolve(towns);
    if (!townsPromise) {
      townsPromise = fetch("/vic-towns.json").then(function (r) { return r.json(); }).then(function (rows) {
        towns = rows;
        return rows;
      });
    }
    return townsPromise;
  }
  function fold(s) {
    return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
  }
  function regionName(lat, lon) {
    if (lat > -35.9) return "Murray & Mallee";
    if (lat < -38.2 && lon < 145) return "Otways & Surf Coast";
    if (lon < 143.6) return "Grampians & South West";
    if (lon < 145.3) return "Goldfields & Central Victoria";
    if (lon >= 146.0 && lat > -37.45) return "High Country";
    if (lon >= 145.9) return "Gippsland";
    return "Yarra Ranges & Central Highlands";
  }
  function matchScore(name, query) {
    var n = fold(name), q = fold(query);
    if (q.length < 2 || !n) return -1;
    if (n === q) return 0;
    var qWords = q.split(" "), nWords = n.split(" "), partial = false, i, j, ok;
    for (i = 0; i < qWords.length; i++) {
      ok = false;
      for (j = 0; j < nWords.length; j++) {
        if (nWords[j].indexOf(qWords[i]) === 0) { ok = true; break; }
      }
      if (!ok && n.indexOf(qWords[i]) >= 0) { ok = true; partial = true; }
      if (!ok) return -1;
    }
    if (n.indexOf(q) === 0) return 1;
    return partial ? 3 : 2;
  }
  function nearestTown(lat, lon) {
    if (!towns || !towns.length) return null;
    var best = null, bestD = Infinity, i, d;
    for (i = 0; i < towns.length; i++) {
      d = kmBetween(lat, lon, towns[i].lat, towns[i].lon);
      if (d < bestD) { bestD = d; best = towns[i]; }
    }
    return best;
  }
  function byRank(a, b) {
    if (a.score !== b.score) return a.score - b.score;
    if (a.rank !== b.rank) return a.rank - b.rank;
    return a.name.localeCompare(b.name, "en");
  }
  function suggestions(q) {
    if (fold(q).length < 2) return [];
    var hits = [];
    (towns || []).forEach(function (town) {
      var score = matchScore(town.name, q);
      if (score < 0) return;
      hits.push({kind: "town", score: score, rank: town.rank || 0, name: town.name, town: town});
    });
    data.forEach(function (camp, index) {
      var score = matchScore(camp.name, q);
      if (score < 0) return;
      hits.push({kind: "camp", score: score, rank: 2, name: camp.name, camp: camp, index: index});
    });
    hits.sort(byRank);
    var top = hits.slice(0, 9);
    var only = top.length && top.every(function (hit) { return hit.kind === top[0].kind; });
    if (only && hits.some(function (hit) { return hit.kind !== top[0].kind; })) {
      hits.filter(function (hit) { return hit.kind !== top[0].kind; }).slice(0, 3).forEach(function (hit) { top.push(hit); });
      top.sort(byRank);
    }
    return top.slice(0, 12);
  }
  var townInput = document.getElementById("town-search");
  var suggest = document.getElementById("town-suggest");
  var clearBtn = document.getElementById("town-clear");
  var lastHits = [];
  var activeIdx = -1;
  function closeSuggest() {
    activeIdx = -1;
    if (suggest) suggest.hidden = true;
    if (townInput) {
      townInput.setAttribute("aria-expanded", "false");
      townInput.removeAttribute("aria-activedescendant");
    }
  }
  function campMeta(camp) {
    var bits = [];
    if (camp.cat) bits.push(camp.cat);
    bits.push(regionName(camp.lat, camp.lon));
    var near = nearestTown(camp.lat, camp.lon);
    if (near && fold(near.name) !== fold(camp.name)) bits.push("near " + near.name);
    return bits.join(" · ");
  }
  function renderSuggest(items) {
    if (!suggest) return;
    lastHits = items;
    activeIdx = -1;
    suggest.innerHTML = "";
    if (townInput) townInput.removeAttribute("aria-activedescendant");
    if (!items.length) { closeSuggest(); return; }
    items.forEach(function (hit, i) {
      var li = document.createElement("li");
      li.setAttribute("role", "presentation");
      var option = hit.kind === "camp" ? document.createElement("a") : document.createElement("button");
      if (hit.kind === "camp") option.href = hit.camp.url;
      else {
        option.type = "button";
        option.addEventListener("click", function () { choose(hit); });
      }
      option.id = "town-suggest-" + i;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      var tag = document.createElement("span");
      tag.className = "hit-tag " + hit.kind;
      tag.textContent = hit.kind === "camp" ? "Camp" : "Town";
      var name = document.createElement("span");
      name.className = "hit-name";
      name.textContent = hit.name;
      option.appendChild(tag);
      option.appendChild(document.createTextNode(" "));
      option.appendChild(name);
      var meta = document.createElement("span");
      meta.className = "hit-meta";
      meta.textContent = hit.kind === "camp" ? campMeta(hit.camp) : (hit.town.place || "place");
      option.appendChild(meta);
      li.appendChild(option);
      suggest.appendChild(li);
    });
    suggest.hidden = false;
    if (townInput) townInput.setAttribute("aria-expanded", "true");
  }
  function moveActive(delta) {
    var options = suggest ? suggest.querySelectorAll('[role="option"]') : [];
    if (!options.length) return;
    if (activeIdx < 0) activeIdx = delta < 0 ? options.length - 1 : 0;
    else activeIdx = (activeIdx + delta + options.length) % options.length;
    options.forEach(function (option, i) { option.setAttribute("aria-selected", i === activeIdx ? "true" : "false"); });
    if (townInput) townInput.setAttribute("aria-activedescendant", options[activeIdx].id);
    options[activeIdx].scrollIntoView({block: "nearest"});
  }
  function choose(hit) {
    if (hit.kind === "camp" && hit.camp && hit.camp.url) {
      window.location.assign(hit.camp.url);
      return;
    }
    if (townInput) townInput.value = hit.name;
    closeSuggest();
    if (clearBtn) clearBtn.hidden = false;
    picked = hit.town;
    map.stop();
    map.setView([hit.town.lat, hit.town.lon], 10);
    redraw(false);
  }
  if (townInput) {
    townInput.addEventListener("focus", function () { loadTowns(); });
    townInput.addEventListener("input", function () {
      var q = townInput.value;
      if (!q.trim()) {
        picked = null;
        var results = document.getElementById("town-results");
        if (results) results.innerHTML = "";
        closeSuggest();
        if (clearBtn) clearBtn.hidden = true;
        redraw(true);
        return;
      }
      loadTowns().then(function () { renderSuggest(suggestions(q)); });
    });
    townInput.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        if (!lastHits.length || (suggest && suggest.hidden)) {
          loadTowns().then(function () {
            renderSuggest(suggestions(townInput.value));
            if (lastHits.length) moveActive(ev.key === "ArrowDown" ? 1 : -1);
          });
          return;
        }
        moveActive(ev.key === "ArrowDown" ? 1 : -1);
      }
      if (ev.key === "Enter") {
        ev.preventDefault();
        if (activeIdx >= 0 && lastHits[activeIdx]) { choose(lastHits[activeIdx]); return; }
        loadTowns().then(function () {
          var items = suggestions(townInput.value);
          if (items.length) choose(items[0]);
        });
      }
      if (ev.key === "Escape") closeSuggest();
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      picked = null;
      if (townInput) townInput.value = "";
      if (suggest) suggest.hidden = true;
      var results = document.getElementById("town-results");
      if (results) results.innerHTML = "";
      clearBtn.hidden = true;
      redraw(true);
    });
  }
  document.querySelectorAll("#camp-filters input").forEach(function (box) {
    box.addEventListener("change", function () { redraw(false); });
  });
  var phoneQuery = window.matchMedia("(max-width: 640px)");
  function phoneLayout() { return phoneQuery.matches; }
  function closeFilterMenus(restore) {
    document.querySelectorAll(".filter-pop .filter-btn").forEach(function (btn) {
      btn.setAttribute("aria-expanded", "false");
      var panel = document.getElementById(btn.getAttribute("aria-controls"));
      if (panel && !phoneLayout()) panel.hidden = true;
    });
    var finder = document.querySelector(".finder");
    var allBtn = document.getElementById("filters-all");
    if (finder) finder.classList.remove("filters-open");
    if (allBtn) allBtn.setAttribute("aria-expanded", "false");
    if (restore && restore.focus) restore.focus();
  }
  function syncPhonePanels() {
    if (phoneLayout()) document.querySelectorAll(".filter-panel").forEach(function (panel) { panel.hidden = false; });
    else closeFilterMenus();
  }
  document.querySelectorAll(".filter-pop .filter-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (phoneLayout()) return;
      var willOpen = btn.getAttribute("aria-expanded") !== "true";
      closeFilterMenus();
      if (!willOpen) return;
      btn.setAttribute("aria-expanded", "true");
      var panel = document.getElementById(btn.getAttribute("aria-controls"));
      if (panel) panel.hidden = false;
    });
  });
  var allFilters = document.getElementById("filters-all");
  if (allFilters) {
    allFilters.addEventListener("click", function () {
      var finder = document.querySelector(".finder");
      var willOpen = finder && !finder.classList.contains("filters-open");
      closeFilterMenus();
      if (!willOpen) return;
      finder.classList.add("filters-open");
      allFilters.setAttribute("aria-expanded", "true");
      document.querySelectorAll(".filter-panel").forEach(function (panel) { panel.hidden = false; });
    });
  }
  document.addEventListener("click", function (ev) {
    if (ev.target.closest(".filter-btn") || ev.target.closest(".filter-panel") || ev.target.closest(".hide-closed")) return;
    closeFilterMenus();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    var open = document.querySelector(".filter-pop .filter-btn[aria-expanded='true']");
    if (open) { closeFilterMenus(open); return; }
    if (allFilters && allFilters.getAttribute("aria-expanded") === "true") closeFilterMenus(allFilters);
  });
  if (phoneQuery.addEventListener) phoneQuery.addEventListener("change", syncPhonePanels);
  syncPhonePanels();
  var clearFilters = document.getElementById("filter-clear");
  if (clearFilters) {
    clearFilters.addEventListener("click", function (ev) {
      ev.preventDefault();
      document.querySelectorAll("#camp-filters input").forEach(function (box) { box.checked = false; });
      redraw(true);
    });
  }
  redraw(true);
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
{ICONS}
<link rel="alternate" type="application/json" href="/status.json" title="Campground status feed"><style>{CSS}</style>{head}{''.join(ld(x) for x in extra_ld)}</head><body>
{BANNER}
<main>{body}</main>{footer()}{foot}</body></html>"""
    h = external_blank(h)
    fp = os.path.join(OUT, path.lstrip("/"), "index.html") if path.endswith("/") else os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "w", encoding="utf-8").write(h)
def badge(c):
    if isinstance(c, str):
        status, text = c, {"open": "No known issues", "closed": "Closed", "check": "Check conditions"}[c]
    else:
        status = c["status"]
        if c.get("source") == "osm" and c.get("category") == "Showground": text = "Call first"
        elif c.get("source") == "osm" and c.get("category") == PV_LABEL: text = "Book ahead"
        elif c.get("source") == "osm": text = "Check with operator"
        else: text = {"open": "No known issues", "closed": "Closed", "check": "Check conditions"}[status]
    return f'<span class="badge {status}">{text}</span>'
def crumbs(items): return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": i+1, "name": n, "item": SITE+u} for i, (n, u) in enumerate(items)]}
NEWS = """<section class="box" id="newsletter"><h2>Get the free weekly Victoria digest</h2><p>Every Thursday: what's closed, which roads are shut, and what campers are reporting — region by region. We'll email a confirmation link first; you're not on the list until you click it.</p>
<form id="digest-form" class="signup" action="/api/subscribe" method="post"><label for="digest-email">Your email</label><div class="signup-row"><input id="digest-email" type="email" name="email" required placeholder="you@example.com" autocomplete="email"> <button type="submit">Subscribe</button></div></form>
<div id="digest-note" class="notice" role="alert" aria-live="assertive" tabindex="-1" hidden></div>
<p class="muted">We'll only use your email to send the CampConditions digest. We never sell or share it. <a href="/unsubscribe/">Unsubscribe any time</a>.</p>
<script>
document.getElementById("digest-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const note = document.getElementById("digest-note");
  const button = form.querySelector("button");
  note.hidden = false;
  note.className = "notice";
  note.textContent = "One moment…";
  button.disabled = true;
  const show = (kind, message) => {
    note.hidden = false;
    note.className = "notice " + kind;
    note.textContent = message;
    note.focus();
    note.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  try {
    const res = await fetch("/api/subscribe", { method: "POST", body: new FormData(form), headers: { accept: "text/plain" } });
    const text = (await res.text()).replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim();
    if (res.ok) {
      show("ok", "Check your email and click the confirmation link. You won't be added until you do.");
      form.reset();
      Array.from(form.elements).forEach((el) => { el.disabled = true; });
      return;
    }
    button.disabled = false;
    show("err", res.status === 503 ? "Sign-ups open soon." : (text.slice(0, 240) || "Something went wrong. Please try again."));
  } catch (err) {
    button.disabled = false;
    show("err", "Something went wrong. Please try again.");
  }
});
</script>
<p class="muted">Coming soon: a paid daily digest with instant alerts for camps you've saved (about $5 a month).</p></section>"""

shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
open(os.path.join(OUT, "map.js"), "w", encoding="utf-8").write(MAP_JS)
shutil.copytree(os.path.join(ROOT, "assets", "brand"), os.path.join(OUT, "assets", "brand"))
shutil.copyfile(os.path.join(ROOT, "assets", "brand", "site.webmanifest"), os.path.join(OUT, "site.webmanifest"))
by_reg = {k: [c for c in camps if c["region"] == k] for k in REGIONS}
n_closed = sum(c["status"] == "closed" for c in camps); n_check = sum(c["status"] == "check" for c in camps)

def list_note(c):
    if c.get("source") == "osm":
        if c.get("category") == "Showground": return "Call first"
        if c.get("category") == PV_LABEL: return "Book ahead — Parks Victoria"
        if c.get("category") == "Pub stay": return "Pub stay — check with the pub"
        return "Conditions: check with operator"
    desc = (c.get("closure") or {}).get("desc") or ""
    if desc: return desc
    if c["nearby_closures"]: return f"{len(c['nearby_closures'])} road closures nearby"
    return ""
def row_attrs(c):
    return (f'data-url="/vic/camp/{c["slug"]}/" data-type="{e(c.get("type_filter") or "")}" data-cost="{e(c.get("cost") or "")}" data-status="{e(c["status"])}" '
            f'data-dogs="{flag_attr(c,"fac_dogs")}" '
            f'data-caravans="{flag_attr(c,"fac_caravans")}" data-motorhomes="{flag_attr(c,"fac_motorhomes")}"')
def yn(value):
    if value is True: return "Yes"
    if value is False: return "No"
    return "Unknown"
def tel_href(phone):
    keep = re.sub(r"[^\d+]", "", phone or "")
    return f"tel:{keep}" if keep else ""
def osm_blocks(c):
    if c.get("category") == "Showground":
        bits = ["<p><strong>Call first.</strong></p>"]
    elif c.get("category") == PV_LABEL:
        phone = c.get("phone") or "13 1963"
        bits = [f'<p><strong>{e(PV_LABEL)}.</strong> Book ahead with Parks Victoria on <a href="{e(tel_href(phone))}">{e(phone)}</a>.</p>']
    elif c.get("category") == "Pub stay":
        bits = ["<p><strong>Pub stay.</strong> Conditions: check with operator.</p>"]
    else:
        bits = ["<p><strong>Conditions: check with operator.</strong></p>"]
    if c.get("needs_review"):
        bits.append(f'<p class="warn"><strong>Unverified, help us confirm</strong> — <a href="/report/?camp={e(c["slug"])}">send a correction</a>.</p>')
    desc = c.get("description") or ""
    unknown_overnight = c.get("category") == "Rest area" and not c.get("max_stay")
    if "follow signs on site" in desc.lower() or unknown_overnight:
        bits.append("<p><strong>Follow signs on site.</strong> Overnight stays are not confirmed.</p>")
    if desc: bits.append(f"<p>{e(desc)}</p>")
    bits.append(facts_html(c, fill_unknown=True))
    if c.get("category"): bits.append(f"<p>Type: {e(c['category'])}</p>")
    if c.get("managed_by"): bits.append(f"<p>Operator: {e(c['managed_by'])}</p>")
    return "".join(bits)
def contact_html(c):
    buttons = []
    if c.get("phone") and tel_href(c["phone"]):
        buttons.append(f'<a class="btn" href="{e(tel_href(c["phone"]))}">Call {e(c["phone"])}</a>')
    if c.get("email") and "@" in c["email"]:
        buttons.append(f'<a class="btn" href="mailto:{e(c["email"])}">Email</a>')
    if (c.get("website") or "").startswith("http"):
        buttons.append(f'<a class="btn" href="{e(c["website"])}">Website</a>')
    return "<p>" + " ".join(buttons) + "</p>" if buttons else ""
FACILITY_CHECKS = (("Dogs", "fac_dogs"), ("Dump point", "fac_dump"), ("Showers", "fac_showers"), ("Tents", "fac_tents"), ("Caravans", "fac_caravans"), ("Motorhomes", "fac_motorhomes"), ("Self-contained only", "fac_self"))
def checklist_rows(c):
    rows = []
    for label, field in FACILITY_CHECKS:
        if label == "Dogs" and c.get("dogs_text"):
            rows.append((label, c["dogs_text"], True)); continue
        value = c.get(field)
        if value is True: rows.append((label, "Yes", True))
        elif value is False: rows.append((label, "No", True))
        else: rows.append((label, "Unknown", False))
    return rows
def facilities_collapsed(c):
    """Hide unconfirmed rows whenever any facility is still unknown."""
    return any(not row[2] for row in checklist_rows(c))
def facility_items(c, fill_unknown):
    items = []
    collapse = facilities_collapsed(c)
    for label, value, known in checklist_rows(c):
        if known or (fill_unknown and not collapse): items.append((label, value))
    if c.get("toilets_text"): items.append(("Toilets", c["toilets_text"]))
    if c.get("drinking_water"): items.append(("Drinking water", c["drinking_water"]))
    if c.get("water_source"): items.append(("Water source", c["water_source"]))
    if c.get("water_tap"): items.append(("Water tap", c["water_tap"]))
    if c.get("rubbish"): items.append(("Rubbish", c["rubbish"]))
    if c.get("accessibility"): items.append(("Accessibility", c["accessibility"]))
    if c.get("vehicle_notes"): items.append(("Vehicles", c["vehicle_notes"]))
    return items
def facts_html(c, fill_unknown):
    bits = []
    if c.get("fee_label"): bits.append(f"<p><strong>{e(c['fee_label'])}</strong></p>")
    if c.get("booking_label"): bits.append(f"<p><strong>Booking required:</strong> {e(c['booking_label'])}</p>")
    if c.get("area"): bits.append(f"<p><strong>Area:</strong> {e(c['area'])}</p>")
    if c.get("access_notes"): bits.append(f"<p><strong>Access: {e(c['access_notes'])}</strong></p>")
    if c.get("self_sufficient_note"): bits.append(f"<p><strong>{e(c['self_sufficient_note'])}</strong></p>")
    contact = contact_html(c)
    if contact: bits.append(contact)
    if c.get("max_stay"): bits.append(f"<p><strong>Max stay: {e(c['max_stay'])}</strong></p>")
    elif fill_unknown: bits.append("<p><strong>Max stay: ask operator</strong></p>")
    items = facility_items(c, fill_unknown)
    collapse = facilities_collapsed(c)
    if items or collapse:
        block = "<h2>Facilities</h2>"
        if items: block += "<ul>" + "".join(f"<li>{label}: {e(value)}</li>" for label, value in items) + "</ul>"
        if collapse: block += f'<p>Other facilities not yet confirmed. Know this spot? <a href="/report/?camp={e(c["slug"])}">Help us confirm</a>.</p>'
        bits.append(block)
    if c.get("source_scope"): bits.append(f"<p>{e(c['source_scope'])}</p>")
    if c.get("source_note"): bits.append(f"<p>{e(c['source_note'])}</p>")
    if c.get("checked_line"): bits.append(f"<p>{e(c['checked_line'])}</p>")
    if (c.get("source_url") or "").startswith("http"):
        bits.append(f'<p>Source: <a href="{e(c["source_url"])}">official source</a></p>')
    if (c.get("source_url2") or "").startswith("http"):
        bits.append(f'<p>Also: <a href="{e(c["source_url2"])}">official source</a></p>')
    return "".join(bits)
def datavic_facts(c):
    if not c.get("enriched"): return ""
    bits = []
    if c.get("description"): bits.append(f"<p>{e(c['description'])}</p>")
    bits.append(facts_html(c, fill_unknown=False))
    if c.get("overlay_operator"): bits.append(f"<p>Operator: {e(c['overlay_operator'])}</p>")
    return "".join(bits)
shutil.copyfile(os.path.join(ROOT, "data", "vic-towns.json"), os.path.join(OUT, "vic-towns.json"))
n_osm = sum(c.get("source") == "osm" for c in camps)
n_dv = len(camps) - n_osm

# Home
reg_cards = "".join(f'<div class="card"><a href="/vic/{k}/">{e(n)}</a><p class="muted">{len(by_reg[k])} campgrounds · {sum(c["status"]=="closed" for c in by_reg[k])} closed · {sum(c["status"]=="check" for c in by_reg[k])} to check</p><p>{e(d)}</p></div>' for k, (n, d) in REGIONS.items())
home_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "CampConditions.au", "url": SITE + "/", "inLanguage": "en-AU", "description": f"Camp and campground conditions for {len(camps)} sites in Victoria, Australia."},
           {"@context": "https://schema.org", "@type": "Organization", "name": "CampConditions.au", "url": SITE + "/", "sameAs": ["https://www.youtube.com/@OptimumQuestforBigThings"]},
           {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
             {"@type": "Question", "name": "How do I know if a free camp in Victoria is open?", "acceptedAnswer": {"@type": "Answer", "text": "DEECA Recreation Sites pages show the closure status and nearby Parks Victoria road and seasonal closures. OpenStreetMap campgrounds are not in that closure feed: the page says to check with the operator, and showgrounds say to call first. CampConditions.au does not republish VicEmergency warnings. Check VicEmergency, Parks Victoria and the Bureau of Meteorology before you travel. In an emergency call 000. The VicEmergency hotline is 1800 226 226."}},
             {"@type": "Question", "name": "How often is CampConditions.au updated?", "acceptedAnswer": {"@type": "Answer", "text": "The site rebuilds from DEECA and Parks Victoria sources several times a day. OpenStreetMap campgrounds and towns are refreshed weekly. Each page shows when it was built. Warning information is not included."}}]}]
page("/", f"Victorian camp conditions — {len(camps)} sites | CampConditions.au", f"Closure status and nearby road closures for {len(camps)} Victorian campgrounds, including {n_osm} OpenStreetMap sites to check with the operator.",
 f"""<div class="page-head"><h1>Victorian camp conditions</h1><p class="head-counts"><span class="badge closed">{n_closed} closed</span> <span class="badge check">{n_check} to check</span></p></div><p>Closures, nearby road conditions and camper reports for <strong>{len(camps)}</strong> campgrounds across Victoria. <strong>{n_dv}</strong> are DEECA Recreation Sites with Parks Victoria closures. <strong>{n_osm}</strong> more are from OpenStreetMap — check with the operator, and call a showground first.</p>
{map_block(camps, "Map of Victorian campgrounds")}{SAFETY}<h2>Regions</h2><div class="grid">{reg_cards}</div>
<p>Weather warnings: <a href="https://www.bom.gov.au/vic/warnings/">check BOM's Victorian warnings</a>. Bushfire, flood and other emergency warnings: check <a href="https://emergency.vic.gov.au/respond/">VicEmergency</a> — they are not republished here.</p>{NEWS}""", home_ld, head=leaflet_head(True), foot=leaflet_foot(True))

page("/vic/", f"Victoria campground conditions — {len(camps)} sites | CampConditions.au", f"Browse {len(camps)} Victorian campgrounds by region, including OpenStreetMap sites.",
     f"<h1>Victoria</h1><p><strong>{len(camps)}</strong> campgrounds. Search by town or camp name, then filter by cost, type and facilities.</p>{map_block(camps, 'Map of Victorian campgrounds')}{SAFETY}<div class='grid'>{reg_cards}</div>", [crumbs([("Home", "/"), ("Victoria", "/vic/")])], head=leaflet_head(True), foot=leaflet_foot(True))

for k, (n, d) in REGIONS.items():
    lst = by_reg[k]
    rows = "".join(f'<tr {row_attrs(c)}><td><a href="/vic/camp/{c["slug"]}/">{e(c["name"])}</a></td><td>{e(c.get("category") or "")}</td><td>{badge(c)}</td><td>{e(list_note(c))}</td></tr>' for c in sorted(lst, key=lambda c: ({"closed":0,"check":1,"open":2}[c["status"]], c["name"])))
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"Campgrounds in {n}, Victoria", "numberOfItems": len(lst), "itemListElement": [{"@type": "ListItem", "position": i+1, "url": f"{SITE}/vic/camp/{c['slug']}/", "name": c["name"]} for i, c in enumerate(lst)]}
    page(f"/vic/{k}/", f"{n} camps and campgrounds — {len(lst)} sites | CampConditions.au", f"{len(lst)} campgrounds in {n}, Victoria: closures, operator checks and facilities. {d}",
         f"<h1>{e(n)} campgrounds</h1><p>{e(d)} <strong>{len(lst)}</strong> sites.</p>{map_block(lst, f'Map of {n} campgrounds')}{SAFETY}<table id=\"camp-list\"><thead><tr><th>Campground</th><th>Type</th><th>Status</th><th>Notes</th></tr></thead><tbody>{rows or '<tr><td colspan=4>No campgrounds listed.</td></tr>'}</tbody></table>{NEWS}",
         [crumbs([("Home", "/"), ("Victoria", "/vic/"), (n, f"/vic/{k}/")]), il], head=leaflet_head(True), foot=leaflet_foot(True))

for c in camps:
    rn = REGIONS[c["region"]][0]
    cl = c["closure"]; parts = []
    osm = c.get("source") == "osm"
    if cl:
        parts.append(f'<div class="warn"><strong>Closed:</strong> {e(cl["desc"] or cl["reason"] or "Full closure")} {("· Reopens "+e(cl["reopen"][:10])) if cl.get("reopen") else ""}</div>')
        if cl.get("outdated"): parts.append(f'<div class="warn"><strong>This closure record may be outdated.</strong> The listed reopening date ({e(cl["reopen"][:10])}) has passed. Check <a href="https://www.parks.vic.gov.au/coc-listing">Parks Victoria changes of conditions</a> or call 13 1963 before you go.</div>')
    if c["nearby_closures"]: parts.append("<h2>Road and track closures within 5 km</h2><ul>" + "".join(f'<li>{e(x["type"])}{": "+e(x["name"]) if x["name"] else ""}{" — "+e(x["reason"]) if x["reason"] else ""}{" · reopens "+e(x["reopens"]) if x.get("reopens") else ""}</li>' for x in c["nearby_closures"]) + "</ul>")
    info_bits = []
    for heading, raw in (("About", c["about"]), ("Camping", c["camping"]), ("Caravans and campervans", c["caravans"]), ("Getting there", c["access"])):
        text = facts.without_prices(raw)
        if text: info_bits.append(f"<h2>{heading}</h2><p>{e(text)}</p>")
    info = "".join(info_bits)
    page_name = c.get("page_name") or c["name"]
    if osm:
        condition = osm_blocks(c)
        title = f"{page_name} showground — call first | CampConditions.au" if c.get("category") == "Showground" else f"{page_name} — check with the operator | CampConditions.au"
        desc = f"{c['name']} in {rn}, Victoria. Conditions: check with the operator. Type: {c.get('category') or 'camp'}."
        dated = "Source: OpenStreetMap. Parks Victoria closure data is not applied to this site."
    else:
        condition = "".join(parts) or "<p>No closure is recorded for this campground, and no road or track closures were found within 5 km.</p>"
        condition += datavic_facts(c)
        title = f"{page_name} campground — is it open? Conditions today | CampConditions.au"
        desc = f"Is {c['name']} campground open? Current closure status and nearby road closures for {c['name']} in {rn}, Victoria."
        dated = f"Campground data dated {e((c['data_date'] or '')[:10])}"
    camp_ld = {"@context": "https://schema.org", "@type": "Campground", "name": c["name"], "url": f"{SITE}/vic/camp/{c['slug']}/", "description": (c.get("description") or c["about"] or desc)[:300],
               "geo": {"@type": "GeoCoordinates", "latitude": c["lat"], "longitude": c["lon"]}, "address": {"@type": "PostalAddress", "addressRegion": "VIC", "addressCountry": "AU"},
               "containedInPlace": {"@type": "AdministrativeArea", "name": f"{rn}, Victoria"}, "publicAccess": c["status"] != "closed", "identifier": str(c["id"])}
    lds = [camp_ld, crumbs([("Home", "/"), ("Victoria", "/vic/"), (rn, f"/vic/{c['region']}/"), (c["name"], f"/vic/camp/{c['slug']}/")])]
    if cl:
        lds.append({"@context": "https://schema.org", "@type": "SpecialAnnouncement", "name": f"Closure: {c['name']}", "text": cl.get("desc") or cl.get("reason") or "This campground is recorded as closed.", "datePosted": NOW.isoformat(), "spatialCoverage": {"@type": "Place", "name": c["name"]}, "url": f"{SITE}/vic/camp/{c['slug']}/"})
    page(f"/vic/camp/{c['slug']}/", title, desc,
     f"""<p class="muted"><a href="/vic/">Victoria</a> › <a href="/vic/{c['region']}/">{e(rn)}</a></p><h1>{e(page_name)}</h1><p>{badge(c)} <span class="muted">Checked {STAMP}</span></p>
{vicemergency_button(c)}
{map_block([c], f"Map of {c['name']}", small=True)}{directions(c)}
{condition}{SAFETY}{info}
<p class="muted">Location: {c['lat']}, {c['lon']} · <a href="https://www.google.com/maps?q={c['lat']},{c['lon']}">Open in maps</a> · <a href="https://www.bom.gov.au/vic/forecasts/">BOM forecast</a> · {dated}</p>
<div class="box"><h2>Been here recently?</h2><p><a href="/report/?camp={c['slug']}">Report conditions at {e(c['name'])}</a> — how full, road access, water, phone coverage.</p></div>{NEWS}""", lds, head=leaflet_head(False), foot=leaflet_foot(False))

page("/unsubscribe/", "Unsubscribe | CampConditions.au", "Unsubscribe from the CampConditions.au weekly digest.",
 """<h1>Unsubscribe</h1>
<p>Every CampConditions email has a one-click unsubscribe link. It works without an account, and you don't need to log in. Open the link in the email and you're off the list.</p>
<p>Can't find that email? Enter your address and we'll send a fresh one-click link. You stay subscribed until you open it.</p>
<form id="unsub-form" class="signup box" action="/api/unsubscribe-request" method="post"><label for="unsub-email">Your email</label><div class="signup-row"><input id="unsub-email" type="email" name="email" required placeholder="you@example.com" autocomplete="email"> <button type="submit">Email me an unsubscribe link</button></div></form>
<div id="unsub-note" class="notice" role="alert" aria-live="assertive" tabindex="-1" hidden></div>
<script>
const preset = new URLSearchParams(location.search).get("e");
if (preset) document.getElementById("unsub-email").value = preset;
document.getElementById("unsub-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const note = document.getElementById("unsub-note");
  const button = form.querySelector("button");
  button.disabled = true;
  const show = (kind, message) => {
    note.hidden = false;
    note.className = "notice " + kind;
    note.textContent = message;
    note.focus();
    note.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  try {
    const res = await fetch("/api/unsubscribe-request", { method: "POST", body: new FormData(form), headers: { accept: "text/html" } });
    const text = (await res.text()).replace(/<[^>]+>/g, " ").replace(/\\s+/g, " ").trim();
    if (res.ok) {
      show("ok", "Check your email for a one-click unsubscribe link. You stay on the list until you open it.");
      form.reset();
      Array.from(form.elements).forEach((el) => { el.disabled = true; });
      return;
    }
    button.disabled = false;
    show("err", text.slice(0, 240) || "Something went wrong. Please try again.");
  } catch (err) {
    button.disabled = false;
    show("err", "Something went wrong. Please try again.");
  }
});
</script>""")
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
<h2>Sources</h2><p>{e(CREDIT)}</p><ul><li>Campground details from DataVic and Explore Outdoors © State of Victoria (Department of Energy, Environment and Climate Action), CC BY 4.0, and Parks Victoria. This includes Recreation Sites, Recreation Assets and Parks Victoria site pages. Facility details only. Closure status stays with DataVic and Parks Victoria.</li><li>Parks Victoria / DEECA MapShare closures on Recreation Sites.</li><li>OpenStreetMap campgrounds and towns (ODbL). These pages say to check with the operator. They are not given Parks Victoria closure data.</li><li>Bureau of Meteorology — linked only</li></ul><p>VicEmergency warnings are not republished. Use the check button on each campground page, or call 1800 226 226. We don't copy reviews from other apps. Camper reports come directly from our readers. We don't publish a downloadable copy of the combined campground list.</p>""")
page("/privacy/", "Privacy | CampConditions.au", "How CampConditions.au handles your email address.",
 """<h1>Privacy</h1><p>Last updated 16 October 2026.</p>
<h2>Who we are</h2><p>CampConditions.au publishes a free weekly digest of Victorian campground conditions. Contact us at <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.</p>
<h2>What we collect</h2><p>If you sign up, we collect your email address and the date and time of your sign-up and confirmation. We don't use tracking cookies. Cloudflare, which hosts this site, may log basic technical data such as your IP address for security.</p>
<h2>Why we collect it</h2><p>We use your email only to send the digest and service emails about your subscription, such as the confirmation message.</p>
<h2>Sharing</h2><p>We never sell, rent or share your email, except with service providers who process it for us: Resend (email delivery) and Cloudflare (hosting). Your data may be stored or processed outside Australia.</p>
<h2>Double opt-in</h2><p>Signing up is double opt-in. We email you a confirmation link, and you are not on the list until you click it.</p>
<h2>Unsubscribe, access, correction and deletion</h2><p id="unsubscribe">Every email includes an unsubscribe link. You can unsubscribe any time on the <a href="/unsubscribe/">unsubscribe page</a>. To ask for access, a correction, or deletion, email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.</p>
<h2>How long we keep it</h2><p>We keep your email while you are subscribed. After you unsubscribe, or after you ask us to delete it, we delete it within 30 days.</p>
<h2>Complaints</h2><p>If you have a complaint, email us. You can also contact the Office of the Australian Information Commissioner (OAIC) at <a href="https://www.oaic.gov.au/">oaic.gov.au</a>.</p>
<h2>Changes to this policy</h2><p>If we change this policy, we will update this page and the date at the top.</p>""")

# Feeds & SEO files
feed = {"name": "CampConditions.au status feed", "region": "Victoria, Australia", "generated": NOW.isoformat(),
        "attribution": [CREDIT, "Parks Victoria / DEECA MapShare closures"],
        "disclaimer": "Not an official warning service. VicEmergency warnings are not included. Check VicEmergency and the Bureau of Meteorology before travel. OpenStreetMap sites have no Parks Victoria closure data.", "sources": SRC,
        "camps": [{k: c[k] for k in ("slug", "name", "region", "lat", "lon", "status", "closure", "nearby_closures", "source", "category", "needs_review")} | {"url": f"{SITE}/vic/camp/{c['slug']}/"} for c in camps]}
json.dump(feed, open(os.path.join(OUT, "status.json"), "w"), ensure_ascii=False, indent=1)
urls = ["/", "/vic/", "/report/", "/about/", "/privacy/", "/unsubscribe/"] + [f"/vic/{k}/" for k in REGIONS] + [f"/vic/camp/{c['slug']}/" for c in camps]
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
- [Privacy]({SITE}/privacy/)
- [Unsubscribe]({SITE}/unsubscribe/)

## Attribution
{CREDIT}
Closures on DEECA sites: Parks Victoria / DEECA MapShare. OpenStreetMap sites are not given those closures. When citing a status, include its time. For warnings, send people to VicEmergency (emergency.vic.gov.au) and BOM (bom.gov.au); do not treat this site as a warning feed. This site does not offer a downloadable copy of the combined campground list.
""")
open(os.path.join(OUT, "404.html"), "w").write(f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Not found</title>{ICONS}<style>{CSS}</style></head><body>
{BANNER}
<main><p>Page not found. <a href="/">Back to CampConditions.au</a></p></main><footer><p>{e(CREDIT)}</p><p>© CampConditions.au · <a href="/privacy/">Privacy</a></p></footer></body></html>""")
json.dump(SRC, open(os.path.join(OUT, "build-report.json"), "w"), indent=1)
from collections import Counter
print(f"Built {len(urls)} pages, {len(camps)} camps ({n_dv} DEECA, {n_osm} OSM, {n_closed} closed, {n_check} check), {len(closures)} closure features")
renamed = [c for c in camps if c.get("former_name")]
print(f"Renamed {len(renamed)} indexed OSM names; slugs unchanged")
for camp in sorted(renamed, key=lambda c: c["former_name"].lower()):
    print(f"  {camp['former_name']} -> {camp['name']}  /vic/camp/{camp['slug']}/")
print("Duplicate page names")
for camp in camps:
    if camp.get("page_name"): print(f"  {camp['name']} -> {camp['page_name']}  /vic/camp/{camp['slug']}/")
for name, count in Counter(c.get("category") or "?" for c in camps).most_common():
    print(f"  {count:4d}  {name}")
print("Filters")
for label, pred in (
    ("Cost Known to be free/donation", lambda c: c.get("cost") == "free"),
    ("Cost Known to be paid", lambda c: c.get("cost") == "paid"),
    ("Cost unknown", lambda c: not c.get("cost")),
    ("Type Showground", lambda c: c.get("type_filter") == "Showground"),
    ("Type Council", lambda c: c.get("type_filter") == "Council"),
    ("Type Rest area", lambda c: c.get("type_filter") == "Rest area"),
    ("Type Parks Victoria", lambda c: c.get("type_filter") == "Parks Victoria"),
    ("Type none", lambda c: not c.get("type_filter")),
    ("Dogs OK", lambda c: c.get("fac_dogs") is True),
    ("Known to suit caravans", lambda c: c.get("fac_caravans") is True),
    ("Known to suit motorhomes", lambda c: c.get("fac_motorhomes") is True),
    ("Hide closed", lambda c: c.get("status") == "closed"),
):
    print(f"  {sum(1 for c in camps if pred(c)):4d}  {label}")
for k, v in SRC.items(): print(("OK  " if v["ok"] else "FAIL"), k, v.get("error", ""))
