#!/usr/bin/env python3
"""Disabled South Australian camp inventory from the supplied files only.

Official Parks SA campgrounds are included only when that file attaches
coordinates. OSM eligibility contributes the eligible rows and nothing marked
hold or exclude. Coordinates are copied from those files and never invented.
A camp with no current notice is not marked open.
"""
import csv
import datetime as dt
import json
import os
import re

import act_sa_notices

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATTRIBUTION = "Source: Department for Environment and Water, parks.sa.gov.au, CC BY 3.0 AU"
OSM_ATTRIBUTION = "Coordinates: OpenStreetMap contributors (ODbL)."
CFS_URL = "https://www.cfs.sa.gov.au/warnings-restrictions/restrictions/total-fire-bans-ratings/"
FIRE_LABEL = (
    "Fire danger / total fire ban status not verified here. "
    "No SA Country Fire Service district map is loaded, so no rating is shown."
)
FIRE_NEEDED = (
    "SA CFS fire weather district polygons that contain each camp",
    "A dated district rating feed for today and tomorrow, with reuse terms that allow showing it",
    "A separate rule for whether a total fire ban closes that camp. A ban alone is not a park closure",
)
REGION = "south-australia"
# George's finished check of the 16 camps that still needed one, 9 Nov 2026.
# Slugs stay on the previous name. Pondalowie stays out of the preview.
CHECKED_OSM = {
    "way/189870423",  # Whyalla Caravan & Tourist Park
    "way/189966968",  # Brighton Beachfront Holiday Park
    "way/266080094",  # Balgowan Caravan & Camping Area
    "way/266254600",  # Port Vincent Foreshore Caravan Park
    "way/296586601",  # Moana Beach Tourist Park
    "way/310185448",  # Quorn Caravan Park
    "way/315185148",  # Port Lincoln Tourist Park
    "way/342488807",  # Kalganyi Holiday Park
    "way/375867507",  # Discovery Parks - Clare
    "way/663118408",  # Echo Holiday Parks - Renmark
    "way/819859535",  # Adelaide Showground Caravan Park
    "way/856987896",  # Pine Country Caravan Park
    "way/75460499",
    "way/671003129",
    "way/943231647",
}
DISPLAY_NAME = {
    "way/75460499": "Discovery Parks – West Beach Parks",
    "way/671003129": "Echo Holiday Parks – Waikerie",
    "way/943231647": "BIG4 Kingston SE Foreshore Holiday Park",
}
# Name and operator are confirmed. The OSM point is outside the official area.
HELD_FROM_PREVIEW = {
    "way/852240175": "OSM point is outside the official campground area",
}


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _paths():
    import states
    state = states.by_slug("sa")
    files = state.get("files") or {}

    def one(key):
        rel = files.get(key) or ""
        if not rel:
            raise SystemExit("SA config is missing files.%s" % key)
        return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)

    return one("official_inventory"), one("osm_eligibility"), one("spot_check"), one("notices")


def _unique_slug(name, seen, suffix):
    base = _slug(name) or _slug(suffix) or "camp"
    candidate = base if base not in seen else ""
    tail = _slug(suffix) or "camp"
    if not candidate:
        candidate = f"{base}-{tail}"
    number = 2
    while candidate in seen:
        candidate = f"{base}-{tail}-{number}"
        number += 1
    seen.add(candidate)
    return candidate


def _booking_ids(value):
    found = []
    for item in re.findall(r"/booking/(\d+)", value or ""):
        if item not in found:
            found.append(item)
    return found


def _first_url(value):
    for part in re.split(r"\s+\|\s+", value or ""):
        part = part.strip()
        if part.startswith("https://"):
            return part
    return ""


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _blank_camp(name, slug, lat, lon, source, source_url):
    return {
        "slug": slug,
        "id": slug,
        "name": name,
        "lat": lat,
        "lon": lon,
        "region": REGION,
        "status": "check",
        "status_label": "No current notice",
        "notice_status": "no_current_notice",
        "notice_summary": "No current Parks SA campground notice is matched to this camp.",
        "notice_url": "",
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
        "source": source,
        "category": "",
        "state_slug": "sa",
        "needs_review": False,
        "check_reason": "",
        "booking_ids": [],
        "source_url": source_url,
        "website": source_url,
        "open_inferred": False,
        "attribution": "",
        "fire_link": fire_link(),
        "fire": None,
    }


def fire_link():
    """No district rating. The page links to CFS instead of inventing one."""
    return {
        "label": FIRE_LABEL,
        "url": CFS_URL,
        "button": "SA Country Fire Service ratings",
        "rating": None,
        "district": None,
        "needed": list(FIRE_NEEDED),
    }


def _apply_notice(camp, bookings, notices, originals):
    ids = [str(item) for item in camp.get("booking_ids") or []]
    statuses = [bookings[item] for item in ids if item in bookings]
    if not ids or not statuses:
        _set_notice(camp, "no_current_notice", "")
        return
    status = act_sa_notices._combine(statuses) if len(statuses) > 1 else statuses[0]
    url = ""
    for row in notices:
        if row["camp_status"] != status:
            continue
        if not any(item in row["booking_ids"] for item in ids):
            continue
        url = originals.get(row["source_index"], {}).get("source_url") or ""
        if url:
            break
    _set_notice(camp, status, url)


def _set_notice(camp, status, url):
    """Map an engine status onto a page. None of these is confirmed open."""
    if status == "closed":
        label = "Closed"
        summary = "Parks SA has a closure that covers this campground."
        page_status = "closed"
    elif status == "partial":
        label = "Partial closure"
        summary = "Parks SA has a partial closure that covers this campground."
        page_status = "check"
    elif status == "upcoming":
        label = "Upcoming closure"
        summary = "Parks SA has listed a closure for this campground that has not started."
        page_status = "check"
    elif status in {"unknown", "expired_not_open"}:
        label = "Unknown"
        if status == "expired_not_open":
            summary = "A Parks SA notice for this campground has expired. That is not a confirmation it is open."
        else:
            summary = "A Parks SA notice mentions this campground, and the status is not resolved."
        page_status = "check"
    else:
        label = "No current notice"
        summary = "No current Parks SA campground notice applies to this camp."
        page_status = "check"
        status = "no_current_notice"
        url = ""
    camp["status"] = page_status
    camp["status_label"] = label
    camp["notice_status"] = status
    camp["notice_summary"] = summary
    camp["notice_url"] = url if str(url).startswith("https://") else ""
    camp["open_inferred"] = False
    if page_status == "closed":
        camp["closure"] = {
            "status": "Closed",
            "desc": summary,
            "reason": "",
            "start": None,
            "reopen": None,
            "outdated": False,
            "source_url": camp["notice_url"],
        }
        camp["upcoming_closure"] = None
    elif status == "upcoming":
        camp["closure"] = None
        camp["upcoming_closure"] = {"desc": summary, "source_url": camp["notice_url"]}
    else:
        camp["closure"] = None
        camp["upcoming_closure"] = None


def load_camps(seen=None, moment=None):
    """Camp records in the same shape the site builder already renders.

    `seen` is the build-wide slug set. The public build does not call this
    while South Australia stays disabled.
    """
    official_path, eligibility_path, spot_path, notice_path = _paths()
    official = _load_json(official_path)["campgrounds"]
    eligibility = _read_csv(eligibility_path)
    spot_rows = _read_csv(spot_path)
    spot = {row["record_id"]: row for row in spot_rows}
    seen = seen if seen is not None else set()

    confident = [row for row in official if row.get("coordinate_status") == "coordinates_attached"]
    if len(confident) != 73:
        raise SystemExit("expected 73 Parks SA campgrounds with coordinates, found %s" % len(confident))
    eligible = [row for row in eligibility if row.get("decision") == "eligible"]
    if len(eligible) != 35:
        raise SystemExit("expected 35 eligible non-park camps, found %s" % len(eligible))
    decisions = {row.get("decision") for row in eligibility}
    if decisions - {"eligible", "hold", "exclude"}:
        raise SystemExit("unexpected OSM eligibility decision")

    camps = []
    used_osm = set()
    used_bookings = set()
    for row in confident:
        lat, lon = _number(row.get("lat")), _number(row.get("lon"))
        if lat is None or lon is None:
            raise SystemExit("confident campground missing coordinates: %s" % row.get("booking_id"))
        booking_ids = [str(item) for item in (row.get("booking_ids") or [])]
        if not booking_ids:
            raise SystemExit("confident campground has no booking id")
        if any(item in used_bookings for item in booking_ids):
            raise SystemExit("booking id repeated: %s" % booking_ids)
        used_bookings.update(booking_ids)
        if row.get("osm_id"):
            used_osm.add(row["osm_id"])
        slug = _unique_slug(row.get("official_name"), seen, booking_ids[0])
        camp = _blank_camp(row["official_name"], slug, lat, lon, "parks_sa", row.get("official_url") or "")
        camp["id"] = booking_ids[0]
        camp["booking_ids"] = booking_ids
        camp["category"] = "Parks SA campground"
        camp["managed_by"] = row.get("park_name") or ""
        camp["osm_id"] = row.get("osm_id") or ""
        camp["data_date"] = str(row.get("booking_page_checked_at_melbourne") or "")[:10]
        camp["attribution"] = ATTRIBUTION + ". " + OSM_ATTRIBUTION
        camp["inventory_group"] = "official_confident"
        camps.append(camp)

    needs_check = 0
    for row in eligible:
        if row.get("decision") != "eligible":
            continue
        osm_id = row.get("record_id") or ""
        if osm_id in used_osm:
            continue
        lat, lon = _number(row.get("osm_lat")), _number(row.get("osm_lon"))
        if lat is None or lon is None:
            raise SystemExit("eligible camp missing coordinates: %s" % osm_id)
        if osm_id in HELD_FROM_PREVIEW:
            continue
        checked = spot.get(osm_id) or {}
        if checked.get("verdict") == "downgrade_to_hold":
            continue
        booking_ids = _booking_ids(row.get("official_or_operator_url") or "")
        if any(item in used_bookings for item in booking_ids):
            raise SystemExit("eligible camp repeats a published booking id: %s" % booking_ids)
        used_bookings.update(booking_ids)
        used_osm.add(osm_id)
        source_url = _first_url(row.get("official_or_operator_url") or "")
        source = "parks_sa" if booking_ids else "sa_operator"
        original_name = row.get("name") or osm_id
        slug = _unique_slug(original_name, seen, osm_id.replace("/", "-"))
        camp = _blank_camp(DISPLAY_NAME.get(osm_id) or original_name, slug, lat, lon, source, source_url)
        if osm_id in DISPLAY_NAME:
            camp["former_name"] = original_name
        camp["id"] = booking_ids[0] if booking_ids else osm_id
        camp["booking_ids"] = booking_ids
        camp["osm_id"] = osm_id
        camp["category"] = "Parks SA campground" if booking_ids else "Campground"
        camp["inventory_group"] = "eligible_osm"
        confirmed = checked.get("check_status") == "checked" and checked.get("verdict") == "confirmed_eligible"
        if osm_id in CHECKED_OSM:
            camp["needs_review"] = False
            camp["check_reason"] = "checked"
        elif not confirmed:
            camp["needs_review"] = True
            camp["check_reason"] = "not_spot_checked"
            needs_check += 1
        if booking_ids and osm_id not in CHECKED_OSM:
            camp["attribution"] = ATTRIBUTION + ". " + OSM_ATTRIBUTION
            camp["check_reason"] = camp["check_reason"] or "official_coordinate_hold"
            if not camp["needs_review"]:
                camp["needs_review"] = True
                needs_check += 1
        else:
            camp["attribution"] = OSM_ATTRIBUTION + " Operator page linked separately. This is not a Parks SA campground record."
        if checked.get("source_checked_at_melbourne"):
            camp["data_date"] = str(checked.get("source_checked_at_melbourne") or "")[:10]
        camps.append(camp)

    published_eligible = [camp for camp in camps if camp.get("inventory_group") == "eligible_osm"]
    if len(published_eligible) != 34:
        raise SystemExit("expected to publish 34 eligible camps, found %s" % len(published_eligible))
    notice_doc = _load_json(notice_path)
    moment = moment or dt.datetime.fromisoformat(notice_doc["as_of_adelaide"])
    scored = act_sa_notices.evaluate_all(notice_doc["notices"], moment)
    originals = {notice["source_index"]: notice for notice in notice_doc["notices"]}
    for camp in camps:
        _apply_notice(camp, scored["bookings"], scored["notices"], originals)
        if camp["status"] == "open" or camp["open_inferred"]:
            raise SystemExit("SA inventory inferred open for %s" % camp["name"])
    return camps


def summary(camps):
    official = [camp for camp in camps if camp.get("inventory_group") == "official_confident"]
    eligible = [camp for camp in camps if camp.get("inventory_group") == "eligible_osm"]
    return {
        "published": len(camps),
        "official_confident": len(official),
        "eligible_osm": len(eligible),
        "needs_check": sum(1 for camp in camps if camp.get("needs_review")),
        "booking_ids": sorted(item for camp in camps for item in camp.get("booking_ids") or []),
        "notice_status": _count(camp.get("notice_status") for camp in camps),
        "open_inferred": any(camp.get("open_inferred") or camp.get("status") == "open" for camp in camps),
        "fire_rating_count": sum(1 for camp in camps if (camp.get("fire") or {}).get("today") or (camp.get("fire_link") or {}).get("rating")),
        "fire_needed": list(FIRE_NEEDED),
        "attribution": ATTRIBUTION,
    }


def _count(values):
    found = {}
    for value in values:
        found[value] = found.get(value, 0) + 1
    return found
