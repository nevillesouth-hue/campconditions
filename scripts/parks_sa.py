#!/usr/bin/env python3
"""Live Parks SA closures index.

One GET of the public closures page per build. The stored record is the
notice title, the park name, the date window and the link. The body and any
photos are discarded. Camp status still comes from the reviewed notice rules
in act_sa_notices, including the booking-id traps. A camp is closed only when
that notice closes the campground or camping area and the date window covers
the moment. A failed read keeps the last good copy and does not fail the build.
"""
import copy
import datetime as dt
import gzip
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import act_sa_notices

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOSURES_URL = "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts"
USER_AGENT = (
    "CampConditions.au/1.0 (South Australia park closures; "
    "contact campconditions@outlook.com; +https://campconditions.au)"
)
REQUEST_TIMEOUT = 20
STEP_LIMIT = 60
MANY_NOTICES = 10
ADELAIDE = ZoneInfo("Australia/Adelaide")
SNAPSHOT_PATH = os.path.join(ROOT, "data", "act-sa", "fixtures", "sa-alerts-index-2026-11-10.json")
CAMP_PATH = os.path.join(ROOT, "data", "act-sa", "inventory", "official-campgrounds.json")
STORED_FIELDS = {"title", "park", "start", "end", "link", "open_ended", "camp_ids"}
# Same-name traps from the reviewed rules. These booking ids belong to a
# different park and must not be attached from a lookalike heading.
_TRAPS = {
    "67710": ("ikara", "flinders"),
    "72075": ("ikara", "flinders"),
}
_GENERIC_PARK = {
    "national", "park", "parks", "conservation", "regional", "reserve",
    "wilderness", "protection", "area", "recreation", "and", "the", "of",
    "mount", "mt",
}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
_WEEKDAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_SKIP_WINDOW = re.compile(
    r"\bevery\b|\bvarious\b|\bintermittent|\bannually\b|\beach year\b|\bselected days\b|see details for (?:all )?dates",
    re.I,
)
_OPEN_ENDED = re.compile(r"until further notice|for the foreseeable future", re.I)
_CAMP_WORD = r"campgrounds?|campsites?|camping areas?"
_CLOSES_CAMP = re.compile(
    rf"\b(?:{_CAMP_WORD})\b.{{0,80}}\b(?:is|are|will be|remain|remains)(?:\s+\w+){{0,3}}\s+closed\b"
    rf"|\bclosed\b.{{0,60}}\b(?:{_CAMP_WORD})\b"
    rf"|\b(?:{_CAMP_WORD})\b.{{0,40}}\bclosed\b",
    re.I,
)
_CAMPS = None


def allowed_url(url):
    """robots.txt allows this path. Query strings and other paths are refused."""
    if not url or "?" in url or not url.startswith("https://www.parks.sa.gov.au/"):
        return False
    path = url[len("https://www.parks.sa.gov.au"):]
    if path.startswith(("/cpresources/", "/vendor/", "/.env", "/cache/")):
        return False
    return path.rstrip("/") == "/know-before-you-go/closures-and-alerts"


def parse_html(page, now=None, camps=None):
    """Notice cards. The sentence and any image are not kept."""
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page or "")
    now = now or dt.datetime.now(ADELAIDE)
    if camps is None:
        camps = published_camps()
    notices = []
    seen = set()
    for block in re.split(r'<div class="c-text[\s"]', text)[1:]:
        row = _card(block, now, camps)
        if not row or row["link"] in seen:
            continue
        seen.add(row["link"])
        notices.append(row)
    return notices


def paginated(page):
    """True when the index says another page exists. This reader does not follow it."""
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page or "")
    low = text.lower()
    if 'rel="next"' in low or "rel='next'" in low:
        return True
    if re.search(r'class="[^"]*pagination', low):
        return True
    if re.search(r"[?&]page=\d+", text):
        return True
    return False


def needs_javascript(page, notices):
    """True when the listing is empty because the page asked for JavaScript."""
    if notices:
        return False
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page or "")
    low = text.lower()
    return "javascript is required" in low or "enable javascript" in low


def published_camps():
    """Official Parks SA campgrounds a new notice can name.

    Held camps stay in this list. A notice can name The Pines or The Gums
    even when those campgrounds have no published coordinate. Park overlap
    still keeps Little Dip's Gums off a Ngarkat notice.
    """
    global _CAMPS
    if _CAMPS is not None:
        return _CAMPS
    try:
        with open(CAMP_PATH, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        _CAMPS = []
        return _CAMPS
    rows = []
    for row in doc.get("campgrounds") or []:
        booking_id = str(row.get("booking_id") or "")
        name = str(row.get("official_name") or "").strip()
        if booking_id and name:
            rows.append({
                "booking_id": booking_id,
                "name": name,
                "park": str(row.get("park_name") or ""),
                "published": row.get("coordinate_status") == "coordinates_attached",
            })
    _CAMPS = rows
    return _CAMPS


def catalogue_for(notices, live_rows):
    """Reviewed notices that are still on the index, plus a named camp a new notice closes.

    A live date window replaces the reviewed window. A weekly or 'various dates'
    notice keeps the reviewed windows. Booking-id traps stay in act_sa_notices.
    """
    by_link = {}
    for row in live_rows or []:
        link = str((row or {}).get("link") or "").rstrip("/")
        if link:
            by_link[link] = row
    chosen = []
    for notice in notices or []:
        url = str(notice.get("source_url") or "").rstrip("/")
        live = by_link.get(url)
        if not live:
            continue
        item = copy.deepcopy(notice)
        _apply_live_window(item, live)
        chosen.append(item)
    seen = {str(item.get("source_url") or "").rstrip("/") for item in chosen}
    index = 1000
    for row in live_rows or []:
        link = str((row or {}).get("link") or "").rstrip("/")
        if not link or link in seen:
            continue
        while index in act_sa_notices.CONFLICT_INDEXES or index == 45:
            index += 1
        synthetic = _synthetic(row, index)
        if not synthetic:
            continue
        chosen.append(synthetic)
        seen.add(link)
        index += 1
    return chosen


def adjust_scores(scored, notices):
    """An open-ended campground closure has no end date and is still closed.

    The reviewed engine treats a missing end as unknown. 'Until further notice'
    on a notice that already names a closed campground is that closure.
    """
    bookings = scored.setdefault("bookings", {})
    for notice in notices or []:
        if not notice.get("_open_ended"):
            continue
        if (notice.get("primary_type") or "") not in {"full_closure", "partial_closure"}:
            continue
        for facility in notice.get("affected_camp_facilities") or []:
            effect = str(facility.get("effect") or "")
            if not effect.startswith("closed"):
                continue
            booking_id = str(facility.get("booking_id") or "")
            if not booking_id or booking_id in act_sa_notices.FORBIDDEN.get(notice.get("source_index"), set()):
                continue
            if _trap(booking_id, " ".join(notice.get("parks") or [])):
                continue
            current = bookings.get(booking_id)
            if current in (None, "unknown", "not_a_camp_closure", "expired_not_open", "not_in_window"):
                bookings[booking_id] = "closed"
    return scored


def http_get(url, timeout, user_agent):
    """One GET. The caller supplies the timeout and the user agent."""
    if not allowed_url(url):
        raise ValueError("url not allowed")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            status = getattr(response, "status", 200) or 200
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return status, raw.decode("utf-8", "replace")


def read_index(fetch, now=None, timeout=REQUEST_TIMEOUT, step_limit=STEP_LIMIT, clock=None):
    """One request, bounded by the request timeout and the step limit.

    `fetch` is `fn(url, timeout, user_agent) -> (status, body)`. It is called
    at most once, and never with a query string.
    """
    clock = clock or time.monotonic
    now = now or dt.datetime.now(ADELAIDE)
    started = clock()

    def elapsed():
        return clock() - started

    if not allowed_url(CLOSURES_URL):
        return _fail("url not allowed")
    if elapsed() >= step_limit:
        return _fail("step limit")
    request_timeout = min(timeout, max(0.001, step_limit - elapsed()))
    try:
        status, body = fetch(CLOSURES_URL, request_timeout, USER_AGENT)
    except Exception as exc:
        timed = isinstance(exc, (TimeoutError, urllib.error.URLError)) and (
            isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
        )
        return _fail("timeout" if timed else "unavailable")
    if elapsed() > step_limit:
        return _fail("step limit")
    if status != 200:
        return _fail("http %s" % status)
    if paginated(body):
        return _fail("paginated")
    notices = parse_html(body, now)
    if needs_javascript(body, notices):
        return _fail("needs javascript")
    if not notices:
        return _fail("no notices")
    return {"ok": True, "notices": notices, "reason": ""}


def load_for_build(directory, now=None, fetch=None, timeout=REQUEST_TIMEOUT, step_limit=STEP_LIMIT, clock=None):
    """Read the index. On any failure, keep the last good file and its fetched time."""
    now = now or dt.datetime.now(ADELAIDE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ADELAIDE)
    previous = load_last_good(directory)
    fetch = fetch or http_get
    try:
        result = read_index(fetch, now=now, timeout=timeout, step_limit=step_limit, clock=clock)
    except Exception:
        result = _fail("unavailable")
    if result.get("ok") and not result.get("notices") and previous and len(previous["notices"]) >= MANY_NOTICES:
        result = _fail("structure change")
    if result.get("reason") == "no notices" and previous and len(previous["notices"]) >= MANY_NOTICES:
        result["reason"] = "structure change"
    if result.get("ok") and result.get("notices"):
        fetched = now.isoformat()
        save_last_good(directory, result["notices"], fetched)
        return {
            "ok": True,
            "notices": result["notices"],
            "fetched": fetched,
            "reason": "",
            "fallback": False,
            "use_snapshot": False,
        }
    reason = result.get("reason") or "unavailable"
    if previous and previous.get("notices"):
        return {
            "ok": False,
            "notices": previous["notices"],
            "fetched": previous.get("fetched") or "",
            "reason": reason,
            "fallback": True,
            "use_snapshot": False,
        }
    snapshot = load_snapshot()
    return {
        "ok": False,
        "notices": None,
        "fetched": snapshot.get("fetched") or "",
        "reason": reason,
        "fallback": True,
        "use_snapshot": True,
    }


def source_status(result):
    """status.json row. fetched stays at the last successful read when this one failed."""
    info = {
        "ok": bool(result.get("ok")),
        "url": CLOSURES_URL,
        "fetched": result.get("fetched") or "",
    }
    if not result.get("ok"):
        info["error"] = str(result.get("reason") or "unavailable")[:200]
        info["fallback"] = True
    return info


def stamp(result):
    """Checked line for the South Australia pages. checked is this data's read time."""
    info = {
        "label": "Parks SA closures",
        "agency": "Parks SA",
        "reader": "parks_sa",
        "wording": "checked",
        "checked": result.get("fetched") or "",
        "updated": result.get("fetched") or "",
        "feed": CLOSURES_URL,
    }
    if not result.get("ok"):
        info["stale"] = True
        info["stale_message"] = (
            "Parks SA closures could not be read for this update. "
            "These notices are from the last check that succeeded. "
            "Check the Parks SA closures and alerts page before you travel."
        )
    return info


def checked_copy(info, now):
    """'Parks SA closures checked <time>.' The time is when the page was read."""
    checked = str((info or {}).get("checked") or "")
    if not checked:
        return None
    try:
        check_at = dt.datetime.fromisoformat(checked)
    except ValueError:
        return None
    if check_at.tzinfo is None:
        check_at = check_at.replace(tzinfo=ADELAIDE)
    zone = now.tzinfo or ADELAIDE
    shown = check_at.astimezone(zone).strftime("%-d %B %Y, %-I:%M %p %Z")
    stale = (now - check_at) > dt.timedelta(days=2)
    return {
        "line": "Parks SA closures checked %s." % shown,
        "warning": (
            "Parks SA closures were checked at %s. That check is more than 2 days old. "
            "Check the Parks SA closures and alerts page before you travel."
        ) % shown,
        "stale": stale,
        "checked_iso": check_at.isoformat(),
        "newest_iso": check_at.isoformat(),
    }


def last_good_path(directory):
    return os.path.join(directory, "parks-sa-closures.json")


def save_last_good(directory, notices, fetched):
    os.makedirs(directory, exist_ok=True)
    path = last_good_path(directory)
    payload = {
        "url": CLOSURES_URL,
        "fetched": fetched,
        "notices": [_stored(row) for row in notices or [] if _stored(row)],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def load_last_good(directory):
    path = last_good_path(directory)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    notices = []
    for row in payload.get("notices") or []:
        stored = _stored(row)
        if stored:
            notices.append(stored)
    if not notices:
        return None
    return {"notices": notices, "fetched": str(payload.get("fetched") or "")}


def load_snapshot():
    """The committed 10 November index, used only when no last good copy exists."""
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return {"fetched": "", "urls": []}
    if not isinstance(doc, dict):
        return {"fetched": "", "urls": []}
    return doc


def _fail(reason):
    return {"ok": False, "notices": [], "reason": reason}


def _stored(row):
    title = _plain(str((row or {}).get("title") or ""))
    park = _plain(str((row or {}).get("park") or ""))
    link = str((row or {}).get("link") or "").rstrip("/")
    if not title or not park or not link.startswith("https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/"):
        return None
    if link.endswith("/closures-and-alerts") or "park-closure-descriptions" in link or "?" in link:
        return None
    stored = {"title": title, "park": park, "start": "", "end": "", "link": link}
    for key in ("start", "end"):
        value = str((row or {}).get(key) or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", value):
            stored[key] = value
    if (row or {}).get("open_ended") is True and not (stored["start"] and stored["end"]):
        stored["open_ended"] = True
    camps = []
    for item in (row or {}).get("camp_ids") or []:
        booking_id = str(item or "")
        if booking_id.isdigit() and booking_id not in camps and not _trap(booking_id, park):
            camps.append(booking_id)
    if camps:
        stored["camp_ids"] = camps
    return stored


def _card(block, now, camps):
    park_match = re.search(r'<p class="font-bold">(.*?)</p>', block, re.S | re.I)
    park = _plain(park_match.group(1) if park_match else "")
    link = ""
    for href in re.findall(r'href="(https://www\.parks\.sa\.gov\.au/know-before-you-go/closures-and-alerts/[^"#]+)"', block):
        href = href.rstrip("/")
        if href.endswith("/closures-and-alerts") or "park-closure-descriptions" in href:
            continue
        link = href
        break
    if not park or not link:
        return None
    sentence = _plain(re.sub(r"<a\b[^>]*>.*?</a>", " ", block, flags=re.S | re.I))
    start, end, open_ended = _window(sentence, now)
    row = {"title": park, "park": park, "start": start, "end": end, "link": link}
    if open_ended and not (start and end):
        row["open_ended"] = True
    camp_ids = _named_camps(sentence, park, camps)
    if camp_ids:
        row["camp_ids"] = camp_ids
    return _stored(row)


def _window(sentence, now):
    """One stated span. Recurring and 'various dates' notices keep no index window.

    'Open from 1 April to 31 October each year' is the opposite window: the
    named campgrounds are closed outside those dates.
    """
    season = _closed_outside_open_season(sentence, now)
    if season:
        return season[0], season[1], False
    if _SKIP_WINDOW.search(sentence or ""):
        return "", "", False
    span = _weekday_span(sentence, now) or _from_until(sentence, now)
    if span:
        return span[0], span[1], False
    if _OPEN_ENDED.search(sentence or ""):
        return "", "", True
    return "", "", False


def _closed_outside_open_season(sentence, now):
    """Campgrounds closed while a seasonal track is shut.

    The Ngarkat notice says the Border Track is open from 1 April to 31 October
    and that The Pines and The Gums are closed during the seasonal closure.
    """
    if not _CLOSES_CAMP.search(sentence or ""):
        return None
    match = re.search(
        rf"\bopen from\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}\s+to\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}",
        sentence or "",
        re.I,
    )
    if not match:
        return None
    open_day = int(match.group(1))
    open_month = _MONTHS[match.group(2).lower()]
    shut_day = int(match.group(3))
    shut_month = _MONTHS[match.group(4).lower()]
    local = now.astimezone(ADELAIDE)
    for year in (local.year - 1, local.year, local.year + 1):
        shut_on = _at(year, shut_month, shut_day, 0, 0)
        open_on = _at(year if open_month > shut_month else year + 1, open_month, open_day, 0, 0)
        if not shut_on or not open_on:
            continue
        start = shut_on + dt.timedelta(days=1)
        if local < open_on and start <= local:
            return start.isoformat(), open_on.isoformat()
        if local < start and (local.month, local.day) < (shut_month, shut_day):
            return start.isoformat(), open_on.isoformat()
    upcoming = None
    for year in (local.year - 1, local.year, local.year + 1):
        shut_on = _at(year, shut_month, shut_day, 0, 0)
        open_on = _at(year if open_month > shut_month else year + 1, open_month, open_day, 0, 0)
        if not shut_on or not open_on:
            continue
        start = shut_on + dt.timedelta(days=1)
        if start > local and (upcoming is None or start < upcoming[0]):
            upcoming = (start, open_on)
    if upcoming:
        return upcoming[0].isoformat(), upcoming[1].isoformat()
    return None


def _weekday_span(sentence, now):
    match = re.search(
        rf"\bfrom\s+{_WEEKDAY}\s+(\d{{1,2}})\s*[-–—]\s*{_WEEKDAY}\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})",
        sentence or "",
        re.I,
    )
    if not match:
        return None
    month = _MONTHS[match.group(3).lower()]
    year = int(match.group(4))
    start = _at(year, month, int(match.group(1)), 0, 0)
    end_day = _at(year, month, int(match.group(2)), 0, 0)
    if not start or not end_day:
        return None
    end = end_day + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _from_until(sentence, now):
    match = re.search(r"\bfrom\b(.+?)\buntil\b(.+?)(?:\.|$)", sentence or "", re.I | re.S)
    if not match:
        return None
    start = _side(match.group(1), now, is_end=False)
    end = _side(match.group(2), now, is_end=True)
    if not start or not end:
        return None
    if start["year"] is None and end["year"] is None:
        start["year"] = now.year
        end["year"] = now.year
    elif start["year"] is None:
        start["year"] = end["year"] if start["month"] <= end["month"] else end["year"] - 1
    elif end["year"] is None:
        end["year"] = start["year"] if end["month"] >= start["month"] else start["year"] + 1
    start_at = _finish_side(start, is_end=False)
    end_at = _finish_side(end, is_end=True)
    if not start_at or not end_at or end_at <= start_at:
        return None
    return start_at.isoformat(), end_at.isoformat()


def _side(fragment, now, is_end):
    clock, rest = _clock(fragment or "")
    year_match = re.search(r"\b(20\d{2})\b", rest)
    month_match = re.search(_MONTH, rest, re.I)
    day_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", rest, re.I)
    if not month_match or not day_match:
        return None
    return {
        "year": int(year_match.group(1)) if year_match else None,
        "month": _MONTHS[month_match.group(1).lower()],
        "day": int(day_match.group(1)),
        "clock": clock,
        "midnight": clock == ("midnight",),
    }


def _finish_side(side, is_end):
    if side["midnight"]:
        base = _at(side["year"], side["month"], side["day"], 0, 0)
        if not base:
            return None
        return base + dt.timedelta(days=1) if is_end else base
    if side["clock"] is None:
        base = _at(side["year"], side["month"], side["day"], 0, 0)
        if not base:
            return None
        return base + dt.timedelta(days=1) if is_end else base
    hour, minute = side["clock"]
    return _at(side["year"], side["month"], side["day"], hour, minute)


def _clock(fragment):
    match = re.search(r"\b(midnight|midday|noon|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", fragment or "", re.I)
    if not match:
        return None, fragment or ""
    raw = re.sub(r"\s+", "", match.group(1).lower())
    rest = (fragment[:match.start()] + " " + fragment[match.end():]).strip()
    if raw == "midnight":
        return ("midnight",), rest
    if raw in {"midday", "noon"}:
        return (12, 0), rest
    parts = re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)", raw)
    if not parts:
        return None, fragment or ""
    hour = int(parts.group(1))
    minute = int(parts.group(2) or 0)
    if parts.group(3) == "pm" and hour < 12:
        hour += 12
    if parts.group(3) == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None, fragment or ""
    return (hour, minute), rest


def _at(year, month, day, hour, minute):
    try:
        return dt.datetime(int(year), int(month), int(day), int(hour), int(minute), tzinfo=ADELAIDE)
    except (TypeError, ValueError):
        return None


def _named_camps(sentence, park, camps):
    if not _CLOSES_CAMP.search(sentence or ""):
        return []
    found = []
    for camp in camps or []:
        if _trap(camp["booking_id"], park):
            continue
        if not _park_overlap(park, camp.get("park") or ""):
            continue
        if _name_in(sentence, camp.get("name") or ""):
            found.append(camp["booking_id"])
    unique = []
    for booking_id in found:
        if booking_id not in unique:
            unique.append(booking_id)
    return unique


def _park_overlap(heading, park):
    left = set(_norm(heading).split()) - _GENERIC_PARK
    right = set(_norm(park).split()) - _GENERIC_PARK
    return bool(left and right and (left & right))


def _name_in(text, name):
    """Match 'The Pines' inside 'The Pines and the Gums campground'."""
    cleaned = re.sub(r"\s*\([^)]*\)", "", name or "")
    cleaned = re.sub(r"\b(campgrounds?|camping areas?|campsites?)\b", " ", cleaned, flags=re.I)
    core = _norm(cleaned)
    if len(core) < 6 or core in _GENERIC_PARK:
        return False
    return re.search(r"\b" + re.escape(core) + r"\b", _norm(text)) is not None


def _trap(booking_id, park):
    needles = _TRAPS.get(str(booking_id or ""))
    if not needles:
        return False
    text = (park or "").lower()
    return not any(needle in text for needle in needles)


def _apply_live_window(notice, live):
    start = str((live or {}).get("start") or "")
    end = str((live or {}).get("end") or "")
    if start and end:
        notice["windows"] = [{"start_local": start, "end_local": end, "precision": "index_window", "note": None}]
        notice["recurrence"] = None
        notice.pop("_open_ended", None)
        return
    if (live or {}).get("open_ended"):
        notice["windows"] = []
        notice["recurrence"] = None
        notice["_open_ended"] = True


def _synthetic(row, source_index):
    ids = [str(item) for item in (row or {}).get("camp_ids") or []]
    ids = [item for item in ids if item and not _trap(item, row.get("park") or "")]
    start = str((row or {}).get("start") or "")
    end = str((row or {}).get("end") or "")
    if not ids or not ((start and end) or row.get("open_ended")):
        return None
    notice = {
        "source_index": source_index,
        "source_url": row["link"],
        "title": row.get("title") or row.get("park") or "",
        "parks": [row.get("park") or ""],
        "scope_level": "named_campground",
        "primary_type": "full_closure",
        "windows": [],
        "recurrence": None,
        "affected_camp_facilities": [
            {"booking_id": booking_id, "title": row.get("park") or "", "effect": "closed"}
            for booking_id in ids
        ],
        "unmapped_camp_scope": None,
        "unknowns": [],
        "reason": "",
    }
    _apply_live_window(notice, row)
    return notice


def _plain(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text).replace("\xa0", " ").replace("\u00ad", "")
    return " ".join(text.split())


def _norm(value):
    text = (value or "").lower().replace("&", " and ").replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())
