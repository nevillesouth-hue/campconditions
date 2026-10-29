#!/usr/bin/env python3
"""Find Parks Victoria campground pages that say closed while our status does not.

Reads parks.vic.gov.au campground links from data/manual-corrections.json.
A camp with only a whole-park link is checked against that park page's
change-of-conditions items that name the camp.
Fetches each page at most once every 24 hours, sequentially, about a second
apart. Writes dist/parksvic-flags.json. Never changes a camp's status.
"""
import hashlib, html, json, os, re, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORRECTIONS = os.path.join(ROOT, "data", "manual-corrections.json")
CACHE_DIR = os.path.join(ROOT, "data", ".parksvic-cache")
USER_AGENT = "CampConditions.au closure checker (+https://campconditions.au; campconditions@outlook.com)"
GAP_SECONDS = 1.0
REQUEST_TIMEOUT = 20
OVERALL_SECONDS = 50 * 60
CACHE_TTL = timedelta(hours=24)
MELBOURNE = timezone(timedelta(hours=11))

CLOSED_RE = re.compile(
    r"remain(?:s)? closed|\bis closed\b|closed until|closed for|closed to visitors|closed following",
    re.I,
)
IGNORE_RE = re.compile(
    r"gates?(?:\s+\w+){0,3}\s+closed at night|\bclosed at night\b|\bclosed at dusk\b|\bcloses at (?:night|dusk)\b",
    re.I,
)
SEASONAL_RE = re.compile(
    r"shoulder|\bseasonal\b|for the winter|over winter|during winter|winter season|off[ -]season",
    re.I,
)
ROAD_RE = re.compile(r"\b(?:roads?|tracks?|motor vehicles?|tk|rd)\b", re.I)
NAME_STOP = {"campground", "camping", "campsite", "camp", "area", "areas", "the", "and", "national", "park", "parks", "reserve", "site", "sites", "victoria", "lake", "river", "creek", "track", "road", "upper", "lower", "north", "south", "east", "west", "mount", "with", "from"}
CAMP_RE = re.compile(r"\bcamp(?:ground|site|ing)?s?\b", re.I)
OTHER_RE = re.compile(r"\b(?:lookouts?|picnic|day visitor)\b", re.I)
FACILITY_RE = re.compile(
    r"\b(?:bbqs?|barbecues?|barbeques?|toilets?|toilet blocks?|picnic shelters?|fireplaces?|showers?|dump points?)\b",
    re.I,
)
CAMP_ITSELF_RE = re.compile(
    r"\b(?:campgrounds?|camping areas?|campsites?|camp sites?)\s+(?:is|are|remains?|remain|will be)\s+closed\b",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
CAMPGROUND_BITS = ("campground", "camping", "where-to-stay", "campsite")
SKIP_TAGS = {"script", "style", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
def _name_tokens(name):
    return {word for word in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(word) > 3 and word not in NAME_STOP}


def site_phrase(name):
    """Distinctive site name, without the park in parentheses or after a dash.

    A trailing "site 3" is dropped so "Farley Bend Camping Area Site 3" still
    matches an alert titled for Farley Bend. A trailing "State Park" is dropped
    too, so a camp named after its park matches the park's campground alert.
    """
    head = (name or "").split("(")[0].split(" - ")[0]
    head = re.sub(r"\bsite\s+\d+\b", " ", head, flags=re.I)
    head = re.sub(r"\b(campgrounds?|camping areas?|camping sites?|bush camps?|picnic(?: and camping)? areas?|camps?)\b", " ", head, flags=re.I)
    phrase = re.sub(r"[^a-z0-9]+", " ", head.lower()).strip()
    # A camp named after its park ("Paddys Range State Park") is matched by the park's own name.
    return re.sub(r" (?:state|national|regional) parks?$", "", phrase) or phrase


def _fold(text):
    """Lower case, apostrophes dropped and a plural s trimmed, so Paddy's Ranges matches Paddys Range."""
    flat = re.sub(r"[^a-z0-9]+", " ", re.sub(r"['\u2019]", "", (text or "").lower())).strip()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word for word in flat.split())


def _phrase_in(phrase, text):
    if not phrase:
        return False
    return f" {_fold(phrase)} " in f" {_fold(text)} "


def _introduces_list(sentence):
    return bool(re.search(r"(?::|\bsuch as)\s*$", sentence or "", re.I))


def _list_item(line):
    """A short bullet, not the next prose sentence or a new list introduction."""
    if not line or len(line) > 180:
        return False
    if re.search(r"[.!?]\s*$", line):
        return False
    if _introduces_list(line) or CLOSED_RE.search(line):
        return False
    return True


def closure_units(text):
    """Sentences, keeping bullets that follow a line ending in ':' or 'such as'."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    text = re.sub(r" *\n+ *", "\n", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip(" \t-–—•")
        if line:
            lines.append(line)
    units = []
    index = 0
    while index < len(lines):
        parts = [bit.strip(" \t-–—") for bit in re.split(r"(?<=[.!?])\s+", lines[index]) if bit.strip(" \t-–—")]
        if not parts:
            index += 1
            continue
        last = parts[-1]
        if _introduces_list(last):
            items = []
            nxt = index + 1
            while nxt < len(lines) and _list_item(lines[nxt]):
                items.append(lines[nxt])
                nxt += 1
            for earlier in parts[:-1]:
                units.append((earlier, []))
            units.append((last, items))
            index = nxt
            continue
        for part in parts:
            units.append((part, []))
        index += 1
    return units


def _facility_only(sentence):
    """A toilet, BBQ, picnic shelter or similar, rather than the camp itself."""
    if not FACILITY_RE.search(sentence or ""):
        return False
    return not CAMP_ITSELF_RE.search(sentence or "")


class _Text(HTMLParser):
    """Overview text, plus a change-of-conditions item only when it names this camp."""

    def __init__(self, camp_name="", named_only=False):
        super().__init__(convert_charrefs=True)
        self.phrase = site_phrase(camp_name)
        self.named_only = named_only
        self.stack = []
        self.region = []
        self.fallback = []
        self.items = []
        self.current = None
        self.saw_structure = False

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag in BLOCK_TAGS:
                self._add("\n")
            return
        classes = ""
        for key, value in attrs:
            if key == "class" and value:
                classes = value
        capture = None
        if "explore__overview" in classes:
            capture = "overview"
            self.saw_structure = True
        elif "change-of-conditions__item" in classes:
            self.current = {"subtitle": [], "content": []}
            self.items.append(self.current)
            self.saw_structure = True
            capture = "item"
        elif "change-of-conditions__subtitle" in classes or "change-of-conditions__title-text" in classes:
            self.saw_structure = True
            if self.current is None or "".join(self.current["subtitle"]).strip():
                self.current = {"subtitle": [], "content": []}
                self.items.append(self.current)
            capture = "subtitle"
        elif "change-of-conditions__content" in classes:
            self.saw_structure = True
            if self.current is None:
                self.current = {"subtitle": [], "content": []}
                self.items.append(self.current)
            capture = "content"
        elif "change-of-conditions" in classes:
            self.saw_structure = True
        self.stack.append({
            "tag": tag,
            "skip": tag in SKIP_TAGS,
            "quick": "quick-reference" in classes,
            "capture": capture,
            "block": tag in BLOCK_TAGS,
        })
        if tag in BLOCK_TAGS:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        idx = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == tag), None)
        if idx is None:
            return
        while len(self.stack) > idx:
            flags = self.stack.pop()
            if flags["capture"] == "item":
                self.current = None
            if flags["block"]:
                self._add("\n")

    def handle_data(self, data):
        # Source wraps mid-sentence. Block tags still insert the line breaks.
        self._add(data.replace("\r", " ").replace("\n", " "))

    def _blocked(self):
        return any(item["skip"] or item["quick"] for item in self.stack)

    def _capture(self):
        caps = [item["capture"] for item in self.stack if item["capture"]]
        return caps[-1] if caps else ""

    def _add(self, data):
        if self._blocked():
            return
        self.fallback.append(data)
        capture = self._capture()
        if capture == "overview":
            self.region.append(data)
        elif self.current is not None and capture in ("subtitle", "content"):
            self.current[capture].append(data)

    def text(self):
        # A whole-park page: only change-of-conditions items that name this camp.
        parts = [] if self.named_only else list(self.region)
        if self.named_only and not self.phrase:
            return ""
        for item in self.items:
            subtitle = "".join(item["subtitle"])
            content = "".join(item["content"])
            title = re.sub(r"\s+", " ", subtitle).lower()
            if not self.phrase or self.phrase in title or _phrase_in(self.phrase, subtitle):
                parts.append("\n")
                parts.append(subtitle)
                parts.append("\n")
                parts.append(content)
                continue
            for sentence, bullets in closure_units(content):
                if not CLOSED_RE.search(sentence):
                    continue
                matched = [bit for bit in bullets if _phrase_in(self.phrase, bit)]
                if _phrase_in(self.phrase, sentence):
                    parts.append("\n")
                    parts.append(sentence if not matched else sentence.rstrip() + " " + matched[0])
                elif matched:
                    parts.append("\n")
                    parts.append(sentence.rstrip() + " " + matched[0])
        chosen = parts if self.saw_structure or self.named_only else self.fallback
        return html.unescape("".join(chosen)).replace("\xa0", " ")


def sentences(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    found = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for bit in re.split(r"(?<=[.!?])\s+", line):
            bit = re.sub(r"\s+", " ", bit).strip(" \t-–—")
            if bit:
                found.append(bit)
    return found


_PV_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_PV_DATE = re.compile(
    r"(?:(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+)?"
    r"(?:the\s+)?"
    r"(?:(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"|(?P<mon2>january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(?P<day2>\d{1,2})(?:st|nd|rd|th)?)"
    r"(?:\s+(?P<year>20\d{2}))?",
    re.I,
)


def _pv_dates(text):
    found = []
    for match in _PV_DATE.finditer(text or ""):
        raw_day = match.group("day") or match.group("day2")
        raw_mon = match.group("mon") or match.group("mon2")
        if not raw_day or not raw_mon:
            continue
        found.append({
            "span": match.span(),
            "day": int(raw_day),
            "month": _PV_MONTHS[raw_mon.lower()],
            "year": int(match.group("year")) if match.group("year") else None,
        })
    return found


def closure_end(text, today=None):
    """Reopen day from 'between X and Y' or 'until Y'. Empty when the text has no end date.

    The named end day is the reopen date: the camp is not closed on that day.
    A missing year uses the Melbourne year of today.
    """
    tokens = _pv_dates(text)
    if not tokens:
        return ""
    low = (text or "").lower()
    end = None
    if len(tokens) >= 2:
        before = low[max(0, tokens[0]["span"][0] - 24):tokens[0]["span"][0]]
        between = low[tokens[0]["span"][1]:tokens[1]["span"][0]]
        if ("between" in before and re.search(r"\band\b", between)) or ("from" in before and re.search(r"\b(?:to|until)\b", between)):
            end = tokens[1]
    if end is None:
        before = low[max(0, tokens[0]["span"][0] - 24):tokens[0]["span"][0]]
        if re.search(r"\b(?:until|to)\b", before):
            end = tokens[0]
    if end is None:
        return ""
    year = end.get("year")
    if not year:
        for token in tokens:
            if token.get("year"):
                year = token["year"]
                break
    if not year:
        when = today or datetime.now(MELBOURNE).date()
        year = when.year if hasattr(when, "year") else int(str(when)[:4])
    try:
        return datetime(int(year), end["month"], end["day"]).date().isoformat()
    except ValueError:
        return ""


def wording_closes_camp(wording, camp_name=""):
    """A reservoir, basin or reopening note does not close the campground."""
    text = wording or ""
    if re.search(r"\bre-?opened\b", text, re.I) and not re.search(r"\b(?:remains?|is|are|will be)\s+closed\b", text, re.I):
        return False
    facility = re.search(r"\b(?:reservoir|basin)\b", text, re.I)
    if facility and not CAMP_RE.search(text):
        return False
    return True


def classify_html(page, camp_name="", named_only=False):
    """Return closure sentences and seasonal sentences from one HTML page.

    named_only is for a whole-park page: the overview is ignored and only
    change-of-conditions items that name the camp are read.
    """
    closed, seasonal = [], []
    try:
        parser = _Text(camp_name, named_only)
        parser.feed(page or "")
        parser.close()
        extracted = parser.text()
    except Exception:
        extracted = "" if named_only else re.sub(r"<[^>]+>", " ", page or "")
    for sentence in sentences(extracted):
        if not CLOSED_RE.search(sentence):
            continue
        if IGNORE_RE.search(sentence) or re.fullmatch(r"this area is closed[.!]?", sentence, re.I):
            continue
        if re.search(r"\bmay be closed\b|fire danger rating", sentence, re.I):
            continue
        if _facility_only(sentence):
            continue
        end = closure_end(sentence)
        if end and end <= datetime.now(MELBOURNE).date().isoformat():
            continue
        if re.search(r"\bre-?opened\b", sentence, re.I) and not re.search(r"\b(?:remains?|is|are|will be)\s+closed\b", sentence, re.I):
            continue
        if re.search(r"\b(?:reservoir|basin)\b", sentence, re.I) and not CAMP_RE.search(sentence):
            continue
        if ROAD_RE.search(sentence) and not CAMP_RE.search(sentence):
            continue
        if OTHER_RE.search(sentence) and not CAMP_RE.search(sentence):
            continue
        if SEASONAL_RE.search(sentence):
            seasonal.append(sentence)
        else:
            closed.append(sentence)
    return {"closed": closed, "seasonal": seasonal}


def campground_url(value):
    if not isinstance(value, str) or "parks.vic.gov.au" not in value.lower():
        return ""
    match = URL_RE.search(value)
    if not match:
        return ""
    raw = match.group(0).rstrip(".,)")
    parts = urllib.parse.urlsplit(raw)
    if "parks.vic.gov.au" not in parts.netloc.lower():
        return ""
    path = parts.path.lower()
    # Some camp pages say "bush-camp" or "mallee-camp" rather than campground.
    if not any(bit in path for bit in CAMPGROUND_BITS) and not re.search(r"(?:^|[-/])camps?(?:$|[-/])", path):
        return ""
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/"), "", ""))


def park_url(value):
    """A Parks Victoria whole-park page, such as /places-to-see/parks/paddys-ranges-state-park."""
    if not isinstance(value, str) or "parks.vic.gov.au" not in value.lower():
        return ""
    match = URL_RE.search(value)
    if not match:
        return ""
    parts = urllib.parse.urlsplit(match.group(0).rstrip(".,)"))
    if "parks.vic.gov.au" not in parts.netloc.lower():
        return ""
    if not re.fullmatch(r"/places-to-see/parks/[a-z0-9-]+/?", parts.path.lower()):
        return ""
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/"), "", ""))


def urls_in(fields, finder=None):
    finder = finder or campground_url
    found = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            url = finder(value)
            if url and url not in found:
                found.append(url)

    walk(fields)
    return found


def _cache_path(url):
    name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json"
    return os.path.join(CACHE_DIR, name)


def _cache_get(url, now):
    path = _cache_path(url)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            row = json.load(handle)
        fetched = datetime.fromisoformat(row.get("fetched") or "")
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=MELBOURNE)
    if now - fetched > CACHE_TTL:
        return None
    return {"error": str(row.get("error") or ""), "html": row.get("html") or "", "status": row.get("status")}


def _cache_put(url, row, now):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    payload = {"url": url, "fetched": now.isoformat(), "status": row.get("status"), "error": row.get("error") or "", "html": row.get("html") or ""}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_page(url, now):
    cached = _cache_get(url, now)
    if cached is not None:
        cached["cached"] = True
        return cached
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    row = {"error": "", "html": "", "status": None, "cached": False}
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            row["status"] = getattr(response, "status", 200)
            row["html"] = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        row["status"] = exc.code
        row["error"] = str(exc.code)
    except Exception as exc:
        row["error"] = str(exc)[:200] or exc.__class__.__name__
    _cache_put(url, row, now)
    return row


def _record(camp, url, checked, sentence=None, error=None):
    row = {
        "slug": camp.get("slug") or "",
        "name": camp.get("name") or "",
        "url": url,
        "checked": checked,
    }
    if error is not None:
        row["error"] = error
    else:
        row["sentence"] = sentence or ""
    return row


def write_flags(camps, dest, fetcher=None, sleeper=None, now=None, overall_seconds=OVERALL_SECONDS):
    """Write the flags file. Returns how many closure mismatches were listed.

    fetcher and sleeper are test hooks. The default fetcher talks to Parks
    Victoria and caches the page. Camp dicts are not modified.
    """
    now = now or datetime.now(MELBOURNE)
    checked = now.date().isoformat()
    fetcher = fetcher or (lambda url: fetch_page(url, now))
    sleeper = sleeper if sleeper is not None else time.sleep
    with open(CORRECTIONS, encoding="utf-8") as handle:
        corrections = json.load(handle)
    by_id = {}
    for camp in camps:
        for key in (camp.get("osm_id"), camp.get("id")):
            if key:
                by_id[str(key)] = camp
    jobs = []
    seen = set()
    for key, fields in corrections.items():
        camp = by_id.get(str(key))
        if not isinstance(fields, dict) or camp is None:
            continue
        urls = [(url, False) for url in urls_in(fields)]
        if not urls:
            # No campground page: read the park page's alerts that name this camp.
            urls = [(url, True) for url in urls_in(fields, park_url)]
        for url, named_only in urls:
            pair = (camp.get("slug"), url)
            if pair in seen:
                continue
            seen.add(pair)
            jobs.append((camp, url, named_only))
    pages = {}
    started = time.monotonic()
    incomplete = False
    for url in dict.fromkeys(url for _, url, _ in jobs):
        if time.monotonic() - started > overall_seconds:
            incomplete = True
            break
        before = time.monotonic()
        try:
            pages[url] = fetcher(url)
        except Exception as exc:
            pages[url] = {"error": str(exc)[:200] or "fetch failed", "html": "", "cached": True}
        if not pages[url].get("cached"):
            wait = GAP_SECONDS - (time.monotonic() - before)
            if wait > 0:
                sleeper(wait)
    flags, seasonal, errors = [], [], []
    for camp, url, named_only in jobs:
        page = pages.get(url)
        if page is None:
            continue
        if page.get("error"):
            errors.append(_record(camp, url, checked, error=str(page["error"])))
            continue
        found = classify_html(page.get("html") or "", camp.get("name") or "", named_only)
        if camp.get("status") != "closed" and found["closed"]:
            flags.append(_record(camp, url, checked, sentence=" ".join(found["closed"])))
        for sentence in found["seasonal"]:
            seasonal.append(_record(camp, url, checked, sentence=sentence))
    if incomplete:
        errors.append({
            "slug": "",
            "name": "",
            "url": "",
            "error": "stopped before all pages were fetched",
            "checked": checked,
        })
    doc = {
        "generated": now.isoformat(),
        "checked": checked,
        "flags": flags,
        "seasonal": seasonal,
        "errors": errors,
    }
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return len(flags)
