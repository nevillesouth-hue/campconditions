#!/usr/bin/env python3
"""SA Country Fire Service ratings for the disabled South Australia preview.

Polygons are used only to name a camp's district. They are not written out.
The rating, ban and date come from the CFS feed. A ban does not close a camp.
A missing, stale or unreadable feed stays unknown and never borrows another
state's rating.
"""
import datetime as dt
import io
import json
import zipfile
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import nsw_conditions

ADELAIDE = ZoneInfo("Australia/Adelaide")
STALE_AFTER = dt.timedelta(hours=36)
CFS_PAGE = "https://www.cfs.sa.gov.au/warnings-restrictions/restrictions/total-fire-bans-ratings/"
CFS_CREDIT = "Fire danger: SA Country Fire Service (cfs.sa.gov.au)"
PARKS_FIRE_URL = "https://www.parks.sa.gov.au/park-management/fire"
CATASTROPHIC_LINE = "Parks SA parks are usually closed on Catastrophic fire danger days, so check before you travel"
BAN_LINE = "Total Fire Ban: fires banned"
UNKNOWN_LABEL = "Fire danger: unknown."
FEED_URL = "https://data.eso.sa.gov.au/prod/cfs/criimson/fireDangerRating.xml"
POLYGON_ZIP = "https://www.dptiapps.com.au/dataportal/FireBanDistricts_geojson.zip"


def unknown_link():
    return {
        "label": UNKNOWN_LABEL,
        "url": CFS_PAGE,
        "button": "SA Country Fire Service ratings",
        "rating": None,
        "district": None,
    }


def _mark_unknown(camp):
    camp.pop("fire", None)
    camp.pop("fire_unmapped", None)
    camp["fire_link"] = unknown_link()


def parse_feed(xml):
    """District ratings keyed by the upper-case district name.

    `<updated>` keeps the offset printed on it. Period dates are the Adelaide
    civil date of each period's own start, which the feed prints at +10:30.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return {"ok": False, "error": "parse", "updated": None, "districts": {}}
    updated = _updated(root)
    districts = {}
    for area in root.iter("area"):
        if (area.get("type") or "") != "fire-district":
            continue
        name = " ".join((area.get("description") or "").split())
        key = name.upper()
        if not key:
            continue
        periods = []
        for period in area.findall("forecast-period"):
            start = period.get("start-time-local") or ""
            try:
                when = dt.datetime.fromisoformat(start).astimezone(ADELAIDE)
            except ValueError:
                continue
            values = {node.get("type"): (node.text or "").strip() for node in period.findall("text")}
            rating = values.get("fire_danger") or ""
            ban_raw = (values.get("fire_ban") or "").lower()
            if not rating or ban_raw not in {"true", "false"}:
                continue
            periods.append({
                "date": when.date().isoformat(),
                "rating": rating,
                "ban": ban_raw == "true",
            })
        if periods:
            districts[key] = {"name": name, "periods": periods}
    if updated is None or not districts:
        return {"ok": False, "error": "parse", "updated": updated, "districts": districts}
    return {"ok": True, "error": "", "updated": updated, "districts": districts}


def _updated(root):
    text = (root.findtext("updated") or "").strip()
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return when


def fresh(updated, now):
    if updated is None or now is None:
        return False
    if updated.tzinfo is None or now.tzinfo is None:
        return False
    age = now - updated
    return dt.timedelta(0) <= age <= STALE_AFTER


def polygons_from_geojson(doc):
    """In-memory district boxes. The caller must not write `doc` anywhere."""
    records = []
    for feature in (doc or {}).get("features") or []:
        props = feature.get("properties") or {}
        name = " ".join(str(props.get("firebandistrict") or "").split())
        rings = _rings(feature.get("geometry") or {})
        prep = nsw_conditions._prepare(rings)
        if not name or not prep:
            continue
        records.append({"name": name, "key": name.upper(), "prep": prep})
    return records


def polygons_from_zip(payload):
    """Read the GDA94 GeoJSON member and drop the archive."""
    if not payload:
        return []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        return []
    chosen = ""
    for name in archive.namelist():
        if name.endswith("GDA94.geojson"):
            chosen = name
            break
    if not chosen:
        return []
    with archive.open(chosen) as handle:
        doc = json.loads(handle.read().decode("utf-8"))
    return polygons_from_geojson(doc)


def _rings(geometry):
    kind = (geometry or {}).get("type") or ""
    coords = (geometry or {}).get("coordinates") or []
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        return []
    rings = []
    for polygon in polygons:
        for ring in polygon or []:
            cleaned = []
            for point in ring or []:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    cleaned.append([float(point[0]), float(point[1])])
            if len(cleaned) >= 3:
                rings.append(cleaned)
    return rings


def _period_for(district, day):
    for period in district.get("periods") or []:
        if period.get("date") == day:
            return period
    return None


def assign(camps, parsed, records, now):
    """Attach today's CFS district rating. Closure fields are left alone.

    `records` are SA polygons only. Nothing in here reads another state's feed.
    """
    counts = {"inside": 0, "fallback": 0, "unmapped": 0, "unknown": 0, "by_district": {}}
    usable = bool(parsed and parsed.get("ok") and fresh(parsed.get("updated"), now) and records)
    day = now.astimezone(ADELAIDE).date().isoformat() if usable else ""
    districts = (parsed or {}).get("districts") or {}
    if usable and not any(_period_for(row, day) for row in districts.values()):
        usable = False
    grid = nsw_conditions._index(records) if usable else {}

    def has_rating(key):
        return _period_for(districts.get(key) or {}, day) is not None

    for camp in camps:
        before = (camp.get("status"), camp.get("closure"), camp.get("status_label"))
        if not usable:
            _mark_unknown(camp)
            counts["unknown"] += 1
            _restore_closure(camp, before)
            continue
        area, km, how = nsw_conditions.district_for(grid, records, camp["lon"], camp["lat"], has_rating)
        if how == "unmapped" or area is None:
            if how == "unmapped":
                nsw_conditions.mark_unmapped(camp, "CFS", CFS_PAGE, "SA Country Fire Service ratings")
                camp.pop("fire_link", None)
                counts["unmapped"] += 1
            else:
                _mark_unknown(camp)
                counts["unknown"] += 1
            _restore_closure(camp, before)
            continue
        period = _period_for(districts[area["key"]], day)
        district = districts[area["key"]]
        camp.pop("fire_link", None)
        camp.pop("fire_unmapped", None)
        camp["fire"] = {
            "authority": "sa_cfs",
            "district": district["name"],
            "rating": period["rating"],
            "date": period["date"],
            "ban": period["ban"],
            "credit": CFS_CREDIT,
            "page_url": CFS_PAGE,
            "button": "SA Country Fire Service ratings",
        }
        if how == "fallback":
            camp["fire"]["fallback_km"] = km
            counts["fallback"] += 1
        else:
            counts["inside"] += 1
        counts["by_district"][district["name"]] = counts["by_district"].get(district["name"], 0) + 1
        _restore_closure(camp, before)
    return counts


def _restore_closure(camp, before):
    """A fire ban is not a closure. Put the notice status back if anything moved it."""
    status, closure, label = before
    camp["status"] = status
    camp["closure"] = closure
    camp["status_label"] = label


def html_line(camp):
    """Rating sentence for one camp. No extra words about what the category means."""
    import html
    fire = camp.get("fire") or {}
    if fire.get("authority") != "sa_cfs":
        return ""
    ban = BAN_LINE if fire.get("ban") else "Total Fire Ban: no"
    sentence = f"{fire.get('district')}: {fire.get('rating')}, {_spoken(fire.get('date'))}. {ban}. {CFS_CREDIT}."
    if "fallback_km" in fire:
        sentence += " " + nsw_conditions.fallback_note(fire["fallback_km"])
    bits = [
        '<h2 class="fire-head" style="font-size:.95rem;line-height:1.25;margin:.45rem 0 0">Fire Ratings</h2>',
        f'<p class="muted fire-line fire-sa" style="margin:.05rem 0 .55rem">{html.escape(sentence)}</p>',
    ]
    if fire.get("rating") == "Catastrophic":
        bits.append(
            f'<p class="fire-catastrophic">{html.escape(CATASTROPHIC_LINE)}. '
            f'<a href="{PARKS_FIRE_URL}">Parks SA fire</a></p>'
        )
    page = str(fire.get("page_url") or "")
    label = str(fire.get("button") or "")
    if page.startswith("https://") and label:
        bits.append(f'<p><a class="btn-alert" href="{html.escape(page)}">{html.escape(label)}</a></p>')
    return "".join(bits)


def _spoken(day):
    try:
        when = dt.date.fromisoformat(str(day or ""))
    except ValueError:
        return str(day or "")
    return f"{when.day} {when:%B %Y}"


def apply(camps, state, fetch_text, src_log=None, now=None):
    """Fetch the CFS feed and district zip for an SA preview. Failures stay unknown."""
    sources = (state or {}).get("sources") or {}
    feed = sources.get("cfs_fdr") or {}
    zones = sources.get("cfs_districts") or {}
    feed_url = feed.get("url") or FEED_URL
    zone_url = zones.get("url") or POLYGON_ZIP
    now = now or dt.datetime.now(ADELAIDE)
    xml = fetch_text("cfs_fdr", feed_url) if fetch_text else None
    payload = fetch_text("cfs_districts", zone_url) if fetch_text else None
    parsed = parse_feed(xml) if xml else {"ok": False, "error": "missing", "updated": None, "districts": {}}
    records = polygons_from_zip(payload)
    if not records:
        parsed = {"ok": False, "error": parsed.get("error") or "districts", "updated": parsed.get("updated"), "districts": {}}
    counts = assign(camps, parsed, records, now)
    if src_log is not None:
        src_log["cfs_fdr"] = {
            "ok": bool(parsed.get("ok") and fresh(parsed.get("updated"), now) and records),
            "url": feed_url,
            "districts": len(records),
            "unmapped": counts["unmapped"],
            "unknown": counts["unknown"],
        }
    print(
        "SA fire: %s inside, %s within 1 km, %s unmapped, %s unknown"
        % (counts["inside"], counts["fallback"], counts["unmapped"], counts["unknown"])
    )
    for name, count in sorted(counts["by_district"].items()):
        print(f"  {count:4d}  {name}")
    return counts
