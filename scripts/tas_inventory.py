#!/usr/bin/env python3
"""Tasmania camp list. Eligible records only. Held and excluded records stay out."""
import csv
import os
import re
from urllib.parse import urlparse

import contacts
import tas_alerts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_CREDIT = "Campground/site from theLIST © State of Tasmania"
OSM_CREDIT = "OpenStreetMap contributors (ODbL)"
LICENCE = "CC BY 3.0 AU"
REGION = "tasmania"
PARK_RE = re.compile(r"\b(?:caravan|holiday|tourist)(?:\s+and\s+[a-z]+){0,4}\s+parks?\b")
CABIN_RE = re.compile(r"\bcabin park\b")
CHAIN_RE = re.compile(r"\bbig\s*4\b")
HOTEL_RE = re.compile(r"\b(?:hotel|pub|motel)\b")
CAMP_RE = re.compile(r"\bcamp|\bcaravan")
ELIGIBLE = "eligible"
PUBLISHED = 178
NEAR_DUPLICATES = os.path.join(ROOT, "data", "tas", "thelist-near-duplicates.csv")


def _paths():
    import states
    files = states.by_slug("tas").get("files") or {}

    def one(key):
        rel = files.get(key) or ""
        if not rel:
            raise SystemExit("TAS config is missing files.%s" % key)
        return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)

    return one("inventory"), one("park_map"), one("park_decisions")


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
    """True for a caravan, holiday, tourist or cabin park, a BIG4 site, or hotel/pub camping."""
    for key in ("name", "category", "osm_name"):
        text = _park_text(camp.get(key))
        if not text:
            continue
        if PARK_RE.search(text) or CABIN_RE.search(text) or CHAIN_RE.search(text):
            return True
        if HOTEL_RE.search(text) and CAMP_RE.search(text):
            return True
    return False


def parks_without_keep(camps):
    """Published park types that do not have a keep decision."""
    missing = []
    for camp in camps:
        if not is_caravan_holiday_or_tourist_park(camp):
            continue
        if camp.get("park_decision") == "keep":
            continue
        missing.append(camp.get("name") or camp.get("id") or "")
    return missing


def commercial_published(camps):
    return parks_without_keep(camps)


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


def _host(url):
    return (urlparse(url).hostname or "").lower()


def _operator_website(value):
    """Official council or Hydro page. theLIST and other catalogues stay out."""
    text = (value or "").strip()
    if not text.startswith("https://") or contacts.is_catalogue(text):
        return ""
    host = _host(text)
    if host == "hydro.com.au" or host.endswith(".hydro.com.au"):
        return text
    if host == "tas.gov.au" or host.endswith(".tas.gov.au"):
        return text
    return ""


def _pws_park_url(value):
    """Official Parks and Wildlife park page. Other hosts, including theLIST, are refused."""
    text = (value or "").strip()
    if not text.startswith("https://"):
        return ""
    if _host(text) in {"parks.tas.gov.au", "www.parks.tas.gov.au"}:
        return text
    return ""


def pws_links_path():
    import states
    rel = ((states.by_slug("tas").get("files") or {}).get("pws_links") or "").strip()
    if not rel:
        return ""
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def load_pws_links(path=None):
    """Optional camp id to parks.tas.gov.au URL. A missing or empty file adds nothing."""
    if path is None:
        path = pws_links_path()
    if not path or not os.path.isfile(path):
        return {}
    found = {}
    for row in _read_csv(path):
        ident = (row.get("camp_id") or row.get("campground_record_id") or "").strip()
        url = _pws_park_url(row.get("url") or row.get("website") or "")
        if not ident or not url or ident in found:
            continue
        found[ident] = url
    return found


def assign_website(camp, links):
    """Council and Hydro pages, or a PWS park URL from the optional file. Never theLIST."""
    if camp.get("tas_council"):
        camp["website"] = _operator_website(camp.get("council_url"))
    else:
        camp["website"] = _pws_park_url((links or {}).get(camp.get("id") or ""))
    return camp.get("website") or ""


def load_rows():
    inventory_path, map_path, _decisions = _paths()
    inventory = _read_csv(inventory_path)
    parks = {row["camp_id"]: row for row in _read_csv(map_path)}
    return inventory, parks


def load_park_decisions():
    _inventory, _map, path = _paths()
    rows = _read_csv(path)
    allowed = {"keep", "exclude", "hold"}
    seen = set()
    for row in rows:
        ident = (row.get("campground_record_id") or "").strip()
        decision = (row.get("decision") or "").strip()
        if not ident or ident in seen:
            raise SystemExit("caravan park decision needs one id: %s" % (row.get("name") or ident))
        seen.add(ident)
        if decision not in allowed:
            raise SystemExit("unexpected caravan park decision for %s" % row.get("name"))
        if decision != "keep" and not (row.get("reason") or "").strip():
            raise SystemExit("caravan park decision has no reason: %s" % row.get("name"))
        if decision == "keep" and not (row.get("source_url") or "").strip():
            raise SystemExit("a kept park needs its source: %s" % row.get("name"))
    return rows


def _collapse_plan(inventory, parks):
    """Which theLIST points are the same camp, and which record to keep.

    The near-duplicate file says which names to collapse. Richardsons Beach
    and Campe Elsewhere are not in that set. The kept record prefers a PWS
    park match, then a public platform over a group pad, then a Parks page,
    then an OpenStreetMap cross-check, then the cluster anchor.
    """
    groups = {}
    anchors = set()
    if not os.path.isfile(NEAR_DUPLICATES):
        return {}, {}
    for row in _read_csv(NEAR_DUPLICATES):
        if not (row.get("recommendation") or "").startswith("Collapse to one camp"):
            continue
        name = (row.get("name") or "").strip()
        ident = (row.get("record_id") or "").strip()
        if not name or not ident:
            continue
        groups.setdefault(name, []).append(ident)
        distance = (row.get("distance_km_to_first") or "").strip()
        if distance in {"0", "0.0", "0.000"}:
            anchors.add(ident)
    by_id = {(row.get("campground_record_id") or "").strip(): row for row in inventory}
    drop = {}
    kept = {}
    for name, idents in groups.items():
        idents = [ident for ident in idents if ident in by_id]
        if len(idents) < 2:
            continue

        def rank(ident):
            row = by_id[ident]
            park = parks.get(ident) or {}
            osm_name = (row.get("osm_name") or "").lower()
            public = "public" in osm_name and "group" not in osm_name
            return (
                1 if (park.get("pws_alert_name") or "").strip() else 0,
                1 if public else 0,
                0 if "group" in osm_name else 1,
                1 if (row.get("official_url") or "").startswith("https://parks.tas.gov.au/") else 0,
                1 if (row.get("osm_id") or "").strip() else 0,
                1 if ident in anchors else 0,
            )

        chosen = max(idents, key=rank)
        if not (parks.get(chosen) or {}).get("pws_alert_name", "").strip():
            raise SystemExit("collapsed %s has no PWS park match" % chosen)
        kept[name] = chosen
        for ident in idents:
            if ident != chosen:
                drop[ident] = chosen
    return drop, kept


def _legacy_slugs(inventory, parks, seen):
    """Slugs the published list used before the near-duplicate collapse."""
    found = {}
    legacy_seen = set(seen)
    for row in inventory:
        if (row.get("decision") or "").strip() != ELIGIBLE:
            continue
        ident = (row.get("campground_record_id") or "").strip()
        mapped = parks.get(ident) or {}
        name = (row.get("official_name") or mapped.get("camp_name") or "").strip()
        lat, lon = _number(row.get("lat")), _number(row.get("lon"))
        if not ident or not name or lat is None or lon is None:
            continue
        found[ident] = _unique_slug(name, legacy_seen, ident)
    return found


def load_camps(seen=None):
    """Camps with decision eligible. Held and excluded decisions are left out."""
    inventory, parks = load_rows()
    seen = seen if seen is not None else set()
    drop, kept = _collapse_plan(inventory, parks)
    legacy = _legacy_slugs(inventory, parks, seen)
    links = load_pws_links()
    camps = []
    for row in inventory:
        if (row.get("decision") or "").strip() != ELIGIBLE:
            continue
        ident = (row.get("campground_record_id") or "").strip()
        if ident in drop:
            continue
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
        assign_website(camp, links)
        if not council:
            camp["info_line"] = {"phone": contacts.PWS_PHONE, "label": contacts.PWS_LABEL}
        camps.append(camp)
    by_camp = {camp["id"]: camp for camp in camps}
    for dropped_id, keep_id in drop.items():
        camp = by_camp.get(keep_id)
        if not camp:
            continue
        for alias in _aliases((parks.get(dropped_id) or {}).get("camp_name_aliases")):
            if alias not in camp["aliases"] and alias != camp["name"]:
                camp["aliases"].append(alias)
    published = _apply_park_decisions(camps)
    published_ids = {camp["id"]: camp["slug"] for camp in published}
    redirects = {}
    for ident, old_slug in legacy.items():
        if ident in drop:
            target = published_ids.get(drop[ident])
        elif ident in published_ids and old_slug != published_ids[ident]:
            target = published_ids[ident]
        else:
            target = ""
        if target and old_slug != target:
            redirects[old_slug] = target
    load_camps.slug_redirects = redirects
    load_camps.collapsed = dict(drop)
    load_camps.collapsed_kept = dict(kept)
    return published


def _park_record(camp, row):
    return {
        "id": camp.get("id") or "",
        "name": camp.get("name") or "",
        "decision": (row.get("decision") or "").strip(),
        "reason": (row.get("reason") or "").strip(),
        "source_url": (row.get("source_url") or "").strip(),
    }


def _apply_park_decisions(camps):
    """Free and council camps stay. Commercial parks are excluded. Unclear parks are held."""
    rows = load_park_decisions()
    by_id = {(row.get("campground_record_id") or "").strip(): row for row in rows}
    published, excluded, held, kept = [], [], [], []
    for camp in camps:
        row = by_id.get(camp.get("id") or "")
        if row:
            decision = (row.get("decision") or "").strip()
            if decision == "keep":
                camp["park_decision"] = "keep"
                kept.append(_park_record(camp, row))
                published.append(camp)
            elif decision == "exclude":
                excluded.append(_park_record(camp, row))
            elif decision == "hold":
                held.append(_park_record(camp, row))
            continue
        if is_caravan_holiday_or_tourist_park(camp):
            held.append(_park_record(camp, {
                "decision": "hold",
                "reason": "ownership is not confirmed",
            }))
            continue
        published.append(camp)
    load_camps.park_excluded = excluded
    load_camps.park_held = held
    load_camps.park_kept = kept
    return published


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
    collapsed = set(getattr(load_camps, "collapsed", {}) or {})
    return {
        "source_rows": len(inventory),
        "map_rows": len(parks),
        "decisions": decisions,
        "eligible": decisions.get(ELIGIBLE, 0),
        "published": len(published),
        "held_published": held,
        "excluded_published": excluded,
        "withheld_eligible": sorted(eligible_ids - ids - collapsed),
        "collapsed": sorted(collapsed),
        "collapsed_kept": dict(getattr(load_camps, "collapsed_kept", {}) or {}),
        "slug_redirects": dict(getattr(load_camps, "slug_redirects", {}) or {}),
        "park_excluded": list(getattr(load_camps, "park_excluded", [])),
        "park_held": list(getattr(load_camps, "park_held", [])),
        "park_kept": list(getattr(load_camps, "park_kept", [])),
        "commercial": commercial_published(published),
        "council": sum(1 for camp in published if camp.get("tas_council")),
        "osm_coordinates": sum(1 for camp in published if camp.get("coordinate_source") == "OSM"),
    }
