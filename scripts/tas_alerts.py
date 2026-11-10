#!/usr/bin/env python3
"""Parks and Wildlife Service site alerts for Tasmania.

One fetch of the alerts page per build. The stored record is the headline,
the affected park names, the link back to that page, and start and end dates
when the page states them. The alert body is not kept. A closure whose start
is still ahead is upcoming, not closed. A failed fetch reuses the last good
record and is marked stale.
"""
import datetime as dt
import html
import json
import os
import re
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERTS_URL = "https://parks.tas.gov.au/explore-our-parks/know-before-you-go/alerts"
USER_AGENT = "CampConditions.au/1.0 (Tasmania park alerts; +https://campconditions.au)"
LINK_TEXT = "Parks and Wildlife Service alerts"
COUNCIL_SENTENCE = "Check with the council before you travel."
CAMPFIRE_NOTE = "Seasonal campfire ban."
AMBER_LABEL = "Alert in this park"
CLOSED_LABEL = "Closed"
UPCOMING_LABEL = "Upcoming closure"
NO_ALERT_LABEL = "No current alert"
HOBART = ZoneInfo("Australia/Hobart")
DATE_FIELDS = ("start", "start_time", "end", "end_time")
STORED_FIELDS = {"headline", "parks", "link", *DATE_FIELDS}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
_CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
COUNCIL_LABEL = "Check with the council"
STALE_MESSAGE = (
    "Park alerts could not be fetched for this update. These headlines are from the last check that succeeded. "
    "Check the Parks and Wildlife Service alerts page before you travel."
)
_RESERVE_TAIL = re.compile(
    r"[\s\-–—:]*((?:national park|conservation area|state reserve|nature reserve|regional reserve|"
    r"historic site|game reserve|forest reserve|marine nature reserve|marine reserve)\b)",
    re.I,
)
_NUM_AND = re.compile(r"(?:no\.?\s*)?(\d+)\s+and\s+(?:no\.?\s*)?(\d+)\b", re.I)


def allowed_url(url):
    """robots.txt allows the alerts path and disallows query strings and SharePoint plumbing."""
    if not url or "?" in url or url.lower().startswith(("http://",)):
        return False
    if not url.startswith("https://parks.tas.gov.au/"):
        return False
    path = url[len("https://parks.tas.gov.au"):]
    if path.startswith((
        "/_layouts/", "/_vti_bin/", "/_catalogs/", "/search", "/feedback",
        "/index.aspx", "/file.aspx",
    )):
        return False
    return path.rstrip("/") == "/explore-our-parks/know-before-you-go/alerts"


def norm_name(value):
    text = (value or "").lower().replace("&", " and ")
    text = text.replace("'", "").replace("’", "").replace("`", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_html(page):
    """Headlines, park names and stated dates. Body text is discarded."""
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page or "")
    block = re.search(r"<h2\b[^>]*>\s*Site Alerts\s*</h2>(.*?)(?:<h2\b|$)", text, re.S | re.I)
    region = block.group(1) if block else ""
    alerts = []
    for part in re.split(r'<div class="section">', region)[1:]:
        title = re.search(r"<h3>(.*?)</h3>", part, re.S | re.I)
        if not title:
            continue
        headline = _text(title.group(1))
        if not headline:
            continue
        parks = []
        loc = re.search(r"<b>\s*Locations affected:\s*</b>(.*?)</p>", part, re.S | re.I)
        if loc:
            for raw in re.findall(r"<a\b[^>]*>(.*?)</a>", loc.group(1), re.S | re.I):
                name = _text(raw)
                if name and name not in parks:
                    parks.append(name)
        applies = re.search(r"Applies from\s+(\d{1,2})/(\d{1,2})/(\d{4})", part, re.I)
        applies_date = None
        if applies:
            day, month, year = int(applies.group(1)), int(applies.group(2)), int(applies.group(3))
            try:
                applies_date = dt.date(year, month, day)
            except ValueError:
                applies_date = None
        listing = re.search(r'class="alert-listing">(.*)', part, re.S | re.I)
        body_html = listing.group(1) if listing else ""
        body_html = re.split(r"<b>\s*Locations affected", body_html, maxsplit=1, flags=re.I)[0]
        body_html = re.split(r"Last reviewed", body_html, maxsplit=1, flags=re.I)[0]
        row = {"headline": headline, "parks": parks, "link": ALERTS_URL}
        row.update(parse_alert_dates(_text(body_html), applies_date))
        alerts.append(row)
    return alerts


def _text(fragment):
    cleaned = re.sub(r"<[^>]+>", " ", fragment or "")
    cleaned = html.unescape(cleaned).replace("\xa0", " ")
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", cleaned)
    return " ".join(cleaned.split())


def _clock(hour, minute, meridiem):
    value = int(hour)
    if meridiem.lower() == "pm" and value < 12:
        value += 12
    if meridiem.lower() == "am" and value == 12:
        value = 0
    return f"{value:02d}:{int(minute or 0):02d}"


def _year_for(month, day, explicit, applies):
    if explicit:
        return int(explicit)
    if applies is None:
        return None
    if (month, day) < (applies.month, applies.day):
        return applies.year + 1
    return applies.year


def _put_date(found, key, year, month, day, clock=None):
    if not year:
        return
    try:
        when = dt.date(int(year), int(month), int(day))
    except ValueError:
        return
    found[key] = when.isoformat()
    if clock:
        found[key + "_time"] = clock


def parse_alert_dates(body, applies=None):
    """Start and end from the alert text. The sentence itself is not returned.

    A date with no clock starts at midnight. An end date with no clock runs
    through that calendar day. 'until further notice' and 'late 2026' are not
    dates.
    """
    text = body or ""
    found = {}
    timed = re.search(
        rf"from\s+{_CLOCK}\s+\w+\s+(\d{{1,2}})\s+{_MONTH}(?:\s+(\d{{4}}))?.*?"
        rf"(?:reopen(?:s|\s+at)?|until)\s+{_CLOCK}\s+\w+\s+(\d{{1,2}})\s+{_MONTH}(?:\s+(\d{{4}}))?",
        text, re.I | re.S,
    )
    same_day = re.search(
        rf"on\s+\w+\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})\s+from\s+{_CLOCK}\s+to\s+{_CLOCK}",
        text, re.I,
    )
    spanned = re.search(
        rf"from\s+(?:the\s+)?(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})\s+(?:through\s+)?(?:to|until)\s+"
        rf"(?:the\s+)?(\d{{1,2}})(?:\s+of)?\s+{_MONTH}\s+(\d{{4}})",
        text, re.I,
    )
    month_span = re.search(rf"from\s+(\d{{1,2}})\s+{_MONTH}\s+to\s+(\d{{1,2}})\s+{_MONTH}\b", text, re.I)
    until = re.search(rf"\buntil\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})", text, re.I)
    starting = re.search(rf"\bstarting\s+(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}})", text, re.I)
    if timed:
        sm, sd = _MONTHS[timed.group(5).lower()], int(timed.group(4))
        em, ed = _MONTHS[timed.group(11).lower()], int(timed.group(10))
        _put_date(found, "start", _year_for(sm, sd, timed.group(6), applies), sm, sd, _clock(*timed.group(1, 2, 3)))
        _put_date(found, "end", _year_for(em, ed, timed.group(12), applies), em, ed, _clock(*timed.group(7, 8, 9)))
    elif same_day:
        month = _MONTHS[same_day.group(2).lower()]
        day = int(same_day.group(1))
        year = int(same_day.group(3))
        _put_date(found, "start", year, month, day, _clock(*same_day.group(4, 5, 6)))
        _put_date(found, "end", year, month, day, _clock(*same_day.group(7, 8, 9)))
    elif spanned:
        _put_date(found, "start", int(spanned.group(3)), _MONTHS[spanned.group(2).lower()], int(spanned.group(1)))
        _put_date(found, "end", int(spanned.group(6)), _MONTHS[spanned.group(5).lower()], int(spanned.group(4)))
    elif month_span and not re.search(r"\d{4}", month_span.group(0)):
        sm, sd = _MONTHS[month_span.group(2).lower()], int(month_span.group(1))
        em, ed = _MONTHS[month_span.group(4).lower()], int(month_span.group(3))
        _put_date(found, "start", _year_for(sm, sd, None, applies), sm, sd)
        _put_date(found, "end", _year_for(em, ed, None, applies), em, ed)
    else:
        if starting:
            _put_date(found, "start", int(starting.group(3)), _MONTHS[starting.group(2).lower()], int(starting.group(1)))
        if until and "further notice" not in text.lower():
            _put_date(found, "end", int(until.group(3)), _MONTHS[until.group(2).lower()], int(until.group(1)))
    if "start" not in found and applies is not None:
        found["start"] = applies.isoformat()
    return {key: value for key, value in found.items() if value}


def _aware(day, clock, bound):
    """Local Hobart instant. A dateless value is None. An end without a clock
    is the next midnight, so 'until 30 November' still covers that day."""
    try:
        when = dt.date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(clock or ""))
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return dt.datetime.combine(when, dt.time(hour, minute), tzinfo=HOBART)
    if bound == "end":
        when = when + dt.timedelta(days=1)
    return dt.datetime.combine(when, dt.time(0, 0), tzinfo=HOBART)


def phase(alert, now):
    """upcoming before the start, ended after the end, otherwise current.

    An alert with no parsed dates stays current. That keeps an undated closure
    closed instead of clearing it.
    """
    now = now.astimezone(HOBART) if now.tzinfo else now.replace(tzinfo=HOBART)
    start = _aware((alert or {}).get("start"), (alert or {}).get("start_time"), "start")
    end = _aware((alert or {}).get("end"), (alert or {}).get("end_time"), "end")
    if start and now < start:
        return "upcoming"
    if end and now >= end:
        return "ended"
    return "current"


def spoken_when(day, clock=None):
    """'2026-12-10' and '10:00' as '10am Thursday 10 December 2026'."""
    try:
        when = dt.date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return ""
    out = f"{when:%A} {when.day} {when:%B %Y}"
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(clock or ""))
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        out = f"{(hour % 12) or 12}{':%02d' % minute if minute else ''}{'am' if hour < 12 else 'pm'} " + out
    return out


def date_sentence(record):
    """Spoken start and end. A date-only end is the day named on the alert."""
    record = record or {}
    bits = []
    if record.get("start"):
        bits.append("Starts " + spoken_when(record["start"], record.get("start_time")))
    if record.get("end") or record.get("reopen"):
        day = record.get("reopen") or record.get("end")
        clock = record.get("reopen_time") if record.get("reopen") else record.get("end_time")
        if record.get("reopen"):
            bits.append("Reopens " + spoken_when(day, clock))
        elif clock:
            bits.append("Until " + spoken_when(day, clock))
        else:
            bits.append("Until " + spoken_when(day))
    return ". ".join(bits)


def parks_match(camp_park, alert_park):
    """Exact match first, then case, ampersand and punctuation.

    A location sometimes prefixes a site and then names the reserve, as in
    "Lake St Clair (Cradle Mountain - Lake St Clair National Park)". The reserve
    name in that text matches. A shorter invented name does not.
    """
    left = (camp_park or "").strip()
    right = (alert_park or "").strip()
    if not left or not right:
        return False
    if left == right or left.casefold() == right.casefold():
        return True
    nleft, nright = norm_name(left), norm_name(right)
    if not nleft or not nright:
        return False
    if nleft == nright:
        return True
    return f" {nleft} " in f" {nright} "


def is_campfire(headline):
    text = (headline or "").strip()
    if not re.match(r"fire ban\s*:", text, re.I):
        return False
    return re.search(r"\bcampfire bans?\b", text, re.I) is not None


def is_closure(headline):
    return re.search(r"\b(?:closed|closure)\b", headline or "", re.I) is not None


def _phrase_in(phrase, headline):
    phrase = (phrase or "").strip()
    if len(phrase) < 3:
        return False
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", headline or "", re.I) is not None


def _park_titles(camp, extra):
    titles = []
    for value in (camp.get("pws_alert_name"), camp.get("reserve_name")):
        if value and value not in titles:
            titles.append(value)
    for value in extra or []:
        if value and value not in titles:
            titles.append(value)
    return titles


def is_park_leading_words(phrase, headline, park_names):
    """A park title in the headline is not the camp's name."""
    if not _phrase_in(phrase, headline):
        return False
    nphrase = norm_name(phrase)
    nhead = norm_name(headline)
    for park in park_names or []:
        npark = norm_name(park)
        if not nphrase or not npark:
            continue
        if npark == nphrase:
            return True
        if npark.startswith(nphrase + " ") and npark in nhead:
            return True
    for match in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(phrase.strip()) + r"(?![A-Za-z0-9])", headline or "", re.I):
        if _RESERVE_TAIL.match(headline[match.end():]):
            return True
    return False


def _phrases(camp):
    found = []
    for value in [camp.get("name")] + list(camp.get("aliases") or []):
        text = (value or "").strip()
        if text and text not in found:
            found.append(text)
    return found


def numbered_group_hit(headline, phrases):
    """'Name 1 and 2' covers aliases 'Name No 1' / 'Name 1' and the same for 2."""
    norms = [norm_name(phrase) for phrase in phrases]
    for match in _NUM_AND.finditer(headline or ""):
        words = re.findall(r"[A-Za-z][A-Za-z'’.-]*", headline[:match.start()])
        for length in range(1, 7):
            if len(words) < length:
                break
            base = norm_name(" ".join(words[-length:]))
            if not base:
                continue
            for number in (match.group(1), match.group(2)):
                options = {f"{base} {number}", f"{base} no {number}"}
                if any(got in options for got in norms):
                    return True
    return False


def names_camp(headline, camp, park_names):
    phrases = _phrases(camp)
    if numbered_group_hit(headline, phrases):
        return True
    titles = _park_titles(camp, park_names)
    for phrase in phrases:
        if not _phrase_in(phrase, headline):
            continue
        if is_park_leading_words(phrase, headline, titles):
            continue
        return True
    return False


def _unique(rows):
    found, seen = [], set()
    for row in rows:
        key = (row or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(row)
    return found


def _unique_alerts(rows):
    found, seen = [], set()
    for row in rows:
        key = (row.get("headline") or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(row)
    return found


def _closure_record(alert, upcoming=False):
    record = {
        "desc": alert.get("headline") or "",
        "reason": alert.get("headline") or "",
        "source_url": ALERTS_URL,
        "status": "Upcoming" if upcoming else "Closed",
    }
    if alert.get("start"):
        record["start"] = alert["start"]
    if alert.get("start_time"):
        record["start_time"] = alert["start_time"]
    if alert.get("end"):
        record["reopen"] = alert["end"]
    if alert.get("end_time"):
        record["reopen_time"] = alert["end_time"]
    return record


def classify(camp, alerts, now=None):
    """One camp's display. Council camps never take a PWS alert.

    A headline that names the camp and says closed is a current closure only
    while its dates say so. A start still ahead is upcoming. A finished end
    is not a closure. An alert with no dates stays a current closure.
    """
    now = now or dt.datetime.now(HOBART)
    if camp.get("tas_council"):
        return {"display": "council", "closures": [], "upcoming": [], "ambers": [], "campfire": False}
    park = (camp.get("pws_alert_name") or "").strip()
    closures, upcoming, ambers, campfire = [], [], [], False
    if not park:
        return {"display": "none", "closures": [], "upcoming": [], "ambers": [], "campfire": False}
    for alert in alerts or []:
        headline = alert.get("headline") or ""
        parks = alert.get("parks") or []
        if not any(parks_match(park, name) for name in parks):
            continue
        if is_campfire(headline):
            campfire = True
        elif is_closure(headline) and names_camp(headline, camp, parks):
            kind = phase(alert, now)
            if kind == "upcoming":
                upcoming.append(alert)
            elif kind == "current":
                closures.append(alert)
        else:
            ambers.append(headline)
    closures = _unique_alerts(closures)
    upcoming = _unique_alerts(upcoming)
    ambers = _unique(ambers)
    if closures:
        display = "closed"
    elif upcoming:
        display = "upcoming"
    elif ambers:
        display = "amber"
    else:
        display = "none"
    return {"display": display, "closures": closures, "upcoming": upcoming, "ambers": ambers, "campfire": campfire}


def counts(camps):
    return {
        "amber": sum(camp.get("tas_display") == "amber" for camp in camps),
        "closed": sum(camp.get("tas_display") == "closed" for camp in camps),
        "upcoming": sum(camp.get("tas_display") == "upcoming" for camp in camps),
        "campfire": sum(bool(camp.get("tas_campfire")) for camp in camps),
        "council": sum(camp.get("tas_display") == "council" for camp in camps),
        "published": len(camps),
    }


def apply_alerts(camps, alerts, now=None):
    now = now or dt.datetime.now(HOBART)
    for camp in camps:
        result = classify(camp, alerts, now)
        camp["tas_display"] = result["display"]
        camp["tas_closures"] = [row.get("headline") or "" for row in result["closures"]]
        camp["tas_upcoming"] = result["upcoming"]
        camp["tas_ambers"] = result["ambers"]
        camp["tas_campfire"] = result["campfire"]
        camp["alerts"] = []
        camp["upcoming_closure"] = None
        if result["display"] == "closed":
            camp["status"] = "closed"
            camp["status_label"] = CLOSED_LABEL
            first = result["closures"][0]
            camp["closure"] = _closure_record(first, upcoming=False)
            if len(result["closures"]) > 1:
                camp["closure"]["desc"] = "; ".join(row.get("headline") or "" for row in result["closures"])
            note = date_sentence(camp["closure"]) or first.get("headline") or ""
            camp["tas_list_note"] = note
        elif result["display"] == "upcoming":
            camp["status"] = "check"
            camp["status_label"] = UPCOMING_LABEL
            first = result["upcoming"][0]
            camp["closure"] = None
            camp["upcoming_closure"] = _closure_record(first, upcoming=True)
            note = date_sentence(camp["upcoming_closure"]) or first.get("headline") or ""
            camp["tas_list_note"] = note
        elif result["display"] == "amber":
            camp["status"] = "check"
            camp["status_label"] = AMBER_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = result["ambers"][0]
            camp["alerts"] = [{"heading": headline, "url": ALERTS_URL} for headline in result["ambers"]]
        elif result["display"] == "council":
            camp["status"] = "check"
            camp["status_label"] = COUNCIL_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = COUNCIL_SENTENCE
        else:
            camp["status"] = "check"
            camp["status_label"] = NO_ALERT_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = CAMPFIRE_NOTE if result["campfire"] else NO_ALERT_LABEL
        camp["open_inferred"] = False
    return counts(camps)


def html_block(camp):
    link = f'<a href="{html.escape(ALERTS_URL)}">{html.escape(LINK_TEXT)}</a>'
    bits = []
    if camp.get("tas_council"):
        url = str(camp.get("council_url") or "")
        sentence = html.escape(COUNCIL_SENTENCE)
        if url.startswith("https://"):
            bits.append(
                f'<p class="tas-council"><strong>{sentence}</strong> '
                f'<a href="{html.escape(url)}">Council information</a></p>'
            )
        else:
            bits.append(f'<p class="tas-council"><strong>{sentence}</strong></p>')
    elif camp.get("tas_display") == "upcoming":
        items = "".join(f"<li>{html.escape(row.get('headline') or '')}</li>" for row in camp.get("tas_upcoming") or [])
        when = date_sentence(camp.get("upcoming_closure") or {})
        lead = f"{html.escape(when)}. " if when else ""
        bits.append(
            f'<div class="warn" id="camp-closure"><strong>Upcoming closure.</strong> {lead}<ul>{items}</ul><p>{link}</p></div>'
        )
    elif camp.get("tas_display") == "closed":
        items = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp.get("tas_closures") or [])
        when = date_sentence(camp.get("closure") or {})
        lead = f"{html.escape(when)}. " if when else ""
        bits.append(f'<div class="warn" id="camp-closure"><strong>Closed.</strong> {lead}<ul>{items}</ul><p>{link}</p></div>')
        if camp.get("tas_ambers"):
            extra = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp["tas_ambers"])
            bits.append(f'<div class="warn" id="camp-alert"><strong>Alert in this park.</strong><ul>{extra}</ul><p>{link}</p></div>')
    elif camp.get("tas_display") == "amber":
        items = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp.get("tas_ambers") or [])
        bits.append(
            f'<div class="warn" id="camp-alert"><strong>Alert in this park.</strong><ul>{items}</ul><p>{link}</p></div>'
        )
    else:
        bits.append(
            "<p><strong>No current alert.</strong> No current alert does not mean the camp is open, so check before you travel.</p>"
        )
    if camp.get("tas_campfire"):
        bits.append(f'<p class="muted tas-campfire">{html.escape(CAMPFIRE_NOTE)} {link}</p>')
    park = (camp.get("pws_alert_name") or "").strip()
    if park and not camp.get("tas_council"):
        bits.append(f"<p>Park: {html.escape(park)}</p>")
    credit = camp.get("attribution") or ""
    if credit:
        bits.append(f'<p class="muted">{html.escape(credit)}</p>')
    source = str(camp.get("source_url") or "")
    if source.startswith("https://"):
        bits.append(f'<p>Campground record: <a href="{html.escape(source)}">theLIST</a></p>')
    return "".join(bits)


def last_good_path(directory):
    return os.path.join(directory, "pws-alerts.json")


def save_last_good(directory, alerts, fetched):
    os.makedirs(directory, exist_ok=True)
    path = last_good_path(directory)
    payload = {
        "url": ALERTS_URL,
        "fetched": fetched,
        "link": ALERTS_URL,
        "alerts": [row for row in (_stored_alert(alert) for alert in alerts) if row],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _stored_alert(row):
    """Headline, parks, link and parsed dates. Never the alert body."""
    headline = str((row or {}).get("headline") or "").strip()
    if not headline:
        return None
    parks = [str(name).strip() for name in (row or {}).get("parks") or [] if str(name).strip()]
    stored = {"headline": headline, "parks": parks, "link": ALERTS_URL}
    for key in DATE_FIELDS:
        value = str((row or {}).get(key) or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or re.fullmatch(r"\d{2}:\d{2}", value):
            stored[key] = value
    return stored


def load_last_good(directory):
    path = last_good_path(directory)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    alerts = []
    for row in payload.get("alerts") or []:
        if not isinstance(row, dict):
            continue
        stored = _stored_alert(row)
        if stored:
            alerts.append(stored)
    if not alerts:
        return None
    return {"alerts": alerts, "fetched": str(payload.get("fetched") or "")}


def fetch_alerts(fetch_text, directory, now=None):
    """One request. On failure, keep the last good headlines and mark them stale."""
    if not allowed_url(ALERTS_URL):
        raise SystemExit("PWS alerts URL is not allowed")
    now = now or dt.datetime.now(dt.timezone.utc)
    body = fetch_text("pws_alerts", ALERTS_URL, {"User-Agent": USER_AGENT, "Accept": "text/html"})
    if body:
        alerts = parse_html(body)
        fetched = now.isoformat()
        if alerts:
            save_last_good(directory, alerts, fetched)
        return {"alerts": alerts, "stale": False, "fetched": fetched, "fallback": False}
    cached = load_last_good(directory)
    if cached:
        return {"alerts": cached["alerts"], "stale": True, "fetched": cached["fetched"], "fallback": True}
    return {"alerts": [], "stale": True, "fetched": "", "fallback": False}


def stamp(result):
    """Feed line for the state page. Stale is set when this build reused the last good fetch."""
    info = {
        "label": "Park alerts",
        "agency": "Parks and Wildlife Service",
        "updated": result.get("fetched") or "",
        "feed": ALERTS_URL,
    }
    if result.get("stale"):
        info["stale"] = True
        info["stale_message"] = STALE_MESSAGE
    return info
