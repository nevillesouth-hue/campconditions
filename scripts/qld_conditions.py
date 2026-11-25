#!/usr/bin/env python3
"""Queensland camps and conditions for the site build.

- QPWS camping grounds from the QSpatial tourist points layer.
- The permit-only area exclusion (Aboriginal shire and Torres Strait council areas).
- QPWS park alerts RSS, matched to QSpatial park and state forest polygons.
- Bureau of Meteorology fire danger ratings (IDQ13016) by fire weather district.
- QLDTraffic flooding and road closures: the QLDTRAFFIC_API_KEY key when set, otherwise TMR's published public key.

Every feed failure is a warning, not a failed build. Nothing is inferred
that the source does not say: a camp is closed only where a QPWS alert
closes its whole park, or names that camping area as closed, and the
closure has started.
"""
import datetime as dt
import html as html_lib
import json
import math
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts
import nsw_conditions as nc

BRISBANE = ZoneInfo("Australia/Brisbane")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# BoM and parks.qld.gov.au refuse script user agents (HTTP 403).
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
}
QPWS_SITE = "https://parks.qld.gov.au/"
QPWS_ALERTS_PAGE = "https://parks.qld.gov.au/park-alerts"


def _path(rel):
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def _load(rel):
    if not rel:
        return None
    try:
        with open(_path(rel), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"WARN {rel} unreadable: {exc}", file=sys.stderr)
        return None


def _files(state):
    return (state or {}).get("files") or {}


# ---------- polygons ----------

def estate_records(doc):
    """Park and state forest records for nsw_conditions point lookups (snap 100 m)."""
    records = []
    for row in (doc or {}).get("estates") or []:
        prep = nc._prepare(row.get("rings"))
        name = str(row.get("name") or "").strip()
        if not prep or not name:
            continue
        records.append({"title": name, "title_norm": nc.norm(name), "loose": loose_key(name),
                        "type": row.get("type") or "", "prep": prep})
    return records


def area_records(rows, key_field="name"):
    """Council or fire district records. No title_norm, so a point never snaps across a line."""
    records = []
    for row in rows or []:
        prep = nc._prepare(row.get("rings"))
        name = str(row.get(key_field) or "").strip()
        if prep and name:
            records.append({"name": name, "key": nc._district_key(name), "prep": prep})
    return records


def lga_at(grid, lon, lat):
    found = nc._reserves_containing(grid, lon, lat)
    return found[0]["name"] if found else ""


# ---------- permit-only areas ----------

def permit_only_config(state):
    cfg = (state or {}).get("permit_only_areas") or {}
    return {
        "include": bool(cfg.get("include_permit_only_areas")),
        "qpws_exempt": bool(cfg.get("permit_only_qpws_exempt")),
        "lgas": set(cfg.get("lgas") or []),
    }


def exclude_permit_only(camps, state, lga_doc=None):
    """Set camp['lga'] and drop camps in permit-only council areas unless the flag includes them.

    Returns (kept, dropped). With include_permit_only_areas true nothing is dropped.
    With permit_only_qpws_exempt true, QPWS camps there are kept and only the others go.
    """
    cfg = permit_only_config(state)
    if lga_doc is None:
        lga_doc = _load(_files(state).get("lgas")) or {}
    grid = nc._index(area_records(lga_doc.get("regions")))
    kept, dropped = [], []
    for camp in camps:
        lga = lga_at(grid, camp["lon"], camp["lat"])
        if lga:
            camp["lga"] = lga
        excluded = (not cfg["include"]) and lga in cfg["lgas"]
        if excluded and cfg["qpws_exempt"] and camp.get("source") == "qpws":
            excluded = False
        (dropped if excluded else kept).append(camp)
    return kept, dropped


# ---------- QPWS camping grounds ----------

def _camp_key(name):
    return nc.camp_key(name)


def permit_area_for(park_names, camp_name, permits):
    """The permits CSV camping area in one of these parks with the same name, or ('', '')."""
    parks = (permits or {}).get("parks") or {}
    for park in park_names:
        for area in parks.get(park) or []:
            if nc.keys_match(camp_name, area):
                return park, area
    return "", ""


def camps_from_features(features, src, estates, permits, region_fn, slug_fn, seen, state_slug, category):
    """Camp rows from QSpatial camping-ground features.

    A point is a QPWS camp when its attribute_source is one of the configured
    Queensland environment or national parks departments, or it lies inside
    a QPWS park or state forest. Other points are returned separately.
    """
    agencies = set(src.get("agencies") or [])
    grid = nc._index(estates)
    found, others = [], []
    permit_hits = 0
    for feature in features or []:
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        name = re.sub(r"\s+", " ", str(attrs.get("name") or "")).strip()
        if not name or "x" not in geom or "y" not in geom:
            continue
        lon, lat = float(geom["x"]), float(geom["y"])
        parks = [record["title"] for record in nc.reserves_at(grid, lon, lat)]
        if str(attrs.get("attribute_source") or "").strip() not in agencies and not parks:
            others.append({"name": name, "lat": lat, "lon": lon, "attribute_source": attrs.get("attribute_source") or ""})
            continue
        ref = str(attrs.get("pfi") or attrs.get("objectid") or "").strip()
        s = slug_fn(name)
        if s in seen:
            s = f"{s}-{slug_fn(ref) or 'qpws'}"[:90].strip("-")
        n = 2
        base_slug = s
        while s in seen:
            s = f"{base_slug}-{n}"
            n += 1
        seen.add(s)
        stamp = attrs.get("attribute_date")
        data_date = ""
        if isinstance(stamp, (int, float)) and stamp > 0:
            data_date = dt.datetime.fromtimestamp(stamp / 1000, dt.timezone.utc).astimezone(BRISBANE).date().isoformat()
        camp = {"slug": s, "id": attrs.get("objectid") if attrs.get("objectid") is not None else (ref or s), "name": name,
                "lat": round(lat, 6), "lon": round(lon, 6), "region": region_fn(lon, lat),
                "status": "check", "closure": None, "access": "", "about": "", "camping": "", "caravans": "",
                "site_class": "", "dis_access": None, "managed_by": "", "data_date": data_date,
                "nearby_closures": [], "source": src.get("source_id") or "qpws", "category": category, "state_slug": state_slug,
                "needs_review": False}
        if ref:
            camp["source_ref"] = ref
        if parks:
            camp["parks"] = parks
        permit_park, permit_area = permit_area_for(parks, name, permits)
        if permit_area:
            camp["permit_area"] = permit_area
            camp["permit_park"] = permit_park
            permit_hits += 1
        found.append(camp)
    return found, others, permit_hits


def fetch_camp_features(fetch_json, src):
    base = str(src.get("url") or "").strip()
    if not base:
        return None
    features, offset = [], 0
    while offset <= 20000:
        query = urllib.parse.urlencode({
            "where": src.get("where") or "feature_type='Camping Ground'",
            "outFields": "objectid,name,attribute_source,attribute_date,pfi",
            "returnGeometry": "true", "outSR": "4326", "f": "json",
            "resultOffset": str(offset), "resultRecordCount": "1000",
        })
        doc = fetch_json(src.get("key") or "qpws_camps", base.rstrip("/") + "/query?" + query)
        if not isinstance(doc, dict) or doc.get("error"):
            return features or None
        batch = doc.get("features") or []
        features.extend(batch)
        if not batch or not doc.get("exceededTransferLimit"):
            break
        offset += len(batch)
    return features


def load_camps(state, fetch_json, region_fn, slug_fn, seen, category):
    """QPWS camps for the build. Empty with a warning if the layer is unavailable."""
    src = (state.get("sources") or {}).get("qpws_camps") or {}
    features = fetch_camp_features(fetch_json, src)
    if not features:
        print("WARN QPWS camping grounds unavailable; no QPWS camps were added", file=sys.stderr)
        return []
    estates = estate_records(_load(_files(state).get("estates")))
    permits = _load(_files(state).get("permit_areas")) or {}
    camps, others, permit_hits = camps_from_features(features, src, estates, permits, region_fn, slug_fn, seen, state["slug"], category)
    print(f"QSpatial camping grounds: {len(features)}; QPWS camps {len(camps)}; other points left out {len(others)}; "
          f"named in the QPWS permits data {permit_hits}")
    return camps


# ---------- QPWS park alerts ----------

_TYPES = ("National Park (Scientific)", "National Park", "Conservation Park", "State Forest", "Resources Reserve",
          "Forest Reserve", "Recreation Area", "Regional Park", "Timber Reserve", "Forest Drive", "Marine Park")
_TYPE_RE = "|".join(re.escape(t) for t in _TYPES)


def loose_key(name):
    """Name without parentheticals: Rinyirru (Lakefield) National Park (CYPAL) is rinyirru national park."""
    text = re.sub(r"\([^)]*\)", " ", str(name or ""))
    text = re.sub(r"\s+\d+$", "", text.strip())  # Danbulla State Forest 1 is Danbulla State Forest
    return nc.norm(text)


def expand_park(name):
    """Every park name an 'Affected parks' entry stands for.

    'Main Range National Park, Goomburra section' is Main Range National Park.
    'Bunya Mountains National Park and Conservation Park' is both.
    'Beerburrum and Beerwah State Forests' is both forests. CYPAL is
    written out as Cape York Peninsula Aboriginal Land, as in QSpatial.
    """
    text = re.sub(r"\s+", " ", html_lib.unescape(str(name or ""))).strip(" .;")
    out = []

    def add(value):
        value = re.sub(r"\s+", " ", value).strip(" ,.;")
        if value and value not in out:
            out.append(value)

    add(text)
    for value in list(out):
        if "," in value:
            parts = [p.strip() for p in value.split(",")]
            for part in parts:
                if re.search(_TYPE_RE, part):
                    add(part)
    for value in list(out):
        add(value.replace("(CYPAL)", "(Cape York Peninsula Aboriginal Land)"))
    for value in list(out):
        match = re.match(r"^(.*?)\s+(" + _TYPE_RE + r")((?:\s*(?:,|and)\s*(?:" + _TYPE_RE + r"))+)(.*)$", value)
        if match:
            base, first, rest, tail = match.groups()
            add(f"{base} {first}{tail}")
            for kind in re.findall(_TYPE_RE, rest):
                add(f"{base} {kind}{tail}")
        pair = re.match(r"^(.+?\b(?:" + _TYPE_RE + r"))\s+and\s+(.+?\b(?:" + _TYPE_RE + r"))$", value)
        if pair:
            add(pair.group(1))
            add(pair.group(2))
        plural = re.match(r"^(.+?)\s+and\s+(.+?)\s+(State Forests|National Parks|Conservation Parks)$", value)
        if plural:
            kind = plural.group(3)[:-1]
            add(f"{plural.group(1)} {kind}")
            add(f"{plural.group(2)} {kind}")
    return out


# Estate type words stripped before a park name is used as a search phrase.
# Longest first so "national park" is removed as a whole, not as two leftovers.
_PARK_SUFFIXES = tuple(sorted((
    "national park",
    "conservation park",
    "resources reserve",
    "state forest",
    "forest reserve",
    "timber reserve",
    "recreation area",
    "regional park",
    "forest drive",
    "marine park",
), key=len, reverse=True))
# A query that is only these words does not match a park. "island" must not
# return every island park, and "range" must not return every range park.
PARK_GENERIC_WORDS = frozenset({
    "national", "park", "island", "islands", "range", "creek", "mount", "forest",
})
# Full <title> length, including " | CampConditions.au". Longer than this, the
# park is left off the title. The meta description can still name it.
TITLE_PARK_LIMIT = 120


def fold_search(value):
    """Same folding as the map search box: lower case, letters and digits only."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def park_distinctive(name):
    """The part of a park name that is not its type.

    'Girraween National Park' is 'girraween'. Parentheticals and a trailing
    number (Danbulla State Forest 1) are qualifiers, not the name.
    """
    text = re.sub(r"\([^)]*\)", " ", str(name or ""))
    text = re.sub(r"\s+\d+\s*$", "", text.strip())
    folded = fold_search(text)
    for suffix in _PARK_SUFFIXES:
        if folded == suffix:
            return ""
        tail = " " + suffix
        if folded.endswith(tail):
            return folded[: -len(tail)].strip()
    return folded


def park_phrases(parks):
    """Distinctive phrases for camp['parks'], in that list's order."""
    phrases = []
    for raw in parks or []:
        phrase = park_distinctive(raw)
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def park_search_key(parks):
    """Map-point field. One phrase per park, separated by |."""
    return "|".join(park_phrases(parks))


def _words_contain(phrase, text):
    phrase_words = fold_search(phrase).split(" ")
    text_words = fold_search(text).split(" ")
    if not phrase_words or not phrase_words[0] or len(phrase_words) > len(text_words):
        return False
    span = len(phrase_words)
    return any(text_words[i:i + span] == phrase_words for i in range(len(text_words) - span + 1))


def park_query_match(phrases, query):
    """True when the query is a whole word or a contiguous phrase in a park name.

    'girra' does not match 'girraween'. 'girraween' does not match Girramay or
    Girringun. A query made only of generic words ('park', 'island', 'range')
    does not match.
    """
    folded = fold_search(query)
    if len(folded) < 2:
        return False
    query_words = folded.split(" ")
    if not query_words or all(word in PARK_GENERIC_WORDS for word in query_words):
        return False
    for phrase in phrases or []:
        if _words_contain(folded, phrase):
            return True
    return False


def _short_park_name(name):
    """Park name without parentheticals or a trailing estate number."""
    text = re.sub(r"\s*\([^)]*\)", " ", str(name or ""))
    text = re.sub(r"\s+\d+\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def park_display_name(parks, *texts):
    """Official park name to show, or '' when a camp name already says it.

    A national park is preferred when the point sits in more than one estate.
    The distinctive phrase has to be missing from every camp name passed in.
    """
    names = []
    for raw in parks or []:
        name = re.sub(r"\s+", " ", str(raw or "")).strip()
        if name and name not in names:
            names.append(name)

    def rank(name):
        folded = fold_search(name)
        if "national park" in folded:
            kind = 0
        elif "conservation park" in folded:
            kind = 1
        else:
            kind = 2
        return (kind, len(name), name)

    for name in sorted(names, key=rank):
        phrase = park_distinctive(name)
        if not phrase:
            continue
        if any(_words_contain(phrase, text) for text in texts if text):
            continue
        return name
    return ""


def park_title_and_description(title, description, name, page_name, parks, limit=TITLE_PARK_LIMIT):
    """Add ', {park}' after the camp name in the title and the meta description.

    No parks, or the camp name already contains the park's distinctive name:
    both strings come back unchanged. A title that would pass `limit` keeps
    its old text. The description still names the park.
    """
    if not parks:
        return title, description
    label = park_display_name(parks, name, page_name)
    if not label:
        return title, description
    short = _short_park_name(label) or label

    def with_title(park):
        if page_name and str(title).startswith(page_name):
            return page_name + ", " + park + title[len(page_name):]
        return ""

    def with_desc(park):
        if name and str(description).startswith(name):
            return name + ", " + park + description[len(name):]
        return description

    full_title = with_title(label)
    if full_title and len(full_title) <= limit:
        return full_title, with_desc(label)
    if short != label:
        short_title = with_title(short)
        if short_title and len(short_title) <= limit:
            return short_title, with_desc(short)
    desc_label = short if len(label) > 60 else label
    return title, with_desc(desc_label)


def parse_rss(payload):
    """QPWS alert items: title, link, published, description (without the parks list) and affected parks."""
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
        title = re.sub(r"\s+", " ", html_lib.unescape(node.findtext("title") or "")).strip()
        link = (node.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        raw = html_lib.unescape(node.findtext("description") or "")
        raw = re.sub(r"<[^>]+>", " ", raw).replace("\xa0", " ")
        raw = re.sub(r"\s+", " ", raw).strip()
        desc, parks = raw, []
        match = re.search(r"\s*Affected parks:\s*(.*)$", raw, re.I)
        if match:
            desc = raw[:match.start()].strip()
            parks = [p.strip() for p in re.split(r";", match.group(1)) if p.strip()]
        keys, loose = set(), set()
        for park in parks:
            for value in expand_park(park):
                keys.add(nc.norm(value))
                loose.add(loose_key(value))
        items.append({"title": title, "title_norm": nc.norm(title), "link": link,
                      "published": (node.findtext("pubDate") or "").strip(), "desc": desc,
                      "parks": parks, "park_keys": keys, "park_loose": loose})
    return items


def item_in_park(item, estate):
    return estate["title_norm"] in item["park_keys"] or (estate["loose"] and estate["loose"] in item["park_loose"])


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]


_CLOSED_PRED = re.compile(
    r"^(?P<subject>.+?)\s+(?:(?:is|are|will be|has been|have been|remains?|remain)\s+(?:temporarily\s+|currently\s+|now\s+|fully\s+|still\s+)?closed\b|will close\b|closes\b)",
    re.I)
_LEAD_CLAUSE = re.compile(r"^(?:as a result of|due to|because of|following|after)\b[^,]*,\s*", re.I)


def whole_park_sentence(item, estate):
    """The description sentence that closes the whole park, or ''.

    The subject must be the park itself, as in 'As a result of wet weather,
    Culgoa Floodplain National Park is closed until declared safe.'. A title
    alone, or 'some areas of', never closes a park.
    """
    for sentence in _sentences(item["desc"]):
        match = _CLOSED_PRED.match(sentence)
        if not match:
            continue
        # Only a leading cause clause is dropped. "Little Crystal Creek day-use
        # area in Mount Spec section, Paluma Range National Park is closed" is
        # not the whole park.
        subject = _LEAD_CLAUSE.sub("", match.group("subject")).strip()
        subject = re.sub(r"^the\s+", "", subject, flags=re.I)
        if "," in subject or re.search(r"\bsection\b", subject, re.I):
            continue  # a section or a place within a park, not the whole park
        if re.search(r"\b(?:some|areas?|parts?|sections?|sites?|roads?|tracks?|trails?|walks?|facilities)\b", subject, re.I) and \
                not re.search(_TYPE_RE, subject):
            continue
        keys = {nc.norm(v) for v in expand_park(subject)} | {loose_key(v) for v in expand_park(subject)}
        if estate["title_norm"] in keys or (estate["loose"] and estate["loose"] in keys):
            return sentence
    # QPWS marks some alerts "Entire park is closed to the public" in the
    # page body without repeating the park name in that sentence.
    if re.search(r"\bentire park is closed\b|\bentire park closure\b", item.get("desc") or "", re.I):
        return "Entire park is closed to the public."
    return ""


_CLOSE_WORD = re.compile(r"\bclos(?:ed|ure|ures|ing|es)\b|\bwill close\b", re.I)
_CAMP_WORDS = re.compile(r"\b(?:camping areas?|campgrounds?|camps?|bush camping|camping zones?|camping)\b", re.I)
_NOT_CAMP_CLOSURE = re.compile(
    r"\b(?:toilets?|phones?|telephones?|jett(?:y|ies)|moorings?|shelters?|bbqs?|barbecues?|boat ramps?|"
    r"camp ?sites? \d+|sites? \d+|bookings?|booking restrictions?|partial(?:ly)?|"
    r"(?:one|several|some|a number) of (?:the )?[a-z ]*?(?:are|is) closed|following facilities|water supply)\b",
    re.I)


def _key_words(name):
    keys = []
    for variant in nc.name_variants(name):
        key = _camp_key(variant)
        if len(key.replace(" ", "")) >= 4 and key not in keys:
            keys.append(key)
    return keys


_FACILITY_WORDS = {"track", "tracks", "road", "roads", "trail", "trails", "walk", "walks", "day", "use", "lookout",
                   "falls", "section", "drive", "picnic", "beach", "bridge", "access"}
_CAMP_AFTER = r"(?:camping|campgrounds?|camps?|bush camping)\b"



def _soft_stem(text):
    """Fold common QPWS/OSM naming variants so a match is not missed.

    Six Mile Waterhole is Six Mile Lagoon in some records. Halifax Bay
    Wetland and Wetlands are the same park.
    """
    text = nc.norm(text)
    text = re.sub(r"\bwetlands\b", "wetland", text)
    text = re.sub(r"\b(waterholes?|lagoons?|lakes?)\b", "water", text)
    return text


def _numbered_camping_area(text, camp_name):
    """'Camping area 2 at Halifax Bay Wetlands National Park' names camping area 2."""
    match = re.search(r"^(.*?)\s+(camping areas?|campgrounds?)\s+(\d+)$", nc.norm(camp_name))
    if not match:
        return False
    park, number = _soft_stem(match.group(1)), match.group(3)
    hay = _soft_stem(text)
    return bool(re.search(r"\b(?:camping areas?|campgrounds?)\s+" + re.escape(number) + r"\b", hay)
                and park and re.search(r"\b" + re.escape(park) + r"\b", hay))


def names_camp(text, camp_name):
    """True when the text names this camp next to a camp word.

    'Carter Creek and Cochable Creek camping areas' names both camps.
    'Koolmoon Creek track' does not name Koolmoon Creek Camping Area, and
    'bush camping in Koombooloomba National Park' does not name a camp
    called Koombooloomba National Park Camping Area.
    """
    hay = " " + nc.norm(text) + " "
    full = re.sub(r" (?:camping area|camping areas|campground|camp ground|camp)$", "", nc.norm(camp_name))
    if re.search(r"\b(?:camping|campground|camp)\b", full) and len(full) >= 8 and f" {full} " in hay:
        return True  # "Beach camping zone 9 (Diray and Carree)" names itself as a camp
    for key in _key_words(camp_name):
        for match in re.finditer(r"(?<= )" + re.escape(key) + r"(?= )", hay):
            rest = hay[match.end():]
            filler = re.match(r" ([a-z0-9']+)", rest)
            if filler and filler.group(1) not in _FACILITY_WORDS and filler.group(1) not in ("and", "or") and \
                    not re.match(_CAMP_AFTER, filler.group(1)):
                rest = rest[filler.end():]
            joined = re.match(r" (?:and|or) (?:[a-z0-9']+ ){1,4}?(?=" + _CAMP_AFTER + ")", rest)
            if joined:
                rest = rest[joined.end() - 1:]
            if re.match(r" " + _CAMP_AFTER, rest):
                return True
    if _numbered_camping_area(text, camp_name):
        return True
    # Same keys after waterhole/lagoon/lake and wetland/wetlands folding.
    hay_soft = " " + _soft_stem(text) + " "
    for key in _key_words(camp_name):
        soft = _soft_stem(key)
        if len(soft.replace(" ", "")) < 4:
            continue
        for match in re.finditer(r"(?<= )" + re.escape(soft) + r"(?= )", hay_soft):
            rest = hay_soft[match.end():]
            filler = re.match(r" ([a-z0-9']+)", rest)
            if filler and filler.group(1) not in _FACILITY_WORDS and filler.group(1) not in ("and", "or") and \
                    not re.match(_CAMP_AFTER, filler.group(1)):
                rest = rest[filler.end():]
            joined = re.match(r" (?:and|or) (?:[a-z0-9']+ ){1,4}?(?=" + _CAMP_AFTER + ")", rest)
            if joined:
                rest = rest[joined.end() - 1:]
            if re.match(r" " + _CAMP_AFTER, rest):
                return True
    return False


def named_camp_text(item, camp_name):
    """The title or sentence that closes this named camping area, or ''."""
    title = item["title"]
    if names_camp(title, camp_name) and _CLOSE_WORD.search(title) and not _NOT_CAMP_CLOSURE.search(title):
        # The dates are in the description; prefer the sentence that names the camp.
        for sentence in _sentences(item["desc"]):
            if names_camp(sentence, camp_name) and not _NOT_CAMP_CLOSURE.search(sentence):
                return sentence
        return item["desc"] or title
    for sentence in _sentences(item["desc"]):
        if names_camp(sentence, camp_name) and \
                re.search(r"\bclosed\b|\bclosure\b|\bwill close\b", sentence, re.I) and not _NOT_CAMP_CLOSURE.search(sentence):
            return sentence
    return ""




def camps_same(camp_name, piece):
    """True when a listed official name is this camp, including feature aliases."""
    if not piece or not camp_name:
        return False
    if nc.keys_match(camp_name, piece) or nc.keys_match(_soft_stem(camp_name), _soft_stem(piece)):
        return True
    return names_camp(piece, camp_name)


_FOLLOWING_CLOSED = re.compile(
    r"(?:will close the following|the following (?:camping(?: and day-use)?|campgrounds?|areas?) will be closed)\b",
    re.I)
_REMAIN_OPEN = re.compile(r"the following camping areas will remain open\b", re.I)
_LIST_STOP = re.compile(
    r"^(?:visitors are advised|please |all camp |for campers|should you|important information|"
    r"the park will|construction |queensland parks)\b",
    re.I)
_NEEDS_PAGE = re.compile(
    r"\bthe following (?:camping|campgrounds?|day-use|areas?)\b|"
    r"\bplease see below\b|"
    r"\blisted below\b",
    re.I)
ALERT_PAGE_CAP = 40


def _list_names(chunk):
    """Camp-like names from a QPWS 'following areas' block."""
    if ":" in chunk[:120]:
        chunk = chunk.split(":", 1)[1]
    found = []
    for line in re.split(r"[\n;]+", chunk):
        line = re.sub(r"\s+", " ", line).strip(" .;-")
        if not line:
            continue
        if _LIST_STOP.search(line) or re.search(r"\b(refund|online account|monitor park alerts)\b", line, re.I):
            break
        if len(line) > 90:
            continue
        line = re.sub(r"\s+and day-use areas?$", "", line, flags=re.I)
        if line and line not in found:
            found.append(line)
    return found


def listed_camp_block(desc):
    """Names closed, then names kept open, from a 'following areas' list."""
    text = desc or ""
    start = _FOLLOWING_CLOSED.search(text)
    if not start:
        return [], []
    rest = text[start.end():]
    opened = _REMAIN_OPEN.search(rest)
    closed_part = rest[:opened.start()] if opened else rest
    open_part = rest[opened.end():] if opened else ""
    return _list_names(closed_part), _list_names(open_part)


def alert_needs_page(item):
    """True when the RSS description defers the named camps to the alert page."""
    blob = f"{item.get('title') or ''} {item.get('desc') or ''}"
    if not _NEEDS_PAGE.search(blob):
        return False
    closed, opened = listed_camp_block(item.get("desc") or "")
    return not (closed or opened)


def alert_page_text(html):
    """Plain text of the official QPWS alert body, with list items on their own lines."""
    if not html:
        return ""
    if isinstance(html, bytes):
        html = html.decode("utf-8", "replace")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    start = re.search(r"This alert applies to the following park:", text)
    if not start:
        start = re.search(r"Closure status:", text)
    if start:
        text = text[start.start():]
    end = re.search(r"Important information about maps", text)
    if end:
        text = text[:end.start()]
    return text.strip()


def enrich_alert_pages(items, fetch_text, cap=ALERT_PAGE_CAP):
    """Fill in RSS items whose description omits the listed camping areas.

    The QPWS RSS often stops at 'the following camping areas' or 'please see
    below' and leaves the names on the alert page. A fetch failure leaves the
    RSS text in place.
    """
    if not fetch_text:
        return 0
    fetched = 0
    for item in items:
        if fetched >= cap or not alert_needs_page(item):
            continue
        link = item.get("link") or ""
        if not link.startswith("https://parks.qld.gov.au/"):
            continue
        payload = fetch_text("qpws_alert_page", link, BROWSER_HEADERS)
        body = alert_page_text(payload)
        if body:
            item["desc"] = body
            item["page_enriched"] = True
        fetched += 1
    return fetched



_UP_TO = re.compile(r"\bup to and including\b", re.I)
_CLOSE_ON = re.compile(r"\b(will close|closes|is closed|will be closed|are closed|close)\b([^.]*?)\bon\b(?=\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d))", re.I)


def qld_now(now=None):
    """Queensland wall clock labelled as Melbourne, so nsw_conditions.closure_timing reads QPWS dates as printed."""
    moment = now or dt.datetime.now(BRISBANE)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BRISBANE)
    return moment.astimezone(BRISBANE).replace(tzinfo=facts.MELBOURNE)


def timing(text, now=None):
    """nsw_conditions.closure_timing on QPWS wording, in Queensland time.

    'up to and including 29 October' ends after 29 October. 'will close on
    20 November' starts then.
    """
    text = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)(?: of)?\s+(?=[A-Z][a-z]+)", r"\1 ", text or "")
    inclusive = bool(_UP_TO.search(text))
    fixed = _UP_TO.sub("until", text)
    fixed = _CLOSE_ON.sub(lambda m: f"{m.group(1)}{m.group(2)}from", fixed)
    result = nc.closure_timing(fixed, qld_now(now))
    if inclusive and result.get("reopen") and not result.get("reopen_time"):
        reopen = dt.date.fromisoformat(result["reopen"]) + dt.timedelta(days=1)
        result["reopen"] = reopen.isoformat()
        if result["kind"] == "expired" and dt.datetime.combine(reopen, dt.time(), facts.MELBOURNE) > qld_now(now):
            result["kind"] = "current"
    return result


def closure_candidates(camp, items, estates_for_camp, now=None):
    """Whole-park and named-camp closures for one camp, each with its timing."""
    found = []
    for item in items:
        parks = [estate for estate in estates_for_camp if item_in_park(item, estate)]
        if not parks:
            continue
        closed_names, open_names = listed_camp_block(item.get("desc") or "")
        camp_name = camp.get("name") or ""
        if any(camps_same(camp_name, name) for name in open_names):
            # "The following camping areas will remain open" beats the listed closure.
            continue
        text = ""
        if any(camps_same(camp_name, name) for name in closed_names):
            # Time the listed closure by the preamble only. A later sentence
            # that names the camp can also contain the remain-open dates.
            desc = item.get("desc") or ""
            opened = _REMAIN_OPEN.search(desc)
            text = desc[:opened.start()] if opened else desc
        if not text:
            for estate in parks:
                text = whole_park_sentence(item, estate)
                if text:
                    break
        if not text:
            text = named_camp_text(item, camp_name)
        if not text:
            continue
        timed = timing(text, now)
        if timed["kind"] == "current" and not timed.get("start"):
            # Dates elsewhere in the alert (a separate sentence) still count.
            whole = timing(item["desc"], now)
            if whole["kind"] in ("upcoming", "expired") or whole.get("reopen"):
                timed = whole
        found.append({"item": item, "text": text, **timed})
    return found


def _choose(candidates):
    current = [c for c in candidates if c["kind"] == "current"]
    if current:
        return current[0]
    upcoming = sorted((c for c in candidates if c["kind"] == "upcoming"), key=lambda c: c.get("start") or "9999")
    return upcoming[0] if upcoming else None


def apply_alert_items(camps, estates, items, now=None):
    """Closure, upcoming notice and notes on every camp in a park with an alert."""
    grid = nc._index(estates)
    summary = {"closed": 0, "upcoming": 0, "noted": 0, "affected": 0, "unmatched_parks": []}
    known = set()
    for estate in estates:
        known.add(estate["title_norm"])
        if estate["loose"]:
            known.add(estate["loose"])
    for item in items:
        for park in item["parks"]:
            keys = {nc.norm(v) for v in expand_park(park)} | {loose_key(v) for v in expand_park(park)}
            if not keys & known and park not in summary["unmatched_parks"]:
                summary["unmatched_parks"].append(park)
    for camp in camps:
        camp["alerts_checked"] = True
        here = nc.reserves_at(grid, camp["lon"], camp["lat"])
        if not here:
            continue
        if not camp.get("parks"):
            camp["parks"] = [estate["title"] for estate in here]
        relevant = [item for item in items if any(item_in_park(item, estate) for estate in here)]
        if not relevant:
            continue
        chosen = _choose(closure_candidates(camp, relevant, here, now))
        notes = [{"heading": item["title"], "url": item["link"], "published": item.get("published") or ""}
                 for item in relevant if not chosen or item is not chosen["item"]]
        if notes:
            camp["alerts"] = notes
            summary["noted"] += 1
        if chosen:
            item = chosen["item"]
            record = {"status": "Closed", "desc": nc.clip(item["desc"] or chosen["text"]), "reason": "",
                      "start": chosen.get("start"), "reopen": chosen.get("reopen") or "", "outdated": False,
                      "source_url": item["link"], "source_published": item.get("published") or ""}
            for key in ("start_time", "reopen_time"):
                if chosen.get(key):
                    record[key] = chosen[key]
            if chosen["kind"] == "upcoming":
                camp["closure"] = None
                camp["upcoming_closure"] = record
                summary["upcoming"] += 1
            else:
                camp["status"] = "closed"
                camp["closure"] = record
                camp.pop("upcoming_closure", None)
                summary["closed"] += 1
        summary["affected"] += 1
    return summary


# ---------- BoM fire danger ----------

def parse_fdr(payload):
    """District key to {district, days {YYYY-MM-DD: rating}} plus the issue time, from IDQ13016."""
    if not payload:
        return {}, None
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return {}, None
    issued = None
    stamp = root.findtext(".//amoc/issue-time-utc")
    if stamp:
        try:
            issued = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            issued = None
    found = {}
    for area in root.iter("area"):
        if area.get("type") != "fire-district":
            continue
        name = re.sub(r"\s+", " ", area.get("description") or "").strip()
        if not name:
            continue
        days = {}
        for period in area.findall("forecast-period"):
            start = period.get("start-time-local") or ""
            rating = ""
            for text in period.findall("text"):
                if text.get("type") == "fire_danger":
                    rating = nc._show_level(text.text or "")
            if start[:10] and rating:
                days[start[:10]] = rating
        if days:
            found[nc._district_key(name)] = {"district": name, "days": days}
    return found, issued


# BoM's Queensland fire danger ratings page (the human page for IDQ13016).
BOM_FDR_PAGE = "https://www.bom.gov.au/qld/forecasts/fire-danger-ratings.shtml"


def apply_fire(camps, district_records, ratings, issued, source_url, links, now=None):
    """Today's and tomorrow's rating (Queensland dates) for the camp's fire weather district."""
    grid = nc._index(district_records)
    today = (now or dt.datetime.now(BRISBANE)).astimezone(BRISBANE).date()
    tomorrow = today + dt.timedelta(days=1)
    issued_text = ""
    if issued:
        local = issued.astimezone(facts.MELBOURNE)
        issued_text = local.strftime("%-I:%M %p %Z %A %-d %B %Y").replace("AM", "am").replace("PM", "pm")
    matched = 0
    for camp in camps:
        # Shore camps just outside the coastline-clipped QFD edge, and Dumaresq/
        # Macintyre border-river camps, take the nearest Queensland district
        # (nsw_conditions FIRE_FALLBACK_KM rule). Islands 1 km or more offshore
        # keep no district: "No fire district mapped", never "No Rating".
        def rated(key):
            days = (ratings.get(key) or {}).get("days") or {}
            return bool(days.get(today.isoformat()) or days.get(tomorrow.isoformat()))
        area, km, how = nc.district_for(grid, district_records, camp["lon"], camp["lat"], rated)
        if how == "unmapped":
            nc.mark_unmapped(camp, "QFD", links.get("fire_danger_page") or BOM_FDR_PAGE,
                             links.get("fire_danger_button") or "Check BoM fire danger ratings")
        if not area:
            continue
        rating = ratings[area["key"]]
        day_today = rating["days"].get(today.isoformat(), "")
        day_tomorrow = rating["days"].get(tomorrow.isoformat(), "")
        camp.pop("fire_unmapped", None)
        camp["fire"] = {
            "district": rating["district"], "today": day_today, "tomorrow": day_tomorrow,
            "ban_today": "", "ban_tomorrow": "",
            "ban_note": "Local fire bans are not shown here",
            "source_url": source_url,
            "page_url": links.get("fire_bans") or "",
            "button": links.get("fire_bans_button") or "",
            "issued": issued_text,
        }
        if how == "fallback":
            camp["fire"]["fallback_km"] = km
        matched += 1
    return matched


# ---------- QLDTraffic ----------

def _vertices(geometry):
    if not geometry:
        return
    kind = geometry.get("type")
    if kind == "GeometryCollection":
        for part in geometry.get("geometries") or []:
            yield from _vertices(part)
        return

    def walk(coords):
        if coords and isinstance(coords[0], (int, float)):
            yield coords
        else:
            for part in coords or []:
                yield from walk(part)
    yield from walk(geometry.get("coordinates") or [])


def _km(lat1, lon1, lat2, lon2):
    rad = math.pi / 180
    dlat, dlon = (lat2 - lat1) * rad, (lon2 - lon1) * rad
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def traffic_events(doc):
    """Flooding events and road closures from a QLDTraffic v2 events FeatureCollection."""
    events = []
    for feature in (doc or {}).get("features") or []:
        props = feature.get("properties") or {}
        kind = str(props.get("event_type") or "").strip()
        impact = props.get("impact") or {}
        impact_type = str(impact.get("impact_type") or "").strip() if isinstance(impact, dict) else ""
        if kind.lower() != "flooding" and "clos" not in impact_type.lower():
            continue
        points = [(float(p[1]), float(p[0])) for p in _vertices(feature.get("geometry")) if len(p) >= 2]
        if not points:
            continue
        road = props.get("road_summary") or {}
        name = ", ".join(x for x in (str(road.get("road_name") or "").strip(), str(road.get("locality") or "").strip()) if x)
        label = kind or "Road event"
        if props.get("event_subtype"):
            label += f" ({str(props['event_subtype']).strip()})"
        if impact_type:
            label += f" — {impact_type}"
        reason = re.sub(r"\s+", " ", str(props.get("description") or props.get("event_due_to") or "")).strip()
        end = ((props.get("duration") or {}).get("end") or "") if isinstance(props.get("duration"), dict) else ""
        reopens = ""
        if end:
            try:
                reopens = dt.datetime.fromisoformat(str(end).replace("Z", "+00:00")).astimezone(facts.MELBOURNE).strftime("%-d %B %Y")
            except ValueError:
                reopens = ""
        events.append({"points": points, "type": label, "name": name, "reason": nc.clip(reason, 240), "reopens": reopens,
                       "id": props.get("id")})
    return events


def apply_traffic_events(camps, events, radius_km=5):
    flagged = 0
    for camp in camps:
        hits = []
        for event in events:
            if any(_km(camp["lat"], camp["lon"], lat, lon) <= radius_km for lat, lon in event["points"]):
                hits.append({"type": event["type"], "name": event["name"], "reason": event["reason"], "reopens": event["reopens"]})
        if hits:
            camp["nearby_closures"] = list(camp.get("nearby_closures") or []) + hits
            flagged += 1
    return flagged


def apply_traffic(camps, src, fetch_text, src_log=None, env=None):
    """Read QLDTraffic with the registered key from the environment, or TMR's published public key when none is set.
    Neither key reaches a log or the site."""
    env = os.environ if env is None else env
    key_env = src.get("key_env") or "QLDTRAFFIC_API_KEY"
    key = str(env.get(key_env) or "").strip()
    base = str(src.get("url") or "").strip()
    if not base:
        return None
    if not key and str(src.get("public_key") or "").strip():
        # The API spec gives a shared key for consumers without their own (100 requests a minute across all users).
        key = str(src["public_key"]).strip()
        print(f"QLDTraffic: {key_env} not set; using the public key from the TMR API specification")
    if not key:
        print(f"WARN QLDTraffic skipped: {key_env} is not set", file=sys.stderr)
        if src_log is not None:
            src_log["qldtraffic"] = {"ok": False, "url": base, "error": f"{key_env} not set; skipped"}
        return None
    payload = fetch_text("qldtraffic", base + "?" + urllib.parse.urlencode({"apikey": key}))
    if src_log is not None and "qldtraffic" in src_log:
        # Never keep the key in the source log, which is published with the site.
        entry = src_log["qldtraffic"]
        entry["url"] = base
        if entry.get("error"):
            entry["error"] = str(entry["error"]).replace(key, "[key]").replace(urllib.parse.quote(key), "[key]")
    if not payload:
        print("WARN QLDTraffic unavailable; no road events were added", file=sys.stderr)
        return None
    try:
        doc = json.loads(payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload)
    except ValueError:
        print("WARN QLDTraffic returned unreadable data", file=sys.stderr)
        return None
    events = traffic_events(doc)
    flagged = apply_traffic_events(camps, events, float(src.get("radius_km") or 5))
    print(f"QLDTraffic: {len(events)} flooding or closure events, {flagged} camps within {src.get('radius_km') or 5} km")
    return flagged


# ---------- build entry ----------

def apply(camps, state, fetch_json, fetch_text, src_log=None, now=None):
    """Alerts, fire danger and road events for every Queensland camp. Returns the alerts stamp for the header."""
    sources = state.get("sources") or {}
    files = _files(state)
    links = state.get("links") or {}
    stamp = {}
    try:
        rss_src = sources.get("qpws_alerts_rss") or {}
        if rss_src.get("url"):
            payload = fetch_text("qpws_alerts_rss", rss_src["url"], BROWSER_HEADERS)
            items = parse_rss(payload)
            estates = estate_records(_load(files.get("estates")))
            if items and estates:
                enriched = enrich_alert_pages(items, fetch_text)
                if enriched:
                    print(f"QPWS alert pages fetched for listed-camp wording: {enriched}")
                updated = nc.rss_built(payload)
                page = rss_src.get("page") or QPWS_ALERTS_PAGE
                for camp in camps:
                    camp["alerts_feed"] = page
                    if updated:
                        camp["alerts_updated"] = updated.isoformat()
                summary = apply_alert_items(camps, estates, items, now)
                stamp = {"updated": updated.isoformat() if updated else "", "feed": page}
                print(f"QPWS alerts RSS: {len(items)} items, updated {stamp['updated'] or 'unknown'}, "
                      f"{summary['affected']} camps affected, {summary['closed']} closed, {summary['upcoming']} upcoming")
                if summary["unmatched_parks"]:
                    print("QPWS alert parks without a park polygon: " + "; ".join(summary["unmatched_parks"][:20]))
            else:
                print("WARN QPWS alerts unavailable or unreadable; camp status left unchanged", file=sys.stderr)
    except Exception as exc:
        print("WARN QPWS alerts", exc, file=sys.stderr)
    try:
        fdr = sources.get("bom_fdr_qld") or {}
        if fdr.get("url"):
            ratings, issued = parse_fdr(fetch_text("bom_fdr_qld", fdr["url"], BROWSER_HEADERS))
            districts = area_records((_load(files.get("fire_districts")) or {}).get("districts"))
            if ratings and districts:
                matched = apply_fire(camps, districts, ratings, issued, fdr["url"], links, now)
                print(f"BoM QLD fire danger: {matched} camps in a feed district")
            else:
                print("WARN BoM QLD fire danger unavailable; no rating was added", file=sys.stderr)
    except Exception as exc:
        print("WARN BoM QLD fire danger", exc, file=sys.stderr)
    try:
        traffic = sources.get("qldtraffic") or {}
        if traffic.get("url"):
            apply_traffic(camps, traffic, fetch_text, src_log)
    except Exception as exc:
        print("WARN QLDTraffic", type(exc).__name__, file=sys.stderr)
    return stamp
