#!/usr/bin/env python3
"""Status for the 49 SA notices from their Adelaide windows.

Saved status labels are not an input. A result is never open. Expired
notices stay unknown. Numbered sites are reported on the parent booking id.
"""
import datetime as dt
from zoneinfo import ZoneInfo

ADELAIDE = ZoneInfo("Australia/Adelaide")
# Same-name traps: these booking ids must not be attached to the notice.
FORBIDDEN = {3: {"67710"}, 41: {"67710"}, 44: {"72075"}, 35: set()}
CONFLICT_INDEXES = {27, 28, 30}


def load_notices(path):
    import json
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["notices"]


def evaluate_all(notices, moment):
    rows = [evaluate(notice, moment) for notice in notices]
    by_index = {row["source_index"]: row for row in rows}
    bookings = _bookings(notices, rows, moment)
    handled = [row for row in rows if row["disposition"] == "handled"]
    held = [row for row in rows if row["disposition"] == "held_unknown"]
    return {
        "notices": rows,
        "by_index": by_index,
        "bookings": bookings,
        "handled": len(handled),
        "held_unknown": len(held),
        "open_inferred": any(row["open_inferred"] for row in rows),
        "geometry_exported": any(row["geometry_exported"] for row in rows),
    }


def evaluate(notice, moment):
    moment = _aware(moment)
    relations = _relations(notice, moment)
    booking_ids = []
    for facility in notice.get("affected_camp_facilities") or []:
        booking_id = str(facility.get("booking_id") or "")
        if booking_id and booking_id not in FORBIDDEN.get(notice["source_index"], set()):
            booking_ids.append(booking_id)
    unmapped = list((notice.get("unmapped_camp_scope") or {}).keys())
    camp_status = _camp_status(notice, relations)
    if notice["source_index"] in CONFLICT_INDEXES or _mentions_conflict(notice):
        camp_status = "unknown"
    if notice["source_index"] == 45:
        camp_status = "not_a_camp_closure"
    if _exception_unknown(notice) and camp_status == "closed":
        camp_status = "unknown"
    disposition = "held_unknown" if camp_status in {"unknown", "expired_not_open"} else "handled"
    return {
        "source_index": notice["source_index"],
        "primary_type": notice["primary_type"],
        "scope_level": notice["scope_level"],
        "booking_ids": booking_ids,
        "unmapped_names": unmapped,
        "camp_status": camp_status,
        "disposition": disposition,
        "open_inferred": False,
        "geometry_exported": False,
        "child_sites_emitted": False,
        "relations": relations,
    }


def _camp_status(notice, relations):
    kind = notice.get("primary_type") or ""
    if kind in {"advisory", "access_restriction"} and not _effect_closes(notice):
        return "not_a_camp_closure"
    if "active" in relations and kind == "full_closure":
        return "closed"
    if "active" in relations and kind == "partial_closure":
        return "partial"
    if "future" in relations and "active" not in relations:
        return "upcoming"
    if relations and set(relations) <= {"expired", "not_in_window"} and "expired" in relations:
        return "expired_not_open"
    if relations == ["not_in_window"] or (relations and set(relations) == {"not_in_window"}):
        return "not_in_window"
    if "undated" in relations or "unknown_zone" in relations or "no_window" in relations:
        return "unknown"
    if not relations:
        return "unknown"
    return "unknown"


def _relations(notice, moment):
    found = []
    for window in notice.get("windows") or []:
        found.append(_window_relation(window, moment))
    recurrence = notice.get("recurrence") or {}
    kind = recurrence.get("type")
    if kind == "weekly":
        found.append("active" if _weekly(recurrence, moment) else "not_in_window")
    elif kind == "night_blocks":
        found.append("active" if _night_blocks(recurrence.get("night_blocks") or [], moment) else "not_in_window")
    elif kind == "night_blocks_by_zone":
        found.append("unknown_zone")
    elif kind == "annual":
        found.append(_window_relation(recurrence.get("current_occurrence") or {}, moment))
    if not found:
        found.append("no_window")
    return found


def _window_relation(window, moment):
    start_raw = window.get("start_local")
    if not start_raw:
        return "undated"
    start = dt.datetime.fromisoformat(start_raw)
    end_raw = window.get("end_local")
    end = dt.datetime.fromisoformat(end_raw) if end_raw else None
    if moment < start:
        return "future"
    if end is not None and moment >= end:
        return "expired"
    if end is not None and start <= moment < end:
        return "active"
    return "undated"


def _weekly(spec, moment):
    if spec.get("weekday") != "Wednesday" or moment.astimezone(ADELAIDE).weekday() != 2:
        return False
    start_day = dt.date.fromisoformat(spec["programme_start"])
    end_day = dt.date.fromisoformat(spec["programme_end"])
    local = moment.astimezone(ADELAIDE)
    if local.date() < start_day or local.date() > end_day:
        return False
    for start, end in spec.get("excluded_date_ranges_inclusive") or []:
        if dt.date.fromisoformat(start) <= local.date() <= dt.date.fromisoformat(end):
            return False
    return local.time() >= dt.time(18, 0)


def _night_blocks(blocks, moment):
    """Every listed date is a closure night, including the last date."""
    local = moment.astimezone(ADELAIDE)
    for block in blocks:
        first = dt.date.fromisoformat(block["first_listed_date"])
        last = dt.date.fromisoformat(block["last_listed_date"])
        start_t = _clock(block["nightly_start_local"])
        end_t = _clock(block["nightly_end_local_next_day"])
        day = first
        while day <= last:
            start = dt.datetime.combine(day, start_t, ADELAIDE)
            end = dt.datetime.combine(day + dt.timedelta(days=1), end_t, ADELAIDE)
            if start <= local < end:
                return True
            day += dt.timedelta(days=1)
    return False


def _bookings(notices, rows, moment):
    """Per booking id after conflicts. Notice 45 cannot clear notice 38."""
    by_index = {row["source_index"]: row for row in rows}
    effects = {}
    for notice, row in zip(notices, rows):
        facilities = {
            str(facility.get("booking_id") or ""): facility
            for facility in notice.get("affected_camp_facilities") or []
        }
        for booking_id in row["booking_ids"]:
            status = _facility_status(notice, facilities.get(booking_id) or {}, row["camp_status"])
            effects.setdefault(booking_id, []).append(status)
    if 38 in by_index and 45 in by_index:
        for booking_id in by_index[38]["booking_ids"]:
            effects[booking_id] = [status for status in effects.get(booking_id, []) if status != "not_a_camp_closure"]
            if not effects[booking_id]:
                effects[booking_id] = [by_index[38]["camp_status"]]
    resolved = {}
    for booking_id, statuses in effects.items():
        resolved[booking_id] = _combine(statuses)
    return resolved


def _combine(statuses):
    """A later or older notice must not turn a real window into open."""
    if "closed" in statuses and "unknown" in statuses:
        return "unknown"
    if "closed" in statuses:
        return "closed"
    if "partial" in statuses and "unknown" in statuses:
        return "unknown"
    if "partial" in statuses:
        return "partial"
    if "upcoming" in statuses:
        return "upcoming"
    if "expired_not_open" in statuses:
        return "expired_not_open"
    if "not_in_window" in statuses:
        return "not_in_window"
    if "park_alert" in statuses:
        return "park_alert"
    if statuses and set(statuses) == {"not_a_camp_closure"}:
        return "not_a_camp_closure"
    return "unknown"


def _facility_status(notice, facility, notice_status):
    """Notice 42 closes Malkumba-Coongie Lakes National Park.

    It says significant parts of Innamincka Regional Reserve are closed and
    does not name those campgrounds. Those camps are a park alert, not closed
    and not a partial closure. Every other notice keeps one status.
    """
    if notice.get("source_index") != 42:
        return notice_status
    effect = str((facility or {}).get("effect") or "")
    if effect == "closed":
        return "closed"
    if effect.startswith("unknown"):
        return "park_alert"
    return notice_status


def _effect_closes(notice):
    for facility in notice.get("affected_camp_facilities") or []:
        effect = str(facility.get("effect") or "")
        if effect.startswith("closed"):
            return True
    return False


def _exception_unknown(notice):
    for facility in notice.get("affected_camp_facilities") or []:
        if str(facility.get("effect") or "").startswith("exception_unknown"):
            return True
    return False


def _mentions_conflict(notice):
    text = " ".join(notice.get("unknowns") or []).lower()
    return "conflict" in text


def _clock(value):
    hour, minute = str(value).split(":")
    return dt.time(int(hour), int(minute))


def _aware(moment):
    if moment.tzinfo is None:
        raise ValueError("moment needs a timezone")
    return moment
