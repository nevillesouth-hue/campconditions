#!/usr/bin/env python3
"""NSW camp closures from the NPWS alerts RSS, and fire danger from the RFS feed.

Official text only. A camp stays "check" unless an alert records a closure of
that reserve or of that campground. Fire danger is the RFS district value for
the polygon that contains the camp. If a feed or its boundary layer is
unavailable, this leaves status and the fire line unset.
"""
import datetime as dt
import html as html_lib
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
_CLOSED_SENTENCE = re.compile(
    r"([A-Z][^.\n]{2,140}?) (?:(?:is|are|will be|will remain|remains|remain|has|have)(?: permanently)?|permanently) closed\b"
)
_GENERIC_WORDS = {"picnic", "area", "areas", "day", "use", "and", "the", "site", "sites"}
_VISITOR_CLOSED = re.compile(
    r"will remain closed|will be closed|is currently closed|\bis closed\b|\bare closed\b|remains closed|"
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


def keys_match(camp_name, piece):
    """True when the official place name is this camp, allowing a picnic/area suffix.

    A short official name such as Cod still matches. Spaces are ignored so
    Blue Water Holes matches Blue Waterholes. An apostrophe is already gone
    in norm, so Alexander's Hut matches Alexanders Hut.
    """
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


def closure_timing(text, now=None):
    """Classify one alert section against the Australia/Melbourne clock.

    Returns kind current, upcoming or expired, plus the start and reopen
    dates named in the alert. A start later than now is upcoming. An end
    that has passed is expired and must not be shown as closed. When the
    end date carries the only year, the start uses that year. A weekday
    that disagrees does not pull a future start back into the past; an
    ambiguous window that is not clearly finished is upcoming.
    """
    now = now or dt.datetime.now(facts.MELBOURNE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=facts.MELBOURNE)
    empty = {"kind": "current", "start": None, "reopen": None}
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
    start_day = _resolve_day(start_tok, start_year)
    end_day = _resolve_day(end_tok, end_year)
    start_ok = start_day is None or start_tok.get("weekday") is None or start_day.weekday() == start_tok["weekday"]
    end_ok = end_day is None or end_tok.get("weekday") is None or end_day.weekday() == end_tok["weekday"]
    start_at = _stamp(start_day, (start_tok or {}).get("clock"), end=False)
    end_at = _stamp(end_day, (end_tok or {}).get("clock"), end=(end_word != "until" or not (end_tok or {}).get("clock")))
    if end_word == "until" and end_tok and not end_tok.get("clock"):
        end_at = _stamp(end_day, None, end=False)
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
    return {
        "kind": kind,
        "start": start_day.isoformat() if start_day else None,
        "reopen": end_day.isoformat() if end_day else None,
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
        match = re.search(r"campgrounds in ([^.]+?) (?:as well as|are not|will remain|remain)", sentence, re.I)
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
                        section = heading + "\n" + body
                        break
                whole[scope] = {"piece": "", "desc": text, "url": url, "section": section or text}
        for heading, body in item.get("sections") or []:
            if not heading.lower().startswith(("closed areas", "closed parks")):
                continue
            section = heading + "\n" + body
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
    return {"whole": whole, "listed": listed, "named": named, "exempt": exempt}


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
        timing = closure_timing(row.get("section") or row.get("desc") or "", now)
        if timing["kind"] == "expired":
            continue
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
    alerts = sources.get("npws_alerts_rss") or {}
    reserves = sources.get("npws_reserves") or {}
    fdr = sources.get("rfs_fdr") or {}
    areas = sources.get("rfs_fire_areas") or {}
    try:
        if alerts.get("url") and reserves.get("url"):
            rss = _fetch_ok(fetch_text("npws_alerts_rss", alerts["url"]), "NPWS alerts RSS")
            features = _fetch_ok(_query(fetch_json, "npws_reserves", reserves["url"], "reservename,reservetype"), "NPWS reserve boundaries") if rss else None
            if rss and features is not None:
                items = parse_rss(rss)
                records = _reserve_records(features)
                if items and records:
                    for camp in camps:
                        camp["alerts_feed"] = alerts["url"]
                    summary = apply_alert_records(camps, records, items)
                    print(
                        f"NPWS alerts: {len(items)} items, {summary['affected']} camps affected, "
                        f"{summary['closed']} closed, {summary['upcoming']} upcoming"
                    )
                    if summary["unmatched_closed"]:
                        print("NPWS closed-park titles without a reserve polygon: " + "; ".join(summary["unmatched_closed"][:12]))
                else:
                    print("WARN NPWS alerts could not be read; camp status left unchanged", file=sys.stderr)
        elif alerts.get("url") or reserves.get("url"):
            print("WARN NPWS alerts need both the RSS and reserve boundaries; neither was applied", file=sys.stderr)
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
