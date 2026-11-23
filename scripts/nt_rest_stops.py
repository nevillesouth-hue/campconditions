#!/usr/bin/env python3
"""Match the saved NT road rest-stop page to the RADAR rest-area points.

The page snapshot is the source for camping status. The build does not fetch nt.gov.au.
"""
import os
import re

import nt_inventory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIGHWAYS = {
    "stuart highway": "STUART HIGHWAY",
    "barkly highway": "BARKLY HIGHWAY",
    "victoria highway": "VICTORIA HIGHWAY",
}
# Page name, after normalisation, to a RADAR name on that highway.
# A comment hint picks one point when the name is shared.
MATCH = {
    "bridge creek": ("BRIDGE CREEK", None),
    "king": ("KING RIVER", None),
    "warloch": ("WARLOCH PONDS", None),
    "newcastle waters": ("NEWCASTLE WATERS", "REST AREA"),
    "attack creek": ("ATTACK CREEK", None),
    "bonney well": ("BONNEY WELL", None),
    "devils marbles": ("DEVILS MARBLES", None),
    "taylor creek": ("TAYLOR CREEK", None),
    "central mount stuart historical reserve": ("CENTRAL MT STUART", None),
    "prowse gap": ("PROWSE GAP", None),
    "connors well": ("CONNORS WELL", None),
    "tropic of capricorn": ("TROPIC OF CAPRICORN", None),
    "mt polhill": ("MOUNT POLHILL", None),
    "finke river": ("FINKE RIVER", None),
    "desert oaks": ("DESERT OAKS", None),
    "nt sa border": ("NT/SA BORDER", None),
    "41 mile bore": ("41 MILE BORE", None),
    "frewena": ("FREWENA", None),
    "wonarah bore": ("WONARAH", None),
    "soudan bore": ("SOUDAN", None),
    "avon downs": ("AVON DOWNS", None),
    "king west": ("KING RIVER WEST", None),
    "limestone": ("LIMESTONE CREEK", None),
    "mathison": ("MATHISON CREEK", None),
    "sullivan campground": ("SULLIVANS CREEK", None),
    "east baines river": ("EAST BAINES", "ROADSIDE STOP"),
    "saddle": ("SADDLE CREEK", None),
}


def snapshot_path():
    files = __import__("states").by_slug("nt").get("files") or {}
    rel = files.get("rest_stops") or "data/nt/nt-gov-rest-stops-snapshot.md"
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def _key(name):
    text = (name or "").lower().replace(".", " ")
    text = text.replace("mt ", "mt ")
    text = text.replace("/", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _status(name, facilities):
    blob = ("%s %s" % (name, facilities)).lower()
    if "temporarily closed" in blob:
        return "temporarily_closed"
    if "camping not permitted" in blob:
        return "camping_not_permitted"
    if "24 hour overnight camping allowed" in blob:
        return "overnight"
    return "no_camping_statement"


def parse_stops(text=None):
    if text is None:
        with open(snapshot_path(), encoding="utf-8") as handle:
            text = handle.read()
    highway = ""
    stops = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") and "highway" in line.lower():
            highway = ""
            for label, road in HIGHWAYS.items():
                if label in line.lower():
                    highway = road
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        name, _distance, facilities = cells[0], cells[1], cells[2]
        if not name or name.lower() == "rest stop" or set(name) <= {"-"}:
            continue
        stops.append({
            "name": name,
            "key": _key(name),
            "highway": highway,
            "facilities": facilities,
            "status": _status(name, facilities),
            "fees": "camping fees apply" in facilities.lower(),
        })
    return stops


def _pick(points, comment_hint):
    rows = list(points)
    if comment_hint:
        hinted = [row for row in rows if comment_hint in (row.get("comments") or "")]
        if len(hinted) == 1:
            return hinted[0]
        if hinted:
            rows = hinted
    # A "5 km east of" point is not the named stop.
    named = [row for row in rows if not re.search(r"\b\d+\s*KM\b", row.get("comments") or "")]
    if len(named) == 1:
        return named[0]
    if len(rows) == 1:
        return rows[0]
    return None


def match_stops(parks):
    """Return published rest-area camps and holds for the page and the dataset."""
    radar = nt_inventory.load_radar().get("rest_areas") or []
    by_road = {}
    for row in radar:
        by_road.setdefault((row.get("road_name") or "", row.get("name") or ""), []).append(row)
    used = set()
    published = []
    holds = []
    for stop in parse_stops():
        spec = MATCH.get(stop["key"]) if stop["highway"] else None
        point = None
        if spec and stop["highway"]:
            radar_name, hint = spec
            point = _pick(by_road.get((stop["highway"], radar_name)) or [], hint)
        if stop["status"] != "overnight":
            reason = {
                "temporarily_closed": "Temporarily closed. Not a camp.",
                "camping_not_permitted": "Camping is not permitted. Not a camp.",
                "no_camping_statement": "The rest-stop page does not say overnight camping is allowed.",
            }[stop["status"]]
            holds.append(_hold(stop, point, stop["status"], reason))
            if point:
                used.add(point.get("radar_id"))
            continue
        if point is None or point.get("radar_id") in used:
            reason = "No confident match in the rest area dataset."
            if stop.get("fees"):
                reason += " The page says camping fees apply."
            holds.append(_hold(stop, None, "unmatched", reason))
            continue
        park_camps = [camp for camp in parks if camp.get("category") == "NT Parks campground"]
        near_name, near_km = nt_inventory._near_park(point["lon"], point["lat"], park_camps, limit_km=1.0)
        if near_name:
            holds.append(_hold(
                stop, point, "duplicate_park",
                "Within 1 km of %s. The NT Parks camp is kept." % near_name,
            ))
            used.add(point.get("radar_id"))
            continue
        used.add(point.get("radar_id"))
        published.append(_camp(stop, point))
    for row in radar:
        if row.get("radar_id") in used:
            continue
        holds.append({
            "id": "NT-RADAR-%s" % row.get("radar_id"),
            "name": (row.get("name") or "").strip() or "Rest area",
            "place": (row.get("road_name") or "").strip(),
            "decision": "hold",
            "reason": "Not listed as an overnight camp on the NT road rest stops page.",
            "reason_code": "no_camping_statement",
            "source": "radar",
            "category": "Rest area",
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "near_park": "",
            "near_km": None,
            "attribution": nt_inventory.RADAR_ATTRIBUTION,
        })
    return published, holds


def _hold(stop, point, code, reason):
    row = {
        "id": "NT-STOP-%s" % nt_inventory._slug(stop["name"]),
        "name": stop["name"],
        "place": stop.get("highway") or "",
        "decision": "hold",
        "reason": reason,
        "reason_code": code,
        "source": "rest_stop",
        "category": "Rest area",
        "lat": None if not point else point.get("lat"),
        "lon": None if not point else point.get("lon"),
        "near_park": "",
        "near_km": None,
        "attribution": nt_inventory.REST_STATUS_ATTRIBUTION,
        "fees": stop.get("fees") or False,
    }
    if point:
        row["radar_id"] = point.get("radar_id")
    return row


def _camp(stop, point):
    fees = bool(stop.get("fees"))
    note = "24 hour overnight camping is allowed."
    if fees:
        note += " Camping fees apply."
    return {
        "name": stop["name"],
        "radar_id": point.get("radar_id"),
        "lat": point.get("lat"),
        "lon": point.get("lon"),
        "road": point.get("road_name") or stop.get("highway") or "",
        "fees": fees,
        "max_stay": "24 hours",
        "status_note": note,
        "attribution": nt_inventory.REST_STATUS_ATTRIBUTION + " " + nt_inventory.RADAR_ATTRIBUTION,
    }


def fees_apply_to_park(name):
    """The page names these two as paid. A nearby NT Parks camp keeps that fee."""
    key = _key(name)
    if "devil" in key and "marble" in key:
        return True
    if key == "sullivan creek campground":
        return True
    return False
