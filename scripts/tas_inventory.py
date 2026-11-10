#!/usr/bin/env python3
"""Tasmania camp list. Eligible records only. Held and excluded records stay out."""
import csv
import os
import re

import tas_alerts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_CREDIT = "Campground/site from theLIST © State of Tasmania"
OSM_CREDIT = "OpenStreetMap contributors (ODbL)"
LICENCE = "CC BY 3.0 AU"
REGION = "tasmania"
PARK_RE = re.compile(r"\b(?:caravan|holiday|tourist)(?:\s+and\s+[a-z]+){0,4}\s+parks?\b")
ELIGIBLE = "eligible"


def _paths():
    import states
    files = states.by_slug("tas").get("files") or {}

    def one(key):
        rel = files.get(key) or ""
        if not rel:
            raise SystemExit("TAS config is missing files.%s" % key)
        return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)

    return one("inventory"), one("park_map")


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _unique_slug(name, seen, suffix):
    base = _slug(name) or "camp"
    tail = _slug(suffix) or "camp"
    candidate = base if base not in seen else f"{base}-{tail}"
    number = 2
    while candidate in seen:
        candidate = f"{base}-{tail}-{number}"
        number += 1
    seen.add(candidate)
    return candidate[:90].strip("-")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _park_text(value):
    text = (value or "").lower().replace("&", " and ").replace("’", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_caravan_holiday_or_tourist_park(camp):
    """True when the name or the type is a caravan, holiday or tourist park."""
    for key in ("name", "category"):
        if PARK_RE.search(_park_text(camp.get(key))):
            return True
    return False


def commercial_published(camps):
    return [camp.get("name") or camp.get("id") or "" for camp in camps if is_caravan_holiday_or_tourist_park(camp)]


def _aliases(value):
    found = []
    for part in (value or "").split("|"):
        text = part.strip()
        if text and text not in found:
            found.append(text)
    return found


def _attribution(source):
    parts = [f"{LIST_CREDIT} ({LICENCE})."]
    if (source or "").strip() == "OSM":
        parts.append(OSM_CREDIT + ".")
    return " ".join(parts)


def _council_url(value):
    text = (value or "").strip()
    if text.startswith("https://"):
        return text
    return ""


def load_rows():
    inventory_path, map_path = _paths()
    inventory = _read_csv(inventory_path)
    parks = {row["camp_id"]: row for row in _read_csv(map_path)}
    return inventory, parks


def load_camps(seen=None):
    """Camps with decision eligible. Held and excluded decisions are left out."""
    inventory, parks = load_rows()
    seen = seen if seen is not None else set()
    camps = []
    for row in inventory:
        if (row.get("decision") or "").strip() != ELIGIBLE:
            continue
        ident = (row.get("campground_record_id") or "").strip()
        mapped = parks.get(ident) or {}
        name = (row.get("official_name") or mapped.get("camp_name") or "").strip()
        lat, lon = _number(row.get("lat")), _number(row.get("lon"))
        if not ident or not name or lat is None or lon is None:
            continue
        pws = (mapped.get("pws_alert_name") or "").strip()
        council = not pws
        camp = {
            "slug": _unique_slug(name, seen, ident),
            "id": ident,
            "name": name,
            "lat": lat,
            "lon": lon,
            "region": REGION,
            "status": "check",
            "status_label": tas_alerts.NO_ALERT_LABEL,
            "closure": None,
            "upcoming_closure": None,
            "access": "",
            "about": "",
            "camping": "",
            "caravans": "",
            "site_class": "",
            "dis_access": None,
            "managed_by": "",
            "data_date": "",
            "nearby_closures": [],
            "source": "tas",
            "source_ref": ident,
            "category": "Council park" if council else "PWS campground",
            "state_slug": "tas",
            "needs_review": False,
            "open_inferred": False,
            "source_url": (row.get("official_url") or "").strip(),
            "website": "",
            "attribution": _attribution(row.get("coordinate_source")),
            "coordinate_source": (row.get("coordinate_source") or "").strip(),
            "osm_id": (row.get("osm_id") or "").strip(),
            "aliases": _aliases(mapped.get("camp_name_aliases")),
            "reserve_name": (mapped.get("reserve_name") or "").strip(),
            "pws_alert_name": pws,
            "tas_council": council,
            "council_url": _council_url(mapped.get("council_url")) if council else "",
            "tas_list_note": tas_alerts.NO_ALERT_LABEL,
            "tas_display": "council" if council else "none",
            "tas_closures": [],
            "tas_ambers": [],
            "tas_campfire": False,
        }
        camps.append(camp)
    return camps


def summary(camps=None):
    inventory, parks = load_rows()
    decisions = {}
    for row in inventory:
        key = (row.get("decision") or "").strip() or "(blank)"
        decisions[key] = decisions.get(key, 0) + 1
    published = camps if camps is not None else load_camps(set())
    ids = {camp["id"] for camp in published}
    held = [row["campground_record_id"] for row in inventory if row.get("decision") == "hold" and row["campground_record_id"] in ids]
    excluded = [row["campground_record_id"] for row in inventory if row.get("decision") == "exclude" and row["campground_record_id"] in ids]
    eligible_ids = {row["campground_record_id"] for row in inventory if row.get("decision") == ELIGIBLE}
    return {
        "source_rows": len(inventory),
        "map_rows": len(parks),
        "decisions": decisions,
        "eligible": decisions.get(ELIGIBLE, 0),
        "published": len(published),
        "held_published": held,
        "excluded_published": excluded,
        "missing_eligible": sorted(eligible_ids - ids),
        "commercial": commercial_published(published),
        "council": sum(1 for camp in published if camp.get("tas_council")),
        "osm_coordinates": sum(1 for camp in published if camp.get("coordinate_source") == "OSM"),
    }
