#!/usr/bin/env python3
"""Disabled ACT and SA status foundations.

This module does not fetch live pages and build.py does not import it.
Inventory here is a labelled candidate list and a three-camp South Australian
pilot, not a census. Closure decisions read structured records. A missing
field, a stale fetch or an ambiguous sentence stays unknown or check.
Nothing in here marks a camp open, invents a fire-danger rating, or borrows
a New South Wales rating for the ACT.

Live HTML selectors, statewide OpenStreetMap reconciliation, official
coordinates and fire-district polygons are not implemented.
"""
import datetime as dt
import json
import os
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "act-sa")
ADELAIDE = ZoneInfo("Australia/Adelaide")
MELBOURNE = ZoneInfo("Australia/Melbourne")
CANBERRA = ZoneInfo("Australia/Canberra")
FIRE_UNKNOWN_LABEL = "Fire danger / total fire ban status not verified here"
CONDITIONAL_TFB_LABEL = (
    "A verified ACT ESA total fire ban applies to this campground, so its own closure rule applies. "
    "Fire danger rating is not shown."
)
FIRE_LINKS = {
    "act": "https://esa.act.gov.au/be-emergency-ready/total-fire-bans",
    "sa": "https://www.cfs.sa.gov.au/warnings-restrictions/restrictions/total-fire-bans-ratings/",
}
NON_CAMP_ASSETS = {"trail", "climbing", "platform", "road", "airstrip", "business", "accommodation", "health"}
ASSET_CLASSES = NON_CAMP_ASSETS | {"campground", "pitch", "park", "subarea", "unknown"}
_NO_RATING = re.compile(r"\bno rating\b", re.I)
_EARLY_2027 = re.compile(r"\bearly\s+2027\b", re.I)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def candidates_path():
    return os.path.join(DATA, "candidates.json")


def load_candidates():
    return load_json(candidates_path())


def load_alerts():
    return load_json(os.path.join(DATA, "fixtures", "alerts.json"))


def load_legacy():
    return load_json(os.path.join(DATA, "fixtures", "legacy-parks.json"))


def load_osm():
    return load_json(os.path.join(DATA, "fixtures", "osm-samples.json"))


def load_failures():
    return load_json(os.path.join(DATA, "fixtures", "failures.json"))


def load_sitemap_xml():
    with open(os.path.join(DATA, "fixtures", "sitemap-sample.xml"), encoding="utf-8") as handle:
        return handle.read()


def contains_no_rating(value):
    return _NO_RATING.search(json.dumps(value, ensure_ascii=False)) is not None


def selectable_camps(records):
    """Camps that a future preview may list. Closed camps stay. Exclusions do not."""
    return [
        row for row in records
        if row.get("entity_type") == "campground" and row.get("inventory_role") in {"candidate", "pilot"}
    ]


def summarise_inventory(doc):
    records = doc.get("records") or []
    act_camps = [
        row for row in records
        if row.get("state") == "act" and row.get("inventory_role") == "candidate" and row.get("entity_type") == "campground"
    ]
    act_excluded = [
        row for row in records
        if row.get("state") == "act" and row.get("inventory_role") == "excluded"
    ]
    pilot = [row for row in records if row.get("inventory_role") == "pilot"]
    return {
        "act_headings": len(act_camps) + len(act_excluded),
        "act_camp_candidates": len(act_camps),
        "act_camp_ids": [row["id"] for row in act_camps],
        "act_excluded_ids": [row["id"] for row in act_excluded],
        "act_statewide": False,
        "act_audited": False,
        "sa_pilot_ids": [row["id"] for row in pilot],
        "sa_statewide": False,
        "legacy_record_count_is_campgrounds": False,
        "sitemap_counts_are_campgrounds": False,
    }


def campgrounds_from_legacy(doc):
    """The 2017 park file is not a campground inventory. It never yields camps."""
    return []


def legacy_alias_candidates(doc):
    rows = []
    for rec in (doc or {}).get("records") or []:
        rows.append({
            "slug": rec.get("slug") or "",
            "name": rec.get("name") or "",
            "use": "reviewed_alias_only",
            "camping_flags_applied": False,
            "exclude_current_camps": False,
            "auto_merge": False,
        })
    return rows


def excluded_ids_from_legacy(doc, current_ids):
    """Camping flags, including false, do not drop a current camp."""
    return []


def campground_count_from_discovery(observations):
    """Page-URL observations are not a campground census."""
    return None


def direct_url_locs(xml_text):
    """Count sitemap url/loc entries. Nested image:loc values are not pages."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"ok": False, "malformed": True, "locs": [], "page_url_count": 0, "campground_count": None}
    locs = []
    for el in root.iter():
        if _local(el.tag) != "url":
            continue
        for child in list(el):
            if _local(child.tag) == "loc" and (child.text or "").strip():
                locs.append(child.text.strip())
    return {"ok": True, "malformed": False, "locs": locs, "page_url_count": len(locs), "campground_count": None}


def osm_campgrounds(elements):
    """camp_site and caravan_site are camps. camp_pitch children are not."""
    pitches = []
    sites = []
    for el in elements or []:
        tourism = str((el.get("tags") or {}).get("tourism") or "")
        if tourism == "camp_pitch":
            pitches.append(el)
        elif tourism in {"camp_site", "caravan_site"}:
            sites.append(el)
    identities = set()
    for site in sites:
        identities.add("%s/%s" % (site.get("type"), site.get("id")))
        identities.add(str(site.get("id")))
    roots = []
    child_sites = []
    unresolved_sites = []
    for site in sites:
        parent = str(site.get("parent") or (site.get("tags") or {}).get("parent") or "")
        if parent and parent in identities:
            child_sites.append(site)
        elif parent:
            unresolved_sites.append(site)
        else:
            roots.append(site)
    used = set()
    camps = []
    for site in roots:
        sid = "%s/%s" % (site.get("type"), site.get("id"))
        kids = []
        for pitch in pitches:
            parent = str(pitch.get("parent") or (pitch.get("tags") or {}).get("parent") or "")
            if parent in {sid, str(site.get("id"))}:
                kids.append(pitch)
                used.add(id(pitch))
        camps.append({
            "osm_type": site.get("type"),
            "osm_id": site.get("id"),
            "name": (site.get("tags") or {}).get("name") or "",
            "pitch_count": len(kids),
            "counts_as": 1,
            "synthetic_children": any(pitch.get("synthetic") for pitch in kids),
        })
    return {
        "campgrounds": camps,
        "pitch_promoted": 0,
        "orphan_pitches": len(pitches) - len(used),
        "child_camp_sites": len(child_sites),
        "unresolved_camp_sites": len(unresolved_sites),
        "campground_count": len(camps),
    }


def merge_official_osm(official, osm_camps, crosswalk):
    """Merge only a reviewed crosswalk row. Name similarity does not merge."""
    consumed = set()
    camps = []
    unresolved = []
    for camp in official or []:
        links = [
            row for row in (crosswalk or [])
            if row.get("official_id") == camp.get("id") and row.get("reviewed") is True
        ]
        if len(links) > 1:
            unresolved.append(camp.get("id"))
            camps.append(dict(camp))
            continue
        if len(links) == 1 and links[0].get("reject_second_camp"):
            key = (links[0].get("osm_type"), links[0].get("osm_id"))
            consumed.add(key)
            row = dict(camp)
            row["osm"] = {"type": key[0], "id": key[1], "distance_tested": bool(links[0].get("distance_tested"))}
            row["second_camp"] = False
            camps.append(row)
            continue
        camps.append(dict(camp))
    extras = []
    for osm in osm_camps or []:
        key = (osm.get("osm_type"), osm.get("osm_id"))
        if key in consumed:
            continue
        extras.append(osm)
    return {"camps": camps, "extra_unmerged": extras, "unresolved": unresolved, "public_count": len(camps)}


def match_camp(slug, camps):
    """Reviewed ids and aliases only. A renamed slug stays unresolved."""
    hits = []
    for camp in camps or []:
        keys = {camp.get("source_record_id"), camp.get("id")}
        keys.update(camp.get("reviewed_aliases") or [])
        if slug in keys:
            hits.append(camp)
    if len(hits) == 1:
        return {"camp": hits[0], "unresolved": False, "guessed": False}
    return {"camp": None, "unresolved": True, "guessed": False}


def normalise_alert(raw):
    if not isinstance(raw, dict):
        return {"ok": False, "reason": "not_an_object", "id": ""}
    ident = str(raw.get("id") or "")
    missing = [key for key in ("id", "state", "source_url", "action", "asset_class") if not str(raw.get(key) or "").strip()]
    if missing:
        return {"ok": False, "reason": "missing:" + ",".join(missing), "id": ident}
    if raw.get("state") not in {"act", "sa"}:
        return {"ok": False, "reason": "state", "id": ident}
    if raw.get("asset_class") not in ASSET_CLASSES:
        return {"ok": False, "reason": "asset_class", "id": ident}
    if raw.get("action") not in {"closure", "restriction", "advisory"}:
        return {"ok": False, "reason": "action", "id": ident}
    if not isinstance(raw.get("targets") or [], list):
        return {"ok": False, "reason": "targets", "id": ident}
    expected_note = None
    for key in ("end", "until", "expected", "reopen", "reopen_at"):
        if _EARLY_2027.search(str(raw.get(key) or "")):
            expected_note = "early 2027"
    reopen_at = raw.get("reopen_at")
    if isinstance(reopen_at, str) and _EARLY_2027.search(reopen_at):
        reopen_at = None
    if expected_note and raw.get("reopen_at_source") == "expected_wording":
        reopen_at = None
    if reopen_at not in (None, ""):
        try:
            dt.date.fromisoformat(str(reopen_at)[:10])
        except ValueError:
            return {"ok": False, "reason": "reopen_at", "id": ident}
    else:
        reopen_at = None
    start = str(raw.get("start") or "")
    if start:
        try:
            dt.date.fromisoformat(start[:10])
        except ValueError:
            return {"ok": False, "reason": "start", "id": ident}
        start = start[:10]
    end_date = ""
    end_raw = str(raw.get("end") or "")
    if end_raw and not _EARLY_2027.search(end_raw):
        try:
            dt.date.fromisoformat(end_raw[:10])
        except ValueError:
            return {"ok": False, "reason": "end", "id": ident}
        end_date = end_raw[:10]
    until = bool(raw.get("until_further_notice")) or expected_note is not None
    recurrence = raw.get("recurrence")
    intervals = list(raw.get("intervals") or [])
    ambiguous = bool(raw.get("ambiguous"))
    if raw.get("action") == "closure" and not any((start, until, recurrence, intervals, ambiguous)):
        return {"ok": False, "reason": "missing_date", "id": ident}
    if recurrence and not _recurrence_ok(recurrence):
        return {"ok": False, "reason": "recurrence", "id": ident}
    if expected_note:
        until = True
        reopen_at = None
    alert = {
        "id": ident,
        "state": raw["state"],
        "source_url": raw["source_url"],
        "action": raw["action"],
        "asset_class": raw["asset_class"],
        "targets": list(raw.get("targets") or []),
        "start": start,
        "end_date": end_date,
        "until_further_notice": until,
        "reopen_at": reopen_at,
        "expected_note": expected_note,
        "date_inferred": False,
        "ambiguous": ambiguous,
        "ambiguity": raw.get("ambiguity") or "",
        "timezone": raw.get("timezone") or ("Australia/Canberra" if raw["state"] == "act" else "Australia/Adelaide"),
        "recurrence": recurrence,
        "intervals": intervals,
        "parent_id": raw.get("parent_id") or "",
        "displayed_on": list(raw.get("displayed_on") or []),
        "listing_contexts": list(raw.get("listing_contexts") or []),
        "content_hash": raw.get("content_hash") or "",
        "exceptions": list(raw.get("exceptions") or []),
        "rows": list(raw.get("rows") or []),
        "published": raw.get("published") or "",
        "window_confirmed": bool(raw.get("window_confirmed")),
        "non_exhaustive_park": bool(raw.get("non_exhaustive_park")),
        "park_id": raw.get("park_id") or "",
        "named_camp_ids": list(raw.get("named_camp_ids") or []),
        "also_named_not_campgrounds": list(raw.get("also_named_not_campgrounds") or []),
    }
    return {"ok": True, "alert": alert}


def dedupe_notices(alerts):
    """Same content hash is one notice. Every listing context is kept."""
    grouped = []
    index = {}
    for alert in alerts:
        key = alert.get("content_hash") or alert.get("id")
        if key not in index:
            index[key] = len(grouped)
            grouped.append(dict(alert))
            grouped[-1]["merged_count"] = 1
            continue
        current = grouped[index[key]]
        current["merged_count"] = current.get("merged_count", 1) + 1
        for ctx in alert.get("listing_contexts") or []:
            if ctx not in current["listing_contexts"]:
                current["listing_contexts"].append(ctx)
        for target in alert.get("targets") or []:
            if target not in current["targets"]:
                current["targets"].append(target)
    return grouped


def recurrence_active(spec, moment):
    """True only inside a source-local occurrence. The end instant is exclusive.

    end_time 24:00 is the next local midnight and is not itself inside the window.
    Holiday ranges are inclusive civil dates in the source zone and suppress
    the occurrence whose start date falls inside them.
    """
    moment = _aware(moment)
    tz = ZoneInfo(spec.get("timezone") or "Australia/Adelaide")
    local = moment.astimezone(tz)
    start_date = dt.date.fromisoformat(spec["start_date"])
    end_date = dt.date.fromisoformat(spec["end_date"])
    if local.date() < start_date or local.date() > end_date:
        return False
    if local.weekday() not in set(spec.get("weekdays") or []):
        return False
    if _date_excluded(local.date(), spec.get("exclude_dates") or []):
        return False
    start_t = _clock(spec.get("start_time"))
    end_token = spec.get("end_time")
    if end_token == "24:00":
        return local.time() >= start_t
    end_t = _clock(end_token)
    if end_t > start_t:
        return start_t <= local.time() < end_t
    return local.time() >= start_t or local.time() < end_t


def occurrence_bounds(spec, moment):
    """Source window for the local date of moment, plus Melbourne civil times."""
    moment = _aware(moment)
    tz = ZoneInfo(spec.get("timezone") or "Australia/Adelaide")
    local = moment.astimezone(tz)
    start_t = _clock(spec.get("start_time"))
    start = dt.datetime.combine(local.date(), start_t, tzinfo=tz)
    if spec.get("end_time") == "24:00":
        end = dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time(0, 0), tzinfo=tz)
    else:
        end = dt.datetime.combine(local.date(), _clock(spec.get("end_time")), tzinfo=tz)
        if end <= start:
            end = end + dt.timedelta(days=1)
    return {
        "start_local": start.isoformat(),
        "end_local": end.isoformat(),
        "start_melbourne": start.astimezone(MELBOURNE).isoformat(),
        "end_melbourne": end.astimezone(MELBOURNE).isoformat(),
    }


def window_is_all_day(interval):
    """A span of 18 hours or more is not an overnight window."""
    start = dt.datetime.fromisoformat(interval["start"])
    end = dt.datetime.fromisoformat(interval["end"])
    if end <= start:
        return False
    return (end - start) >= dt.timedelta(hours=18)


def _confirmed_window(base, alert, moment):
    """Explicit source clock window. End is exclusive. Generic wording does not override it."""
    tz = ZoneInfo(alert.get("timezone") or "Australia/Adelaide")
    interval = alert["intervals"][0]
    start = dt.datetime.fromisoformat(interval["start"])
    end = dt.datetime.fromisoformat(interval["end"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    local = moment.astimezone(tz)
    base["applies"] = True
    base["open_claim"] = False
    base["all_day"] = False
    base["melbourne"] = {
        "start_melbourne": start.astimezone(MELBOURNE).isoformat(),
        "end_melbourne": end.astimezone(MELBOURNE).isoformat(),
    }
    if local < start:
        base.update(status="upcoming", closed=False, reason="not_started")
    elif local < end:
        base.update(status="closed", closed=True, reason="confirmed_window", generic_overrode=False)
    else:
        base.update(status="check", closed=False, reason="window_ended")
    return base


def effect(camp, alert, moment):
    moment = _aware(moment)
    base = _blank(alert.get("id"))
    if camp.get("state") != alert.get("state"):
        base["reason"] = "other_state"
        return base
    if alert.get("asset_class") in NON_CAMP_ASSETS or alert.get("asset_class") == "unknown":
        base["reason"] = "non_camp_asset" if alert.get("asset_class") in NON_CAMP_ASSETS else "unknown_asset"
        return base
    if alert.get("non_exhaustive_park"):
        named = set(alert.get("named_camp_ids") or [])
        if camp.get("entity_type") != "campground":
            base["reason"] = "not_a_campground"
            return base
        if camp.get("id") not in named:
            if camp.get("parent_id") == alert.get("park_id"):
                base.update(applies=True, status="unknown", review=True, closed=False, open_claim=False, reason="non_exhaustive_list")
            return base
    if alert.get("ambiguity") == "unnamed_parts":
        if _parent_mentioned(camp, alert) and camp.get("entity_type") == "campground":
            base.update(applies=True, status="check", advisory="unknown", closed=False, open_claim=False, reason="unnamed_parts")
        return base
    scope = _scope(camp, alert)
    if not scope:
        base["reason"] = "out_of_scope"
        return base
    if _exception(camp, alert):
        base.update(applies=True, status="check", closed=False, open_claim=False, reason="explicit_exception")
        return base
    if alert.get("ambiguous"):
        base.update(
            applies=True, status="unknown", review=True, closed=False, open_claim=False,
            available=None, all_day=False, all_day_inferred=False,
            reason=alert.get("ambiguity") or "ambiguous", intervals=list(alert.get("intervals") or []),
        )
        return base
    if alert.get("recurrence"):
        base["applies"] = True
        base["open_claim"] = False
        base["all_day"] = False
        if recurrence_active(alert["recurrence"], moment):
            base.update(status="closed", closed=True, reason="recurrence", melbourne=occurrence_bounds(alert["recurrence"], moment))
        else:
            base.update(status="check", closed=False, reason="outside_recurrence")
        return base
    if alert.get("window_confirmed") and alert.get("intervals") and scope in {"full", "named"}:
        return _confirmed_window(base, alert, moment)
    if alert.get("intervals") and scope in {"full", "named"}:
        return _interval_effect(base, alert, moment)
    if alert.get("until_further_notice") and scope in {"full", "named"}:
        tz = ZoneInfo(alert.get("timezone") or "Australia/Canberra")
        local_day = moment.astimezone(tz).date()
        if alert.get("start") and local_day < dt.date.fromisoformat(alert["start"]):
            base.update(applies=True, status="upcoming", closed=False, open_claim=False, reason="not_started", reopen_at=None)
        else:
            base.update(
                applies=True, status="closed", closed=True, open_claim=False, reason="until_further_notice",
                reopen_at=None, expected_note=alert.get("expected_note"), date_inferred=False,
                reopen_instant_known=False, all_day=True,
            )
        return base
    inside = _range_contains(alert, moment)
    if scope == "pitch":
        base["applies"] = True
        base["open_claim"] = False
        base["end_precision"] = "date"
        base["reopen_instant_known"] = False
        if inside is None:
            base.update(status="unknown", review=True, closed=False, reason="undated_pitch")
        elif inside:
            base.update(status="closed", closed=True, reason="pitch")
        else:
            base.update(status="check", closed=False, reason="outside_dates")
        return base
    if scope == "named":
        base["applies"] = True
        base["open_claim"] = False
        base["end_precision"] = "date"
        base["reopen_instant_known"] = False
        if inside:
            base.update(status="closed", closed=True, reason="named_camp")
        else:
            base.update(status="check", closed=False, reason="outside_dates")
        return base
    if scope == "partial":
        base["applies"] = True
        base["open_claim"] = False
        base["end_precision"] = "date"
        base["reopen_instant_known"] = False
        if inside:
            base.update(status="partial", partial=True, closed=False, reason="partial_area")
        else:
            base.update(status="check", closed=False, reason="outside_dates")
        return base
    base["reason"] = "unhandled_scope"
    return base


def resolve(camp, decisions):
    summary = {
        "camp_id": camp.get("id"),
        "status": "check",
        "closed": False,
        "open_claim": False,
        "available": None,
        "partial": False,
        "review": False,
        "all_day": False,
        "all_day_inferred": False,
        "alert_ids": [],
        "advisories": [],
        "advisory": None,
        "reopen_at": None,
        "expected_note": None,
        "date_inferred": False,
        "latest_wins": False,
        "in_inventory": camp.get("inventory_role") in {"candidate", "pilot"},
    }
    applied = [row for row in decisions if row.get("applies")]
    summary["alert_ids"] = [row.get("alert_id") for row in applied]
    summary["advisories"] = [row.get("alert_id") for row in applied if row.get("advisory")]
    if any(row.get("advisory") == "unknown" for row in applied):
        summary["advisory"] = "unknown"
    unknowns = [row for row in applied if row.get("status") == "unknown"]
    closers = [row for row in applied if row.get("closed") or row.get("partial")]
    exceptions = [row for row in applied if row.get("reason") == "explicit_exception"]
    if unknowns and closers:
        summary.update(status="unknown", review=True, closed=False, open_claim=False, all_day=False, all_day_inferred=False)
        return summary
    shapes = {(row.get("status"), row.get("all_day")) for row in closers if row.get("closed")}
    if len(shapes) > 1:
        summary.update(status="unknown", review=True, closed=False, open_claim=False, all_day=False, latest_wins=False)
        return summary
    if unknowns:
        summary.update(
            status="unknown", review=True, closed=False, open_claim=False, all_day=False,
            all_day_inferred=False, available=None, intervals=unknowns[0].get("intervals") or [],
        )
        return summary
    if exceptions:
        summary.update(status="check", closed=False, open_claim=False, reason="explicit_exception")
        return summary
    upcoming = [row for row in applied if row.get("status") == "upcoming"]
    if upcoming and not closers:
        summary.update(
            status="upcoming", closed=False, open_claim=False,
            melbourne=next((row.get("melbourne") for row in upcoming if row.get("melbourne")), None),
            generic_overrode=False if camp.get("generic_camping_text") else None,
        )
        return summary
    if any(row.get("partial") for row in applied) and not any(row.get("closed") for row in applied):
        summary.update(status="partial", partial=True, closed=False, open_claim=False, reopen_instant_known=False, end_precision="date")
        return summary
    if any(row.get("closed") for row in applied):
        closed_rows = [row for row in applied if row.get("closed")]
        summary.update(
            status="closed",
            closed=True,
            open_claim=False,
            reopen_at=None,
            expected_note=next((row.get("expected_note") for row in closed_rows if row.get("expected_note")), None),
            date_inferred=False,
            melbourne=next((row.get("melbourne") for row in closed_rows if row.get("melbourne")), None),
            all_day=any(row.get("all_day") for row in closed_rows),
            reopen_instant_known=False if any(row.get("reopen_instant_known") is False for row in closed_rows) else None,
            end_precision=next((row.get("end_precision") for row in closed_rows if row.get("end_precision")), None),
        )
        if camp.get("generic_camping_text"):
            summary["generic_overrode"] = False
        return summary
    return summary


def apply_alerts(camps, raw_alerts, moment):
    good = []
    for raw in raw_alerts or []:
        parsed = normalise_alert(raw)
        if parsed.get("ok"):
            good.append(parsed["alert"])
    alerts = dedupe_notices(good)
    out = []
    for camp in camps or []:
        decisions = [effect(camp, alert, moment) for alert in alerts]
        out.append(resolve(camp, decisions))
    return out


def bulletin_rows(alert):
    """Desert bulletin rows are not campgrounds and do not cross into Queensland."""
    parsed = alert if alert.get("rows") and alert.get("asset_class") else (normalise_alert(alert).get("alert") or {})
    rows = []
    for row in parsed.get("rows") or []:
        kind = row.get("entity_type") or "unknown"
        rows.append({
            "name": row.get("name") or "",
            "entity_type": kind,
            "becomes_campground": False,
            "in_pilot": False,
            "transfers_across_states": False,
            "open_claim": False,
            "closed_claim": False,
            "reason": "desert_excluded" if kind in {"park", "campground", "pitch"} else "not_a_campground",
        })
    return rows


def fire_status(camp, observation=None):
    """Link out. Do not invent a rating, a no-ban, or a territory-wide closure."""
    obs = observation or {}
    row = {
        "camp_id": camp.get("id"),
        "status": "unknown",
        "rating": None,
        "label": FIRE_UNKNOWN_LABEL,
        "banned": None,
        "closed": False,
        "state_wide_closure": False,
        "borrowed_from": None,
        "link": camp.get("fire_link") or FIRE_LINKS.get(camp.get("state") or "", ""),
        "ignored_reason": "",
    }
    if obs.get("source") in {"nsw_rfs", "nsw"} or obs.get("authority") == "nsw_rfs" or obs.get("borrow_nsw"):
        row["ignored_reason"] = "no_nsw_fdr_fallback"
        return _checked_fire(row)
    if camp.get("state") == "sa" and (
        obs.get("authority") in {"cfs", "sa_cfs"} or obs.get("kind") == "total_fire_ban" or obs.get("verified")
    ):
        row["ignored_reason"] = "tfb_is_not_universal_park_closure"
        return _checked_fire(row)
    if "banner" in obs and not obs.get("banner") and not obs.get("verified"):
        row["ignored_reason"] = "missing_banner_is_not_no_ban"
        return _checked_fire(row)
    if not _ban_verified(obs):
        if obs:
            row["ignored_reason"] = "unverified_fire_value"
        return _checked_fire(row)
    covers = obs.get("scope") == "all" or camp.get("id") in set(obs.get("area_ids") or [])
    if camp.get("closes_on_verified_tfb") and covers:
        row["status"] = "conditional_closure"
        row["closed"] = True
        row["banned"] = True
        row["rating"] = None
        row["state_wide_closure"] = False
        row["label"] = CONDITIONAL_TFB_LABEL
        return _checked_fire(row)
    row["ignored_reason"] = "ban_does_not_close_this_camp"
    return _checked_fire(row)


def interpret_fetch(result, previous=None, now=None):
    """A failed or empty source must not delete camps or call them open."""
    now = now or dt.datetime.now(dt.timezone.utc)
    status = result.get("status")
    body = result.get("body")
    empty = not str(body or "").strip()
    malformed = bool(result.get("malformed")) or (status == 200 and result.get("parsed_ok") is False)
    empty_alerts = bool(result.get("empty_alerts"))
    sentinel = bool(result.get("sentinel"))
    if status == 200 and empty_alerts and sentinel:
        return {
            "ok": False,
            "anomaly": "empty_feed",
            "degraded": True,
            "stale": True,
            "reopened": False,
            "open_inferred": False,
            "no_ban_inferred": False,
            "camps_removed": False,
            "operational_claim": False,
            "retain_closures": bool(previous),
            "uncertainty": True,
            "status": "unknown",
        }
    ok = status == 200 and not empty and not malformed and not empty_alerts
    if ok:
        return {
            "ok": True, "stale": False, "degraded": False, "camps_removed": False, "reopened": False,
            "open_inferred": False, "no_ban_inferred": False, "operational_claim": True, "uncertainty": False,
        }
    return _failed_fetch(previous, now)


def proximity_decision(metres, reviewed_crosswalk=False):
    """Distance never merges or relocates a camp, including under 200 m."""
    return {
        "merged": False,
        "relocated": False,
        "unresolved": True,
        "reason": "proximity_only_unsafe",
        "metres": metres,
        "reviewed_crosswalk_used": False,
    }


def eligible_count_from_tag_totals(totals):
    """Raw camp_site / caravan_site / camp_pitch totals are not eligible camps."""
    return None


def classify_manifest(rows):
    """URL inventory. PDFs, errors and alert pages are not campground counts."""
    kinds = {}
    errors = 0
    for row in rows or []:
        kind = row.get("source_kind") or ""
        kinds[kind] = kinds.get(kind, 0) + 1
        if row.get("error"):
            errors += 1
    return {
        "url_count": len(rows or []),
        "by_kind": kinds,
        "fetch_errors": errors,
        "campground_count": None,
        "pdf_assets_are_camps": False,
        "fetch_errors_are_camps": False,
        "alert_pages_are_active_closures": False,
        "claim_320_campgrounds": False,
    }


def carry_forward_fire(last_value, validity_date, target_date):
    """A ban or no-ban value dies with its validity date."""
    if str(validity_date or "") < str(target_date or ""):
        return {"tfb": "unknown", "fdr": "unknown", "carry_forward_no_ban": False, "banned": None, "rating": None}
    return {"tfb": "unknown", "fdr": "unknown", "carry_forward_no_ban": False, "banned": None, "rating": None}


def use_html_point_as_camp_geometry(latlng):
    """A park-page coordinate is not a campground entrance."""
    return False


def esa_grant_covers_parks_or_fire(target):
    """The named incident-feed grant does not cover Parks text or FDR/TFB."""
    return False


def rss_absence_is_all_clear(rss_items, other_messages=0):
    """Zero RSS items is not an empty incident picture and not a no-ban."""
    return {"treat_as_empty": False, "infer_no_ban_or_open": False, "other_messages": other_messages, "rss_items": rss_items}


def asset_point_is_entrance():
    return False


def capacity_counts_as_extra_camps(amount):
    """A family or guest capacity is one facility, not that many campgrounds."""
    return 0


def scale_bar_labels_are_pitches(labels):
    return False


def cottermouth_children(children):
    """Site-labelled camp_site polygons are children, not extra campgrounds."""
    rows = list(children or [])
    points = sum(1 for row in rows if row.get("representative_point_inside_parent"))
    entire = sum(1 for row in rows if row.get("entire_polygon_inside_parent"))
    return {
        "child_features": len(rows),
        "representative_points_inside_parent": points,
        "entire_polygons_inside_parent": entire,
        "boundary_crossing_review": len(rows) - entire,
        "publish_as_new_campgrounds": False,
        "added_to_camp_count": 0,
        "treat_as_child_candidates": True,
    }


def activation_blockers(state):
    release = (state or {}).get("release") or {}
    blockers = []
    if release.get("public") is not True:
        blockers.append("public_false")
    if release.get("signup") is not True:
        blockers.append("signup_false")
    if release.get("digest") is not True:
        blockers.append("digest_false")
    for gate in release.get("gates") or []:
        if gate.get("ok") is not True:
            blockers.append(gate.get("id") or "gate")
    return blockers


def build_preview_report(moment=None):
    """Local preview only. send and enrol stay false."""
    import states
    moment = moment or dt.datetime(2026, 11, 11, 7, 30, tzinfo=dt.timezone.utc)
    doc = load_candidates()
    raw_alerts = load_alerts()
    camps = selectable_camps(doc["records"])
    statuses = apply_alerts(camps, raw_alerts, moment)
    examples = apply_alerts(
        [row for row in doc["records"] if row.get("inventory_role") == "fixture_only"],
        raw_alerts,
        moment,
    )
    fires = [fire_status(camp) for camp in camps]
    act = states.by_slug("act")
    sa = states.by_slug("sa")
    report = {
        "send": False,
        "enrol": False,
        "public": False,
        "preview_only": True,
        "live_fetch": False,
        "moment": moment.isoformat(),
        "evidence_checked": "2026-11-09",
        "evidence_note": "George brief and evidence CSV are unverified inputs. This run did not refetch ACT or SA sources.",
        "inventory": summarise_inventory(doc),
        "statuses": statuses,
        "fixture_examples_not_inventory": examples,
        "fire": fires,
        "blockers": {"act": activation_blockers(act), "sa": activation_blockers(sa)},
        "resend": {
            "create_remote_segments": False,
            "enrol": False,
            "send": False,
            "variables": [
                {
                    "name": "RESEND_SEGMENT_ACT_ID",
                    "required_before_activation": True,
                    "read_by_signup": False,
                    "note": "Do not create the segment in this change. Setting the variable enrols nobody while the hold stands.",
                },
                {
                    "name": "RESEND_SEGMENT_SA_ID",
                    "required_before_activation": True,
                    "read_by_signup": False,
                    "note": "Do not create the segment in this change. Setting the variable enrols nobody while the hold stands.",
                },
            ],
            "existing_unchanged": [
                "RESEND_API_KEY", "CONFIRM_SECRET", "FROM_EMAIL", "SITE_URL",
                "RESEND_SEGMENT_ID", "RESEND_SEGMENT_NSW_ID", "RESEND_SEGMENT_QLD_ID",
            ],
        },
        "implemented": [
            "Disabled ACT and SA configs with release gates",
            "Candidate and pilot records kept out of the public build",
            "Structured closure matcher for the evidence cases",
            "Sitemap url/loc counter that refuses a campground count",
            "Legacy park JSON kept as alias hints only",
            "OSM camp_pitch children not counted as camps",
            "Fire link-out with no fabricated rating and no NSW fallback",
            "Source failure policy that does not reopen camps",
            "Signup and digest refusal, including when segment env vars are set",
            "Explicit local preview report",
        ],
        "not_implemented": [
            "Live HTML extraction",
            "Network fetch of the ACT or SA inventories during the public build",
            "Statewide OpenStreetMap extract, state-boundary clipping, or official coordinate verification",
            "Publication of GeoPDF-derived geometry or campground map images",
            "Fire district polygons or a dated ESA/CFS value parser",
            "Public camp pages, signup checkboxes or digest sends",
            "Treating the 24-facility research cohort or the three-camp test set as a state launch",
            "Resend segment creation",
            "WA, NT or other states",
        ],
        "next_steps": [
            "Audit the eight ACT detail pages, parents, access and coordinates. Keep Woods Reserve closed with no reopen date.",
            "Resolve Parks ACT and ESA reuse before republishing any ACT text. Do not extend the act.gov.au licence.",
            "Classify current SA sitemap pages. Do not filter camps with the 2017 JSON. Keep the pilot at Pink Gum, Wirra and Stringybark until that work is reviewed.",
            "Human-review the Pink Gum booking exception, Wirra occurrences, Chowilla overlaps and the desert bulletin. Leave desert and route-dependent sites out.",
            "Prove a dated ESA and CFS parser, district boundaries and reuse terms, or keep the link-out.",
            "Only after approval, create the two Resend segments, set RESEND_SEGMENT_ACT_ID and RESEND_SEGMENT_SA_ID, remove the token.js hold, and remove those segments on unsubscribe.",
            "Re-run the Victoria, New South Wales and Queensland build and tests before any enabled flag.",
        ],
    }
    import act_sa_fixtures
    evaluation = act_sa_fixtures.evaluate_all()
    report["proposed_fixtures"] = {
        "ran": evaluation["ran"],
        "not_adopted": evaluation["not_adopted"],
        "production_matcher_was_already_executed": evaluation["production_matcher_was_already_executed"],
        "agreements": {
            "full": sum(1 for row in evaluation["results"] if row["agreement"] == "full"),
            "safety": sum(1 for row in evaluation["results"] if row["agreement"] == "safety"),
            "not_adopted": sum(1 for row in evaluation["results"] if row["agreement"] == "not_adopted"),
        },
    }
    if contains_no_rating(report):
        raise RuntimeError("preview report used the No Rating label")
    return report


def _local(tag):
    return str(tag).split("}")[-1]


def _aware(moment):
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment


def _clock(value):
    hour, minute = str(value).split(":")
    return dt.time(int(hour), int(minute))


def _recurrence_ok(spec):
    try:
        dt.date.fromisoformat(spec["start_date"])
        dt.date.fromisoformat(spec["end_date"])
        if not spec.get("weekdays") or not spec.get("start_time") or not spec.get("end_time"):
            return False
        ZoneInfo(spec.get("timezone") or "Australia/Adelaide")
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _date_excluded(day, ranges):
    for span in ranges:
        if dt.date.fromisoformat(span[0]) <= day <= dt.date.fromisoformat(span[1]):
            return True
    return False


def _blank(alert_id):
    return {
        "alert_id": alert_id,
        "applies": False,
        "status": None,
        "closed": False,
        "open_claim": False,
        "available": None,
        "all_day": False,
        "partial": False,
        "advisory": None,
        "review": False,
        "reason": "",
    }


def _site_numbers(target):
    if target.get("site_numbers"):
        return {int(number) for number in target["site_numbers"]}
    span = target.get("site_number_range")
    if isinstance(span, list) and len(span) == 2 and all(isinstance(number, int) for number in span):
        start, end = span
        if 0 < start <= end <= 500:
            return set(range(start, end + 1))
    return set()


def _scope(camp, alert):
    for target in alert.get("targets") or []:
        tid = target.get("id") or ""
        scope = target.get("scope") or "full"
        numbers = _site_numbers(target)
        names = {str(name).casefold() for name in target.get("names") or []}
        parent = target.get("parent_id") or alert.get("parent_id") or tid
        if scope == "partial":
            if camp.get("entity_type") == "pitch" and camp.get("parent_id") == parent and camp.get("site_number") in numbers:
                return "pitch"
            if (
                camp.get("entity_type") == "campground"
                and camp.get("parent_id") == parent
                and names
                and str(camp.get("name") or "").casefold() in names
            ):
                return "named"
            if camp.get("aggregate") and camp.get("parent_id") == parent and (numbers or names):
                return "partial"
            continue
        if scope == "full" and tid and tid in {camp.get("id"), camp.get("parent_id")}:
            if camp.get("entity_type") in {"campground", "pitch", "park"}:
                return "full"
        if scope == "named" and tid == camp.get("id"):
            return "named"
    return None


def _parent_mentioned(camp, alert):
    ids = {camp.get("id"), camp.get("parent_id")}
    for target in alert.get("targets") or []:
        if target.get("id") in ids:
            return True
    return False


def _exception(camp, alert):
    for row in alert.get("exceptions") or []:
        if row.get("kind") != "remain_open":
            continue
        if row.get("id") and row.get("id") == camp.get("id"):
            return True
        same_name = str(row.get("name") or "").casefold() == str(camp.get("name") or "").casefold()
        same_parent = row.get("parent_id") in (None, "", camp.get("parent_id"))
        if row.get("name") and same_name and same_parent:
            return True
    return False


def _interval_contains(interval, moment, tz):
    start = dt.datetime.fromisoformat(interval["start"])
    end = dt.datetime.fromisoformat(interval["end"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    return start <= moment.astimezone(tz) < end.astimezone(tz)


def _interval_effect(base, alert, moment):
    tz = ZoneInfo(alert.get("timezone") or "Australia/Adelaide")
    intervals = list(alert.get("intervals") or [])
    base["applies"] = True
    base["open_claim"] = False
    base["intervals"] = intervals
    if any(window_is_all_day(interval) for interval in intervals):
        base.update(status="unknown", review=True, closed=False, all_day=False, all_day_inferred=False, reason="all_day_not_inferred")
        return base
    hits = [interval for interval in intervals if _interval_contains(interval, moment, tz)]
    base["all_day"] = False
    base["all_day_inferred"] = False
    if hits:
        base.update(status="closed", closed=True, reason="interval")
    else:
        base.update(status="check", closed=False, reason="outside_interval")
    return base


def _range_contains(alert, moment):
    tz = ZoneInfo(alert.get("timezone") or "Australia/Adelaide")
    local_day = moment.astimezone(tz).date()
    if alert.get("start") and alert.get("end_date"):
        return dt.date.fromisoformat(alert["start"]) <= local_day <= dt.date.fromisoformat(alert["end_date"])
    return None


def _ban_verified(obs):
    if not obs.get("verified") or not obs.get("reuse_cleared"):
        return False
    if obs.get("authority") != "act_esa":
        return False
    if obs.get("scope") not in {"all", "partial"}:
        return False
    if obs.get("scope") == "partial" and not obs.get("area_ids"):
        return False
    try:
        dt.date.fromisoformat(str(obs.get("valid_on") or "")[:10])
    except ValueError:
        return False
    return True


def _checked_fire(row):
    if contains_no_rating(row):
        raise RuntimeError("fire status used the No Rating label")
    return row


def _failed_fetch(previous, now):
    base = {
        "ok": False,
        "degraded": True,
        "camps_removed": False,
        "reopened": False,
        "open_inferred": False,
        "no_ban_inferred": False,
        "status": "unknown",
    }
    checked_raw = (previous or {}).get("checked_at")
    if not checked_raw:
        base.update(stale=True, operational_claim=False, retain_closures=False, uncertainty=True)
        return base
    checked = dt.datetime.fromisoformat(checked_raw)
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=dt.timezone.utc)
    age_h = (now - checked).total_seconds() / 3600.0
    base["checked_at"] = checked_raw
    base["age_hours"] = age_h
    base["retain_closures"] = True
    if age_h <= 6:
        base.update(stale=False, degraded=False, operational_claim=True, uncertainty=False)
    elif age_h <= 24:
        base.update(stale=True, degraded=True, operational_claim=True, uncertainty=True)
    else:
        base.update(stale=True, degraded=True, operational_claim=False, uncertainty=True, status="unknown")
    return base
