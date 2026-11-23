#!/usr/bin/env python3
"""Northern Territory camps from the saved NT Parks booking search.

Published camps are NT Parks campgrounds with a booking coordinate.
Permit-only Aboriginal land is left out. A camp with no booking coordinate
is left out. Commercial caravan, holiday and tourist parks are left out.
Nothing here is fetched at build time.
"""
import csv
import json
import os
import re

import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION = "northern-territory"
CATEGORY = "NT Parks campground"
ATTRIBUTION = "Campground information: NT Parks (Northern Territory Government)"
CAUTION = (
    "Campground locations and details come from the NT Parks booking system and may not be exact. "
    "Check with NT Parks and on the ground before you travel."
)
BOOKING_URL = "https://parkbookings.nt.gov.au/Web/"
FETCHED = "2026-11-23"
STATUS_NIGHT = "25 November 2026"
PERMIT_PLACES = {
    "Garig Gunak Barlu National Park",
    "Barranyi (North Island) National Park",
}
PARK_RE = re.compile(r"\b(?:caravan|holiday|tourist)(?:\s+and\s+[a-z]+){0,4}\s+parks?\b")
CABIN_RE = re.compile(r"\bcabin park\b")
CHAIN_RE = re.compile(r"\bbig\s*4\b")
HOTEL_RE = re.compile(r"\b(?:hotel|pub|motel)\b")
CAMP_RE = re.compile(r"\bcamp|\bcaravan")
AMENDED_NOTES = {
    "Ormiston Gorge (Walker) Campground": "The booking list has Ormiston Gorge campground, which is a different name.",
    "Matt Wilson Campground": "The booking list has Gumil Campground, which is a different name.",
    "Southern Campground": "The booking list has Southern Lost City Campground, which is a different name.",
}


def _paths():
    files = states.by_slug("nt").get("files") or {}

    def one(key):
        rel = files.get(key) or ""
        if not rel:
            raise SystemExit("NT config is missing files.%s" % key)
        return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)

    return one("booking"), one("amended"), one("park_decisions")


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _norm(name):
    text = (name or "").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _slug(name):
    text = (name or "").replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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


def _park_text(value):
    text = (value or "").lower().replace("&", " and ").replace("’", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_caravan_holiday_or_tourist_park(camp):
    """True for a caravan, holiday, tourist or cabin park, a BIG4 site, or hotel/pub camping."""
    for key in ("name", "category", "place"):
        text = _park_text(camp.get(key))
        if not text:
            continue
        if PARK_RE.search(text) or CABIN_RE.search(text) or CHAIN_RE.search(text):
            return True
        if HOTEL_RE.search(text) and CAMP_RE.search(text):
            return True
    return False


def parks_without_keep(camps):
    missing = []
    for camp in camps:
        if not is_caravan_holiday_or_tourist_park(camp):
            continue
        if camp.get("park_decision") == "keep":
            continue
        missing.append(camp.get("name") or camp.get("id") or "")
    return missing


def load_decisions():
    _booking, _amended, path = _paths()
    rows = _read_csv(path)
    allowed = {"keep", "exclude", "hold"}
    found = {}
    for row in rows:
        ident = str(row.get("facility_id") or "").strip()
        decision = (row.get("decision") or "").strip()
        if not ident or ident in found:
            raise SystemExit("NT park decision needs one facility id: %s" % (row.get("name") or ident))
        if decision not in allowed:
            raise SystemExit("unexpected NT park decision for %s" % row.get("name"))
        if decision != "keep" and not (row.get("reason") or "").strip():
            raise SystemExit("NT park decision has no reason: %s" % row.get("name"))
        found[ident] = row
    return found


def load_amended():
    _booking, path, _decisions = _paths()
    rows = []
    seen = set()
    for row in _read_csv(path):
        name = (row.get("name") or "").strip()
        if not name or _norm(name) in seen:
            raise SystemExit("amended coordinate needs one name: %s" % name)
        seen.add(_norm(name))
        rows.append({"name": name, "lat": float(row["lat"]), "lon": float(row["lon"])})
    return rows


def _status(row):
    if row.get("in_season") is True and row.get("available") is True:
        return "In season", "The NT Parks booking system listed this campground as in season on %s." % FETCHED
    if row.get("in_season") is True:
        return (
            "Not available to book",
            "The NT Parks booking system listed this campground as in season. It was not available to book for %s." % STATUS_NIGHT,
        )
    return "Out of season", "The NT Parks booking system listed this campground as out of season on %s." % FETCHED


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_booking():
    path, _amended, _decisions = _paths()
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    return doc.get("campgrounds") or []


def amended_report(records=None):
    """Match amended coordinates to booking names. A miss is not applied."""
    if records is None:
        records = load_booking()
    by_name = {}
    for row in records:
        by_name.setdefault(_norm(row.get("name")), []).append(row)
    matched, missed = [], []
    for item in load_amended():
        hits = by_name.get(_norm(item["name"])) or []
        if len(hits) == 1:
            matched.append({
                "name": item["name"],
                "facility_id": hits[0].get("facility_id"),
                "booking_name": hits[0].get("name"),
                "lat": item["lat"],
                "lon": item["lon"],
            })
        else:
            missed.append({
                "name": item["name"],
                "lat": item["lat"],
                "lon": item["lon"],
                "note": AMENDED_NOTES.get(item["name"]) or "No booking-system campground uses this name.",
            })
    return {"matched": matched, "missed": missed}


def load_camps(seen=None):
    """Published NT Parks campgrounds. Excluded and held records stay out.

    seen is the build's source-id set and is not changed here.
    """
    del seen
    decisions = load_decisions()
    report = amended_report()
    amended_by_id = {str(row["facility_id"]): row for row in report["matched"]}
    slug_seen = set()
    camps = []
    excluded = []
    held = []
    for row in load_booking():
        ident = str(row.get("facility_id") or "").strip()
        name = (row.get("name") or "").strip()
        place = (row.get("place_name") or "").strip()
        decision = decisions.get(ident) or {}
        choice = (decision.get("decision") or "").strip()
        lat, lon = _number(row.get("lat")), _number(row.get("lon"))
        if not ident or not name:
            raise SystemExit("NT booking camp is missing an id or a name")
        if place in PERMIT_PLACES and choice != "exclude":
            raise SystemExit("permit-only park has no exclude decision: %s" % name)
        if (lat is None or lon is None) and choice not in {"exclude", "hold"}:
            raise SystemExit("booking camp with no coordinates needs a decision: %s" % name)
        if choice in {"exclude", "hold"}:
            bucket = excluded if choice == "exclude" else held
            bucket.append({
                "id": "NT-BOOK-%s" % ident,
                "facility_id": ident,
                "name": name,
                "place": place,
                "decision": choice,
                "reason": (decision.get("reason") or "").strip(),
                "lat": lat,
                "lon": lon,
            })
            continue
        if choice == "keep":
            park_decision = "keep"
        else:
            park_decision = ""
        label, note = _status(row)
        amended = amended_by_id.get(ident)
        if amended:
            lat, lon = amended["lat"], amended["lon"]
            coord_source = "amended"
        else:
            coord_source = "booking"
        website = (row.get("place_url") or "").strip()
        if not website.startswith("https://"):
            website = ""
        camps.append({
            "slug": _unique_slug(name, slug_seen, ident),
            "id": "NT-BOOK-%s" % ident,
            "facility_id": ident,
            "name": name,
            "lat": lat,
            "lon": lon,
            "booking_lat": _number(row.get("lat")),
            "booking_lon": _number(row.get("lon")),
            "coord_source": coord_source,
            "region": REGION,
            "status": "check",
            "status_label": label,
            "status_note": note,
            "closure": None,
            "upcoming_closure": None,
            "access": "",
            "about": "NT Parks campground in %s." % place,
            "camping": "",
            "caravans": "",
            "site_class": CATEGORY,
            "dis_access": None,
            "managed_by": "NT Parks",
            "phone": (row.get("phone") or "").strip(),
            "data_date": FETCHED,
            "nearby_closures": [],
            "source": "nt",
            "category": CATEGORY,
            "state_slug": "nt",
            "needs_review": False,
            "place": place,
            "place_id": row.get("place_id"),
            "in_season": row.get("in_season") is True,
            "bookable_on_search_night": row.get("available") is True,
            "website": website,
            "source_url": BOOKING_URL,
            "attribution": ATTRIBUTION,
            "park_decision": park_decision,
            "fee_type": "",
        })
    load_camps.excluded = excluded
    load_camps.held = held
    load_camps.amended = report
    return camps


load_camps.excluded = []
load_camps.held = []
load_camps.amended = {"matched": [], "missed": []}


def summary(camps=None):
    if camps is None:
        camps = load_camps()
    types = {
        "NT Parks campground": 0,
        "Free": 0,
        "Donation": 0,
        "Council showground": 0,
        "Council or community caravan park": 0,
    }
    for camp in camps:
        if camp.get("category") in types:
            types[camp["category"]] += 1
    report = load_camps.amended
    return {
        "booking": len(load_booking()),
        "published": len(camps),
        "excluded": len(load_camps.excluded),
        "held": len(load_camps.held),
        "by_type": types,
        "in_season": sum(1 for camp in camps if camp.get("in_season")),
        "out_of_season": sum(1 for camp in camps if not camp.get("in_season")),
        "amended_matched": [row["name"] for row in report.get("matched") or []],
        "amended_missed": [row["name"] for row in report.get("missed") or []],
        "osm_only": 0,
        "commercial_published": parks_without_keep(camps),
    }


def html_block(camp):
    import html
    bits = [
        "<p><strong>%s.</strong> %s</p>" % (html.escape(camp.get("status_label") or ""), html.escape(camp.get("status_note") or "")),
        "<p>Park: %s</p>" % html.escape(camp.get("place") or ""),
    ]
    if camp.get("phone"):
        bits.append("<p>Phone: %s</p>" % html.escape(camp["phone"]))
    bits.append('<p>Camp record: <a href="%s">NT Parks booking system</a></p>' % html.escape(BOOKING_URL))
    website = camp.get("website") or ""
    if website.startswith("https://"):
        safe = html.escape(website)
        bits.append('<p>Park page: <a href="%s">%s</a></p>' % (safe, safe))
    bits.append('<p class="muted">%s</p>' % html.escape(camp.get("attribution") or ATTRIBUTION))
    return "".join(bits)
