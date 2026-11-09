#!/usr/bin/env python3
"""Fetch and parse public ACT and SA closure HTML into short dated records.

Only https pages on parks.act.gov.au and parks.sa.gov.au are requested.
No booking API, no GeoPDF, no CAP feed. The parsed record keeps the source
URL, the check time, and the dates and names. It does not keep page prose,
photos, or coordinates. A failed or unreadable response is a source failure.
"""
import datetime as dt
import html
import re
import urllib.error
import urllib.request

import act_sa_status as status

ALLOWED_HOSTS = {"www.parks.act.gov.au", "www.parks.sa.gov.au"}
USER_AGENT = "CampConditionsPreview/1.0 (+https://campconditions.au)"
MONTHS = {name: index for index, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}

# Explicit joins from a parsed title or affected name to a camp already in the
# foundation. This is not an inventory crawl.
CAMP_IDS = {
    "woods reserve": "act:woods-reserve",
    "mambray creek campground": "sa:mambray-creek",
    "baroota ruins campground": "sa:baroota-ruins",
    "para wirra conservation park": "sa:para-wirra-conservation-park",
    "onkaparinga river national park": "sa:onkaparinga-river-national-park",
}
NON_CAMP_SUFFIXES = ("cabin", "lodge", "cottage")


def fetch_public_html(url, timeout=25):
    """GET one public HTML page. Other hosts are refused before any request."""
    checked = dt.datetime.now(dt.timezone.utc).isoformat()
    host = urllib.request.urlparse(url).hostname or ""
    if urllib.request.urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        return {"ok": False, "source_url": url, "http_status": None, "body": "", "checked_at": checked,
                "error": "host_not_allowed", "open_inferred": False}
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": response.status == 200,
                "source_url": url,
                "http_status": response.status,
                "body": raw.decode(charset, errors="replace"),
                "checked_at": checked,
                "error": "" if response.status == 200 else "http_%s" % response.status,
                "open_inferred": False,
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "source_url": url, "http_status": exc.code, "body": "", "checked_at": checked,
                "error": "http_%s" % exc.code, "open_inferred": False}
    except Exception as exc:
        kind = "timeout" if "timed out" in str(exc).lower() else "unavailable"
        return {"ok": False, "source_url": url, "http_status": kind, "body": "", "checked_at": checked,
                "error": kind, "open_inferred": False}


def parse_closure_html(page_html, url, checked_at=None):
    """Turn one public page into a closure record, or a failure record."""
    checked_at = checked_at or dt.datetime.now(dt.timezone.utc).isoformat()
    state = "act" if "parks.act.gov.au" in url else "sa"
    text = visible_text(page_html or "")
    if len(text) < 40 or "published" not in text.casefold():
        return _failed(url, checked_at, state, "malformed")
    title = _title(page_html) or _title_from_text(text)
    published = _published(text)
    if not title or not published:
        return _failed(url, checked_at, state, "missing_date" if not published else "malformed")
    affected, non_camps = _affected(text)
    ambiguous = "available for bookings" in text.casefold()
    record = {
        "ok": True,
        "source_url": url,
        "checked_at": checked_at,
        "state": state,
        "timezone": "Australia/Canberra" if state == "act" else "Australia/Adelaide",
        "title": title,
        "published": published,
        "affected_names": affected,
        "also_named_not_campgrounds": non_camps,
        "camp_ids": _camp_ids(title, affected),
        "until_further_notice": "until further notice" in text.casefold(),
        "expected_note": "early 2027" if re.search(r"early\s+2027", text, re.I) else None,
        "reopen_at": None,
        "recurrence": _recurrence(text) if state == "sa" else None,
        "intervals": _intervals(text, state),
        "ambiguous": ambiguous,
        "ambiguity": "booking_availability_exception" if ambiguous else "",
        "open_inferred": False,
        "prose_stored": False,
        "photos_stored": False,
        "coordinates_stored": False,
        "http_status": 200,
    }
    if record["until_further_notice"]:
        record["intervals"] = []
        record["reopen_at"] = None
    return record


def closure_failure(fetch_result):
    """A transport failure is unknown, never open."""
    return _failed(
        fetch_result.get("source_url") or "",
        fetch_result.get("checked_at"),
        "act" if "parks.act.gov.au" in str(fetch_result.get("source_url")) else "sa",
        fetch_result.get("error") or "unavailable",
        fetch_result.get("http_status"),
    )


def ingest_pages(pages, camps, moment):
    """Parse fetched pages and run the existing matcher. Failures close nothing."""
    alerts = []
    failures = []
    for page in pages:
        if not page.get("ok"):
            failures.append(closure_failure(page))
            continue
        parsed = parse_closure_html(page.get("body") or "", page.get("source_url") or "", page.get("checked_at"))
        if not parsed.get("ok"):
            failures.append(parsed)
            continue
        alerts.extend(record_to_alerts(parsed))
    statuses = status.apply_alerts(camps, alerts, moment) if camps else []
    return {"alerts": alerts, "failures": failures, "statuses": statuses, "open_inferred": False}


def record_to_alerts(record):
    """Matcher alerts for camps named by the page. No new camps are created."""
    if not record.get("ok"):
        return []
    alerts = []
    for camp_id in record.get("camp_ids") or []:
        alert = {
            "id": "%s:%s" % (record["source_url"].rstrip("/").split("/")[-1], camp_id),
            "state": record["state"],
            "source_url": record["source_url"],
            "action": "closure",
            "asset_class": "park" if camp_id.endswith("park") or "park" in camp_id else "campground",
            "published": record.get("published") or "",
            "timezone": record["timezone"],
            "targets": [{"id": camp_id, "scope": "full" if camp_id.endswith("park") or "conservation-park" in camp_id or "national-park" in camp_id else "named"}],
            "ambiguous": bool(record.get("ambiguous")),
            "ambiguity": record.get("ambiguity") or "",
        }
        if record.get("ambiguous"):
            alert["intervals"] = list(record.get("intervals") or [])
        elif record.get("until_further_notice"):
            alert["until_further_notice"] = True
            alert["expected"] = record.get("expected_note") or ""
            alert["start"] = record.get("published") or ""
        elif record.get("recurrence"):
            alert["recurrence"] = record["recurrence"]
        elif record.get("intervals"):
            alert["window_confirmed"] = True
            alert["intervals"] = record["intervals"]
        else:
            continue
        alerts.append(alert)
    return alerts


def preview_digest(slug, statuses, generated):
    """Local digest text for a disabled state. It has no send fields."""
    closed = [row for row in statuses if row.get("status") == "closed"]
    upcoming = [row for row in statuses if row.get("status") == "upcoming"]
    lines = [
        "PREVIEW ONLY. Do not send. Do not enrol.",
        "%s digest preview is not a public send." % slug.upper(),
        "Generated %s" % generated,
        "Closed: %s. Upcoming: %s. Open claims: 0." % (len(closed), len(upcoming)),
        "",
    ]
    for row in statuses:
        lines.append("%s: %s" % (row.get("camp_id"), row.get("status")))
    lines.append("")
    lines.append("Required before any send: %s" % ("RESEND_SEGMENT_ACT_ID" if slug == "act" else "RESEND_SEGMENT_SA_ID" if slug == "sa" else "none"))
    lines.append("That variable is not read while the state is disabled.")
    text = "\n".join(lines) + "\n"
    meta = {"state": slug, "send": False, "enrol": False, "reads_segment_env": False, "closed": len(closed), "upcoming": len(upcoming)}
    return {"text": text, "meta": meta}


def visible_text(page_html):
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", page_html or "")
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\u00ad", "")
    raw = re.sub(r"(\d+)\s+(st|nd|rd|th)\b", r"\1", raw, flags=re.I)
    raw = re.sub(r"\s+", " ", raw).strip()
    end = raw.find("Open navigation")
    if end > 0:
        raw = raw[:end]
    return raw


def _failed(url, checked_at, state, reason, http_status=None):
    return {
        "ok": False,
        "source_url": url,
        "checked_at": checked_at,
        "state": state,
        "http_status": http_status,
        "error": reason,
        "status": "unknown",
        "open_inferred": False,
        "alerts": [],
        "prose_stored": False,
    }


def _title(page_html):
    match = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page_html or "")
    if not match:
        return ""
    return re.sub(r"\s+", " ", visible_text(match.group(1))).strip()


def _title_from_text(text):
    match = re.search(r"Full closure of ([A-Z][^.]{3,80}?) Published", text)
    return ("Full closure of " + match.group(1)).strip() if match else ""


def _published(text):
    match = re.search(r"Published:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if not match:
        return ""
    month = MONTHS.get(match.group(2).title())
    if not month:
        return ""
    return "%04d-%02d-%02d" % (int(match.group(3)), month, int(match.group(1)))


def _affected(text):
    match = re.search(r"Affected campgrounds include:\s*(.+)$", text, re.I)
    if not match:
        return [], []
    chunk = match.group(1)
    parts = re.findall(r"([A-Z][A-Za-z' ]{2,40}?(?:Campground|Cabin|Lodge|Cottage))", chunk)
    camps, other = [], []
    for name in parts:
        cleaned = re.sub(r"\s+", " ", name).strip()
        if cleaned.casefold().endswith(NON_CAMP_SUFFIXES):
            other.append(cleaned)
        else:
            camps.append(cleaned)
    return camps, other


def _camp_ids(title, affected):
    found = []
    haystack = " ".join([title] + list(affected))
    for name, camp_id in CAMP_IDS.items():
        if name in haystack.casefold() and camp_id not in found:
            found.append(camp_id)
    return found


def _recurrence(text):
    if "every Wednesday" not in text:
        return None
    span = re.search(r"from\s+(\d{1,2}/\d{1,2}/\d{4})\s+[—-]\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    if not span:
        return None
    exclusions = []
    for start, end in re.findall(r"(\d{2}/\d{2}/\d{4})\s+[—-]\s+(\d{2}/\d{2}/\d{4})", text):
        if start == span.group(1):
            continue
        exclusions.append([_slash_date(start), _slash_date(end)])
    return {
        "start_date": _slash_date(span.group(1)),
        "end_date": _slash_date(span.group(2)),
        "weekdays": [2],
        "start_time": "18:00",
        "end_time": "24:00",
        "timezone": "Australia/Adelaide",
        "exclude_dates": exclusions,
    }


def _intervals(text, state):
    zone = "Australia/Canberra" if state == "act" else "Australia/Adelaide"
    rows = []
    window = re.search(
        r"from\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)|midnight)\s+\w+\s+(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?\s+until\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)|midnight)\s+\w+\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
        text, re.I)
    if window:
        year = int(window.group(8))
        start_year = int(window.group(4) or year)
        start_day = dt.date(start_year, MONTHS[window.group(3).title()], int(window.group(2)))
        end_day = dt.date(year, MONTHS[window.group(7).title()], int(window.group(6)))
        sh, sm = _clock(window.group(1))
        eh, em = _clock(window.group(5))
        rows.append({
            "start": "%sT%02d:%02d" % (start_day.isoformat(), sh, sm),
            "end": "%sT%02d:%02d" % (end_day.isoformat(), eh, em),
            "timezone": zone,
        })
        return rows
    for match in re.finditer(
        r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}),\s*([0-9:.]+)\s*(am|pm)\s*-\s*([0-9:.]+)\s*(am|pm)",
        text, re.I):
        month = MONTHS.get(match.group(3).title())
        if not month:
            continue
        year = int(match.group(4))
        first = dt.date(year, month, int(match.group(1)))
        last = dt.date(year, month, int(match.group(2)))
        sh, sm = _clock(match.group(5) + match.group(6))
        eh, em = _clock(match.group(7) + match.group(8))
        day = first
        while day < last:
            end_day = day + dt.timedelta(days=1)
            rows.append({
                "start": "%sT%02d:%02d" % (day.isoformat(), sh, sm),
                "end": "%sT%02d:%02d" % (end_day.isoformat(), eh, em),
                "timezone": zone,
            })
            day = end_day
    return rows


def _clock(token):
    cleaned = token.strip().lower().replace(".", ":")
    if cleaned == "midnight":
        return 0, 0
    ampm = "am" if cleaned.endswith("am") else "pm" if cleaned.endswith("pm") else ""
    number = cleaned[:-2] if ampm else cleaned
    if ":" in number:
        hour, minute = number.split(":")
    else:
        hour, minute = number, "0"
    hour, minute = int(hour), int(minute or 0)
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def _slash_date(value):
    day, month, year = value.split("/")
    return "%04d-%02d-%02d" % (int(year), int(month), int(day))
