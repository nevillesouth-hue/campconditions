#!/usr/bin/env python3
"""Build CampConditions.au. Python 3 stdlib only.

Each enabled state in config/states supplies its name, sources, regions, labels
and page copy. Victoria and New South Wales are both enabled. Victoria stays
the primary state: /map.js, the about page and the top-level digest draft.
"""
import importlib, io, json, math, os, re, html, shutil, sys, urllib.parse, urllib.request, gzip, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts
import states as statecfg
SITE = "https://campconditions.au"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist")
TZ = dt.timezone(dt.timedelta(hours=11))  # AEDT; good enough for display stamp
NOW = dt.datetime.now(TZ)
STAMP = NOW.strftime("%-d %B %Y, %-I:%M %p AEDT")
MAP_V = NOW.strftime("%Y%m%d%H%M")
SRC = {}
STATE = None
CREDIT = PV_LABEL = SAFETY = SLUG = ""
LABELS, LINKS, COPY, REGIONS = {}, {}, {}, {}
WFS = MS = ""

def bind(state):
    """Point the page templates at one state's config."""
    global STATE, CREDIT, PV_LABEL, SAFETY, SLUG, LABELS, LINKS, COPY, REGIONS, WFS, MS
    STATE = state
    CREDIT = state.get("credit") or ""
    LABELS = facts.state_labels(state["slug"])
    LINKS = state.get("links") or {}
    COPY = state.get("copy") or {}
    SLUG = state["slug"]
    PV_LABEL = LABELS.get("paid_book") or ""
    SAFETY = state.get("safety_html") or ""
    REGIONS = {key: (name, blurb) for key, name, blurb in statecfg.regions(state)}
    rec = (state.get("sources") or {}).get("recreation_sites") or {}
    clo = (state.get("sources") or {}).get("closures") or {}
    WFS = rec.get("url") or ""
    MS = clo.get("url_template") or ""

bind(statecfg.enabled()[0])
OSM_CATEGORIES = ["Free", "Camping area", "Donation", "Showground", "Council park", "Council park (leased)", "Rest area", "Pub stay", PV_LABEL]
CAT_LABEL = {"free": "Free", "donation": "Donation", "showground": "Showground", "council_park": "Council park", "council_park_leased": "Council park (leased)", "rest_area": "Rest area", "pub_stay": "Pub stay", "park_campground": PV_LABEL, "osm_camp": "Camp"}

def _read_response(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CampConditions.au/0.1 (+https://campconditions.au)", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=90) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
    return b

def fetch(name, url):
    try:
        d = json.loads(_read_response(url))
        SRC[name] = {"ok": True, "url": url, "fetched": NOW.isoformat()}
        return d
    except Exception as e:
        SRC[name] = {"ok": False, "url": url, "error": str(e)[:200]}; print("WARN", name, e, file=sys.stderr); return None

def fetch_text(name, url):
    """Bytes of a non-JSON feed. A failure is recorded and returns nothing."""
    try:
        body = _read_response(url)
        SRC[name] = {"ok": True, "url": url, "fetched": NOW.isoformat()}
        return body
    except Exception as e:
        SRC[name] = {"ok": False, "url": url, "error": str(e)[:200]}; print("WARN", name, e, file=sys.stderr); return None

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

def region(lon, lat):
    return statecfg.region_id(STATE, lon, lat)

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
# A leading "12 " is an index, not part of the name, unless the next word is a
# unit or place descriptor (6 Mile Flat, 82 Bend, 14 Creek).
_KEEP_UNIT = {"mile", "miles", "bend", "bends", "km", "kms", "kilometre", "kilometres", "kilometer", "kilometers", "creek", "creeks"}
def strip_index_name(name):
    match = re.match(r"^(\d+)\s+([A-Za-z]+)", name or "")
    if not match or match.group(2).lower() in _KEEP_UNIT: return name
    return name[match.start(2):]
e = lambda s: html.escape(str(s or ""), quote=True)
def feed_date(value):
    """Day month year from an RSS pubDate. Empty when the feed has no date."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    return f"{when.day} {when.strftime('%B %Y')}"
def feed_iso(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
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
# Last full camping='Y' response. On 27 Oct 2026 the column was still in the
# schema and null on every feature, so the filter returned nothing. A live
# response of at least this many sites replaces the file. A smaller non-zero
# response is left for the tests to reject, and does not overwrite the file.
RECREATION_CACHE = os.path.join(ROOT, "data", "recweb-camping-cache.json.gz")
RECREATION_CACHE_MIN = 342

def _recreation_cache_bytes(doc):
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as handle:
        handle.write(payload)
    return buf.getvalue()

def _load_recreation_cache():
    if not os.path.isfile(RECREATION_CACHE):
        return None
    try:
        with gzip.open(RECREATION_CACHE, "rt", encoding="utf-8") as handle:
            doc = json.load(handle)
    except Exception as exc:
        print("WARN recreation cache", exc, file=sys.stderr)
        return None
    if not (doc or {}).get("features"):
        return None
    return doc

def _save_recreation_cache(doc):
    try:
        body = _recreation_cache_bytes(doc)
        current = b""
        if os.path.isfile(RECREATION_CACHE):
            with open(RECREATION_CACHE, "rb") as handle:
                current = handle.read()
        if current == body:
            return
        os.makedirs(os.path.dirname(RECREATION_CACHE), exist_ok=True)
        tmp = RECREATION_CACHE + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(body)
        os.replace(tmp, RECREATION_CACHE)
    except Exception as exc:
        print("WARN recreation cache write", exc, file=sys.stderr)

def _recreation_sites_or_cache(name, doc):
    """Use the live camping feed, or the last full response when that feed is empty."""
    features = (doc or {}).get("features") or []
    if len(features) >= RECREATION_CACHE_MIN:
        _save_recreation_cache(doc)
        return doc
    if features:
        return doc
    cached = _load_recreation_cache()
    cached_n = len((cached or {}).get("features") or [])
    if not cached_n:
        return doc
    print(f"WARN {name}: camping filter returned no features; using cached recreation sites ({cached_n})", file=sys.stderr)
    info = dict(SRC.get(name) or {"ok": True, "url": ""})
    info["ok"] = True
    info["fallback"] = "cached recreation sites; live camping filter returned no features"
    info["fallback_features"] = cached_n
    SRC[name] = info
    return cached

def load_official(seen):
    """Campgrounds from the active state's official feed. Empty when that state has no feed yet."""
    rec_src = (STATE.get("sources") or {}).get("recreation_sites") or {}
    clo = (STATE.get("sources") or {}).get("closures") or {}
    found, state_closures = [], []
    if not rec_src.get("url"):
        return found, state_closures
    rec = _recreation_sites_or_cache(rec_src["key"], fetch(rec_src["key"], rec_src["url"]))
    for layer in clo.get("layers") or []:
        d = fetch(layer["key"], clo["url_template"].format(layer["id"]))
        for feature in (d or {}).get("features", []):
            state_closures.append((layer["label"], feature))
    source_id = rec_src.get("source_id") or SLUG
    category = LABELS.get("park_category") or ""
    for f in (rec or {}).get("features", []):
        q = f["properties"]; g = f.get("geometry")
        if q.get("published") != "Y" or not g: continue
        lon, lat = g["coordinates"][:2]
        s = slug(q["name"]); 
        if s in seen: s = f"{s}-{q['serial_no']}"
        seen.add(s)
        closed = (q.get("clos_stat") or "").upper()
        nearby_c = [closure_info(lab, c["properties"]) for lab, c in state_closures if c.get("geometry") and near((lon, lat), c["geometry"], 5)]
        status = "closed" if "CLOSURE" in closed else ("check" if nearby_c else "open")
        found.append({"slug": s, "id": q["serial_no"], "name": q["name"].strip(), "lat": round(lat, 6), "lon": round(lon, 6), "region": region(lon, lat),
            "status": status, "closure": {"status": q.get("clos_stat"), "desc": clean(q.get("clos_desc")), "reason": clean(q.get("clos_reas")), "start": q.get("clos_start"), "reopen": q.get("clos_open"), "outdated": bool(q.get("clos_open")) and q["clos_open"][:10] < NOW.date().isoformat()} if closed else None,
            "access": clean(q.get("access_dsc")), "about": clean(q.get("comments")), "camping": clean(q.get("camping_c")), "caravans": clean(q.get("campervan_c")),
            "site_class": q.get("site_class"), "dis_access": q.get("dis_access"), "managed_by": q.get("maintained_by"), "data_date": q.get("vers_date"),
            "nearby_closures": nearby_c[:10], "source": source_id, "category": category, "state_slug": SLUG,
            "needs_review": False})
    return found, state_closures

def _coded_label(table, code):
    """Domain label for a coded value. Unknown and missing codes stay blank."""
    if not isinstance(table, dict) or code in (None, ""):
        return ""
    label = str(table.get(str(code)) or "").strip()
    if not label or label.lower() == "unknown":
        return ""
    return label

def load_npws(seen):
    """Camping areas from the NPWS Visitor Area layer. No fees or facilities are filled in.

    The layer URL and the camping subtype come from the state config. Day use
    areas and cemeteries are a different subtype and are not requested.
    """
    src = (STATE.get("sources") or {}).get("npws_visitor_areas") or {}
    base = str(src.get("url") or "").strip()
    subtype = src.get("camping_subtype")
    if not base or subtype in (None, ""):
        return []
    import urllib.parse
    import build_osm
    found = []
    offset = 0
    key = src.get("key") or "npws_visitor_areas"
    source_id = src.get("source_id") or "npws"
    category_fallback = LABELS.get("park_category") or ""
    while True:
        query = urllib.parse.urlencode({
            "where": f"SubtypeCD={int(subtype)}",
            "outFields": "OBJECTID,SubtypeCD,SAPEquipID,SAPFLID,AssetName,AssetType,AssetStyle",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultOffset": str(offset),
            "resultRecordCount": "5000",
        })
        doc = fetch(key, base.rstrip("/") + "/query?" + query)
        features = (doc or {}).get("features") or []
        for feature in features:
            attrs = feature.get("attributes") or {}
            geom = feature.get("geometry") or {}
            name = str(attrs.get("AssetName") or "").strip()
            if not name or "x" not in geom or "y" not in geom:
                continue
            lon, lat = float(geom["x"]), float(geom["y"])
            if build_osm.in_state(lat, lon):
                print(f"NPWS point inside Victoria, skipped: {name}")
                continue
            style = _coded_label(src.get("asset_style"), attrs.get("AssetStyle"))
            kind = _coded_label(src.get("asset_type"), attrs.get("AssetType"))
            flid = str(attrs.get("SAPFLID") or "").strip()
            oid = attrs.get("OBJECTID")
            s = slug(name)
            if s in seen:
                tail = slug(flid) or (str(oid) if oid is not None else "npws")
                s = f"{s}-{tail}"[:90].strip("-")
            n = 2
            base_slug = s
            while s in seen:
                s = f"{base_slug}-{n}"
                n += 1
            seen.add(s)
            camp = {"slug": s, "id": oid if oid is not None else (flid or s), "name": name,
                "lat": round(lat, 6), "lon": round(lon, 6), "region": region(lon, lat),
                "status": "check", "closure": None, "access": "", "about": "", "camping": "", "caravans": "",
                "site_class": style, "dis_access": None, "managed_by": "", "data_date": "",
                "nearby_closures": [], "source": source_id, "category": style or category_fallback, "state_slug": SLUG,
                "needs_review": False}
            if style:
                camp["asset_style"] = style
            if kind:
                camp["asset_type"] = kind
            if flid:
                camp["source_ref"] = flid
            found.append(camp)
        if not features or not (doc or {}).get("exceededTransferLimit"):
            break
        offset += len(features)
        if offset > 20000:
            break
    print(f"NPWS camping areas: {len(found)}")
    return found

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
    path = statecfg.path(STATE, "enrichment")
    if not os.path.isfile(path): return {}
    with open(path, encoding="utf-8") as handle: doc = json.load(handle)
    camps = doc.get("camps") if isinstance(doc, dict) else None
    return camps if isinstance(camps, dict) else {}
def apply_datavic_enrichment(camps):
    """Fill display facts on DataVic camps. Never changes status or closure.

    A site that leaves the Recreation Sites feed is omitted with the rest of
    the build. Its overlay row is left in place and reported, not written back.
    """
    overlay = load_datavic_enrichment()
    applied = mismatches = 0
    present = set()
    for camp in camps:
        source_id = ((STATE.get("sources") or {}).get("recreation_sites") or {}).get("source_id")
        if camp.get("source") != source_id: continue
        camp_id = str(camp.get("id"))
        present.add(camp_id)
        extra = overlay.get(camp_id)
        if not isinstance(extra, dict): continue
        want = str(extra.get("slug") or "").strip()
        if want and want != camp.get("slug"):
            mismatches += 1
            print(f"WARN datavic enrichment slug {camp.get('id')}: built {camp.get('slug')} overlay {want}", file=sys.stderr)
        apply_row_facts(camp, extra)
        camp["enriched"] = True
        applied += 1
    gone = []
    for key, extra in overlay.items():
        if key in present or not isinstance(extra, dict): continue
        name = str(extra.get("name") or extra.get("slug") or key).strip()
        slug_name = str(extra.get("slug") or "").strip()
        label = f"{name} ({key})" if not slug_name or slug_name == name else f"{name} / {slug_name} ({key})"
        gone.append(label)
    if gone:
        print(f"WARN datavic enrichment: {len(gone)} overlay site(s) no longer in the feed, so no page was built: {', '.join(gone)}", file=sys.stderr)
    print(f"DataVic enrichment applied to {applied} camps, {mismatches} slug mismatches")
    return applied
def apply_closed_override(camp, row):
    """Mark one OSM camp closed from a manual Parks Victoria page note.

    Runs after apply_row_facts, which puts status and closure back. DataVic
    camps never come through here.
    """
    override = row.get("closed_override")
    if not isinstance(override, dict):
        return False
    source_url = str(override.get("source_url") or "").strip()
    wording = str(override.get("wording") or "").strip()
    if not source_url or not wording:
        return False
    until = str(override.get("until") or "").strip()
    if facts.override_expired(until, NOW.date().isoformat()):
        print(f"Closure override expired: {camp.get('name')} until {until}")
        return False
    camp["status"] = "closed"
    camp["closure"] = {
        "status": LABELS.get("closure_status") or "",
        "desc": wording,
        "reason": "",
        "start": None,
        "reopen": None,
        "outdated": False,
        "source_url": source_url,
        "checked": override.get("checked_date"),
    }
    return True
def load_osm(seen):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import build_osm
    path = statecfg.path(STATE, "osm_camps")
    if not path or not os.path.isfile(path):
        print("Closure overrides applied: 0")
        return []
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if isinstance(doc, dict): rows = doc.get("sites") or doc.get("camps") or []
    else: rows = doc
    corr_path = statecfg.path(STATE, "corrections")
    if corr_path:
        rows = build_osm.apply_corrections(rows, build_osm.load_corrections(corr_path))
    extra = []
    overrides = 0
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
            "nearby_closures": [], "source": "osm", "category": cat, "state_slug": SLUG,
            "needs_review": bool(row.get("needs_review"))}
        apply_row_facts(camp, row)
        if apply_closed_override(camp, row):
            overrides += 1
        if cat == "Free" and str(row.get("fee_type") or "").strip().lower() == "paid":
            camp["category"] = "Camping area"
            camp["site_class"] = "Camping area"
        if cat == PV_LABEL and not camp.get("phone"): camp["phone"] = LABELS.get("phone") or ""
        shown = strip_index_name(camp["name"])
        if shown != camp["name"]:
            # Slug stays on the original name so the old URL keeps working.
            camp["former_name"] = camp["name"]
            camp["name"] = shown
        extra.append(camp)
    print(f"Closure overrides applied: {overrides}")
    return extra
camps, seen, closures = [], set(), []
loaded = []
for state in statecfg.enabled():
    bind(state)
    CAT_LABEL["park_campground"] = PV_LABEL
    visitor = (STATE.get("sources") or {}).get("npws_visitor_areas") or {}
    if visitor.get("url") and visitor.get("camping_subtype") not in (None, ""):
        official, state_closures = load_npws(seen), []
    else:
        official, state_closures = load_official(seen)
    loaded.append((state, official, load_osm(seen), state_closures))
def assign_filters(camp):
    """Cost is the known fee. Type is the place filter, separate from the page label."""
    if camp.get("source") == "npws":
        camp["cost"] = ""
        camp["type_filter"] = LABELS.get("type_filter") or ""
        return camp
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
    elif cat in (LABELS.get("park_category") or "", PV_LABEL): camp["type_filter"] = LABELS.get("type_filter") or ""
    else: camp["type_filter"] = ""
    return camp
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
def assign_near_places(camps):
    """NSW camp pages name the nearest city or town, not a closer locality.

    The place file is official PlacePoint rows. Victoria has no file, so its
    pages are unchanged. A locality is used only when no city or town is
    within 40 km.
    """
    places_path = statecfg.path(STATE, "places")
    if not places_path or not os.path.isfile(places_path):
        return
    import towns as town_mod
    places = json.load(open(places_path, encoding="utf-8"))
    for camp in camps:
        name, dist = town_mod.nearest_label(camp["lat"], camp["lon"], places)
        if not name or name.casefold() == camp["name"].casefold():
            continue
        camp["near_place"] = name
        camp["near_km"] = round(dist, 1)
def assign_page_names(camps):
    """Duplicate names get a nearest-place subtitle so the title and h1 differ."""
    import towns as town_mod
    towns = town_mod.load(STATE["slug"])
    groups = {}
    for camp in camps:
        groups.setdefault(camp["name"].casefold(), []).append(camp)
    for group in groups.values():
        if len(group) < 2: continue
        choices = {id(camp): nearest_places(camp, towns) for camp in group}
        used = set()
        for camp in sorted(group, key=lambda camp: choices[id(camp)][0][0]):
            if camp.get("near_place"):
                place = camp["near_place"]
            else:
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
def disambiguate_names(group):
    """Duplicate names with no towns file keep the source id, which is a real field."""
    groups = {}
    for camp in group:
        groups.setdefault(camp["name"].casefold(), []).append(camp)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        for camp in rows:
            ref = str(camp.get("source_ref") or camp.get("id") or "").strip()
            if ref:
                camp["page_name"] = f"{camp['name']} ({ref})"
by_state = {}
for state, official, osm_rows, state_closures in loaded:
    bind(state)
    visitor = (state.get("sources") or {}).get("npws_visitor_areas") or {}
    if official and visitor.get("url"):
        import build_osm
        before = len(osm_rows)
        osm_rows = build_osm.dedupe_datavic(osm_rows, official)
        print(f"OSM camps near an NPWS point left out: {before - len(osm_rows)}")
    state_camps = official + osm_rows
    if statecfg.path(state, "enrichment"):
        apply_datavic_enrichment(state_camps)
    sources = state.get("sources") or {}
    if sources.get("npws_alerts_rss") or sources.get("rfs_fdr"):
        import nsw_conditions
        nsw_conditions.apply(state_camps, sources, fetch, fetch_text)
    for camp in state_camps:
        assign_filters(camp)
    town_path = statecfg.path(state, "towns")
    if town_path and os.path.isfile(town_path):
        assign_near_places(state_camps)
        assign_page_names(state_camps)
    else:
        disambiguate_names(state_camps)
    camps.extend(state_camps)
    closures.extend(state_closures)
    by_state[state["slug"]] = state_camps
camps.sort(key=lambda c: c["name"].lower())
for rows in by_state.values():
    rows.sort(key=lambda c: c["name"].lower())

# ---------- rendering ----------
CSS = """:root{--g:#2f5d3a;--o:#c2571a;--bg:#fbfaf6}*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:var(--bg)}
header{background:var(--g);color:#fff}.banner{max-width:1120px;margin:0 auto;padding:.45rem 1rem .35rem;display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-start;gap:.15rem 0}
.banner-row{display:flex;align-items:center;justify-content:flex-start;width:100%;min-width:0;flex:1 0 100%;flex-wrap:nowrap;gap:.25rem .5rem}
.brand{order:0;flex:0 0 auto;min-width:0;max-width:100%;color:#fff;text-decoration:none;font-weight:700;font-size:2.4rem;line-height:1.05;display:inline-flex;align-items:center;gap:.45rem;white-space:nowrap}
.logo{width:4.8rem;height:4.8rem;flex:0 0 auto;display:block;object-fit:contain}
nav{flex:1 1 auto;min-width:0;display:flex;flex-wrap:nowrap;justify-content:flex-start;align-items:center;gap:.3rem .85rem}
nav a{color:#e8f0e9;text-decoration:none;font-weight:400;font-size:.95rem;white-space:nowrap}
.digest-cta{order:2;margin-left:auto;flex:0 0 auto;display:inline-flex;align-items:center;gap:.32rem;background:#f6c445;color:#1a1208;text-decoration:none;font-weight:700;font-size:.76rem;line-height:1.1;padding:.32rem .6rem;border-radius:6px;white-space:nowrap;min-height:32px}
.digest-cta:hover{background:#ffd36a;color:#1a1208}
.digest-cta:focus-visible{outline:3px solid #fff;outline-offset:3px}
.digest-icon{display:block;flex:0 0 auto;width:14px;height:14px}
.digest-cta-short,.digest-cta-narrow{display:none}.digest-cta-mini{display:none}
.soon{margin:0;padding:6px 1rem;text-align:center;font-size:16px;font-weight:700;line-height:1.25;color:#fff;background:var(--o)}
.soon-sep{font-weight:700}
@media (max-width:720px){.soon{font-size:15px;padding:6px .5rem;white-space:nowrap}}
@media (max-width:360px){.soon{white-space:normal}}
@media (max-width:860px){.logo{width:clamp(2.9rem,15.9vw,4.8rem);height:clamp(2.9rem,15.9vw,4.8rem)}nav{gap:.2rem .55rem}nav a{font-size:clamp(.78rem,2.4vw,.95rem)}}
@media (max-width:720px){.banner{padding-left:.55rem;padding-right:.55rem}.brand{font-size:clamp(1.2rem,4.7vw,2.4rem);gap:.3rem}}
@media (max-width:640px){.digest-cta-long{display:none}.digest-cta-short{display:inline}}
@media (max-width:420px){.brand{font-size:clamp(1.12rem,5vw,1.35rem)}.digest-cta{padding:.2rem .4rem;gap:.2rem;min-height:0}.digest-cta-short{display:none}.digest-cta-narrow{display:inline}nav{gap:.12rem .32rem}nav a{font-size:.74rem}}
@media (max-width:370px){nav{gap:.1rem .26rem}nav a{font-size:.7rem}}
@media (max-width:359px){.digest-cta{padding:.1rem .28rem;gap:.12rem;font-size:.68rem}.digest-icon{width:12px;height:12px}.digest-cta-narrow{display:none}.digest-cta-mini{display:inline}}
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
.signup-row input[type=email]:focus{outline:3px solid var(--g);outline-offset:2px}
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
.filter-status{display:inline-flex;align-items:center;gap:.7rem;margin-left:.35rem}
.filter-status-rule{width:1px;height:1.35rem;background:#d4cfc3;flex:0 0 auto}
.filter-empty{background:#fff;border:1px solid #e3e0d6;border-radius:8px;padding:.75rem .9rem;margin:0 0 .8rem}
.filter-note{margin:0 0 .35rem;font-size:.85rem;color:#555}
.hide-closed{display:inline-flex;align-items:center;gap:.35rem;margin:0;min-height:44px;white-space:nowrap;font-weight:600}
.filter-panel .filter-row{display:flex;flex-direction:column}
.filter-panel .filter-row label{display:flex;align-items:center;gap:.4rem;margin:0;min-height:2.25rem;font-weight:500}
.filter-sheet-body{display:contents}
.filter-sheet-top,.filter-sheet-bottom{display:none}
.filter-backdrop{display:none;position:fixed;inset:0;z-index:640;width:100%;height:100%;margin:0;padding:0;border:0;background:rgba(17,24,16,.45);cursor:pointer;touch-action:manipulation}
.filter-backdrop[hidden]{display:none !important}
html.filters-locked,html.filters-locked body{overflow:hidden}
@media (max-width:640px){
  .filters-all{display:inline-flex;flex:0 0 auto}
  .finder{flex-wrap:nowrap}
  .filters{display:none}
  .filter-backdrop:not([hidden]){display:block}
  .finder.filters-open{z-index:650}
  .finder.filters-open .filters{display:flex;position:fixed;z-index:660;left:0;right:0;bottom:0;top:auto;max-height:80vh;overflow:hidden;flex-direction:column;align-items:stretch;gap:0;margin:0;padding:0;background:#fff;border:0;border-radius:14px 14px 0 0;box-shadow:0 -8px 28px rgba(0,0,0,.22);pointer-events:auto;touch-action:manipulation}
  .filter-pop .filter-btn{display:none}
  .filter-panel{position:static;box-shadow:none;border:0;padding:0 0 .35rem;min-width:0}
  .filter-panel-title{display:block}
  .filter-count{white-space:normal}
  .filter-status{display:flex;flex-direction:column;align-items:stretch;gap:.35rem;margin:.2rem 0 0;width:100%}
  .filter-status-rule{width:100%;height:1px}
  .filter-sheet-body{display:block;overflow:auto;-webkit-overflow-scrolling:touch;flex:1 1 auto;min-height:0;padding:.35rem .9rem .7rem}
  .filter-sheet-top,.filter-sheet-bottom{display:flex;flex:0 0 auto;align-items:center;background:#fff;z-index:2}
  .filter-sheet-top{position:sticky;top:0;justify-content:space-between;padding:.25rem .35rem .25rem .9rem;border-bottom:1px solid #e3e0d6}
  .filter-sheet-title{margin:0;font-weight:700;font-size:1.05rem}
  .filter-sheet-close{background:transparent;color:#222;border:0;box-shadow:none;width:44px;height:44px;padding:0;font-size:1.8rem;line-height:1;touch-action:manipulation}
  .filter-sheet-bottom{position:sticky;bottom:0;padding:.65rem .9rem calc(.65rem + env(safe-area-inset-bottom));border-top:1px solid #e3e0d6}
  .filter-done{width:100%;min-height:48px;background:var(--g);color:#fff;border:0;border-radius:8px;font-weight:700;font-size:1.05rem;touch-action:manipulation}
}
.pin{background:transparent;border:none}.pin span{display:block;width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.35)}
a.btn,a.btn-alert{display:inline-block;background:var(--o);color:#fff;text-decoration:none;font-weight:600;padding:.45rem .8rem;border-radius:6px}
a.btn-alert{background:#9a3412;font-weight:700;padding:.7rem 1rem;font-size:1.05rem}
.leaflet-popup-content a{color:var(--g);font-weight:600}
a.back-map{display:inline-flex;align-items:center;min-height:44px;margin:0 0 .35rem;padding:.35rem .8rem;background:#fff;color:var(--g);border:1px solid var(--g);border-radius:6px;font-weight:700;text-decoration:none}
a.back-map:focus-visible{outline:3px solid var(--g);outline-offset:2px}
.a2hs{position:fixed;z-index:30;left:50%;bottom:12px;transform:translateX(-50%);width:min(28rem,calc(100% - 1.5rem));display:flex;align-items:flex-start;gap:.35rem;background:#fff;color:#222;border:1px solid #d9d4c8;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.16);padding:.45rem .35rem .45rem .75rem;font-size:.85rem;line-height:1.35}
.a2hs[hidden]{display:none !important}
.a2hs p{margin:.35rem 0}
.a2hs button{flex:0 0 auto;background:transparent;color:#222;border:0;box-shadow:none;width:44px;height:44px;padding:0;font-size:1.5rem;line-height:1}
.share-btn{margin-left:auto;flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;gap:.2rem;background:transparent;color:#fff;border:1px solid rgba(255,255,255,.75);border-radius:5px;font-weight:700;font-size:.72rem;line-height:1.1;padding:.12rem .4rem;min-height:0;box-shadow:none;cursor:pointer}
.share-btn svg{display:block;flex:0 0 auto;width:11px;height:11px}
.share-btn:focus-visible{outline:3px solid #fff;outline-offset:2px}
.freshness{display:flex;flex-wrap:nowrap;align-items:center;justify-content:space-between;gap:.5rem;margin:0;padding:.15rem .75rem;background:#fff;border-bottom:1px solid #e3e0d6;font-size:.8rem;line-height:1.2;color:#222}
#updated-line{font-weight:700;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.refresh-btn{flex:0 0 auto;background:#fff;color:var(--g);border:1px solid var(--g);border-radius:5px;font-weight:700;font-size:.72rem;line-height:1.1;padding:.12rem .4rem;min-height:0;box-shadow:none;cursor:pointer}
.refresh-btn:focus-visible{outline:3px solid var(--g);outline-offset:2px}
html.standalone .freshness{position:sticky;top:0;z-index:45}
html.standalone .refresh-btn{background:var(--g);color:#fff}
footer{max-width:980px;margin:2rem auto;padding:1rem;font-size:.8rem;color:#555;border-top:1px solid #ddd}"""
SHARE_JS = r"""<script>
(function () {
  var btn = document.getElementById("share-page");
  if (!btn) return;
  function flash(message) {
    var label = btn.querySelector(".share-label");
    if (!label) return;
    var prev = label.textContent;
    label.textContent = message;
    btn.classList.add("share-done");
    setTimeout(function () {
      label.textContent = prev;
      btn.classList.remove("share-done");
    }, 1600);
  }
  function legacyCopy(url, done) {
    var area = document.createElement("textarea");
    area.value = url;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    document.body.removeChild(area);
    if (ok) done();
    else window.prompt("Copy this link", url);
  }
  function copyLink(url) {
    var done = function () { flash("Link copied"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(function () { legacyCopy(url, done); });
      return;
    }
    legacyCopy(url, done);
  }
  btn.addEventListener("click", function () {
    var canon = document.querySelector('link[rel="canonical"]');
    var url = (canon && canon.href) ? canon.href : String(location.href || "").split("#")[0];
    var payload = { title: document.title || "CampConditions.au", url: url };
    if (navigator.share) {
      navigator.share(payload).catch(function (err) {
        if (err && err.name === "AbortError") return;
        copyLink(url);
      });
      return;
    }
    copyLink(url);
  });
})();
</script>"""
STATE_PICK_CSS = """<style>
.state-pick{position:relative;flex:0 0 auto;margin:0;line-height:1}
.state-pick summary{list-style:none;cursor:pointer;color:#fff;font-weight:700;font-size:.95rem;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;gap:.28rem;min-height:44px;padding:0 .45rem;border:1px solid rgba(255,255,255,.85);border-radius:6px;background:rgba(255,255,255,.14)}
.state-pick summary::-webkit-details-marker{display:none}
.state-pick summary::marker{content:""}
.state-pick summary:focus-visible{outline:3px solid #fff;outline-offset:2px}
.state-caret{display:block;width:16px;height:16px;flex:0 0 auto;transition:transform .15s ease}
.state-pick[open] .state-caret{transform:rotate(180deg)}
.state-menu{position:absolute;z-index:40;left:0;top:calc(100% + .3rem);min-width:11.5rem;margin:0;padding:.2rem 0;background:#244a2e;border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,.28)}
.state-menu a{display:block;padding:.45rem .75rem;color:#fff;font-size:.95rem;white-space:nowrap}
.state-menu a[aria-current="page"]{font-weight:700}
@media (max-width:860px){.state-pick summary{font-size:clamp(.78rem,2.4vw,.95rem)}}
@media (max-width:420px){.state-pick summary{font-size:.74rem;padding:0 .32rem;gap:.16rem}.state-menu a{font-size:.9rem}}
@media (max-width:370px){.state-pick summary{font-size:.72rem;padding:0 .26rem}nav{gap:.08rem .16rem}}
@media (max-width:480px){.soon{white-space:normal}}
</style>"""
# Leaflet panes use z-index 1000, above the sheet's 660, so zoom and clusters paint
# through the open Filters panel. Injected only while more than one state is built,
# so the Victoria-only pages stay unchanged.
FILTER_COVER_CSS = """<style>
html.filters-locked .leaflet-control-container{display:none!important}
html.filters-locked .share-btn{visibility:hidden}
.finder.filters-open{z-index:2000}
.finder.filters-open .town-search,.finder.filters-open > .filters-all{visibility:hidden}
@media (max-width:640px){
.filter-backdrop:not([hidden]){z-index:1900}
.finder.filters-open .filters{z-index:2001;left:0;right:0;width:auto;max-width:none;margin:0;border-radius:0;box-sizing:border-box}
}
</style>"""
def state_nav(national=False):
    """One state keeps the plain link. Several states share a compact menu."""
    states = statecfg.enabled()
    if len(states) < 2:
        return "".join(f'<a href="/{state["slug"]}/">{state["name"]}</a>' for state in states)
    caret = ('<svg class="state-caret" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">'
             '<path d="M3.2 6.2 8 11l4.8-4.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    if national:
        options = "".join(f'<a href="/{state["slug"]}/">{e(state.get("name") or "")}</a>' for state in states)
        return (f'<details class="state-pick"><summary aria-label="All states">All '
                f'{caret}</summary><div class="state-menu">{options}</div></details>')
    current = next((state for state in states if state.get("slug") == SLUG), states[0])
    abbrev = current.get("abbrev") or current.get("name") or ""
    options = []
    for state in states:
        current_attr = ' aria-current="page"' if state.get("slug") == current.get("slug") else ""
        options.append(f'<a href="/{state["slug"]}/"{current_attr}>{e(state.get("name") or "")}</a>')
    label = e(current.get("name") or abbrev)
    return (f'<details class="state-pick"><summary aria-label="State: {label}">{e(abbrev)} '
            f'{caret}</summary>'
            f'<div class="state-menu">{"".join(options)}</div></details>')
def banner(on_home=False, national=False):
    href = "#newsletter" if on_home else "/#newsletter"
    states = statecfg.enabled()
    multi = len(states) > 1
    nav_links = state_nav(national)
    picker_css = (STATE_PICK_CSS + FILTER_COVER_CSS) if multi else ""
    cover = (STATE.get("banner") or {}).get("covering") or ""
    coming = (STATE.get("banner") or {}).get("coming") or ""
    soon = "" if multi else f"""<p class="soon"><span>{cover}</span><span class="soon-sep"> · </span><span>{coming}</span></p>"""
    return picker_css + f"""<header><div class="banner"><div class="banner-row"><a class="brand" href="/"><img class="logo" src="/assets/brand/logo-160.png" width="160" height="160" alt="CampConditions.au logo">CampConditions.au</a><a class="digest-cta" href="{href}" aria-label="Free weekly newsletter"><svg class="digest-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false"><path fill="currentColor" d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4-8 5L4 8V6l8 5 8-5z"/></svg><span class="digest-cta-long">Free weekly newsletter</span><span class="digest-cta-short">Free newsletter</span><span class="digest-cta-narrow">Newsletter</span><span class="digest-cta-mini">News</span></a></div><div class="banner-row"><nav>{nav_links}<a href="/#newsletter">Free digest</a><a href="/report/">Report conditions</a><a href="/about/">About</a></nav><button type="button" class="share-btn" id="share-page" aria-label="Share this page"><svg viewBox="0 0 24 24" width="11" height="11" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg><span class="share-label">Share</span></button></div></div></header>""" + soon + SHARE_JS
ICONS = """<link rel="icon" href="/assets/brand/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/assets/brand/favicon-32.png"><link rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png"><link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#113521">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="CampConditions.au">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta property="og:image" content="https://campconditions.au/assets/brand/og-image.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://campconditions.au/assets/brand/og-image.png">"""

def ld(obj): return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'
A2HS = """<div id="a2hs" class="a2hs" hidden><p id="a2hs-text"></p><button type="button" id="a2hs-dismiss" aria-label="Dismiss add to home screen tip">×</button></div>
<script>
(function () {
  var tip = document.getElementById("a2hs");
  if (!tip) return;
  var key = "campconditions-a2hs";
  try { if (localStorage.getItem(key) === "dismissed") return; } catch (err) { return; }
  if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true) return;
  var ua = navigator.userAgent || "";
  var iOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var android = /Android/i.test(ua);
  var text = "";
  if (iOS) text = "On iPhone or iPad: in Safari, tap Share, then Add to Home Screen.";
  else if (android) text = "On Android: in Chrome, tap the menu \\u22ee, then Add to Home screen or Install app.";
  else return;
  document.getElementById("a2hs-text").textContent = text;
  tip.hidden = false;
  document.getElementById("a2hs-dismiss").addEventListener("click", function () {
    tip.hidden = true;
    try { localStorage.setItem(key, "dismissed"); } catch (err) {}
  });
})();
</script>"""
STANDALONE_BOOT = """<script>try{if(window.matchMedia("(display-mode: standalone)").matches||window.navigator.standalone===true)document.documentElement.classList.add("standalone")}catch(e){}</script>"""
FRESH_BAR = f'<p class="freshness" id="freshness" role="status"><span id="updated-line">Updated {STAMP}</span><button type="button" class="refresh-btn" id="refresh-data" aria-label="Refresh camp data">Refresh</button></p>'
FRESH_JS = r"""<script>
(function () {
  var meta = document.querySelector('meta[name="campconditions-built"]');
  var embedded = meta ? meta.getAttribute("content") || "" : "";
  var line = document.getElementById("updated-line");
  var button = document.getElementById("refresh-data");
  var PV = "__PV_LABEL__";
  var appliedAt = 0;
  var lastStarted = 0;
  var inflight = null;
  function timeOf(value) {
    var t = Date.parse(value || "");
    return isNaN(t) ? 0 : t;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
    });
  }
  function melbourneStamp(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    try {
      var date = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", day: "numeric", month: "long", year: "numeric" }).format(d);
      var time = new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", hour: "numeric", minute: "2-digit", hour12: true }).format(d);
      time = time.replace(/\s*([ap])\.?m\.?$/i, function (_, ap) { return " " + ap.toUpperCase() + "M"; });
      var tz = "AEDT";
      new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", timeZoneName: "short" }).formatToParts(d).forEach(function (part) {
        if (part.type === "timeZoneName" && part.value) tz = part.value;
      });
      return date + ", " + time + " " + tz;
    } catch (err) {
      return "";
    }
  }
  function badgeText(c) {
    if (c.status === "closed") return "Closed";
    if (c.source === "osm" && c.category === "Showground") return "Call first";
    if (c.source === "osm" && c.category === PV) return "Book ahead";
    if (c.source === "osm") return "Check with operator";
    if (c.status === "check") return "Check conditions";
    return "No known issues";
  }
  function setBadge(el, c) {
    if (!el || !c || !c.status) return;
    el.className = "badge " + c.status;
    el.textContent = badgeText(c);
  }
  function listNote(c) {
    if (c.source === "osm") {
      if (c.status === "closed" && c.closure && c.closure.desc) return c.closure.desc;
      if (c.category === "Showground") return "Call first";
      if (c.category === PV) return "__BOOK_NOTE__";
      if (c.category === "Pub stay") return "Pub stay — check with the pub";
      return "Conditions: check with operator";
    }
    var desc = c.closure && c.closure.desc ? c.closure.desc : "";
    if (desc) return desc;
    if (c.nearby && c.nearby.length) return c.nearby.length + " road closures nearby";
    return "";
  }
  function closureHtml(c) {
    if (!c) return null;
    if (c.source === "osm") {
      var ov = c.closure || null;
      if (!ov || !ov.desc || !ov.source_url) return null;
      return '<div class="warn"><strong>Closed:</strong> ' + esc(ov.desc) + ' <a href="' + esc(ov.source_url) + '">' + esc(ov.source_url) + "</a></div>";
    }
    var parts = [];
    var cl = c.closure || null;
    if (cl) {
      var label = cl.desc || cl.reason || "Full closure";
      var reopen = cl.reopen ? " · Reopens " + esc(String(cl.reopen).slice(0, 10)) : " ";
      parts.push('<div class="warn"><strong>Closed:</strong> ' + esc(label) + reopen + "</div>");
      if (cl.outdated) parts.push('<div class="warn"><strong>This closure record may be outdated.</strong> The listed reopening date (' + esc(String(cl.reopen || "").slice(0, 10)) + ') has passed. Check <a href="__COC__">__CONDITIONS_NAME__</a> or call __PHONE__ before you go.</div>');
    }
    var nearby = c.nearby || [];
    if (nearby.length) {
      var items = nearby.map(function (x) {
        var bit = esc(x.type || "");
        if (x.name) bit += ": " + esc(x.name);
        if (x.reason) bit += " — " + esc(x.reason);
        if (x.reopens) bit += " · reopens " + esc(x.reopens);
        return "<li>" + bit + "</li>";
      }).join("");
      parts.push("<h2>Road and track closures within 5 km</h2><ul>" + items + "</ul>");
    }
    return parts.join("") || "<p>No closure is recorded for this campground, and no " + "road or track closures were found within 5 km.</p>";
  }
  function indexFeed(feed) {
    var map = {};
    (feed.camps || []).forEach(function (c) {
      if (!c || !c.slug) return;
      map[c.slug] = {
        status: c.status,
        note: c.closure && c.closure.outdated ? "Closure record may be outdated" : "",
        source: c.source,
        category: c.category,
        closure: c.closure || null,
        nearby: c.nearby_closures || [],
        region: c.region
      };
    });
    return map;
  }
  function slugFromUrl(url) {
    var match = String(url || "").match(/\/__SLUG__\/camp\/([^/]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }
  function readPoints() {
    var raw = document.getElementById("camp-map-data");
    if (!raw) return [];
    try { return JSON.parse(raw.textContent); } catch (err) { return []; }
  }
  function statusesDiffer(bySlug) {
    var points = readPoints();
    for (var i = 0; i < points.length; i++) {
      var fresh = bySlug[points[i].slug || slugFromUrl(points[i].url)];
      if (!fresh || !fresh.status) continue;
      if (fresh.status !== points[i].status) return true;
      if ((fresh.note || "") !== (points[i].note || "")) return true;
    }
    var camp = document.querySelector("[data-camp]");
    if (camp) {
      var live = bySlug[camp.getAttribute("data-camp")];
      var badge = camp.querySelector(".badge");
      if (live && badge && live.status && !badge.classList.contains(live.status)) return true;
    }
    return false;
  }
  function writePoints(bySlug) {
    var raw = document.getElementById("camp-map-data");
    if (!raw) return;
    var points = readPoints();
    points.forEach(function (p) {
      var fresh = bySlug[p.slug || slugFromUrl(p.url)];
      if (!fresh || !fresh.status) return;
      p.status = fresh.status;
      if (fresh.note) p.note = fresh.note;
      else delete p.note;
    });
    raw.textContent = JSON.stringify(points).replace(/</g, "\\u003c");
  }
  function patch(feed, bySlug) {
    var stamp = melbourneStamp(feed.generated) || feed.generated;
    if (line) line.textContent = "Updated " + stamp;
    var shell = document.getElementById("shell-built");
    if (shell) shell.textContent = stamp;
    var checked = document.getElementById("checked-line");
    if (checked) checked.textContent = "Checked " + stamp;
    document.querySelectorAll("[data-camp]").forEach(function (el) {
      setBadge(el.querySelector(".badge"), bySlug[el.getAttribute("data-camp")]);
    });
    document.querySelectorAll("tr[data-slug]").forEach(function (row) {
      var c = bySlug[row.getAttribute("data-slug")];
      if (!c) return;
      row.setAttribute("data-status", c.status || "");
      setBadge(row.querySelector(".camp-badge .badge"), c);
      var note = row.querySelector(".camp-note");
      if (note) note.textContent = listNote(c);
    });
    var closure = document.getElementById("camp-closure");
    var campEl = document.querySelector("[data-camp]");
    if (closure && campEl) {
      var html = closureHtml(bySlug[campEl.getAttribute("data-camp")]);
      if (html != null) closure.innerHTML = html;
    }
    var closedN = 0;
    var checkN = 0;
    var tally = {};
    (feed.camps || []).forEach(function (c) {
      if (c.status === "closed") closedN += 1;
      else if (c.status === "check") checkN += 1;
      var row = tally[c.region] || (tally[c.region] = { n: 0, closed: 0, check: 0 });
      row.n += 1;
      if (c.status === "closed") row.closed += 1;
      else if (c.status === "check") row.check += 1;
    });
    var closedEl = document.getElementById("count-closed");
    var checkEl = document.getElementById("count-check");
    if (closedEl) closedEl.textContent = closedN + " closed";
    if (checkEl) checkEl.textContent = checkN + " to check";
    document.querySelectorAll("[data-region]").forEach(function (card) {
      var row = tally[card.getAttribute("data-region")];
      var el = card.querySelector(".region-counts");
      if (!row || !el) return;
      el.textContent = row.n + " campgrounds · " + row.closed + " closed · " + row.check + " to check";
    });
    writePoints(bySlug);
    window.__campStatusPending = bySlug;
    if (window.campApplyStatus) window.campApplyStatus(bySlug);
    if (meta && feed.generated) meta.setAttribute("content", feed.generated);
    embedded = feed.generated || embedded;
  }
  function applyFeed(feed) {
    window.__campPatched = false;
    if (!feed || !feed.generated) return false;
    var next = timeOf(feed.generated);
    if (next && appliedAt && next < appliedAt) return false;
    var bySlug = indexFeed(feed);
    var embeddedTime = timeOf(embedded);
    var newer = !!(next && (!embeddedTime || next > embeddedTime + 999));
    var older = !!(next && embeddedTime && next + 999 < embeddedTime);
    if (older) return false;
    if (!(newer || statusesDiffer(bySlug))) return false;
    if (next) appliedAt = next;
    patch(feed, bySlug);
    window.__campPatched = true;
    return true;
  }
  function loadStatus(force) {
    var now = Date.now();
    if (!force && inflight) return inflight;
    if (!force && now - lastStarted < 2000) return inflight || Promise.resolve(window.__campFeed || null);
    lastStarted = now;
    var run = fetch("/status.json?v=" + now, {
      cache: "no-store",
      headers: { accept: "application/json", "cache-control": "no-cache", pragma: "no-cache" }
    }).then(function (res) {
      if (!res.ok) throw new Error("status");
      return res.json();
    }).then(function (feed) {
      window.__campFeed = feed;
      applyFeed(feed);
      return feed;
    }).catch(function () {
      return null;
    }).finally(function () {
      if (inflight === run) inflight = null;
    });
    inflight = run;
    return run;
  }
  loadStatus(false);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") loadStatus(false);
  });
  window.addEventListener("pageshow", function () {
    if (document.visibilityState !== "hidden") loadStatus(false);
  });
  if (button) {
    button.addEventListener("click", function () {
      button.disabled = true;
      button.textContent = "Refreshing";
      loadStatus(true).then(function (feed) {
        button.textContent = !feed ? "Retry" : (window.__campPatched ? "Refreshed" : "Up to date");
      }).then(function () {
        setTimeout(function () {
          button.disabled = false;
          button.textContent = "Refresh";
        }, 1400);
      });
    });
  }
})();
</script>""".replace("__PV_LABEL__", PV_LABEL).replace("__BOOK_NOTE__", LABELS.get("book_ahead_note") or "").replace("__COC__", LINKS.get("conditions") or "").replace("__CONDITIONS_NAME__", LINKS.get("conditions_name") or "").replace("__PHONE__", LABELS.get("phone") or "").replace("__SLUG__", SLUG)
def footer_credits(shared=False):
    """State data credits. Shared pages list every enabled state."""
    blocks = [f"<p>{e(CREDIT)}</p>", COPY.get("footer_attribution") or ""]
    if shared and len(statecfg.enabled()) > 1:
        current = STATE.get("slug") if STATE else ""
        for state in statecfg.enabled():
            if state.get("slug") == current:
                continue
            credit = state.get("credit") or ""
            other = (state.get("copy") or {}).get("footer_attribution") or ""
            if credit:
                blocks.append(f"<p>{e(credit)}</p>")
            if other:
                blocks.append(other)
    return "\n".join(block for block in blocks if block)
def footer(shared=False):
    return f"""<footer>{footer_credits(shared)}
<p>Site built <span id="shell-built">{STAMP}</span>. Conditions change quickly; information is provided as is without warranty. © CampConditions.au · <a href="/about/">About</a> · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a> · <a href="/status.json">JSON feed</a> · <a href="/llms.txt">llms.txt</a></p></footer>
{A2HS}
{FRESH_JS}"""
def vicemergency_url(lat, lon, name="", slug=""):
    # Verified against the respond app: ?bbox= is Leaflet toBBoxString order (west,south,east,north) and fitBounds centres the map on that box.
    base = LINKS.get("emergency") or ""
    if LINKS.get("emergency_fdr"):
        # The RFS fire danger map reads fullAddress, lat, lng and placeId together, then centres at zoom 8. Fires Near Me ignores location parameters.
        query = urllib.parse.urlencode({
            "fullAddress": name or "Camp",
            "lat": lat,
            "lng": lon,
            "placeId": slug or "camp",
        })
        return "https://www.rfs.nsw.gov.au/fire-information/fdr-and-tobans?" + query
    if LINKS.get("emergency_bbox") is False:
        return base
    pad = 0.2
    west, south, east, north = lon - pad, lat - pad, lon + pad, lat + pad
    return f"{base}?bbox={west:.5f},{south:.5f},{east:.5f},{north:.5f}"
def vicemergency_button(c):
    return f'<p><a class="btn-alert" href="{e(vicemergency_url(c["lat"], c["lon"], c.get("page_name") or c.get("name") or "", c.get("slug") or ""))}">{LINKS.get("emergency_button") or ""}</a></p>'
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
def map_script_src():
    """Victoria keeps /map.js. Each other built state has its own town search."""
    slug = STATE.get("slug") or ""
    if slug and slug != primary["slug"]:
        return f"/map-{slug}.js"
    return "/map.js"
def leaflet_foot(cluster=False):
    return LEAFLET_JS + (CLUSTER_JS if cluster else "") + f'<script src="{map_script_src()}" defer></script>'
def camp_url(c):
    return f"/{c.get('state_slug') or SLUG}/camp/{c['slug']}/"
def report_href(c):
    return "/report/?" + urllib.parse.urlencode({"camp": c["slug"], "name": c.get("name") or ""})
def region_label(c):
    slug = c.get("state_slug") or SLUG
    names = region_label.cache.get(slug)
    if names is None:
        names = {key: name for key, name, _blurb in statecfg.regions(statecfg.by_slug(slug))}
        region_label.cache[slug] = names
    return names.get(c.get("region") or "", "")
region_label.cache = {}
def map_points(items):
    pts = []
    for c in items:
        cl = c.get("closure") or {}
        pt = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "status": c["status"], "url": camp_url(c), "slug": c["slug"], "cat": c.get("category") or "", "type": c.get("type_filter") or "", "cost": c.get("cost") or ""}
        if cl.get("outdated"): pt["note"] = "Closure record may be outdated"
        if len(statecfg.enabled()) > 1:
            slug = c.get("state_slug") or SLUG
            pt["stateName"] = {"vic": "Victoria", "nsw": "New South Wales"}.get(slug, slug)
        if (c.get("state_slug") or SLUG) == "nsw":
            label = region_label(c)
            if label:
                pt["reg"] = label
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
def filters_html(items, types=None):
    costs = (("free", "Known to be free/donation"), ("paid", "Known to be paid"))
    if types is None:
        types = ("Showground", "Council", "Rest area", LABELS.get("type_filter") or "")
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
    return f'''<button type="button" id="filter-backdrop" class="filter-backdrop" hidden aria-label="Close filters"></button><div class="finder"><div class="town-search"><label class="sr" for="town-search">Search by town or camp name</label><div class="town-row"><input id="town-search" type="search" role="combobox" placeholder="Search by town or camp name" autocomplete="off" enterkeyhint="search" aria-autocomplete="list" aria-haspopup="listbox" aria-controls="town-suggest" aria-expanded="false"><button type="button" id="town-clear" hidden>Clear</button></div><ul id="town-suggest" role="listbox" aria-label="Towns and camps" hidden></ul></div>
<button type="button" class="filter-btn filters-all" id="filters-all" aria-expanded="false" aria-controls="camp-filters"><span class="filter-btn-label">Filters</span></button>
<div class="filters" id="camp-filters"><div class="filter-sheet-top"><p class="filter-sheet-title" id="filter-sheet-title">Filters</p><button type="button" class="filter-sheet-close" id="filter-sheet-close" aria-label="Close filters">×</button></div><div class="filter-sheet-body">{pop("cost", "Cost", cost_panel)}{pop("type", "Type", type_panel)}{pop("facilities", "Facilities", fac_panel)}<div class="filter-status"><label class="hide-closed"><input type="checkbox" data-flag="hide-closed"> Hide closed</label><span class="filter-status-rule" aria-hidden="true"></span><p id="filter-count" class="filter-count" aria-live="polite">Showing {total} of {total} camps</p></div></div><div class="filter-sheet-bottom"><button type="button" class="filter-done" id="filter-done">Show {total} camps</button></div></div></div>
<div id="town-results" aria-live="polite"></div>'''
def map_points_href(key, items):
    """Write map points beside the HTML so the page itself stays small."""
    rel = f"map-points/{key}.json"
    dest = os.path.join(OUT, "map-points", f"{key}.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w", encoding="utf-8").write(map_points(items))
    return f"/{rel}?v={MAP_V}"
def map_block(items, label, small=False, types=None, external=None):
    cls = "map map-sm" if small else "map"
    legend = "" if small else LEGEND
    tools = "" if small else filters_html(items, types)
    empty = "" if small else '<p id="filter-empty" class="filter-empty" hidden>No camps match these filters. <a href="#camp-filters" id="filter-clear">Clear filters</a></p>'
    if external and not small:
        href = e(map_points_href(external, items))
        data = f'<script type="application/json" id="camp-map-data" data-url="{href}"></script>'
    else:
        data = f'<script type="application/json" id="camp-map-data">{map_points(items)}</script>'
    return f'{tools}{empty}<div id="camp-map" class="{cls}" role="region" aria-label="{e(label)}"></div>{legend}{data}'
def directions(c):
    url = f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lon']}"
    # toiletmap.gov.au centres a map only for a facility id (/123) or a saved custom map.
    # lat/lng query strings are ignored, so this opens the Toilet Map home page.
    toilets = "https://toiletmap.gov.au/"
    # traffic.vicroads.vic.gov.au does not resolve. The live VicTraffic map is
    # traffic.transport.vic.gov.au. Its app reads a disruption id query only,
    # not lat/lng or zoom, so this opens the main map.
    roads = LINKS.get("roads") or ""
    road_label = "Check Live Traffic NSW" if (LINKS.get("roads_name") or "") == "Live Traffic NSW" else "Check road closures"
    return (f'<p><a class="btn" href="{e(url)}">Directions in Google Maps</a> '
            f'<a class="btn" href="{toilets}" target="_blank" rel="noopener noreferrer">Find nearby toilets</a> '
            f'<a class="btn" href="{roads}" target="_blank" rel="noopener noreferrer">{road_label}</a></p>'
            f'<p class="muted">{COPY.get("directions_note") or ""}</p>')
MAP_JS = r"""(function () {
  var el = document.getElementById("camp-map");
  var raw = document.getElementById("camp-map-data");
  if (!el || !raw || typeof L === "undefined") return;
  function boot(data) {
  if (!data || !data.map) return;
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
  function slugOf(p) {
    if (p.slug) return p.slug;
    var m = String(p.url || "").match(/\/vic\/camp\/([^/]+)/);
    return m ? m[1] : "";
  }
  function applyLiveStatus(bySlug) {
    if (!bySlug) return;
    data.forEach(function (p, i) {
      var fresh = bySlug[slugOf(p)];
      if (!fresh || !fresh.status) return;
      var note = fresh.note || "";
      if (p.status === fresh.status && (p.note || "") === note) return;
      p.status = fresh.status;
      if (note) p.note = note;
      else delete p.note;
      var marker = markers[i];
      if (!marker) return;
      marker.setIcon(icon(p.status));
      marker.setPopupContent(popup(p));
      var title = p.name + (p.note ? " — " + p.note : "");
      marker.options.title = title;
      var node = marker.getElement && marker.getElement();
      if (node) node.setAttribute("title", title);
    });
    document.querySelectorAll("#camp-list tbody tr[data-slug]").forEach(function (row) {
      var fresh = bySlug[row.getAttribute("data-slug")];
      if (fresh && fresh.status) row.setAttribute("data-status", fresh.status);
    });
    if (group) redraw(false);
  }
  window.campApplyStatus = applyLiveStatus;
  if (window.__campStatusPending) applyLiveStatus(window.__campStatusPending);
  if (small || typeof L.markerClusterGroup !== "function") {
    markers.forEach(function (m) { m.addTo(map); });
    if (markers.length === 1) map.setView([data[0].lat, data[0].lon], 13);
    else if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.08));
    else map.setView([__MAP_LAT__, __MAP_LON__], __MAP_ZOOM__);
    return;
  }
  var group = L.markerClusterGroup(__CLUSTER__);
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
    var done = document.getElementById("filter-done");
    if (done) done.textContent = "Show " + formatCount(shownCount) + (shownCount === 1 ? " camp" : " camps");
    refreshFilterButtons();
  }
  function redraw(fit) {
__REDRAW_BODY__
  }
  function loadTowns() {
    if (towns) return Promise.resolve(towns);
    if (!townsPromise) {
      townsPromise = fetch("__TOWNS_URL__").then(function (r) { return r.json(); }).then(function (rows) {
        towns = rows;
        __AFTER_TOWNS__
      });
    }
    return townsPromise;
  }
  function fold(s) {
    return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
  }
__REGION_FN__
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
__NEAREST_FN__
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
    bits.push(__REGION_BIT__);
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
  function revealMap() {
    var mapEl = document.getElementById("camp-map");
    if (!mapEl) return;
    var rect = mapEl.getBoundingClientRect();
    var visible = Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0);
    if (visible < Math.min(rect.height, window.innerHeight) * 0.45) mapEl.scrollIntoView({ block: "center" });
    var campMap = mapEl._campMap;
    if (campMap && campMap.invalidateSize) {
      campMap.invalidateSize();
      setTimeout(function () { campMap.invalidateSize(); }, 200);
    }
  }
  function closeFilterMenus(restore) {
    var finder = document.querySelector(".finder");
    var wasPhoneSheet = phoneLayout() && finder && finder.classList.contains("filters-open");
    document.querySelectorAll(".filter-pop .filter-btn").forEach(function (btn) {
      btn.setAttribute("aria-expanded", "false");
      var panel = document.getElementById(btn.getAttribute("aria-controls"));
      if (panel && !phoneLayout()) panel.hidden = true;
    });
    var allBtn = document.getElementById("filters-all");
    var backdrop = document.getElementById("filter-backdrop");
    if (finder) finder.classList.remove("filters-open");
    if (allBtn) allBtn.setAttribute("aria-expanded", "false");
    if (backdrop) backdrop.hidden = true;
    document.documentElement.classList.remove("filters-locked");
    if (wasPhoneSheet) revealMap();
    if (restore && restore.focus) restore.focus();
  }
  function openPhoneSheet() {
    var finder = document.querySelector(".finder");
    var backdrop = document.getElementById("filter-backdrop");
    if (finder) finder.classList.add("filters-open");
    if (allFilters) allFilters.setAttribute("aria-expanded", "true");
    if (backdrop) backdrop.hidden = false;
    document.documentElement.classList.add("filters-locked");
    document.querySelectorAll(".filter-panel").forEach(function (panel) { panel.hidden = false; });
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
    allFilters.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var finder = document.querySelector(".finder");
      var willOpen = finder && !finder.classList.contains("filters-open");
      closeFilterMenus();
      if (willOpen) openPhoneSheet();
    });
  }
  function dismissPhoneSheet(ev) {
    if (ev.type === "touchend") ev.preventDefault();
    ev.stopPropagation();
    closeFilterMenus(allFilters);
  }
  ["filter-done", "filter-sheet-close", "filter-backdrop"].forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("touchend", dismissPhoneSheet, { passive: false });
    el.addEventListener("click", dismissPhoneSheet);
  });
  document.addEventListener("click", function (ev) {
    if (phoneLayout()) {
      if (ev.target.closest("#camp-filters") || ev.target.closest("#filters-all") || ev.target.closest("#filter-backdrop")) return;
      closeFilterMenus();
      return;
    }
    if (ev.target.closest(".filter-btn") || ev.target.closest(".filter-panel") || ev.target.closest(".hide-closed")) return;
    closeFilterMenus();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    var open = document.querySelector(".filter-pop .filter-btn[aria-expanded='true']");
    if (open && !phoneLayout()) { closeFilterMenus(open); return; }
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
  }
  var pointsUrl = raw.getAttribute("data-url");
  if (pointsUrl) {
    fetch(pointsUrl, { headers: { accept: "application/json" } }).then(function (res) {
      if (!res.ok) throw new Error("map");
      return res.json();
    }).then(boot).catch(function () {});
  } else {
    try { boot(JSON.parse(raw.textContent)); } catch (err) {}
  }
})();
"""
def external_blank(html):
    def repl(m):
        tag = m.group(0)
        if "target=" in tag: return tag
        return tag[:-1] + ' target="_blank" rel="noopener noreferrer">'
    return re.sub(r'<a\b[^>]*\bhref="https?://[^"]*"[^>]*>', repl, html)
def page(path, title, desc, body, extra_ld=(), head="", foot="", on_home=None):
    canon = SITE + path
    built = NOW.isoformat()
    if on_home is None:
        on_home = path == "/"
    national = bool(on_home and path == "/" and len(statecfg.enabled()) > 1)
    shared = len(statecfg.enabled()) > 1 and path in {"/", "/about/", "/privacy/", "/report/", "/terms/", "/unsubscribe/"}
    h = f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="msvalidate.01" content="9B5113D2D0D8C52837F0DC893FCA3616" />
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{canon}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{canon}"><meta property="og:type" content="website"><meta property="og:locale" content="en_AU">
{ICONS}
<meta name="campconditions-built" content="{built}">
{STANDALONE_BOOT}
<link rel="alternate" type="application/json" href="/status.json" title="Campground status feed"><style>{CSS}</style>{head}{''.join(ld(x) for x in extra_ld)}</head><body>
{banner(on_home, national)}
{FRESH_BAR}
<main>{body}</main>{footer(shared)}{foot}</body></html>"""
    h = external_blank(h)
    fp = os.path.join(OUT, path.lstrip("/"), "index.html") if path.endswith("/") else os.path.join(OUT, path.lstrip("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "w", encoding="utf-8").write(h)
def badge(c):
    if isinstance(c, str):
        status, text = c, {"open": "No known issues", "closed": "Closed", "check": "Check conditions"}[c]
    else:
        status = c["status"]
        if status == "closed": text = "Closed"
        elif c.get("source") == "osm" and c.get("category") == "Showground": text = "Call first"
        elif c.get("source") == "osm" and c.get("category") == PV_LABEL: text = "Book ahead"
        elif c.get("source") == "osm": text = "Check with operator"
        else: text = {"open": "No known issues", "closed": "Closed", "check": "Check conditions"}[status]
    return f'<span class="badge {status}">{text}</span>'
def crumbs(items): return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": i+1, "name": n, "item": SITE+u} for i, (n, u) in enumerate(items)]}
NEWS = """<section class="box" id="newsletter"><h2>__NEWSLETTER_H2__</h2><p>Every Thursday: what's closed, which roads are shut, and what campers are reporting — region by region. We'll email a confirmation link first; you're not on the list until you click it.</p>
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
<script>
(function () {
  const email = document.getElementById("digest-email");
  const box = document.getElementById("newsletter");
  if (!email || !box) return;
  const openDigest = () => {
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    email.focus({ preventScroll: true });
  };
  document.querySelectorAll("a.digest-cta").forEach((link) => {
    if (link.getAttribute("href") !== "#newsletter") return;
    link.addEventListener("click", (ev) => {
      ev.preventDefault();
      if (location.hash !== "#newsletter") history.pushState(null, "", "#newsletter");
      openDigest();
    });
  });
  if (location.hash === "#newsletter") openDigest();
})();
</script>
</section>"""
def news_section(heading=None):
    title = (COPY.get("newsletter_h2") or "") if heading is None else heading
    html_form = NEWS.replace("__NEWSLETTER_H2__", title)
    if len(statecfg.enabled()) < 2:
        return html_form
    boxes = []
    for state in statecfg.enabled():
        picked = state.get("slug") == ("nsw" if SLUG == "nsw" else "vic")
        checked = " checked" if picked else ""
        boxes.append(
            '<label style="display:inline-flex;align-items:center;gap:.35rem;font-weight:700;min-height:44px;margin:0">'
            f'<input type="checkbox" name="states" value="{e(state["slug"])}"{checked} style="width:1.15rem;height:1.15rem;margin:0"> {e(state.get("abbrev") or state["name"])}</label>'
        )
    field = (
        '<fieldset style="border:0;margin:0 0 .45rem;padding:0;display:flex;flex-wrap:wrap;gap:.15rem .85rem;align-items:center">'
        '<legend style="font-weight:700;padding:0;margin:0 .35rem 0 0">States</legend>'
        + "".join(boxes)
        + '<input type="hidden" name="choose_states" value="1"></fieldset>'
    )
    return html_form.replace('<label for="digest-email">Your email</label>', field + '<label for="digest-email">Your email</label>', 1)

shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
primary = next(state for state in statecfg.enabled() if state.get("enabled"))
bind(primary)
VIC_NEAREST_FN = """  function nearestTown(lat, lon) {
    if (!towns || !towns.length) return null;
    var best = null, bestD = Infinity, i, d;
    for (i = 0; i < towns.length; i++) {
      d = kmBetween(lat, lon, towns[i].lat, towns[i].lon);
      if (d < bestD) { bestD = d; best = towns[i]; }
    }
    return best;
  }"""
NSW_NEAREST_FN = """  var places = null;
  function nearestTown(lat, lon) {
    var rows = (places && places.length) ? places : (towns || []);
    if (!rows.length) return null;
    var bestTown = null, bestTownD = Infinity, best = null, bestD = Infinity, i, d, row;
    for (i = 0; i < rows.length; i++) {
      row = rows[i];
      d = kmBetween(lat, lon, row.lat, row.lon);
      if (d < bestD) { bestD = d; best = row; }
      if ((row.place === "city" || row.place === "town") && d < bestTownD) { bestTownD = d; bestTown = row; }
    }
    if (bestTown && bestTownD <= 40) return bestTown;
    return best;
  }"""
NSW_AFTER_TOWNS = """return fetch("__PLACES_URL__").then(function (r) { return r.json(); }).then(function (labelRows) {
          places = labelRows;
          return towns;
        }, function () { return towns; });"""
REDRAW_BODY = """    group.clearLayers();
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
    } else if (!shownCount) map.setView([__MAP_LAT__, __MAP_LON__], __MAP_ZOOM__);"""
HOME_REDRAW_BODY = """    group.clearLayers();
    var shown = [];
    var shownCount = 0;
    data.forEach(function (p, i) {
      if (!matches(p)) return;
      shown.push(markers[i]);
      shownCount += 1;
    });
    document.querySelectorAll("#camp-list tbody tr[data-url]").forEach(function (row) {
      row.hidden = !matches(row.dataset);
    });
    updateFilterStatus(shownCount);
    if (picked) showNearest();
    if (!shownCount) {
      map.setView([__MAP_LAT__, __MAP_LON__], __MAP_ZOOM__);
      return;
    }
    if (fit && !picked) {
      try {
        map.fitBounds(L.latLngBounds(shown.map(function (marker) { return marker.getLatLng(); })).pad(0.08));
      } catch (err) {}
    }
    group.addLayers(shown);"""
def render_map_js(cluster="{showCoverageOnHover: false, maxClusterRadius: 42}", region_bit="regionName(camp.lat, camp.lon)", redraw_body=None, after=None, towns_url=None, lat=None, lon=None, zoom=None, nearest=None):
    fallback = STATE.get("map") or {}
    if lat is None: lat = fallback.get("fallback_lat")
    if lon is None: lon = fallback.get("fallback_lon")
    if zoom is None: zoom = fallback.get("fallback_zoom")
    if towns_url is None: towns_url = statecfg.public_file(STATE, "towns")
    if redraw_body is None: redraw_body = REDRAW_BODY
    if after is None or nearest is None:
        places_url = statecfg.public_file(STATE, "places")
        if places_url:
            nearest, after = NSW_NEAREST_FN, NSW_AFTER_TOWNS.replace("__PLACES_URL__", places_url)
        else:
            nearest, after = VIC_NEAREST_FN, "return rows;"
    return (MAP_JS
        .replace("__REDRAW_BODY__", redraw_body)
        .replace("__TOWNS_URL__", towns_url)
        .replace("__REGION_FN__", statecfg.js_region_function(STATE))
        .replace("__MAP_LAT__", str(lat))
        .replace("__MAP_LON__", str(lon))
        .replace("__MAP_ZOOM__", str(zoom))
        .replace("__AFTER_TOWNS__", after)
        .replace("__NEAREST_FN__", nearest)
        .replace("__CLUSTER__", cluster)
        .replace("__REGION_BIT__", region_bit))
def home_town_after():
    """Victoria's town file is fetched first. Other states are appended and tagged."""
    urls, tags = [], []
    for state in statecfg.enabled():
        if state["slug"] == primary["slug"]:
            continue
        url = statecfg.public_file(state, "towns")
        if not url:
            continue
        urls.append(url)
        tags.append(state.get("abbrev") or state["name"])
    fetches = ", ".join(
        'fetch("%s").then(function (r) { return r.json(); }, function () { return []; })' % url
        for url in urls
    )
    return (
        "var tags = %s;\n"
        "        return Promise.all([%s]).then(function (lists) {\n"
        "          lists.forEach(function (list, i) {\n"
        "            (list || []).forEach(function (town) {\n"
        "              var copy = {}, key;\n"
        "              for (key in town) if (Object.prototype.hasOwnProperty.call(town, key)) copy[key] = town[key];\n"
        "              if (tags[i]) copy.place = copy.place ? (copy.place + \" \\u00b7 \" + tags[i]) : tags[i];\n"
        "              rows.push(copy);\n"
        "            });\n"
        "          });\n"
        "          towns = rows;\n"
        "          return rows;\n"
        "        });" % (json.dumps(tags, ensure_ascii=False), fetches)
    )
def write_map_js(state):
    bind(state)
    name = "map.js" if state["slug"] == primary["slug"] else f"map-{state['slug']}.js"
    bit = "camp.reg || regionName(camp.lat, camp.lon)" if state["slug"] == "nsw" else "regionName(camp.lat, camp.lon)"
    open(os.path.join(OUT, name), "w", encoding="utf-8").write(render_map_js(region_bit=bit))
def write_home_map_js():
    """One map script for the national page. /map.js stays the Victorian search."""
    bind(primary)
    script = render_map_js(
        cluster="{showCoverageOnHover: false, maxClusterRadius: 42, chunkedLoading: true, chunkInterval: 40, chunkDelay: 16}",
        region_bit="camp.stateName || regionName(camp.lat, camp.lon)",
        redraw_body=HOME_REDRAW_BODY,
        after=home_town_after(),
        towns_url=statecfg.public_file(primary, "towns"),
        lat=-35.2,
        lon=146.2,
        zoom=5,
        nearest=VIC_NEAREST_FN,
    )
    open(os.path.join(OUT, "map-home.js"), "w", encoding="utf-8").write(script)
write_map_js(primary)
for state in statecfg.enabled():
    if state["slug"] != primary["slug"]:
        write_map_js(state)
bind(primary)
shutil.copytree(os.path.join(ROOT, "assets", "brand"), os.path.join(OUT, "assets", "brand"))
shutil.copyfile(os.path.join(ROOT, "assets", "brand", "site.webmanifest"), os.path.join(OUT, "site.webmanifest"))
by_reg = {k: [c for c in camps if c["region"] == k] for k in REGIONS}
n_closed = sum(c["status"] == "closed" for c in camps); n_check = sum(c["status"] == "check" for c in camps)

def list_note(c):
    if c.get("source") == "osm":
        if c.get("status") == "closed" and (c.get("closure") or {}).get("desc"):
            return c["closure"]["desc"]
        if c.get("alerts"):
            return c["alerts"][0].get("heading") or ""
        if c.get("category") == "Showground": return "Call first"
        if c.get("category") == PV_LABEL: return LABELS.get("book_ahead_note") or ""
        if c.get("category") == "Pub stay": return "Pub stay — check with the pub"
        return "Conditions: check with operator"
    desc = (c.get("closure") or {}).get("desc") or ""
    if desc: return desc
    if c.get("alerts"):
        return c["alerts"][0].get("heading") or ""
    if c["nearby_closures"]: return f"{len(c['nearby_closures'])} road closures nearby"
    return ""
def fire_line(c):
    """One sentence for the camp's fire weather district. Absent unless the feed matched a polygon."""
    fire = c.get("fire") or {}
    district, today, ban = fire.get("district") or "", fire.get("today") or "", fire.get("ban_today") or ""
    url = fire.get("source_url") or ""
    if not district or not today or not ban or not str(url).startswith("https://"):
        return ""
    sentence = f"{district}: {today} today"
    if fire.get("tomorrow"):
        sentence += f", {fire['tomorrow']} tomorrow"
    sentence += f". Total fire ban: {ban}."
    return '<h2 class="fire-head" style="font-size:.95rem;line-height:1.25;margin:.45rem 0 0">Fire Ratings</h2>' + f'<p class="muted fire-line" style="margin:.05rem 0 .55rem">{e(sentence)}</p>'
def official_npws_closure(desc, url, published):
    """Quoted NPWS alert text, labelled, with the feed date when the item has one."""
    when = feed_date(published)
    dated = f" Alert dated {e(when)}." if when else ""
    link = f' <a href="{e(url)}">NPWS alert</a>' if str(url).startswith("https://") else ""
    return f'<div class="warn"><strong>Closed:</strong> {e(desc)} <span class="muted">Official NPWS wording.{dated}</span>{link}</div>'
def alert_notes_html(c):
    rows, seen = [], set()
    for alert in c.get("alerts") or []:
        heading = str(alert.get("heading") or "").strip()
        if not heading or (c.get("status") == "closed" and heading.lower().startswith("closed parks")):
            continue
        key = heading.casefold()
        if key in seen:
            continue
        seen.add(key)
        url = str(alert.get("url") or "")
        when = feed_date(alert.get("published"))
        dated = f" ({e(when)})" if when else ""
        rows.append((f'<a href="{e(url)}">{e(heading)}</a>' if url.startswith("https://") else e(heading)) + dated)
    if not rows:
        return ""
    return '<p class="muted">Official NPWS wording. NPWS alerts: ' + "; ".join(rows) + ".</p>"
def row_attrs(c):
    return (f'data-slug="{e(c["slug"])}" data-url="{camp_url(c)}" data-type="{e(c.get("type_filter") or "")}" data-cost="{e(c.get("cost") or "")}" data-status="{e(c["status"])}" '
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
        phone = c.get("phone") or LABELS.get("phone") or ""
        bits = [f'<p><strong>{e(PV_LABEL)}.</strong> {LABELS.get("book_ahead_with") or ""} on <a href="{e(tel_href(phone))}">{e(phone)}</a>.</p>']
    elif c.get("category") == "Pub stay":
        bits = ["<p><strong>Pub stay.</strong> Conditions: check with operator.</p>"]
    else:
        bits = ["<p><strong>Conditions: check with operator.</strong></p>"]
    if c.get("needs_review"):
        bits.append(f'<p class="warn"><strong>Unverified, help us confirm</strong> — <a href="{report_href(c)}">send a correction</a>.</p>')
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
        if collapse: block += f'<p>Other facilities not yet confirmed. Know this spot? <a href="{report_href(c)}">Help us confirm</a>.</p>'
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
for state in statecfg.enabled():
    for key in ("towns", "places"):
        src = statecfg.path(state, key)
        if src and os.path.isfile(src):
            shutil.copyfile(src, os.path.join(OUT, os.path.basename(src)))
def emit_state(state, camps, include_home):
    """Write one state's pages. Home is the Victoria page, so only the primary state includes it."""
    bind(state)
    by_reg = {k: [c for c in camps if c["region"] == k] for k in REGIONS}
    n_closed = sum(c["status"] == "closed" for c in camps)
    n_check = sum(c["status"] == "check" for c in camps)
    n_osm = sum(c.get("source") == "osm" for c in camps)
    n_dv = len(camps) - n_osm
    reg_cards = "".join(f'<div class="card" data-region="{k}"><a href="/{SLUG}/{k}/">{e(n)}</a><p class="muted region-counts">{len(by_reg[k])} campgrounds · {sum(c["status"]=="closed" for c in by_reg[k])} closed · {sum(c["status"]=="check" for c in by_reg[k])} to check</p><p>{e(d)}</p></div>' for k, (n, d) in REGIONS.items())
    home_counts = {"count": len(camps), "osm": n_osm, "official": n_dv}
    faq_entities = [{"@type": "Question", "name": item.get("q") or "", "acceptedAnswer": {"@type": "Answer", "text": item.get("a") or ""}} for item in COPY.get("faq") or []]
    def full_home(path, on_home):
        home_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "CampConditions.au", "url": SITE + path, "inLanguage": "en-AU", "description": COPY["website_description"].format(count=len(camps))},
                   {"@context": "https://schema.org", "@type": "Organization", "name": "CampConditions.au", "url": SITE + "/", "sameAs": ["https://www.youtube.com/@OptimumQuestforBigThings"]},
                   {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_entities}]
        page(path, COPY["home_title"].format(count=len(camps)), COPY["home_description"].format(**home_counts),
         f"""<div class="page-head"><h1>{COPY["home_h1"]}</h1><p class="head-counts"><span class="badge closed" id="count-closed">{n_closed} closed</span> <span class="badge check" id="count-check">{n_check} to check</span></p></div><p>{COPY["home_intro"].format(**home_counts)}</p>
{map_block(camps, COPY["home_map"], external=SLUG)}{SAFETY}<h2>Regions</h2><div class="grid">{reg_cards}</div>
<p>{COPY["home_weather"]}</p>{news_section()}""", home_ld, head=leaflet_head(True), foot=leaflet_foot(True), on_home=on_home)
    multi = len(statecfg.enabled()) > 1
    state_is_home = multi and state.get("slug") == primary["slug"] and not include_home
    if include_home:
        full_home("/", True)
    if state_is_home:
        full_home(f"/{SLUG}/", True)
    else:
        state_body = f"<h1>{COPY['state_h1']}</h1><p>{COPY['state_intro'].format(count=len(camps))}</p>{map_block(camps, COPY['home_map'], external=SLUG)}{SAFETY}<div class='grid'>{reg_cards}</div>"
        if multi:
            state_body += news_section()
        page(f"/{SLUG}/", COPY["state_title"].format(count=len(camps)), COPY["state_description"].format(count=len(camps)),
             state_body, [crumbs([("Home", "/"), (STATE["name"], f"/{SLUG}/")])], head=leaflet_head(True), foot=leaflet_foot(True))
    for k, (n, d) in REGIONS.items():
        lst = by_reg[k]
        rows = "".join(f'<tr {row_attrs(c)}><td><a href="{camp_url(c)}">{e(c["name"])}</a></td><td>{e(c.get("category") or "")}</td><td class="camp-badge">{badge(c)}</td><td class="camp-note">{e(list_note(c))}</td></tr>' for c in sorted(lst, key=lambda c: ({"closed":0,"check":1,"open":2}[c["status"]], c["name"])))
        il = {"@context": "https://schema.org", "@type": "ItemList", "name": COPY["region_list_name"].format(name=n), "numberOfItems": len(lst), "itemListElement": [{"@type": "ListItem", "position": i+1, "url": f"{SITE}{camp_url(c)}", "name": c["name"]} for i, c in enumerate(lst)]}
        page(f"/{SLUG}/{k}/", COPY["region_title"].format(name=n, count=len(lst)), COPY["region_description"].format(count=len(lst), name=n, blurb=d),
             f'<p class="muted"><a href="/{SLUG}/">{e(STATE["name"])}</a> › {e(n)}</p><h1>{e(n)} campgrounds</h1><p>{e(d)} <strong>{len(lst)}</strong> sites.</p>{map_block(lst, f"Map of {n} campgrounds", external=SLUG + "-" + k)}{SAFETY}<table id="camp-list"><thead><tr><th>Campground</th><th>Type</th><th>Status</th><th>Notes</th></tr></thead><tbody>{rows or "<tr><td colspan=4>No campgrounds listed.</td></tr>"}</tbody></table>{news_section()}',
             [crumbs([("Home", "/"), (STATE["name"], f"/{SLUG}/"), (n, f"/{SLUG}/{k}/")]), il], head=leaflet_head(True), foot=leaflet_foot(True))
    for c in camps:
        rn = REGIONS[c["region"]][0]
        cl = c["closure"]; parts = []
        osm = c.get("source") == "osm"
        if cl:
            parts.append(f'<div class="warn"><strong>Closed:</strong> {e(cl["desc"] or cl["reason"] or "Full closure")} {("· Reopens "+e(cl["reopen"][:10])) if cl.get("reopen") else ""}</div>')
            if cl.get("outdated"): parts.append(COPY["outdated_html"].format(date=e(cl["reopen"][:10])))
        if c["nearby_closures"]: parts.append("<h2>Road and track closures within 5 km</h2><ul>" + "".join(f'<li>{e(x["type"])}{": "+e(x["name"]) if x["name"] else ""}{" — "+e(x["reason"]) if x["reason"] else ""}{" · reopens "+e(x["reopens"]) if x.get("reopens") else ""}</li>' for x in c["nearby_closures"]) + "</ul>")
        info_bits = []
        for heading, raw in (("About", c["about"]), ("Camping", c["camping"]), ("Caravans and campervans", c["caravans"]), ("Getting there", c["access"])):
            text = facts.without_prices(raw)
            if text: info_bits.append(f"<h2>{heading}</h2><p>{e(text)}</p>")
        info = "".join(info_bits)
        page_name = c.get("page_name") or c["name"]
        if osm:
            condition = osm_blocks(c)
            wording = str((cl or {}).get("desc") or "").strip()
            source_url = str((cl or {}).get("source_url") or "").strip()
            if wording and source_url:
                if c.get("state_slug") == "nsw" and "nationalparks.nsw.gov.au" in source_url:
                    block = official_npws_closure(wording, source_url, (cl or {}).get("source_published"))
                else:
                    block = f'<div class="warn"><strong>Closed:</strong> {e(wording)} <a href="{e(source_url)}">{e(source_url)}</a></div>'
                condition = f'<div id="camp-closure">{block}</div>' + condition
            notes = alert_notes_html(c)
            if notes:
                condition += notes
            title = f"{page_name} showground — call first | CampConditions.au" if c.get("category") == "Showground" else f"{page_name} — check with the operator | CampConditions.au"
            desc = COPY["osm_place"].format(name=c["name"], region=rn, category=c.get("category") or "camp")
            dated = COPY["osm_source_line"]
        elif c.get("source") == "npws":
            bits = []
            if cl and (cl.get("desc") or cl.get("reason")):
                url = str(cl.get("source_url") or "")
                wording = cl.get("desc") or cl.get("reason")
                if url.startswith("https://"):
                    bits.append(official_npws_closure(wording, url, cl.get("source_published")))
                else:
                    bits.append(f'<div class="warn"><strong>Closed:</strong> {e(wording)}</div>')
            else:
                bits.append("<p><strong>No status in this layer.</strong> The NPWS Visitor Area record does not include open or closed status, fees or facilities.</p>")
            notes = alert_notes_html(c)
            if notes:
                bits.append(notes)
            if c.get("asset_style"):
                bits.append(f"<p>Visitor area style: {e(c['asset_style'])}</p>")
            if c.get("asset_type"):
                bits.append(f"<p>Visitor area type: {e(c['asset_type'])}</p>")
            if c.get("source_ref"):
                bits.append(f"<p>Asset id: {e(c['source_ref'])}</p>")
            condition = "".join(bits)
            title = f"{page_name} | CampConditions.au"
            desc = COPY["official_place"].format(name=c["name"], region=rn)
            feed = str(c.get("alerts_feed") or "")
            dated = "Source: NPWS Visitor Area layer (camping areas)"
            if c.get("alerts_checked") and feed.startswith("https://"):
                dated += f'. <a href="{e(feed)}">NPWS alerts</a>'
        else:
            closure = "".join(parts) or "<p>No closure is recorded for this campground, and no road or track closures were found within 5 km.</p>"
            condition = f'<div id="camp-closure">{closure}</div>' + datavic_facts(c)
            title = f"{page_name} campground — is it open? Conditions today | CampConditions.au"
            desc = COPY["official_place"].format(name=c["name"], region=rn)
            dated = f"Campground data dated {e((c['data_date'] or '')[:10])}"
        camp_path = camp_url(c)
        camp_ld = {"@context": "https://schema.org", "@type": "Campground", "name": c["name"], "url": f"{SITE}{camp_path}", "description": (c.get("description") or c["about"] or desc)[:300],
                   "geo": {"@type": "GeoCoordinates", "latitude": c["lat"], "longitude": c["lon"]}, "address": {"@type": "PostalAddress", "addressRegion": STATE.get("abbrev") or "", "addressCountry": "AU"},
                   "containedInPlace": {"@type": "AdministrativeArea", "name": COPY["place_admin"].format(region=rn)}, "publicAccess": c["status"] != "closed", "identifier": str(c["id"])}
        lds = [camp_ld, crumbs([("Home", "/"), (STATE["name"], f"/{SLUG}/"), (rn, f"/{SLUG}/{c['region']}/"), (c["name"], camp_path)])]
        if cl:
            posted = feed_iso(cl.get("source_published")) or NOW.isoformat()
            lds.append({"@context": "https://schema.org", "@type": "SpecialAnnouncement", "name": f"Closure: {c['name']}", "text": cl.get("desc") or cl.get("reason") or "This campground is recorded as closed.", "datePosted": posted, "spatialCoverage": {"@type": "Place", "name": c["name"]}, "url": f"{SITE}{camp_path}"})
        page(camp_path, title, desc,
         f"""<p class="muted"><a href="/{SLUG}/">{STATE["name"]}</a> › <a href="/{SLUG}/{c['region']}/">{e(rn)}</a></p><h1>{e(page_name)}</h1>{f'<p class="muted">Near {e(c["near_place"])}</p>' if c.get("near_place") else ''}<p class="status-line" data-camp="{e(c['slug'])}">{badge(c)} <span class="muted" id="checked-line">Checked {STAMP}</span></p>{fire_line(c)}
{vicemergency_button(c)}
{map_block([c], f"Map of {c['name']}", small=True)}{directions(c)}
{condition}{SAFETY}{info}
<p class="muted">Location: {c['lat']}, {c['lon']} · <a href="https://www.google.com/maps?q={c['lat']},{c['lon']}">Open in maps</a> · <a href="{LINKS.get('bom_forecast') or ''}">BOM forecast</a> · {dated}</p>
<div class="box"><h2>Been here recently?</h2><p><a href="{report_href(c)}">Report conditions at {e(c['name'])}</a> — how full, road access, water, phone coverage.</p></div>{news_section()}""", lds, head=leaflet_head(False), foot=leaflet_foot(False))
multi_state = len(statecfg.enabled()) > 1
emit_state(primary, by_state[primary["slug"]], not multi_state)
for state in statecfg.enabled():
    if state["slug"] == primary["slug"]:
        continue
    emit_state(state, by_state[state["slug"]], False)
bind(primary)
if multi_state:
    all_rows = []
    for state in statecfg.enabled():
        all_rows.extend(by_state[state["slug"]])
    home_closed = sum(c["status"] == "closed" for c in all_rows)
    home_check = sum(c["status"] == "check" for c in all_rows)
    type_labels, seen_types = [], set()
    for label in ("Showground", "Council", "Rest area"):
        type_labels.append(label)
        seen_types.add(label)
    for state in statecfg.enabled():
        label = (facts.state_labels(state["slug"]).get("type_filter") or "").strip()
        if label and label not in seen_types:
            type_labels.append(label)
            seen_types.add(label)
    names = " and ".join(state["name"] for state in statecfg.enabled())
    safety = "".join(state.get("safety_html") or "" for state in statecfg.enabled())
    browse = '<p>Browse <a href="/vic/">Victoria</a> or <a href="/nsw/">New South Wales</a>.</p>'
    write_home_map_js()
    national_ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "CampConditions.au", "url": SITE + "/", "inLanguage": "en-AU", "description": f"Camp and campground conditions for {len(all_rows)} sites in Victoria and New South Wales."},
                   {"@context": "https://schema.org", "@type": "Organization", "name": "CampConditions.au", "url": SITE + "/", "sameAs": ["https://www.youtube.com/@OptimumQuestforBigThings"]}]
    page("/", "Camp conditions | CampConditions.au",
         f"Closures and camp conditions for {len(all_rows)} campgrounds in Victoria and New South Wales.",
         f"""<div class="page-head"><h1>Camp conditions</h1><p class="head-counts"><span class="badge closed" id="count-closed">{home_closed} closed</span> <span class="badge check" id="count-check">{home_check} to check</span></p></div><p>Closures and camp conditions for <strong>{len(all_rows)}</strong> campgrounds in {e(names)}.</p>
{map_block(all_rows, "Map of Victorian and New South Wales campgrounds", types=tuple(type_labels), external="home")}{safety}{browse}{news_section("Get the free weekly digest")}""",
         national_ld, head=leaflet_head(True), foot=LEAFLET_JS + CLUSTER_JS + '<script src="/map-home.js" defer></script>', on_home=True)


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
page("/report/", "Report campground conditions | CampConditions.au", "Email campconditions@outlook.com with what you saw: how full, access, water, coverage.",
 """<p><a class="back-map" href="/">← Back to map</a></p><h1>Report conditions</h1>
<p>This page does not store a report and it has no form to submit. It opens an email to <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a> with the camp name filled in when you opened a camp's report link. The message is sent only when you send that email.</p>
<p id="report-camp" class="muted"></p>
<p><a class="btn" id="report-mail" href="mailto:campconditions@outlook.com?subject=Camp%20conditions%20report&amp;body=Camp%3A%0ADate%20visited%3A%0AHow%20full%3A%0ARoad%20access%3A%0ANotes%3A%0A">Email a report</a></p>
<script>
(function () {
  var params = new URLSearchParams(location.search);
  var slug = params.get("camp") || "";
  var given = params.get("name") || "";
  var name = given.replace(/\\s+/g, " ").trim() || slug.replace(/-/g, " ").replace(/\\s+/g, " ").trim();
  var subject = name ? "Camp conditions report: " + name : "Camp conditions report";
  var body = "Camp: " + name + "\\nDate visited:\\nHow full:\\nRoad access:\\nNotes:\\n";
  var link = document.getElementById("report-mail");
  if (link) link.href = "mailto:campconditions@outlook.com?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
  var line = document.getElementById("report-camp");
  if (line && name) line.textContent = "Camp: " + name;
})();
</script>""")
def about_body():
    lead = COPY["about_lead"]
    roads = f"<p>{COPY['about_roads']}</p>"
    sources = f"<h2>Sources</h2><p>{e(CREDIT)}</p><ul>{COPY['about_sources']}</ul><p>{COPY['about_tail']}</p>"
    safety = SAFETY
    if len(statecfg.enabled()) > 1:
        lead = 'CampConditions.au is a free digest of campground conditions in Victoria and New South Wales, built for motorhomers, caravanners and campers by the team behind the YouTube channel <a href="https://www.youtube.com/@OptimumQuestforBigThings">Optimum Quest for Big Things</a>.'
        nsw = statecfg.by_slug("nsw")
        nsw_copy = nsw.get("copy") or {}
        safety = "".join(state.get("safety_html") or "" for state in statecfg.enabled())
        roads += '<p>Every New South Wales camp page has a Check Live Traffic NSW button. It opens <a href="https://www.livetraffic.com/">Live Traffic NSW</a>. Road-closure data is not copied onto this site.</p>'
        sources = (
            "<h2>Sources</h2><h3>Victoria</h3><p>" + e(CREDIT) + "</p><ul>" + COPY["about_sources"] + "</ul><p>" + COPY["about_tail"] + "</p>"
            + "<h3>New South Wales</h3><ul>" + (nsw_copy.get("about_sources") or "")
            + '<li>Live Traffic NSW (<a href="https://www.livetraffic.com/">livetraffic.com</a>) is linked from New South Wales camp pages. Road-closure data is not copied onto this site.</li></ul><p>'
            + (nsw_copy.get("about_tail") or "") + "</p>"
        )
    return f"""<h1>About</h1><p>{lead}</p><p>Feedback, corrections or questions? Email us at <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.</p>{safety}
<h2>Add to your home screen</h2><p>On an iPhone or iPad, open this site in Safari, tap Share, then Add to Home Screen. The icon opens CampConditions full screen. Tap Refresh under the header for the latest camp status.</p><p>On an Android phone, open this site in Chrome, tap the menu ⋮, then Add to Home screen or Install app.</p>
<h2>Nearby toilets</h2><p>Every camp page has a Find nearby toilets button. It opens the <a href="https://toiletmap.gov.au/">National Public Toilet Map</a>, an Australian Government site.</p>{roads}
{sources}"""
page("/about/", "About CampConditions.au", "Who we are and where our data comes from.", about_body())
privacy_who = COPY["privacy_who"]
privacy_date = "16 October 2026"
if len(statecfg.enabled()) > 1:
    privacy_who = 'CampConditions.au publishes a free weekly digest of campground conditions for Victoria and New South Wales. Contact us at <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.'
    privacy_date = "27 October 2026"
page("/privacy/", "Privacy | CampConditions.au", "How CampConditions.au handles your email address.",
 f"<h1>Privacy</h1><p>Last updated {privacy_date}.</p>\n<h2>Who we are</h2><p>{privacy_who}</p>\n" + """<h2>What we collect</h2><p>If you sign up, we collect your email address and the date and time of your sign-up and confirmation. We don't use tracking cookies. Cloudflare, which hosts this site, may log basic technical data such as your IP address for security.</p>
<h2>Why we collect it</h2><p>We use your email only to send the digest and service emails about your subscription, such as the confirmation message.</p>
<h2>Sharing</h2><p>We never sell, rent or share your email, except with service providers who process it for us: Resend (email delivery) and Cloudflare (hosting). Your data may be stored or processed outside Australia.</p>
<h2>Double opt-in</h2><p>Signing up is double opt-in. We email you a confirmation link, and you are not on the list until you click it.</p>
<h2>Unsubscribe, access, correction and deletion</h2><p id="unsubscribe">Every email includes an unsubscribe link. You can unsubscribe any time on the <a href="/unsubscribe/">unsubscribe page</a>. To ask for access, a correction, or deletion, email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.</p>
<h2>How long we keep it</h2><p>We keep your email while you are subscribed. After you unsubscribe, or after you ask us to delete it, we delete it within 30 days.</p>
<h2>Complaints</h2><p>If you have a complaint, email us. You can also contact the Office of the Australian Information Commissioner (OAIC) at <a href="https://www.oaic.gov.au/">oaic.gov.au</a>.</p>
<h2>Changes to this policy</h2><p>If we change this policy, we will update this page and the date at the top.</p>""")
def terms_body():
    """Restate the disclaimers already on the site. No extra legal claims."""
    parts = ["<h1>Terms of use</h1>", "<p>Last updated 27 October 2026.</p>",
             "<p>Conditions change quickly. Information on CampConditions.au is provided as is, without warranty.</p>"]
    for state in statecfg.enabled():
        disc = (state.get("copy") or {}).get("feed_disclaimer") or ""
        if disc:
            parts.append(f"<p><strong>{e(state['name'])}.</strong> {e(disc)}</p>")
    parts.append("<p>Check the official sources linked on each page before you travel. In an emergency call 000.</p>")
    parts.append('<p>Questions: <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>. The <a href="/privacy/">privacy page</a> covers the email list.</p>')
    return "".join(parts)
page("/terms/", "Terms of use | CampConditions.au", "How to use CampConditions.au. Not an official warning service.", terms_body())

# Feeds & SEO files
bind(primary)
home_camps = by_state[primary["slug"]]
attribution = []
for state in statecfg.enabled():
    credit = state.get("credit") or ""
    extra = (state.get("copy") or {}).get("feed_attribution_extra") or ""
    if credit and credit not in attribution:
        attribution.append(credit)
    if extra and extra not in attribution:
        attribution.append(extra)
    for line in (state.get("copy") or {}).get("status_credits") or []:
        if line and line not in attribution:
            attribution.append(line)
if len(statecfg.enabled()) > 1:
    feed_region = "Victoria and New South Wales, Australia"
    feed_disclaimer = " ".join(
        f"{state['name']}: {(state.get('copy') or {}).get('feed_disclaimer') or ''}".strip()
        for state in statecfg.enabled()
        if (state.get("copy") or {}).get("feed_disclaimer")
    )
else:
    feed_region = COPY["feed_region"]
    feed_disclaimer = COPY["feed_disclaimer"]
feed = {"name": "CampConditions.au status feed", "region": feed_region, "generated": NOW.isoformat(),
        "attribution": attribution,
        "disclaimer": feed_disclaimer, "sources": SRC,
        "camps": [{k: c[k] for k in ("slug", "name", "region", "lat", "lon", "status", "closure", "nearby_closures", "source", "category", "needs_review")} | {"url": f"{SITE}{camp_url(c)}"} for c in camps]}
json.dump(feed, open(os.path.join(OUT, "status.json"), "w"), ensure_ascii=False, indent=1)
# HTML and JSON revalidate. Do not also set Cache-Control on /assets/*:
# Pages joins every matching Cache-Control, and the strictest directive wins.
# iOS standalone still pins the saved HTML; pages refetch /status.json with cache: no-store.
def headers_text():
    """Cache rules. State paths are filled from the enabled configs and keep this order."""
    parts = ["/", "  Cache-Control: no-cache", "", "/index.html", "  Cache-Control: no-cache", "", "/404.html", "  Cache-Control: no-cache", ""]
    for state in statecfg.enabled():
        parts += [f"/{state['slug']}/*", "  Cache-Control: no-cache", ""]
    parts += ["/about/*", "  Cache-Control: no-cache", "", "/privacy/*", "  Cache-Control: no-cache", "", "/terms/*", "  Cache-Control: no-cache", "", "/report/*", "  Cache-Control: no-cache", "", "/unsubscribe/*", "  Cache-Control: no-cache", "", "/status.json", "  Cache-Control: no-cache", ""]
    for state in statecfg.enabled():
        flag = statecfg.public_file(state, "flags")
        if flag:
            parts += [flag, "  Cache-Control: no-cache", ""]
    parts += ["/build-report.json", "  Cache-Control: no-cache", ""]
    for state in statecfg.enabled():
        for key in ("towns", "places"):
            town = statecfg.public_file(state, key)
            if town:
                parts += [town, "  Cache-Control: no-cache", ""]
    parts += ["/map.js", "  Cache-Control: no-cache", ""]
    if len(statecfg.enabled()) > 1:
        parts += ["/map-home.js", "  Cache-Control: no-cache", ""]
    for state in statecfg.enabled():
        if state["slug"] == primary["slug"]:
            continue
        parts += [f"/map-{state['slug']}.js", "  Cache-Control: no-cache", ""]
    parts += ["/site.webmanifest", "  Cache-Control: no-cache", ""]
    parts += ["/map-points/*", "  Cache-Control: public, max-age=86400", ""]
    return "\n".join(parts)
open(os.path.join(OUT, "_headers"), "w", encoding="utf-8").write(headers_text())
open(os.path.join(OUT, "_redirects"), "w", encoding="utf-8").write("""/contact /about/ 301
/contact/ /about/ 301
/nsw/nsw /nsw/ 301
/nsw/nsw/ /nsw/ 301
""")
urls = ["/", f"/{SLUG}/", "/report/", "/about/", "/privacy/", "/terms/", "/unsubscribe/"] + [f"/{SLUG}/{k}/" for k in REGIONS] + [camp_url(c) for c in home_camps]
if len(statecfg.enabled()) > 1:
    for state in statecfg.enabled():
        if state["slug"] == primary["slug"]:
            continue
        bind(state)
        urls.append(f"/{SLUG}/")
        urls += [f"/{SLUG}/{k}/" for k in REGIONS]
        urls += [camp_url(c) for c in by_state[state["slug"]]]
    bind(primary)
open(os.path.join(OUT, "sitemap.xml"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"<url><loc>{SITE}{u}</loc><lastmod>{NOW.date()}</lastmod></url>\n" for u in urls) + "</urlset>\n")
open(os.path.join(OUT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
llms_regions = []
llms_intros = []
llms_closures = []
for state in statecfg.enabled():
    bind(state)
    intro = COPY["llms_intro"].format(count=len(by_state[state["slug"]]))
    llms_intros.append(intro)
    llms_closures.append(COPY["llms_closures"])
    for key, (name, blurb) in REGIONS.items():
        llms_regions.append(f"- [{name}]({SITE}/{SLUG}/{key}/): {blurb}\n")
bind(primary)
llms_states = ""
if len(statecfg.enabled()) > 1:
    llms_states = "- [Victoria]({site}/vic/)\n- [New South Wales]({site}/nsw/)\n".format(site=SITE)
open(os.path.join(OUT, "llms.txt"), "w").write(f"""# CampConditions.au

> {" ".join(llms_intros)}

Machine-readable status for every campground: {SITE}/status.json (includes attribution, sources and last-updated times).

## Regions
""" + "".join(llms_regions) + f"""
## Key pages
{llms_states}- [Report conditions]({SITE}/report/)
- [About and data sources]({SITE}/about/)
- [Privacy]({SITE}/privacy/)
- [Terms of use]({SITE}/terms/)
- [Unsubscribe]({SITE}/unsubscribe/)

## Attribution
{CREDIT}
{" ".join(llms_closures)}
""")
open(os.path.join(OUT, "404.html"), "w").write(external_blank(f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Not found</title>{ICONS}<style>{CSS}</style></head><body>
{banner()}
<main><p>Page not found. <a href="/">Back to CampConditions.au</a></p></main><footer>{footer_credits(len(statecfg.enabled()) > 1)}<p>© CampConditions.au · <a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a></p></footer></body></html>"""))
json.dump(SRC, open(os.path.join(OUT, "build-report.json"), "w"), indent=1)
from collections import Counter
n_osm = sum(c.get("source") == "osm" for c in camps)
n_dv = len(camps) - n_osm
n_closed = sum(c["status"] == "closed" for c in camps)
n_check = sum(c["status"] == "check" for c in camps)
print(f"Built {len(urls)} pages, {len(camps)} camps ({n_dv} {LABELS.get('official_short') or 'official'}, {n_osm} OSM, {n_closed} closed, {n_check} check), {len(closures)} closure features")
renamed = [c for c in camps if c.get("former_name")]
print(f"Renamed {len(renamed)} indexed OSM names; slugs unchanged")
for camp in sorted(renamed, key=lambda c: c["former_name"].lower()):
    print(f"  {camp['former_name']} -> {camp['name']}  {camp_url(camp)}")
print("Duplicate page names")
for camp in camps:
    if camp.get("page_name"): print(f"  {camp['name']} -> {camp['page_name']}  {camp_url(camp)}")
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
    (f"Type {LABELS.get('type_filter') or ''}", lambda c: c.get("type_filter") == (LABELS.get("type_filter") or "")),
    ("Type none", lambda c: not c.get("type_filter")),
    ("Dogs OK", lambda c: c.get("fac_dogs") is True),
    ("Known to suit caravans", lambda c: c.get("fac_caravans") is True),
    ("Known to suit motorhomes", lambda c: c.get("fac_motorhomes") is True),
    ("Hide closed", lambda c: c.get("status") == "closed"),
):
    print(f"  {sum(1 for c in camps if pred(c)):4d}  {label}")
for k, v in SRC.items(): print(("OK  " if v["ok"] else "FAIL"), k, v.get("error", ""))
for state in statecfg.enabled():
    checker_name = (state.get("closure_checker") or "").strip()
    if not checker_name:
        continue
    flag_count = 0
    try:
        checker = importlib.import_module(checker_name)
        dest_name = os.path.basename((state.get("files") or {}).get("flags") or "")
        if dest_name:
            flag_count = checker.write_flags(camps, os.path.join(OUT, dest_name))
    except Exception as exc:
        print(f"WARN parksvic check: {exc}", file=sys.stderr)
    print(f"{state.get('closure_flag_log') or 'ParksVic closure flags'}: {flag_count}")
