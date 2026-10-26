#!/usr/bin/env python3
"""Find Parks Victoria campground pages that say closed while our status does not.

Reads parks.vic.gov.au campground links from data/manual-corrections.json.
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
ROAD_RE = re.compile(r"\b(?:roads?|tracks?|motor vehicles?)\b", re.I)
CAMP_RE = re.compile(r"\bcamp(?:ground|site|ing)?s?\b", re.I)
OTHER_RE = re.compile(r"\b(?:lookouts?|picnic|day visitor)\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
CAMPGROUND_BITS = ("campground", "camping", "where-to-stay", "campsite")
SKIP_TAGS = {"script", "style", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
INTERESTING = ("explore__overview", "change-of-conditions__content", "change-of-conditions__title-text", "change-of-conditions__subtitle")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.saw_region = False
        self.region = []
        self.fallback = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag in BLOCK_TAGS:
                self._add("\n")
            return
        classes = ""
        for key, value in attrs:
            if key == "class" and value:
                classes = value
        interesting = any(bit in classes for bit in INTERESTING)
        if interesting:
            self.saw_region = True
        self.stack.append({
            "tag": tag,
            "skip": tag in SKIP_TAGS,
            "quick": "quick-reference" in classes,
            "interest": interesting,
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
            if flags["block"]:
                self._add("\n")

    def handle_data(self, data):
        self._add(data)

    def _blocked(self):
        return any(item["skip"] or item["quick"] for item in self.stack)

    def _interest(self):
        return any(item["interest"] for item in self.stack)

    def _add(self, data):
        if self._blocked():
            return
        self.fallback.append(data)
        if self._interest():
            self.region.append(data)

    def text(self):
        parts = self.region if self.saw_region else self.fallback
        return html.unescape("".join(parts)).replace("\xa0", " ")


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


def classify_html(page):
    """Return closure sentences and seasonal sentences from one HTML page."""
    closed, seasonal = [], []
    try:
        parser = _Text()
        parser.feed(page or "")
        parser.close()
        extracted = parser.text()
    except Exception:
        extracted = re.sub(r"<[^>]+>", " ", page or "")
    for sentence in sentences(extracted):
        if not CLOSED_RE.search(sentence):
            continue
        if IGNORE_RE.search(sentence) or re.fullmatch(r"this area is closed[.!]?", sentence, re.I):
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
    if not any(bit in parts.path.lower() for bit in CAMPGROUND_BITS):
        return ""
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/"), "", ""))


def urls_in(fields):
    found = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            url = campground_url(value)
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
        for url in urls_in(fields):
            pair = (camp.get("slug"), url)
            if pair in seen:
                continue
            seen.add(pair)
            jobs.append((camp, url))
    pages = {}
    started = time.monotonic()
    incomplete = False
    for url in dict.fromkeys(url for _, url in jobs):
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
    for camp, url in jobs:
        page = pages.get(url)
        if page is None:
            continue
        if page.get("error"):
            errors.append(_record(camp, url, checked, error=str(page["error"])))
            continue
        found = classify_html(page.get("html") or "")
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
