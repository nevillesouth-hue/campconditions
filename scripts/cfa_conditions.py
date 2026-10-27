"""CFA fire danger ratings and Total Fire Ban status for Victorian camps.

Ratings come from the CFA RSS feed listed on DataVic under CC BY 4.0.
A camp is placed only when it falls inside a Vicmap Admin CFA Total Fire Ban
district polygon from the DataVic WFS, also CC BY 4.0. If either source cannot
be read, no rating is added.
"""
import html
import re
import sys
import xml.etree.ElementTree as ET

import nsw_conditions

_LINE = re.compile(r"^([A-Za-z][A-Za-z ]{1,40}):\s*(.+)$")


def _plain(fragment):
    text = html.unescape(fragment or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("\r", "")


def _rows(block):
    found = {}
    for raw in (block or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        match = _LINE.match(line)
        if not match:
            continue
        name, value = match.group(1).strip(), match.group(2).strip()
        if "forecast" in name.lower() or not value:
            continue
        key = nsw_conditions._district_key(name)
        if not key:
            continue
        found[key] = {"district": name, "value": nsw_conditions._show_level(value)}
    return found


def _forecast_items(payload):
    """RSS items whose link is the CFA page. Empty if the feed is not RSS."""
    if not payload:
        return []
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for node in channel.findall("item"):
        link = (node.findtext("link") or "").strip()
        description = node.findtext("description") or ""
        if not link.startswith("https://") or not description:
            continue
        items.append({"link": link, "body": _plain(description)})
    return items


def parse_cfa(payload):
    """Today and tomorrow, keyed by district. Other days in the feed are ignored."""
    found = {"today": {}, "tomorrow": {}}
    for item in _forecast_items(payload):
        body = item["body"]
        head = re.sub(r"\s+", " ", body).strip().lower()
        if head.startswith("today"):
            role = "today"
        elif head.startswith("tomorrow"):
            role = "tomorrow"
        else:
            continue
        parts = re.split(r"Fire Danger Ratings", body, maxsplit=1)
        bans = _rows(parts[0])
        ratings = _rows(parts[1] if len(parts) > 1 else "")
        day = {}
        for key, ban in bans.items():
            rating = ratings.get(key)
            if not rating or not ban["value"] or not rating["value"]:
                continue
            day[key] = {
                "district": rating["district"],
                "today": rating["value"],
                "ban_today": ban["value"],
            }
        if day:
            found[role] = day
    return found


def _rings(geometry):
    kind = (geometry or {}).get("type") or ""
    coords = (geometry or {}).get("coordinates") or []
    if kind == "Polygon":
        return coords
    if kind == "MultiPolygon":
        rings = []
        for poly in coords:
            rings.extend(poly)
        return rings
    return []


def _district_records(doc):
    records = []
    features = doc.get("features") if isinstance(doc, dict) else None
    for feature in features or []:
        props = feature.get("properties") or {}
        name = re.sub(r"\s+", " ", str(props.get("tfb_district") or "")).strip()
        prep = nsw_conditions._prepare(_rings(feature.get("geometry") or {}))
        if not name or not prep:
            continue
        records.append({"name": name, "key": nsw_conditions._district_key(name), "prep": prep})
    return records


def apply_fire_records(camps, records, today, tomorrow, source_url, pages, button):
    """Attach a district rating only where the polygon matches the CFA feed."""
    grid = nsw_conditions._index(records)
    matched = 0
    for camp in camps:
        chosen = None
        for area in nsw_conditions.reserves_at(grid, camp["lon"], camp["lat"]):
            rating = today.get(area["key"])
            if rating:
                chosen = (area, rating)
                break
        if not chosen:
            continue
        area, rating = chosen
        later = tomorrow.get(area["key"]) or {}
        page = str(pages.get(area["key"]) or "")
        camp["fire"] = {
            "district": rating["district"],
            "today": rating["today"],
            "tomorrow": later.get("today") or "",
            "ban_today": rating["ban_today"],
            "ban_tomorrow": later.get("ban_today") or "",
            "source_url": source_url,
            "page_url": page if page.startswith("https://") else "",
            "button": button if page.startswith("https://") else "",
        }
        matched += 1
    return matched


def apply(camps, sources, fetch_json, fetch_text):
    """Fetch the CFA forecast and district polygons. A failure leaves camps unchanged."""
    sources = sources or {}
    fdr = sources.get("cfa_fdr") or {}
    areas = sources.get("cfa_tfb_districts") or {}
    if not fdr.get("url") or not areas.get("url"):
        print("WARN CFA fire danger needs both the forecast feed and district boundaries", file=sys.stderr)
        return 0
    try:
        xml = fetch_text("cfa_fdr", fdr["url"])
        geo = fetch_json("cfa_tfb_districts", areas["url"]) if xml else None
        if not xml or not isinstance(geo, dict):
            print("WARN CFA fire danger unavailable; no rating was added", file=sys.stderr)
            return 0
        parsed = parse_cfa(xml)
        records = _district_records(geo)
        today = parsed.get("today") or {}
        if not today or not records:
            print("WARN CFA fire danger could not be read; no rating was added", file=sys.stderr)
            return 0
        pages = {}
        for name, url in (fdr.get("pages") or {}).items():
            pages[nsw_conditions._district_key(name)] = url
        matched = apply_fire_records(
            camps, records, today, parsed.get("tomorrow") or {}, fdr["url"], pages, fdr.get("button") or ""
        )
        print(f"CFA fire danger: {matched} camps in a feed district")
        return matched
    except Exception as exc:
        print("WARN CFA fire danger", exc, file=sys.stderr)
        return 0
