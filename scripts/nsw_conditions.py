#!/usr/bin/env python3
"""NSW camp closures from the NPWS alerts API (RSS as fallback), and fire danger from the RFS feed.

Official text only. A camp stays "check" unless an alert records a closure of
that reserve or of that campground. Fire danger is the RFS district value for
the polygon that contains the camp. If a feed or its boundary layer is
unavailable, this leaves status and the fire line unset.
"""
import datetime as dt
import html as html_lib
import json
import math
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

import facts

# reservetype on the NPWSReserve layer, paired there with classsubtype.
# The class labels are the NSW Spatial Services cadastre ClassSubtype renderer:
# 1 National Park, 2 Nature Reserve, 3 Historic Site, 4 Regional Park,
# 5 Karst Conservation Reserve, 6 Aboriginal Area, 7 State Conservation Area.
TYPE_LABEL = {
    "NP": "National Park",
    "NR": "Nature Reserve",
    "HS": "Historic Site",
    "RP": "Regional Park",
    "KC": "Karst Conservation Reserve",
    "AA": "Aboriginal Area",
    "SC": "State Conservation Area",
}
# NPWS alert bullets shorten three of those labels. Read from the bullet text.
BULLET_ABBREV = {"NP": "np", "NR": "nr", "SC": "sca"}
_HEADING_PREFIXES = (
    "fire bans",
    "closed areas",
    "closed parks",
    "safety alerts",
    "other planned events",
    "other incidents",
    "fires",
)
_EXEMPT = re.compile(
    r"remain open|remains open|not impacted|not be directly affected|will not be directly affected|"
    r"not directly affected|does not effect|do not affect",
    re.I,
)
_PARTIAL = re.compile(
    r"areas of\s+.{0,80}?\sare closed|the closed areas are|parts of\s+.{0,80}?\s(?:are|is) closed|precincts\)",
    re.I,
)
_FIRE_BAN = re.compile(r"park fire ban|solid fuel|no solid fuel", re.I)
# NPWS often puts an adverb between the verb and "closed": "remains temporarily
# closed", "is currently closed". "Partially closed" is not in this list.
_CLOSED_ADVERB = r"(?: (?:permanently|temporarily|currently|still|now|fully|completely|indefinitely))?"
_CLOSED_SENTENCE = re.compile(
    r"([A-Z][^.\n]{2,140}?) (?:(?:is|are|will be|will remain|remains|remain|has been|have been|has|have)"
    + _CLOSED_ADVERB + r"|permanently|temporarily) closed\b"
)
# A Closed areas heading that names the campground: "White Tree Bay campground
# closed due to flood repairs". Closed to 4WD vehicles, caravans or dogs is not
# a campground closure; closed to the public or visitors is.
_HEADING_CLOSED = re.compile(
    r"^(?:Closed areas|Closed parks)\s*:\s*(.+?\b(?:campgrounds?|camping areas?|campsites?))\s+"
    r"(?:(?:is|are|remains|remain)" + _CLOSED_ADVERB + r"\s+)?(?:temporarily\s+)?closed\b(?!\s+to\s+(?!the public|visitors|public))",
    re.I,
)
_GENERIC_WORDS = {"picnic", "area", "areas", "day", "use", "and", "the", "site", "sites"}
_VISITOR_CLOSED = re.compile(
    r"will remain closed|will be closed|is currently closed|\bis closed\b|\bare closed\b|remains closed|"
    r"\b(?:is|are|remains|remain|will remain) temporarily closed\b|"
    r"closed to (?:the public|visitors|public)|no public access|there is no access|no access to|"
    r"permanently closed|do not enter|visitors may not|\barea closed\b",
    re.I,
)


def norm(value):
    text = html_lib.unescape(str(value or "")).replace("\xa0", " ").lower()
    text = text.replace("'", "").replace("’", "").replace("`", "")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def camp_key(name):
    text = norm(name)
    text = re.sub(r"\b(camping area|campground|campgrounds|campsite|camp site|camping|camp)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(the|a)\s+", "", text)


def pretty_reserve(reservename, reservetype):
    label = TYPE_LABEL.get(str(reservetype or "").strip())
    raw = str(reservename or "").strip()
    if not label or not raw:
        return ""
    words = []
    for token in raw.split():
        bits = [bit[:1].upper() + bit[1:].lower() for bit in token.split("-") if bit]
        if bits:
            words.append("-".join(bits))
    if not words:
        return ""
    return " ".join(words) + " " + label


def clip(text, limit=480):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" .,;")
    return cut + "…"


def plain(raw):
    text = raw or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|h\d|ul|ol|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text).replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _is_heading(text):
    folded = re.sub(r"\s+", " ", text or "").strip().lower()
    return any(folded.startswith(prefix) for prefix in _HEADING_PREFIXES)


def sections_from_html(description):
    """Category headings only. Nested place names inside a fire-ban list stay in the body."""
    parts = re.split(r"(<strong>.*?</strong>)", description or "", flags=re.I | re.S)
    sections = []
    heading = None
    buf = []

    def flush():
        if heading is not None:
            sections.append((heading, plain("".join(buf))))

    for part in parts:
        match = re.fullmatch(r"<strong>(.*?)</strong>", part, flags=re.I | re.S)
        if match:
            inner = plain(match.group(1))
            if _is_heading(inner):
                flush()
                heading = re.sub(r"\s+", " ", inner).strip()
                buf = []
                continue
        buf.append(part)
    flush()
    return sections


def parse_rss(payload):
    """RSS items with a title, link and category sections. Empty if the feed is not RSS."""
    if not payload:
        return []
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for node in channel.findall("item"):
        title = re.sub(r"\s+", " ", (node.findtext("title") or "")).strip()
        link = (node.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        items.append({
            "title": title,
            "title_norm": norm(title),
            "link": link,
            "published": (node.findtext("pubDate") or "").strip(),
            "sections": sections_from_html(node.findtext("description") or ""),
        })
    return items


NPWS_SITE = "https://www.nationalparks.nsw.gov.au"
NPWS_ALERTS_PAGE = NPWS_SITE + "/alerts/alerts-list"
# NPWS alert Type to the RSS category heading the parser already reads.
_API_HEADING = {
    "npws fire ban": "Fire bans",
    "safety warning": "Safety alerts",
    "hazard reduction burn": "Fires",
    "notice": "Other planned events",
}
_ALL_CLOSED = re.compile(r"all parts are closed", re.I)
# NPWS titles a closure "Upcoming closure today due to ..." before it starts and
# does not always retitle it once the window opens (Flea Creek, 2 Nov 2026).
_UPCOMING_TITLE = re.compile(r"^upcoming closure (?:today|tomorrow|in \d+ days?)\s+", re.I)
# NPWS marks an end date it only estimates with this EndDateTimeStatusId; the
# alert's DateTimeText then ends "(estimated end date)".
_ESTIMATED_END_ID = "eb218444-5aac-482d-98ed-575078b361a6"
# Section text -> NPWS estimated end date (ISO), filled by parse_api.
ESTIMATED_END = {}
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?!\s*,?\s*\d)"
_OPEN_DAYS = re.compile(r"\bopen (?:from |on |between )?" + _DAY + r" (?:to|and|-|–) " + _DAY + r"\b", re.I)
_CLOSED_DAYS = re.compile(r"\bclosed (?:from |on |between )?" + _DAY + r" (?:to|and|-|–) " + _DAY + r"\b", re.I)


def _day_span(first, last):
    a, b = _DAYS.index(first.lower()), _DAYS.index(last.lower())
    return [(a + i) % 7 for i in range(((b - a) % 7) + 1)]


def weekly_closed_days(text):
    """Weekdays closed by a recurring weekly closure, or None.

    Only when the text says the closure repeats ("each week", "every week",
    "weekday closures"). An open span ("open from Friday to Sunday each week")
    wins over a closed span, since a closed span can name a trail instead.
    """
    low = (text or "").lower()
    if not re.search(r"\beach week\b|\bevery week\b|\bweekday closures?\b|\bweekly closures?\b", low):
        return None
    match = _OPEN_DAYS.search(low)
    if match:
        open_days = set(_day_span(match.group(1), match.group(2)))
        closed = [d for d in range(7) if d not in open_days]
        return closed or None
    match = _CLOSED_DAYS.search(low)
    if match:
        return _day_span(match.group(1), match.group(2))
    return None


def _days_label(days):
    names = [_DAYS[d].capitalize() for d in sorted(days)]
    if len(names) > 2 and sorted(days) == list(range(min(days), max(days) + 1)):
        return f"{names[0]} to {names[-1]}"
    return ", ".join(names)


def estimated_end_for(section, lead_only=False):
    for key, (value, staged) in ESTIMATED_END.items():
        if section and section.endswith(key):
            return staged if lead_only else value
    return None
# A campground NPWS marks closed whose text keeps it open on some days, or
# closes only part of it ("closed Monday to Thursday ... open Friday to
# Sunday", "partially closed"), is left to the text rules, not the flag.
_OPEN_PART = re.compile(r"\b(?:remains?|will be|will remain|is|are|stays?)\s+open\b|\bpartial(?:ly)?\b|\bopen from\b", re.I)


def _open_part_for(name, description):
    """True when a sentence naming this campground says part of it, or some
    days, stay open (Flea Creek opens Fri-Sun; Three Mile Dam is partly
    closed). "All other areas ... remain open" (Mimosa Rocks) does not count."""
    base = re.sub(r"(?i)\s*\b(?:campground|camping area|camp)\b\s*", " ", name).strip().lower()
    if not base:
        return bool(_OPEN_PART.search(description or ""))
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", description or ""):
        if base in sentence.lower() and _OPEN_PART.search(sentence):
            return True
    return False


def _md_plain(text):
    """NPWS markdown as plain lines: links keep their text, list items become bullets."""
    text = (text or "").replace("\xa0", " ").replace("\r", "")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__", "", text)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            continue
        line = re.sub(r"^[*\-\u2022]\s+", "- ", line)
        lines.append(line)
    return "\n".join(lines)


def _api_time(value):
    """An NPWS API UTC stamp (no zone suffix) in Australia/Melbourne."""
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw).rstrip("Z")
    try:
        when = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(facts.MELBOURNE)


def _spoken(when, with_clock=True):
    day = f"{when.strftime('%A')} {when.day} {when.strftime('%B %Y')}"
    if not with_clock:
        return day
    clock = when.strftime("%I:%M%p").lstrip("0").lower().replace(":00", "")
    return f"{clock} {day}"


def _window_line(alert, closure=True):
    """The structured window as a sentence closure_timing reads. A 11:58pm or
    later end is the whole of that day, written without a clock. Only a
    closure says "Closed"; a fire ban or notice is "In place from"."""
    for window in alert.get("AlertDateTimes") or []:
        start = _api_time(window.get("StartDateTimeUtc"))
        end = _api_time(window.get("EndDateTimeUtc"))
        if not start:
            continue
        line = ("Closed from " if closure else "In place from ") + _spoken(start)
        if end:
            late = (end.hour, end.minute) >= (23, 58)
            line += " to " + _spoken(end, with_clock=not late)
        return line + "."
    return ""


def _rfc2822(when):
    from email.utils import format_datetime
    return format_datetime(when) if when else ""


def parse_api(payload):
    """NPWS alerts API (the JSON the NPWS alerts pages load) as RSS-shaped items.

    One item per park, titled with the park name and linked to that park's
    local alerts page. Each alert is a section under the RSS category heading.
    A Closure that NPWS records as "All parts are closed" for a campground is
    also listed in closed_places with its official wording. Returns the items
    and the newest LastModifiedDate in Australia/Melbourne.
    """
    if not payload:
        return [], None
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        data = json.loads(payload)
    except ValueError:
        return [], None
    if not isinstance(data, dict) or not isinstance(data.get("Alerts"), list):
        return [], None
    meta = data.get("AlertsMeta") or {}
    parent = {}
    for row in meta.get("LocationAlerts") or []:
        if row.get("ContentDataFeedItemId") and row.get("ParentName"):
            parent[row["ContentDataFeedItemId"]] = row["ParentName"]
    park_url = {}
    for alert in data["Alerts"]:
        for loc in alert.get("Locations") or []:
            if loc.get("Type") == "Park" and loc.get("Name") and str(loc.get("Url") or "").startswith("/"):
                park_url.setdefault(loc["Name"], loc["Url"])
    items = {}
    newest = None
    ESTIMATED_END.clear()

    def item_for(park):
        if park not in items:
            url = park_url.get(park)
            link = NPWS_SITE + url.rstrip("/") + "/local-alerts" if url else NPWS_ALERTS_PAGE
            items[park] = {"title": park, "title_norm": norm(park), "link": link, "published": None,
                           "sections": [], "closed_places": [], "windows": {}}
        return items[park]

    for alert in data["Alerts"]:
        if str(alert.get("AlertStatus") or "").lower() not in ("active", "upcoming"):
            continue
        title = re.sub(r"\s+", " ", str(alert.get("Title") or "")).strip()
        kind = str(alert.get("Type") or "").strip()
        windows_all = alert.get("AlertDateTimes") or []
        first_window = windows_all[0] if windows_all else {}
        window_start = _api_time(first_window.get("StartDateTimeUtc"))
        window_end = _api_time(first_window.get("EndDateTimeUtc"))
        if _UPCOMING_TITLE.match(title) and window_start and window_start <= dt.datetime.now(facts.MELBOURNE):
            # The window has opened: "Upcoming closure today due to X" is now "Closure due to X".
            title = "Closure " + _UPCOMING_TITLE.sub("", title)
        estimated_end = None
        if window_end and (first_window.get("EndDateTimeStatusId") == _ESTIMATED_END_ID
                           or "(estimated end date)" in str(first_window.get("DateTimeText") or "")):
            estimated_end = window_end.date().isoformat()
        modified = _api_time(alert.get("LastModifiedDate")) or _api_time(alert.get("FirstPublishDate"))
        if modified and (newest is None or modified > newest):
            newest = modified
        description = _md_plain(alert.get("Description"))
        detail = _md_plain(alert.get("LocationDetail"))
        detail = re.sub(r"^Where:\s*", "", detail)
        detail = re.sub(r"\s*\(see (?:on )?map\)", "", detail)
        # "All parts of" means the whole of each park; the camp matcher reads
        # "parts of" as a narrow area, so say it plainly.
        detail = re.sub(r"^All parts of\s+", "Applies to all of ", detail)
        lines = [description] if description else []
        if detail:
            lines.append(detail)
        window = _window_line(alert, kind.lower() == "closure")
        lead = ""
        staged_end, estimated_end = estimated_end, None
        if window and not _date_tokens(description):
            lines.append(window)
        elif window:
            timing = closure_timing(description)
            if not timing["start"] and not timing["reopen"]:
                # Dates the text rules cannot place: time it by the NPWS window.
                lead = window
            if staged_end and not timing["reopen"]:
                # An estimated end is not a reopening date: carry it on its own.
                estimated_end = (staged_end, False)
                if window_start and len(re.findall(r"(?m)^\s*[-*•] *From ", description)) >= 2:
                    # A staged works notice (Mimosa Rocks) lists each camp's own dates
                    # in one alert; time this alert by the NPWS window instead.
                    lead = ("Closed from " if kind.lower() == "closure" else "In place from ") + _spoken(window_start) + "."
                    estimated_end = (staged_end, True)
        parks = {}
        camps = []
        for loc in alert.get("Locations") or []:
            name = re.sub(r"\s+", " ", str(loc.get("Name") or "")).strip()
            if not name:
                continue
            if loc.get("Type") == "Park":
                # Whole park only when the flag and the Where text agree:
                # Kwiambal's caves alert flags the park but says "Some parts of".
                entire = bool(loc.get("EntireArea")) and not re.search(
                    r"some parts of[^.]*?" + re.escape(name), detail, re.I)
                parks[name] = parks.get(name, False) or entire
                continue
            owner = parent.get(loc.get("ContentDataFeedItemId"))
            if owner:
                parks.setdefault(owner, False)
            if (kind.lower() == "closure" and loc.get("Type") == "Campground" and loc.get("EntireArea")
                    and _ALL_CLOSED.search(str(loc.get("LocationImpact") or "")) and owner
                    and not _open_part_for(name, description)):
                camps.append((owner, name))
        for park, entire in parks.items():
            item = item_for(park)
            if kind.lower() == "closure":
                heading = ("Closed parks: " if entire else "Closed areas: ") + title
            else:
                heading = _API_HEADING.get(kind.lower(), "Other incidents") + ": " + title
            body = list(lines)
            if kind.lower() == "closure" and entire:
                body.append(f"{park} is closed.")
            body_text = "\n".join(body)
            item["sections"].append((heading, body_text))
            if estimated_end:
                ESTIMATED_END[heading + "\n" + body_text] = estimated_end
            if lead:
                # Keyed by the whole section: two alerts in one park can share
                # a title (Kosciuszko has two "facilities maintenance" closures).
                item["windows"][(heading, body_text)] = lead
            for owner, camp in camps:
                if owner == park:
                    item["closed_places"].append({
                        "piece": camp,
                        "desc": clip(". ".join(part for part in (title, " ".join(_sentences(description)[:2])) if part)),
                        "section": (lead + "\n" if lead else "") + heading + "\n" + body_text,
                    })
            if modified and (item["published"] is None or modified > item["published"]):
                item["published"] = modified
    out = []
    for item in items.values():
        item["published"] = _rfc2822(item["published"])
        out.append(item)
    return out, newest


def rss_built(payload):
    """The RSS channel lastBuildDate in Australia/Melbourne, or None."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    match = re.search(r"<lastBuildDate>([^<]+)</lastBuildDate>", payload or "")
    if not match:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(match.group(1).strip()).astimezone(facts.MELBOURNE)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def parse_fdr(payload):
    """District name to today's and tomorrow's rating and total fire ban. Empty if unreadable."""
    if not payload:
        return {}
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return {}
    found = {}
    for node in root.iter("District"):
        name = re.sub(r"\s+", " ", (node.findtext("Name") or "")).strip()
        today = (node.findtext("DangerLevelToday") or "").strip()
        ban = (node.findtext("FireBanToday") or "").strip()
        if not name or not today or not ban:
            continue
        found[_district_key(name)] = {
            "district": name,
            "today": _show_level(today),
            "tomorrow": _show_level(node.findtext("DangerLevelTomorrow") or ""),
            "ban_today": ban,
            "ban_tomorrow": (node.findtext("FireBanTomorrow") or "").strip(),
        }
    return found


def _district_key(name):
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _show_level(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower() in ("none", "no rating"):
        return "No Rating"  # the AFDRS name for days below Moderate
    if text.isupper():
        return text[:1] + text[1:].lower()
    return text


def _sentences(body):
    found = []
    for line in (body or "").split("\n"):
        if line.startswith("- "):
            continue
        found.extend(part.strip() for part in re.split(r"(?<=\.)\s+", line) if part.strip())
    return found


def _name_pieces(text):
    parts = re.split(r",|;| and | & ", text or "")
    cleaned = []
    for part in parts:
        part = part.strip(" .")
        part = re.sub(r"^(?:including|and)\s+", "", part, flags=re.I)
        part = re.sub(r"\s+and$", "", part, flags=re.I)
        if part:
            cleaned.append(part)
    return cleaned


_CAMP_WORD = re.compile(r"\b(?:camping area|campgrounds?|campsite|camp site|camping|camp)\b", re.I)


def name_variants(name):
    """The whole name plus each alternative a compound name gives.

    Yalwal/Toorooroo campground is also Yalwal and Toorooroo. Bandahngan
    (Tooloom Falls) campground is also Bandahngan and Tooloom Falls. In
    Black Rocks - Booroora campground the specific camp is the part after
    the dash; the part before it is used only when it is itself a camp
    name, as in Mt Warrawolong Campground - GNW.
    """
    text = html_lib.unescape(str(name or "")).replace("\xa0", " ").strip()
    found = [text]

    def add(value):
        value = re.sub(r"\s+", " ", value or "").strip(" -–—/")
        if value and value not in found:
            found.append(value)

    for part in re.split(r"\s+[–—-]\s+", text)[1:]:
        add(part)
    dash = re.split(r"\s+[–—-]\s+", text)
    if len(dash) > 1 and _CAMP_WORD.search(dash[0]):
        add(dash[0])
    for value in list(found):
        inner = re.findall(r"\(([^)]*)\)", value)
        if inner:
            add(re.sub(r"\([^)]*\)", " ", value))
            for bit in inner:
                add(bit)
    for value in list(found):
        if "/" in value:
            for bit in value.split("/"):
                add(bit)
    return found


def keys_match(camp_name, piece):
    """True when the official place name is this camp, allowing a picnic/area suffix.

    A short official name such as Cod still matches. Spaces are ignored so
    Blue Water Holes matches Blue Waterholes. An apostrophe is already gone
    in norm, so Alexander's Hut matches Alexanders Hut. A compound name such
    as Yalwal/Toorooroo matches either of its names (see name_variants).
    """
    for camp_alt in name_variants(camp_name):
        for place_alt in name_variants(piece):
            if _keys_match_one(camp_alt, place_alt):
                return True
    return False


def _keys_match_one(camp_name, piece):
    camp, place = camp_key(camp_name), camp_key(piece)
    if len(camp) < 3 or len(place) < 3:
        return False
    if camp == place or camp.replace(" ", "") == place.replace(" ", ""):
        return True
    if place.startswith(camp + " "):
        rest = [word for word in place[len(camp):].split() if word not in _GENERIC_WORDS]
        return not rest
    if camp.startswith(place + " "):
        rest = [word for word in camp[len(place):].split() if word not in _GENERIC_WORDS]
        return not rest
    return False


_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_TOKEN = re.compile(
    r"(?:(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+)?"
    r"(?:on\s+)?"
    r"(?:(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+)?"
    r"(?:the\s+)?"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"\s+"
    r"(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"(?:\s+(?P<year>20\d{2}))?",
    re.I,
)
_NO_ACCESS = re.compile(r"\bno access to\s+(.+?)\s+campgrounds?\b", re.I)
_CAMPGROUND_NAME = re.compile(
    r"(?:^|[,:]|\band\b|\bincluding\b)\s*([^,:\n]+?)\s+campgrounds?\b",
    re.I | re.M,
)
_NARROW = re.compile(
    r"\bincluding\b|\bparts of\b|\bsome parts\b|\bsections of\b|\bwest of\b|\beast of\b|"
    r"\bnorth of\b|\bsouth of\b|\bsection\b|\([^)]*\barea\b[^)]*\)",
    re.I,
)
# A point this close to a reserve boundary still belongs to that reserve.
# River camps such as Taylors Bridge sit just outside the drawn polygon.
_SNAP_METRES = 100


def _camp_piece(piece):
    """True when a bullet is long enough to be a camp name, including Cod."""
    key = camp_key(piece)
    if len(key) >= 4:
        return True
    return len(key) >= 3 and bool(re.search(r"\bcamp", piece or "", re.I))


def _clock(token):
    raw = (token or "").strip().lower().replace(" ", "")
    if not raw:
        return None
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)", raw)
    if not match:
        return None
    hour, minute, mer = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if hour > 12 or minute > 59:
        return None
    if mer == "pm" and hour != 12:
        hour += 12
    if mer == "am" and hour == 12:
        hour = 0
    return hour, minute


def _date_tokens(text):
    found = []
    for match in _DATE_TOKEN.finditer(text or ""):
        mon = _MONTHS.get((match.group("mon") or "").lower())
        if not mon:
            continue
        found.append({
            "span": match.span(),
            "day": int(match.group("day")),
            "month": mon,
            "year": int(match.group("year")) if match.group("year") else None,
            "weekday": _WEEKDAYS.get((match.group("wd") or "").lower()),
            "clock": _clock(match.group("time")),
        })
    return found


def _stamp(day, clock, end=False):
    if day is None:
        return None
    if clock:
        hour, minute = clock
        return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=facts.MELBOURNE)
    if end:
        return dt.datetime(day.year, day.month, day.day, 23, 59, tzinfo=facts.MELBOURNE)
    return dt.datetime(day.year, day.month, day.day, tzinfo=facts.MELBOURNE)


def _resolve_day(token, year):
    if not token or not year:
        return None
    try:
        return dt.date(int(year), token["month"], token["day"])
    except ValueError:
        return None


def _weekday_year(token, year):
    """The year nearest the default whose date falls on the printed weekday."""
    if not token or token.get("year") or token.get("weekday") is None or not year:
        return year
    for candidate in (year, year - 1, year + 1):
        day = _resolve_day(token, candidate)
        if day and day.weekday() == token["weekday"]:
            return candidate
    return year


def closure_timing(text, now=None):
    """Classify one alert section against the Australia/Melbourne clock.

    Returns kind current, upcoming or expired, plus the start date and the
    first open day. A "to <day>" end is inclusive, so reopen is the next
    day; an "until <time> <day>" end reopens that day at that time. A start later than now is upcoming. An end
    that has passed is expired and must not be shown as closed. When the
    end date carries the only year, the start uses that year, unless a
    printed weekday only fits the year before or after (13 April is a
    Monday in 2026, not 2027). A weekday that fits no nearby year leaves
    the window ambiguous; one that is not clearly finished is upcoming.
    """
    now = now or dt.datetime.now(facts.MELBOURNE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=facts.MELBOURNE)
    empty = {"kind": "current", "start": None, "reopen": None, "start_time": None, "reopen_time": None}
    tokens = _date_tokens(text)
    if not tokens:
        return empty
    low = (text or "").lower()
    start_tok = end_tok = None
    end_word = ""
    if len(tokens) >= 2:
        before = low[max(0, tokens[0]["span"][0] - 16):tokens[0]["span"][0]]
        between = low[tokens[0]["span"][1]:tokens[1]["span"][0]]
        if "from" in before and re.search(r"\b(?:to|until)\b", between):
            start_tok, end_tok = tokens[0], tokens[1]
            end_word = "until" if "until" in between else "to"
    if end_tok is None:
        before = low[max(0, tokens[0]["span"][0] - 16):tokens[0]["span"][0]]
        if re.search(r"\buntil\b", before):
            end_tok = tokens[0]
            end_word = "until"
        elif "from" in before:
            start_tok = tokens[0]
    if start_tok is None and end_tok is None and len(tokens) >= 2:
        before = low[max(0, tokens[0]["span"][0] - 24):tokens[0]["span"][0]]
        between = low[tokens[0]["span"][1]:tokens[1]["span"][0]]
        if "between" in before and re.search(r"\band\b", between):
            start_tok, end_tok = tokens[0], tokens[1]
            end_word = "to"
    if start_tok is None and end_tok is None:
        dashed = _dash_range_tokens(text)
        if dashed:
            start_tok, end_tok = dashed
            end_word = "to"
    if start_tok is None and end_tok is None:
        return empty
    end_year = (end_tok or {}).get("year") or (start_tok or {}).get("year") or now.year
    start_year = (start_tok or {}).get("year") or end_year
    if start_tok and end_tok and not start_tok.get("year") and end_tok.get("year"):
        if (start_tok["month"], start_tok["day"]) > (end_tok["month"], end_tok["day"]):
            start_year = end_tok["year"] - 1
        else:
            start_year = end_tok["year"]
    if end_tok and not end_tok.get("year") and start_tok and start_tok.get("year"):
        if (end_tok["month"], end_tok["day"]) < (start_tok["month"], start_tok["day"]):
            end_year = start_tok["year"] + 1
        else:
            end_year = start_tok["year"]
    if end_tok and not end_tok.get("year") and start_tok is None:
        end_year = now.year
    # A weekday printed with a yearless date picks the year: "Monday 13 April
    # to Wednesday 30 June 2027" is 13 April 2026, the nearest Monday 13 April.
    start_year = _weekday_year(start_tok, start_year)
    end_year = _weekday_year(end_tok, end_year)
    start_day = _resolve_day(start_tok, start_year)
    end_day = _resolve_day(end_tok, end_year)
    start_ok = start_day is None or start_tok.get("weekday") is None or start_day.weekday() == start_tok["weekday"]
    end_ok = end_day is None or end_tok.get("weekday") is None or end_day.weekday() == end_tok["weekday"]
    start_at = _stamp(start_day, (start_tok or {}).get("clock"), end=False)
    end_clock = (end_tok or {}).get("clock")
    # "to Saturday 31 October" is inclusive: closed all of that day, open
    # from midnight. "until 10am Saturday 31 October" ends at that time and
    # is compared with the clock, so a 9am build still shows it closed.
    reopen_day = end_day
    if end_day and end_word != "until" and not end_clock:
        reopen_day = end_day + dt.timedelta(days=1)
    end_at = _stamp(reopen_day, end_clock, end=False)
    will_be = bool(re.search(r"\bwill be closed\b", low))
    if start_at and start_at > now:
        kind = "upcoming"
    elif end_at and end_at <= now and start_ok and end_ok and not (will_be and not start_ok):
        kind = "expired"
    elif (not start_ok or not end_ok) and will_be and (end_at is None or end_at > now):
        kind = "upcoming"
    elif end_at and end_at <= now:
        kind = "expired"
    else:
        kind = "current"
    start_clock = (start_tok or {}).get("clock")
    return {
        "kind": kind,
        "start": start_day.isoformat() if start_day else None,
        "reopen": reopen_day.isoformat() if reopen_day else None,
        # Clock times NPWS printed ("from 2pm", "until 10am"), as HH:MM in
        # Australia/Melbourne. None when the text gives the day only.
        "start_time": "%02d:%02d" % start_clock if start_day and start_clock else None,
        "reopen_time": "%02d:%02d" % end_clock if reopen_day and end_clock else None,
    }


def _dash_range_tokens(text):
    """'CLOSED 15 – 25 October' shares one month across both days."""
    match = re.search(
        r"(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s*[–—-]\s*(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"(?:\s+(?P<year>20\d{2}))?",
        text or "",
        re.I,
    )
    if not match:
        return None
    mon = _MONTHS[(match.group("mon") or "").lower()]
    year = int(match.group("year")) if match.group("year") else None
    span = match.span()
    return (
        {"span": span, "day": int(match.group("d1")), "month": mon, "year": year, "weekday": None, "clock": None},
        {"span": span, "day": int(match.group("d2")), "month": mon, "year": year, "weekday": None, "clock": None},
    )


def _sentence_closes_camp(sentence, piece):
    """True when the sentence closes this camp, not a road, alternative or landmark.

    A camp named only inside brackets, as a place that stays open, or as an
    alternative to the closure is not itself closed.
    """
    if not sentence or not piece:
        return False
    if _EXEMPT.search(sentence):
        return False
    if re.search(r"\balternative\b", sentence, re.I):
        return False
    if re.search(r"\baccessible\b", sentence, re.I) and not re.search(r"\bclosed\b", sentence, re.I):
        return False
    outside = re.sub(r"\([^)]*\)", " ", sentence)
    if piece.lower() not in outside.lower():
        return False
    return bool(
        _CLOSED_SENTENCE.search(sentence)
        or _NO_ACCESS.search(sentence)
        or re.search(r"\bCLOSED\b", sentence)
    )


def _campground_names(text):
    found = []
    for match in _CAMPGROUND_NAME.finditer(text or ""):
        piece = re.sub(r"^(?:the|and|including)\s+", "", match.group(1).strip(" .-"), flags=re.I)
        if piece and not re.match(r"(?i)^(?:following|all|these|some)$", piece):
            found.append(piece)
    for match in _NO_ACCESS.finditer(text or ""):
        found.append(match.group(1).strip(" ."))
    return found


def _narrow_text(text):
    return bool(_NARROW.search(text or ""))


def _preamble(body):
    lines = []
    for line in (body or "").split("\n"):
        if line.startswith("- "):
            break
        lines.append(line)
    return " ".join(lines)


def camp_named_exempt(body, camp_name):
    key = camp_key(camp_name)
    if len(key) < 5:
        return False
    for sentence in _sentences(body):
        if not _EXEMPT.search(sentence):
            continue
        if re.search(r"\ball campgrounds?\b", sentence, re.I):
            return True
        for piece in _name_pieces(sentence):
            if camp_key(piece) == key:
                return True
    return False


def reserve_campgrounds_exempt(body, reserve):
    for sentence in _sentences(body):
        if not _EXEMPT.search(sentence):
            continue
        match = re.search(r"campgrounds in ([^.]+?) (?:as well as|and|are not|will remain|remain)", sentence, re.I)
        if match and reserve["title_norm"] in norm(match.group(1)):
            return True
    return False


def _list_is_closure(heading, body):
    text = heading + " " + _preamble(body)
    return bool(re.search(r"\bclosed\b", text, re.I)) and not _EXEMPT.search(text)


def _bullet_is_reserve(text, reserve):
    """A plain reserve bullet closes that whole reserve. A Green Cape or
    'including these campgrounds' bullet does not."""
    if _narrow_text(text):
        return False
    raw = re.sub(r"\s*\(including\b[^)]*\)", "", text or "", flags=re.I).strip()
    folded = norm(raw)
    if folded == reserve["title_norm"]:
        return True
    abbrev = reserve.get("abbrev") or ""
    if abbrev and folded == (reserve["name_norm"] + " " + abbrev).strip():
        return True
    return False


def _listed_reserve(body, reserve):
    prose = _preamble(body)
    if "following" not in norm(prose) or "closed" not in norm(prose):
        return False
    for line in (body or "").split("\n"):
        if line.startswith("- ") and _bullet_is_reserve(line[2:], reserve):
            return True
    return False


def _reserve_named(text, reserve):
    folded = norm(text)
    if reserve["title_norm"] and reserve["title_norm"] in folded:
        return True
    name = reserve.get("name_norm") or ""
    if name and re.search(r"\b" + re.escape(name) + r"\b", folded):
        return True
    if re.search(r"\bthis park\b|\bthe park is closed\b|\bthe reserve is closed\b", folded):
        return True
    return False


def _visitor_closed(text, reserve):
    folded = norm(text)
    title = reserve.get("title_norm") or ""
    if title and re.search(re.escape(title) + r" closed\b", folded):
        return True
    return bool(_VISITOR_CLOSED.search(text or ""))


def _official(heading, body):
    head = re.sub(r"^(?:Closed parks|Closed areas)\s*:\s*", "", heading or "", flags=re.I).strip()
    snippet = " ".join(_sentences(body)[:2])
    bullets = [line[2:].strip() for line in (body or "").split("\n") if line.startswith("- ")][:6]
    text = ". ".join(part for part in (head, snippet) if part)
    if bullets:
        text = (text + " " + "; ".join(bullets)).strip()
    return clip(text)


def whole_park_closure(reserve, item):
    """Closure text when this reserve's own Closed parks alert shuts the reserve."""
    for heading, body in item.get("sections") or []:
        if not heading.lower().startswith("closed parks"):
            continue
        text = heading + "\n" + body
        if _FIRE_BAN.search(text) and not _visitor_closed(text, reserve):
            continue
        if _PARTIAL.search(text):
            if _listed_reserve(body, reserve):
                return _official(heading, body), item["link"]
            continue
        if _reserve_named(text, reserve) and _visitor_closed(text, reserve):
            return _official(heading, body), item["link"]
        if _listed_reserve(body, reserve):
            return _official(heading, body), item["link"]
    return None


def _title_in(text, title_norms):
    folded = norm(text)
    found = ""
    for title_norm in title_norms:
        if title_norm and title_norm in folded and len(title_norm) > len(found):
            found = title_norm
    return found


def index_closures(items, reserves):
    """Closures keyed by reserve title.

    A bullet list applies to the reserve named in its heading. An OPEN list is
    not a closure. Whole-reserve Closed parks alerts stay on that reserve's own item.
    """
    by_norm = {}
    for reserve in reserves:
        by_norm.setdefault(reserve["title_norm"], reserve)
    title_norms = sorted(by_norm, key=len, reverse=True)
    whole = {}
    whole_all = {}
    listed = {}
    named = {}
    exempt = {}

    def add_named(target, piece, text, url, section):
        if not target or not _camp_piece(piece):
            return
        row = {"piece": piece, "desc": text, "url": url, "section": section}
        named.setdefault(target, []).append(row)
        if scope and target != scope:
            named.setdefault(scope, []).append(row)

    for item in items:
        scope = item["title_norm"] if item["title_norm"] in by_norm else ""
        if scope:
            found = whole_park_closure(by_norm[scope], item)
            if found and scope not in whole:
                text, url = found
                section = ""
                for heading, body in item.get("sections") or []:
                    if heading.lower().startswith("closed parks"):
                        lead = (item.get("windows") or {}).get((heading, body))
                        section = (lead + "\n" if lead else "") + heading + "\n" + body
                        break
                whole[scope] = {"piece": "", "desc": text, "url": url, "section": section or text}
            # Every whole-park section, so a closure in force today beats a
            # later one for the same park (Capertee has two shooting windows).
            windows = item.get("windows") or {}
            for heading, body in item.get("sections") or []:
                if not heading.lower().startswith("closed parks"):
                    continue
                one = whole_park_closure(by_norm[scope], {"link": item["link"], "sections": [(heading, body)]})
                if one:
                    lead = windows.get((heading, body))
                    whole_all.setdefault(scope, []).append({
                        "piece": "", "desc": one[0], "url": one[1],
                        "section": (lead + "\n" if lead else "") + heading + "\n" + body,
                    })
        windows = item.get("windows") or {}
        for heading, body in item.get("sections") or []:
            if not heading.lower().startswith(("closed areas", "closed parks")):
                continue
            lead = windows.get((heading, body))
            section = (lead + "\n" if lead else "") + heading + "\n" + body
            group = _title_in(heading, title_norms) or scope
            mode = "closed" if group and _list_is_closure(heading, body) else ""
            if group and reserve_campgrounds_exempt(body, by_norm[group]):
                exempt.setdefault(group, []).append(("*", "", item["link"]))
            for line in body.split("\n"):
                if not line.startswith("- "):
                    mentioned = _title_in(line, title_norms)
                    opened = bool(re.search(r"\bopen\b", line, re.I)) and not re.search(r"\bclosed\b", line, re.I)
                    closed = bool(re.search(r"\bclosed\b", line, re.I))
                    if opened:
                        mode = "open"
                        if mentioned:
                            group = mentioned
                    elif closed:
                        mode = "closed"
                        if mentioned:
                            group = mentioned
                    continue
                if not group or mode not in ("open", "closed"):
                    continue
                bullet = line[2:].strip()
                target = _title_in(bullet, title_norms) or group
                reserve = by_norm.get(target)
                if mode == "closed" and reserve and _bullet_is_reserve(bullet, reserve) and target not in listed:
                    listed[target] = {"piece": "", "desc": _official(heading, body), "url": item["link"], "section": section}
                    continue
                if mode == "open":
                    for piece in _name_pieces(bullet):
                        if _camp_piece(piece):
                            exempt.setdefault(target, []).append((piece, clip(bullet), item["link"]))
                    continue
                for piece in _name_pieces(bullet):
                    add_named(target, piece, clip(bullet), item["link"], section)
                for piece in _campground_names(bullet):
                    add_named(target, piece, clip(bullet), item["link"], section)
            if not scope or scope not in by_norm:
                continue
            if reserve_campgrounds_exempt(body, by_norm[scope]) or any(piece == "*" for piece, _text, _url in exempt.get(scope, [])):
                continue
            prose = "\n".join(line for line in section.split("\n") if not line.startswith("- "))
            for match in _CLOSED_SENTENCE.finditer(prose):
                start = prose.rfind("\n", 0, match.start()) + 1
                end = prose.find(".", match.end())
                sentence = prose[start: end + 1 if end != -1 else match.end()].strip()
                if _EXEMPT.search(sentence):
                    continue
                for piece in _name_pieces(match.group(1)):
                    add_named(scope, piece, clip(sentence), item["link"], section)
            for piece in _campground_names(prose):
                sentence = ""
                for part in _sentences(body):
                    if piece.lower() in part.lower():
                        sentence = part
                        break
                if not _sentence_closes_camp(sentence, piece):
                    continue
                add_named(scope, piece, clip(sentence), item["link"], section)
            head = _HEADING_CLOSED.search(heading)
            # Only a heading over plain prose; a bulleted list names its own camps.
            bulleted = any(line.startswith("- ") for line in body.split("\n"))
            if head and not bulleted and not _PARTIAL.search(heading) and not re.search(r"\bpartial", heading, re.I) and not _EXEMPT.search(body):
                for piece in _name_pieces(head.group(1)):
                    piece = re.sub(r"\s+(?:campgrounds?|camping areas?|campsites?)$", "", piece.strip(), flags=re.I)
                    add_named(scope, piece, clip(_official(heading, body)), item["link"], section)
        # NPWS records the campground itself as "All parts are closed".
        for place in item.get("closed_places") or []:
            add_named(scope, place["piece"], place["desc"], item["link"], place["section"])
    return {"whole": whole, "whole_all": whole_all, "listed": listed, "named": named, "exempt": exempt}


def _piece_hits(rows, camp_name):
    found = []
    for row in rows or []:
        piece = row["piece"] if isinstance(row, dict) else row[0]
        if piece != "*" and keys_match(camp_name, piece):
            found.append(row if isinstance(row, dict) else {"piece": row[0], "desc": row[1], "url": row[2], "section": row[1]})
    return found


def _exempt_hit(rows, camp_name):
    for piece, _text, _url in rows or []:
        if piece != "*" and keys_match(camp_name, piece):
            return True
    return False


def _choose_closure(candidates, now):
    ranked = []
    for row in candidates:
        if not row:
            continue
        text = row.get("section") or row.get("desc") or ""
        if estimated_end_for(row.get("section") or "", lead_only=True):
            # Time it by the NPWS window lead only: the body dates belong to other stages.
            timing = closure_timing(text.split("\n", 1)[0], now)
        else:
            timing = closure_timing(text, now)
        if timing["kind"] == "expired":
            continue
        days = weekly_closed_days(text)
        if days:
            timing = dict(timing, weekly=_days_label(days), closed_days=sorted(days))
            if timing["kind"] == "current" and now.weekday() not in days:
                # Open today (Flea Creek is open Friday to Sunday): the next closed
                # day is upcoming, unless the window has ended by then.
                ahead = now.date()
                while ahead.weekday() not in days:
                    ahead += dt.timedelta(days=1)
                if timing["reopen"] and ahead.isoformat() >= timing["reopen"]:
                    continue
                timing = dict(timing, kind="upcoming", start=ahead.isoformat(), start_time=None)
        ranked.append((row, timing))
    if not ranked:
        return None

    def sort_key(item):
        timing = item[1]
        kind = 0 if timing["kind"] == "current" else 1
        dated = 0 if (timing["start"] or timing["reopen"]) else 1
        # A later reopen stays closed longer, so it wins among current dated rows.
        reopen = tuple(-ord(ch) for ch in (timing["reopen"] or "0000-00-00"))
        return (kind, dated, reopen)

    ranked.sort(key=sort_key)
    row, timing = ranked[0]
    return {
        "desc": row.get("desc") or "",
        "url": row.get("url") or "",
        "section": row.get("section") or "",
        "kind": timing["kind"],
        "start": timing["start"],
        "reopen": timing["reopen"],
        "start_time": timing.get("start_time"),
        "reopen_time": timing.get("reopen_time"),
        "weekly": timing.get("weekly"),
        "closed_days": timing.get("closed_days"),
        "estimated_end": None if timing["reopen"] else estimated_end_for(row.get("section") or ""),
    }


def lookup_closure(index, reserve, camp_name, now=None):
    """Closed parks text covers the reserve. An OPEN list blocks a named or listed closure.

    A finished date window is omitted. A start still in the future is upcoming,
    not a closure that is in force now.
    """
    now = now or dt.datetime.now(facts.MELBOURNE)
    title = reserve["title_norm"]
    rows = index["exempt"].get(title) or []
    starred = any(piece == "*" for piece, _text, _url in rows)
    candidates = []
    if title in index["whole"]:
        candidates.append(index["whole"][title])
    candidates.extend((index.get("whole_all") or {}).get(title) or [])
    if not starred and not _exempt_hit(rows, camp_name):
        if title in index["listed"]:
            candidates.append(index["listed"][title])
        candidates.extend(_piece_hits(index["named"].get(title), camp_name))
    return _choose_closure(candidates, now)


def closure_for(reserve, camp_name, item, now=None):
    """Whole-reserve closure wins. A fire-ban exemption in another section does not reopen it."""
    return lookup_closure(index_closures([item], [reserve]), reserve, camp_name, now)


def alert_notes(item):
    notes = []
    seen = set()
    for heading, _body in item.get("sections") or []:
        key = heading.casefold()
        if key in seen:
            continue
        seen.add(key)
        notes.append({"heading": heading, "url": item["link"], "published": item.get("published") or ""})
    return notes


def _point_in_ring(x, y, ring):
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            denom = (yj - yi) or 1e-15
            if x < (xj - xi) * (y - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def _contains(prep, lon, lat):
    if lon < prep["minx"] or lon > prep["maxx"] or lat < prep["miny"] or lat > prep["maxy"]:
        return False
    hits = 0
    for ring in prep["rings"]:
        if _point_in_ring(lon, lat, ring):
            hits += 1
    return hits % 2 == 1


def _prepare(rings):
    kept = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for ring in rings or []:
        if not ring or len(ring) < 3:
            continue
        kept.append(ring)
        for x, y in ring:
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
    if not kept:
        return None
    return {"rings": kept, "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _cell(lon, lat):
    return int(math.floor(lon)), int(math.floor(lat))


def _index(records):
    grid = {}
    for record in records:
        prep = record["prep"]
        x0, y0 = _cell(prep["minx"], prep["miny"])
        x1, y1 = _cell(prep["maxx"], prep["maxy"])
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                grid.setdefault((x, y), []).append(record)
    return grid


def _reserves_containing(grid, lon, lat):
    found = []
    for record in grid.get(_cell(lon, lat), []):
        if _contains(record["prep"], lon, lat):
            found.append(record)
    return found


def _offset_point(lon, lat, north_m, east_m):
    dlat = north_m / 111320
    dlon = east_m / (111320 * max(0.2, math.cos(math.radians(lat))))
    return lon + dlon, lat + dlat


def reserves_at(grid, lon, lat):
    """Reserves containing the point. A point just outside the line snaps to it."""
    found = _reserves_containing(grid, lon, lat)
    if found:
        return found
    # Fire-district polygons have no reserve title. Snapping those would
    # assign a neighbouring district, so only NPWS reserve records snap.
    seen = set()
    snapped = []
    for north, east in ((_SNAP_METRES, 0), (-_SNAP_METRES, 0), (0, _SNAP_METRES), (0, -_SNAP_METRES),
                        (_SNAP_METRES, _SNAP_METRES), (_SNAP_METRES, -_SNAP_METRES),
                        (-_SNAP_METRES, _SNAP_METRES), (-_SNAP_METRES, -_SNAP_METRES)):
        x, y = _offset_point(lon, lat, north, east)
        for record in _reserves_containing(grid, x, y):
            key = record.get("title_norm")
            if not key or key in seen:
                continue
            seen.add(key)
            snapped.append(record)
    return snapped


def section_applies(heading, body, reserve, camp_name):
    """True when this alert section is about this camp, not merely the same park.

    A section that names campgrounds applies only to those camps. A plain
    reserve bullet applies to every camp in that reserve. A partial area
    that names no campground does not.
    """
    text = (heading or "") + "\n" + (body or "")
    for line in (body or "").split("\n"):
        if line.startswith("- ") and _bullet_is_reserve(line[2:], reserve):
            return True
    names = _campground_names(text)
    if names:
        return any(keys_match(camp_name, name) for name in names)
    if _narrow_text(text):
        return False
    return _reserve_named(text, reserve)


def _query(fetch_json, name, base, out_fields):
    features = []
    offset = 0
    while offset <= 5000:
        params = urllib.parse.urlencode({
            "where": "1=1",
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultOffset": str(offset),
            "resultRecordCount": "25",
        })
        doc = fetch_json(name, base.rstrip("/") + "/query?" + params)
        if not isinstance(doc, dict) or doc.get("error"):
            return None
        batch = doc.get("features") or []
        features.extend(batch)
        if not batch or not doc.get("exceededTransferLimit"):
            return features
        offset += len(batch)
    return features


def _reserve_records(features):
    records = []
    for feature in features or []:
        attrs = feature.get("attributes") or {}
        title = pretty_reserve(attrs.get("reservename"), attrs.get("reservetype"))
        prep = _prepare((feature.get("geometry") or {}).get("rings"))
        if not title or not prep:
            continue
        code = str(attrs.get("reservetype") or "").strip()
        records.append({
            "title": title,
            "title_norm": norm(title),
            "name_norm": norm(attrs.get("reservename")),
            "abbrev": BULLET_ABBREV.get(code, ""),
            "prep": prep,
        })
    return records


def _fire_records(features):
    records = []
    for feature in features or []:
        attrs = feature.get("attributes") or {}
        name = re.sub(r"\s+", " ", str(attrs.get("firearea") or "")).strip()
        prep = _prepare((feature.get("geometry") or {}).get("rings"))
        if not name or not prep:
            continue
        records.append({"name": name, "key": _district_key(name), "prep": prep})
    return records


def _items_by_title(items):
    found = {}
    for item in items:
        found.setdefault(item["title_norm"], []).append(item)
    return found


def apply_alert_records(camps, reserve_records, items):
    """Set closure, notes and alerts_checked from already parsed official records."""
    grid = _index(reserve_records)
    by_title = _items_by_title(items)
    published_by_link = {item["link"]: item.get("published") or "" for item in items}
    index = index_closures(items, reserve_records)
    matched_titles = {record["title_norm"] for record in reserve_records}
    closed_titles = []
    for item in items:
        if any(heading.lower().startswith("closed parks") for heading, _body in item["sections"]):
            if item["title_norm"] not in matched_titles:
                closed_titles.append(item["title"])
    noted = closed = upcoming = affected = 0
    for camp in camps:
        camp["alerts_checked"] = True
        reserves = reserves_at(grid, camp["lon"], camp["lat"])
        notes = []
        chosen = None
        seen = set()
        camp_name = camp.get("name") or ""
        for reserve in reserves:
            for item in by_title.get(reserve["title_norm"], []):
                for heading, body in item.get("sections") or []:
                    if not section_applies(heading, body, reserve, camp_name):
                        continue
                    key = (heading.casefold(), item["link"])
                    if key in seen:
                        continue
                    seen.add(key)
                    notes.append({"heading": heading, "url": item["link"], "published": item.get("published") or ""})
            if chosen is None:
                chosen = lookup_closure(index, reserve, camp_name)
        if notes:
            camp["alerts"] = notes
            noted += 1
        already = camp.get("status") == "closed" and (camp.get("closure") or {}).get("source_url")
        if chosen and chosen.get("desc") and chosen.get("url") and not already:
            record = {
                "status": "Closed",
                "desc": chosen["desc"],
                "reason": "",
                "start": chosen.get("start"),
                "reopen": chosen.get("reopen") or "",
                "outdated": False,
                "source_url": chosen["url"],
                "source_published": published_by_link.get(chosen["url"]) or "",
            }
            for key in ("start_time", "reopen_time", "weekly", "closed_days", "estimated_end"):
                if chosen.get(key):
                    record[key] = chosen[key]
            if chosen.get("kind") == "upcoming":
                # The visitor-area layer still has no open status. Leave check,
                # and show the upcoming notice instead of a Closed badge.
                camp["closure"] = None
                camp["upcoming_closure"] = record
                upcoming += 1
            else:
                camp["status"] = "closed"
                camp["closure"] = record
                camp.pop("upcoming_closure", None)
                closed += 1
        if camp.get("alerts") or str((camp.get("closure") or {}).get("source_url") or "").startswith("https://www.nationalparks.nsw.gov.au/") or camp.get("upcoming_closure"):
            affected += 1
    return {"noted": noted, "closed": closed, "upcoming": upcoming, "affected": affected, "unmatched_closed": closed_titles}


def apply_fire_records(camps, area_records, ratings, source_url):
    """Attach a district rating only where the polygon name matches the RFS feed."""
    grid = _index(area_records)
    matched = 0
    for camp in camps:
        rating = None
        for area in reserves_at(grid, camp["lon"], camp["lat"]):
            rating = ratings.get(area["key"])
            if rating:
                break
        if not rating:
            continue
        camp["fire"] = {
            "district": rating["district"],
            "today": rating["today"],
            "tomorrow": rating["tomorrow"],
            "ban_today": rating["ban_today"],
            "ban_tomorrow": rating["ban_tomorrow"],
            "source_url": source_url,
        }
        matched += 1
    return matched


def _fetch_ok(payload, label):
    if payload:
        return payload
    print(f"WARN {label} unavailable; nothing from that feed was applied", file=sys.stderr)
    return None


def apply(camps, sources, fetch_json, fetch_text):
    """Fetch NSW alerts and fire danger. Failures are warnings, not a failed build."""
    sources = sources or {}
    api = sources.get("npws_alerts_api") or {}
    alerts = sources.get("npws_alerts_rss") or {}
    reserves = sources.get("npws_reserves") or {}
    fdr = sources.get("rfs_fdr") or {}
    areas = sources.get("rfs_fire_areas") or {}
    try:
        if (api.get("url") or alerts.get("url")) and reserves.get("url"):
            items, updated, label, page = [], None, "", ""
            if api.get("url"):
                payload = _fetch_ok(fetch_text("npws_alerts_api", api["url"]), "NPWS alerts API")
                items, updated = parse_api(payload)
                label, page = "NPWS alerts API", api.get("page") or NPWS_ALERTS_PAGE
                if payload and not items:
                    print("WARN NPWS alerts API returned no readable alerts", file=sys.stderr)
            if not items and alerts.get("url"):
                # The RSS stopped updating on 20 Oct 2026. It is a fallback only,
                # and its own build date is shown, so a stale feed is visible.
                rss = _fetch_ok(fetch_text("npws_alerts_rss", alerts["url"]), "NPWS alerts RSS")
                items, updated = parse_rss(rss), rss_built(rss)
                label, page = "NPWS alerts RSS", alerts["url"]
                if items:
                    print("WARN NPWS alerts from the RSS fallback, built " + (updated.isoformat() if updated else "unknown"), file=sys.stderr)
            features = _fetch_ok(_query(fetch_json, "npws_reserves", reserves["url"], "reservename,reservetype"), "NPWS reserve boundaries") if items else None
            if items and features is not None:
                records = _reserve_records(features)
                if records:
                    for camp in camps:
                        camp["alerts_feed"] = page
                        if updated:
                            camp["alerts_updated"] = updated.isoformat()
                    summary = apply_alert_records(camps, records, items)
                    print(
                        f"{label}: {len(items)} items, updated {updated.isoformat() if updated else 'unknown'}, "
                        f"{summary['affected']} camps affected, {summary['closed']} closed, {summary['upcoming']} upcoming"
                    )
                    if summary["unmatched_closed"]:
                        print("NPWS closed-park titles without a reserve polygon: " + "; ".join(summary["unmatched_closed"][:12]))
                else:
                    print("WARN NPWS alerts could not be read; camp status left unchanged", file=sys.stderr)
            elif not items:
                print("WARN NPWS alerts unavailable from the API and the RSS; camp status left unchanged", file=sys.stderr)
        elif alerts.get("url") or api.get("url") or reserves.get("url"):
            print("WARN NPWS alerts need an alerts source and reserve boundaries; neither was applied", file=sys.stderr)
    except Exception as exc:
        print("WARN NPWS alerts", exc, file=sys.stderr)
    try:
        if fdr.get("url") and areas.get("url"):
            xml = _fetch_ok(fetch_text("rfs_fdr", fdr["url"]), "RFS fire danger feed")
            features = _fetch_ok(_query(fetch_json, "rfs_fire_areas", areas["url"], "firearea"), "NSW fire area boundaries") if xml else None
            if xml and features is not None:
                ratings = parse_fdr(xml)
                records = _fire_records(features)
                if ratings and records:
                    matched = apply_fire_records(camps, records, ratings, fdr["url"])
                    print(f"RFS fire danger: {matched} camps in a feed district")
                else:
                    print("WARN RFS fire danger could not be read; no rating was added", file=sys.stderr)
        elif fdr.get("url") or areas.get("url"):
            print("WARN RFS fire danger needs both the feed and fire-area boundaries; neither was applied", file=sys.stderr)
    except Exception as exc:
        print("WARN RFS fire danger", exc, file=sys.stderr)
