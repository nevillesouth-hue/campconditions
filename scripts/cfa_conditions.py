"""CFA fire danger ratings and Total Fire Ban status for Victorian camps.

Ratings come from the CFA RSS feed listed on DataVic under CC BY 4.0.
A camp is placed only when it falls inside a Vicmap Admin CFA Total Fire Ban
district polygon from the DataVic WFS, also CC BY 4.0.

CloudFront blocks www.cfa.vic.gov.au from some build hosts (403, independent
of User-Agent and Accept). The VicEmergency FDR XML, JSON and RSS page ids
return an empty body, so they are not a second copy of this feed. A failed
read is retried, then the last successful parse is reused when it is under
24 hours old and still covers today or tomorrow in Australia/Melbourne.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import facts
import nsw_conditions

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(_ROOT, "data", "cfa-fdr-cache.json")
COMMITTED_CACHE_PATH = os.path.join(_ROOT, "data", "cfa-fdr-cache.committed.json")
CACHE_MAX_AGE = dt.timedelta(hours=24)
_ACCEPT = {
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
    "Accept-Language": "en-AU,en;q=0.9",
}
_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DATE = re.compile(r"(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{4})", re.I)
_ISSUED = re.compile(r"forecast issued at:\s*(.+)", re.I)

_LINE = re.compile(r"^([A-Za-z][A-Za-z ]{1,40}):\s*(.+)$")


def _plain(fragment):
    text = html.unescape(fragment or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("\r", "")


def _rows(block):
    found = {}
    for raw in (block or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        match = _LINE.match(line)
        if not match:
            continue
        name, value = match.group(1).strip(), match.group(2).strip()
        if "forecast" in name.lower() or not value:
            continue
        key = nsw_conditions._district_key(name)
        if not key:
            continue
        found[key] = {"district": name, "value": nsw_conditions._show_level(value)}
    return found


def _forecast_items(payload):
    """RSS items whose link is the CFA page. Empty if the feed is not RSS."""
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
        link = (node.findtext("link") or "").strip()
        description = node.findtext("description") or ""
        if not link.startswith("https://") or not description:
            continue
        items.append({"link": link, "body": _plain(description)})
    return items


def _day_record(body):
    """District ratings for one feed item, plus the Bureau issued line when present."""
    parts = re.split(r"Fire Danger Ratings", body, maxsplit=1)
    bans = _rows(parts[0])
    ratings = _rows(parts[1] if len(parts) > 1 else "")
    issued_match = _ISSUED.search(body or "")
    issued = re.sub(r"\s+", " ", issued_match.group(1)).strip(" .") if issued_match else ""
    districts = {}
    for key, ban in bans.items():
        rating = ratings.get(key)
        if not rating or not ban["value"] or not rating["value"]:
            continue
        districts[key] = {"district": rating["district"], "rating": rating["value"], "ban": ban["value"]}
    return {"issued": issued, "districts": districts}


def _item_date(body):
    match = _DATE.search(body or "")
    if not match:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if not month:
        return None
    try:
        return dt.date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def parse_cfa(payload):
    """Today and tomorrow, keyed by district. Other days in the feed are ignored."""
    found = {"today": {}, "tomorrow": {}}
    for item in _forecast_items(payload):
        body = item["body"]
        head = re.sub(r"\s+", " ", body).strip().lower()
        if head.startswith("today"):
            role = "today"
        elif head.startswith("tomorrow"):
            role = "tomorrow"
        else:
            continue
        day = {}
        for key, row in _day_record(body)["districts"].items():
            day[key] = {"district": row["district"], "today": row["rating"], "ban_today": row["ban"]}
        if day:
            found[role] = day
    return found


def forecast_days(payload):
    """Calendar days named in the feed. Keys are YYYY-MM-DD in the item text."""
    found = {}
    for item in _forecast_items(payload):
        when = _item_date(item["body"])
        row = _day_record(item["body"])
        if when and row["districts"]:
            found[when.isoformat()] = row
    return found


def fetched_phrase(value):
    """Australia/Melbourne clock time for a stored fetch timestamp."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        when = dt.datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    when = when.astimezone(facts.MELBOURNE)
    return when.strftime("%-d %B %Y, %-I:%M %p %Z")


def cache_window(doc, now):
    """Today and tomorrow from a saved parse, or None when it is too old or for other days.

    `now` is timezone-aware. The fetch must be under 24 hours ago. A saved day is
    used only when its date is today or tomorrow in Australia/Melbourne.
    """
    if not isinstance(doc, dict):
        return None
    raw = str(doc.get("fetched") or "").strip()
    try:
        fetched = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=dt.timezone.utc)
    moment = now if now.tzinfo else now.replace(tzinfo=facts.MELBOURNE)
    age = moment - fetched
    if age > CACHE_MAX_AGE or age < dt.timedelta(hours=-1):
        return None
    today = moment.astimezone(facts.MELBOURNE).date()
    days = doc.get("days") if isinstance(doc.get("days"), dict) else {}
    today_row = days.get(today.isoformat())
    tomorrow_row = days.get((today + dt.timedelta(days=1)).isoformat())
    if not isinstance(today_row, dict) and not isinstance(tomorrow_row, dict):
        return None
    return today_row if isinstance(today_row, dict) else None, tomorrow_row if isinstance(tomorrow_row, dict) else None


def _read_cache(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print("WARN CFA cache", path, exc, file=sys.stderr)
        return None
    return doc if isinstance(doc, dict) else None


def _cache_fetched(doc):
    try:
        fetched = dt.datetime.fromisoformat(str((doc or {}).get("fetched") or ""))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=dt.timezone.utc)
    return fetched


def choose_cache(now):
    """Newest saved parse that is still inside the 24-hour window for today or tomorrow."""
    best_doc = None
    best_window = None
    best_fetched = None
    for path in (CACHE_PATH, COMMITTED_CACHE_PATH):
        doc = _read_cache(path)
        window = cache_window(doc, now)
        fetched = _cache_fetched(doc)
        if not window or fetched is None:
            continue
        if best_fetched is None or fetched > best_fetched:
            best_doc, best_window, best_fetched = doc, window, fetched
    if not best_doc:
        return None
    return best_doc, best_window


def _write_cache(doc):
    try:
        body = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        current = ""
        if os.path.isfile(CACHE_PATH):
            with open(CACHE_PATH, encoding="utf-8") as handle:
                current = handle.read()
        if current == body:
            return
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(tmp, CACHE_PATH)
    except OSError as exc:
        print("WARN CFA cache write", exc, file=sys.stderr)


def _ratings(row, require_ban):
    found = {}
    if not isinstance(row, dict):
        return found
    for key, item in (row.get("districts") or {}).items():
        if not isinstance(item, dict):
            continue
        ban = item.get("ban") or ""
        rating = item.get("rating") or ""
        name = item.get("district") or ""
        if not rating or not name or (require_ban and not ban):
            continue
        found[key] = {"district": name, "today": rating, "ban_today": ban}
    return found


def _rings(geometry):
    kind = (geometry or {}).get("type") or ""
    coords = (geometry or {}).get("coordinates") or []
    if kind == "Polygon":
        return coords
    if kind == "MultiPolygon":
        rings = []
        for poly in coords:
            rings.extend(poly)
        return rings
    return []


def _district_records(doc):
    records = []
    features = doc.get("features") if isinstance(doc, dict) else None
    for feature in features or []:
        props = feature.get("properties") or {}
        name = re.sub(r"\s+", " ", str(props.get("tfb_district") or "")).strip()
        prep = nsw_conditions._prepare(_rings(feature.get("geometry") or {}))
        if not name or not prep:
            continue
        records.append({"name": name, "key": nsw_conditions._district_key(name), "prep": prep})
    return records


def apply_fire_records(camps, records, today, tomorrow, source_url, pages, button, issued="", fetched=""):
    """Attach a district rating only where the polygon matches the CFA feed."""
    grid = nsw_conditions._index(records)
    matched = 0
    for camp in camps:
        chosen = None
        for area in nsw_conditions.reserves_at(grid, camp["lon"], camp["lat"]):
            rating = today.get(area["key"])
            if rating:
                chosen = (area, rating)
                break
        if not chosen:
            continue
        area, rating = chosen
        later = tomorrow.get(area["key"]) or {}
        page = str(pages.get(area["key"]) or "")
        camp["fire"] = {
            "district": rating["district"],
            "today": rating["today"],
            "tomorrow": later.get("today") or "",
            "ban_today": rating["ban_today"],
            "ban_tomorrow": later.get("ban_today") or "",
            "source_url": source_url,
            "page_url": page if page.startswith("https://") else "",
            "button": button if page.startswith("https://") else "",
            "issued": issued or "",
            "fetched": fetched or "",
        }
        matched += 1
    return matched


def _fetch_forecast(fetch_text, url):
    """Three reads of the official RSS. Backoff covers a short CloudFront blip."""
    body = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 ** attempt)
        body = fetch_text("cfa_fdr", url, _ACCEPT)
        if body and forecast_days(body):
            return body
    return body


def apply(camps, sources, fetch_json, fetch_text, source_log=None):
    """Fetch the CFA forecast and district polygons. A stale or failed feed omits the line."""
    sources = sources or {}
    fdr = sources.get("cfa_fdr") or {}
    areas = sources.get("cfa_tfb_districts") or {}
    if not fdr.get("url") or not areas.get("url"):
        print("WARN CFA fire danger needs both the forecast feed and district boundaries", file=sys.stderr)
        return 0
    now = dt.datetime.now(facts.MELBOURNE)
    try:
        xml = _fetch_forecast(fetch_text, fdr["url"])
        geo = fetch_json("cfa_tfb_districts", areas["url"])
        if not isinstance(geo, dict):
            print("WARN CFA district boundaries unavailable; no rating was added", file=sys.stderr)
            return 0
        records = _district_records(geo)
        days = forecast_days(xml) if xml else {}
        issued = ""
        fetched = ""
        today = {}
        tomorrow = {}
        if days:
            doc = {"fetched": now.isoformat(), "source_url": fdr["url"], "days": days}
            window = cache_window(doc, now)
            if window:
                _write_cache(doc)
                today = _ratings(window[0], require_ban=True)
                tomorrow = _ratings(window[1], require_ban=False)
                issued = (window[0] or {}).get("issued") or (window[1] or {}).get("issued") or ""
                if isinstance(source_log, dict) and source_log.get("cfa_fdr"):
                    source_log["cfa_fdr"]["issued"] = issued
        if not today:
            chosen = choose_cache(now)
            if not chosen or not records:
                print("WARN CFA fire danger unavailable; no rating was added", file=sys.stderr)
                return 0
            doc, window = chosen
            today = _ratings(window[0], require_ban=True)
            tomorrow = _ratings(window[1], require_ban=False)
            issued = (window[0] or {}).get("issued") or ""
            fetched = fetched_phrase(doc.get("fetched"))
            info = source_log.get("cfa_fdr") if isinstance(source_log, dict) else None
            if isinstance(info, dict):
                info["ok"] = False
                info["fallback"] = "cached CFA forecast fetched " + str(doc.get("fetched") or "")
                info["cache_fetched"] = doc.get("fetched") or ""
                info["issued"] = issued
            print(f"WARN CFA feed failed; using cached forecast fetched {doc.get('fetched')}", file=sys.stderr)
        if not today or not records:
            print("WARN CFA fire danger could not be read; no rating was added", file=sys.stderr)
            return 0
        pages = {}
        for name, url in (fdr.get("pages") or {}).items():
            pages[nsw_conditions._district_key(name)] = url
        matched = apply_fire_records(
            camps, records, today, tomorrow, fdr["url"], pages, fdr.get("button") or "", issued, fetched
        )
        print(f"CFA fire danger: {matched} camps in a feed district")
        return matched
    except Exception as exc:
        print("WARN CFA fire danger", exc, file=sys.stderr)
        return 0
