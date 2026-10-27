#!/usr/bin/env python3
"""NSW camp closures from the NPWS alerts RSS, and fire danger from the RFS feed.

Official text only. A camp stays "check" unless an alert records a closure of
that reserve or of that campground. Fire danger is the RFS district value for
the polygon that contains the camp. If a feed or its boundary layer is
unavailable, this leaves status and the fire line unset.
"""
import html as html_lib
import math
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

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
    """True when the official place name is this camp, allowing a picnic/area suffix."""
    camp, place = camp_key(camp_name), camp_key(piece)
    if len(camp) < 4 or len(place) < 4:
        return False
    if camp == place:
        return True
    if place.startswith(camp + " "):
        rest = [word for word in place[len(camp):].split() if word not in _GENERIC_WORDS]
        return not rest
    if camp.startswith(place + " "):
        rest = [word for word in camp[len(place):].split() if word not in _GENERIC_WORDS]
        return not rest
    return False


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
    for item in items:
        scope = item["title_norm"] if item["title_norm"] in by_norm else ""
        if scope:
            found = whole_park_closure(by_norm[scope], item)
            if found and scope not in whole:
                whole[scope] = found
        for heading, body in item.get("sections") or []:
            if not heading.lower().startswith(("closed areas", "closed parks")):
                continue
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
                    listed[target] = (_official(heading, body), item["link"])
                    continue
                bucket = exempt if mode == "open" else named
                for piece in _name_pieces(bullet):
                    if len(camp_key(piece)) >= 4:
                        bucket.setdefault(target, []).append((piece, clip(bullet), item["link"]))
            if not scope or scope not in by_norm:
                continue
            if reserve_campgrounds_exempt(body, by_norm[scope]) or any(piece == "*" for piece, _text, _url in exempt.get(scope, [])):
                continue
            prose = "\n".join(line for line in (heading + "\n" + body).split("\n") if not line.startswith("- "))
            for match in _CLOSED_SENTENCE.finditer(prose):
                start = prose.rfind("\n", 0, match.start()) + 1
                end = prose.find(".", match.end())
                sentence = prose[start: end + 1 if end != -1 else match.end()].strip()
                if _EXEMPT.search(sentence):
                    continue
                for piece in _name_pieces(match.group(1)):
                    if len(camp_key(piece)) >= 4:
                        named.setdefault(scope, []).append((piece, clip(sentence), item["link"]))
    return {"whole": whole, "listed": listed, "named": named, "exempt": exempt}


def _piece_hit(rows, camp_name):
    for piece, text, url in rows or []:
        if piece != "*" and keys_match(camp_name, piece):
            return text, url
    return None


def lookup_closure(index, reserve, camp_name):
    """Closed parks text covers the reserve. An OPEN list blocks a named or listed closure."""
    title = reserve["title_norm"]
    rows = index["exempt"].get(title) or []
    starred = any(piece == "*" for piece, _text, _url in rows)
    if title in index["whole"]:
        return index["whole"][title]
    if starred or _piece_hit(rows, camp_name):
        return None
    if title in index["listed"]:
        return index["listed"][title]
    return _piece_hit(index["named"].get(title), camp_name)


def closure_for(reserve, camp_name, item):
    """Whole-reserve closure wins. A fire-ban exemption in another section does not reopen it."""
    return lookup_closure(index_closures([item], [reserve]), reserve, camp_name)


def alert_notes(item):
    notes = []
    seen = set()
    for heading, _body in item.get("sections") or []:
        key = heading.casefold()
        if key in seen:
            continue
        seen.add(key)
        notes.append({"heading": heading, "url": item["link"]})
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


def reserves_at(grid, lon, lat):
    found = []
    for record in grid.get(_cell(lon, lat), []):
        if _contains(record["prep"], lon, lat):
            found.append(record)
    return found


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
    index = index_closures(items, reserve_records)
    matched_titles = {record["title_norm"] for record in reserve_records}
    closed_titles = []
    for item in items:
        if any(heading.lower().startswith("closed parks") for heading, _body in item["sections"]):
            if item["title_norm"] not in matched_titles:
                closed_titles.append(item["title"])
    noted = closed = affected = 0
    for camp in camps:
        camp["alerts_checked"] = True
        reserves = reserves_at(grid, camp["lon"], camp["lat"])
        notes = []
        chosen = None
        seen = set()
        for reserve in reserves:
            for item in by_title.get(reserve["title_norm"], []):
                for note in alert_notes(item):
                    key = (note["heading"].casefold(), note["url"])
                    if key in seen:
                        continue
                    seen.add(key)
                    notes.append(note)
            if chosen is None:
                chosen = lookup_closure(index, reserve, camp.get("name") or "")
        if notes:
            camp["alerts"] = notes
            noted += 1
        if chosen and not (camp.get("status") == "closed" and (camp.get("closure") or {}).get("source_url")):
            text, url = chosen
            if text and url:
                camp["status"] = "closed"
                camp["closure"] = {
                    "status": "Closed",
                    "desc": text,
                    "reason": "",
                    "start": None,
                    "reopen": "",
                    "outdated": False,
                    "source_url": url,
                }
                closed += 1
        if camp.get("alerts") or str((camp.get("closure") or {}).get("source_url") or "").startswith("https://www.nationalparks.nsw.gov.au/"):
            affected += 1
    return {"noted": noted, "closed": closed, "affected": affected, "unmatched_closed": closed_titles}


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
                        f"NPWS alerts: {len(items)} items, {summary['affected']} camps affected, {summary['closed']} closed"
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
