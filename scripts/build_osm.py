#!/usr/bin/env python3
"""Rebuild data/osm-camps-vic.json, data/osm-camps-vic.csv and data/vic-towns.json.

Uses the Geofabrik Victoria extract and classify.decide(), which drops unnamed sites,
commercial caravan parks, big chains, hiker/group/scout/school camps, rest areas with
no overnight indication, and private or disused sites. DataVic wins: drop an OSM site
within 300 m, or within 3 km when the names share a word.

The Geofabrik extract spills onto the NSW bank of the Murray and into South Australia.
Camp candidates are kept only when they fall inside data/victoria-boundary.json, the
Geoscape state boundary. A small bounding box rejects points before that test.

data/manual-corrections.json is only read. A missing file is an empty overlay and is
never created. The overlay is a dict keyed by osm_id: exclusions remove sites,
other records override fields, and keys starting with "new:" add sites (they carry
their own lat/lon). A legacy {"drop", "overrides"} object is still accepted.

An OSM id is published when it already has a non-exclude correction, or when it is
already in the published file and has not been excluded. Any other id is written to
data/pending-osm.json and left off the map. A filled-in correction whose id is no
longer in the extract is kept and logged as "missing id, needs remap".
"""
import csv
import gzip
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify
import states
import towns

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
# Paths and the extract box come from the state config. Victoria is the only
# enabled state, so this refresh still writes data/osm-camps-vic.json,
# data/osm-camps-vic.csv, data/vic-towns.json and data/pending-osm.json.
# manual-corrections.json is only read.
_STATE = states.by_slug("vic")
CORRECTIONS = states.path(_STATE, "corrections")
BOUNDARY = states.path(_STATE, "boundary")
PENDING = states.path(_STATE, "pending")
PUBLISHED = states.path(_STATE, "osm_camps")
CSV_PATH = states.path(_STATE, "osm_csv")
TOWNS_PATH = states.path(_STATE, "towns")
PBF_URL = (_STATE.get("osm") or {}).get("pbf_url") or ""
DEFAULT_PBF = os.environ.get("OSM_PBF") or (_STATE.get("osm") or {}).get("default_pbf") or ""
WFS = ((_STATE.get("sources") or {}).get("recreation_sites") or {}).get("url") or ""
BBOX = tuple((_STATE.get("osm") or {}).get("bbox") or ())
OUTSIDE_NOTE = ((_STATE.get("osm") or {}).get("outside_note") or "outside Victoria")
DUPLICATE_M = 600
_FILLED = {"name", "category", "operator", "description", "phone", "website", "email", "fee_type", "booking", "toilets", "lat", "lon", "source_url", "source_url2", "suits"}
UA = "CampConditions.au/0.1 (+https://campconditions.au)"
STOP = {"camp", "camping", "ground", "area", "site", "reserve", "the", "park", "caravan", "campground"}
FIELDS = ["name", "lat", "lon", "category", "suits", "self_contained_only", "max_nights", "dogs", "dump_point",
          "showers", "toilets", "phone", "email", "website", "operator", "label", "osm_id", "needs_review",
          "description", "source_url", "checked_date", "water_tap", "fee_type", "booking", "access"]


def metres(lat1, lon1, lat2, lon2):
    return 6371000 * math.hypot(math.radians(lat2 - lat1), math.radians(lon2 - lon1) * math.cos(math.radians(lat1)))


def in_victoria(lat, lon):
    """Fast reject. This box still includes the NSW bank of the Murray and a sliver of SA."""
    west, south, east, north = BBOX
    return west <= lon <= east and south <= lat <= north


def _pip(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i, point in enumerate(ring):
        xi, yi = point[0], point[1]
        xj, yj = ring[j][0], ring[j][1]
        den = yj - yi
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (den if den else 1e-30) + xi):
            inside = not inside
        j = i
    return inside


_BOUNDARY = None


def load_boundary(path=BOUNDARY):
    """Ring bounding boxes plus rings. The file is the Geoscape Victoria polygon."""
    global _BOUNDARY
    if _BOUNDARY is not None and _BOUNDARY[0] == path:
        return _BOUNDARY[1]
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    indexed = []
    for poly in doc.get("polygons") or []:
        if not poly or len(poly[0]) < 4:
            continue
        xs = [point[0] for point in poly[0]]
        ys = [point[1] for point in poly[0]]
        indexed.append((min(xs), min(ys), max(xs), max(ys), poly))
    _BOUNDARY = (path, indexed)
    return indexed


def in_state(lat, lon, path=BOUNDARY):
    """True inside the Victorian state boundary, not merely inside the extract box."""
    if not in_victoria(lat, lon):
        return False
    for west, south, east, north, poly in load_boundary(path):
        if not (west <= lon <= east and south <= lat <= north):
            continue
        if not _pip(lon, lat, poly[0]):
            continue
        if any(_pip(lon, lat, ring) for ring in poly[1:]):
            continue
        return True
    return False


def toks(value):
    return {word for word in re.findall(r"[a-z]+", (value or "").lower()) if word not in STOP}


def download_pbf(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
        print(f"Using cached extract {path}")
        return path
    print(f"Downloading {PBF_URL}")
    request = urllib.request.Request(PBF_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=180) as response, open(path, "wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return path


def fetch_datavic():
    request = urllib.request.Request(WFS, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    points = []
    for feature in json.loads(raw).get("features") or []:
        props = feature.get("properties") or {}
        if props.get("published") != "Y":
            continue
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        points.append({"name": props.get("name") or "", "lat": coords[1], "lon": coords[0]})
    print(f"DataVic camping sites: {len(points)}")
    return points


def load_corrections(path=CORRECTIONS):
    """Read the overlay. Never creates or writes the file."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


_SKIP = {"exclude", "new", "reason", "coords_approx"}


def _legacy_corrections(corrections):
    return isinstance(corrections, dict) and ("drop" in corrections or "overrides" in corrections)


def apply_corrections(camps, corrections):
    """Overlay corrections onto extracted camps. Never writes the corrections file.

    Legacy shape: {"drop": [osm_id], "overrides": {osm_id: {fields}}}.
    Current shape: {osm_id: {fields}}. A truthy exclude removes the site. Other
    fields replace the extracted camp. Keys starting with "new:" (or records
    flagged new) are added when they have a name and coordinates. Applying the
    overlay twice does not duplicate new sites.
    """
    corrections = corrections or {}
    if not isinstance(corrections, dict):
        return list(camps)
    if _legacy_corrections(corrections):
        drop = set(corrections.get("drop") or [])
        overrides = corrections.get("overrides") or {}
        kept = []
        for camp in camps:
            osm_id = camp.get("osm_id")
            if osm_id in drop:
                continue
            extra = overrides.get(osm_id)
            if isinstance(extra, dict) and extra:
                camp = dict(camp)
                camp.update(extra)
                camp["osm_id"] = osm_id
            kept.append(camp)
        return kept
    excluded = {key for key, fields in corrections.items() if isinstance(fields, dict) and fields.get("exclude")}
    seen = set()
    kept = []
    for camp in camps:
        osm_id = camp.get("osm_id")
        if osm_id in excluded:
            continue
        extra = corrections.get(osm_id)
        if isinstance(extra, dict):
            camp = dict(camp)
            camp.update({k: v for k, v in extra.items() if k not in _SKIP and v not in (None, "")})
            camp["osm_id"] = osm_id
        kept.append(camp)
        if osm_id:
            seen.add(osm_id)
    for key, fields in corrections.items():
        if not isinstance(fields, dict) or fields.get("exclude") or key in seen:
            continue
        if not (str(key).startswith("new:") or fields.get("new")):
            continue
        if not fields.get("name") or "lat" not in fields or "lon" not in fields:
            continue
        row = {k: v for k, v in fields.items() if k not in _SKIP and v not in (None, "")}
        row["osm_id"] = key
        kept.append(row)
        seen.add(key)
    return kept


def dedupe_datavic(camps, official):
    kept = []
    for camp in camps:
        drop = False
        for other in official:
            distance = metres(camp["lat"], camp["lon"], other["lat"], other["lon"])
            if distance < 300 or (distance < 3000 and toks(camp["name"]) & toks(other["name"])):
                drop = True
                break
        if not drop:
            kept.append(camp)
    return kept


def dedupe_internal(camps):
    seen = {}
    kept = []
    for camp in camps:
        key = camp["name"].lower()
        if any(metres(camp["lat"], camp["lon"], other["lat"], other["lon"]) < 500 for other in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append(camp)
        kept.append(camp)
    return kept


def _tags(obj):
    return {tag.k: tag.v for tag in obj.tags}


def _centroid(way):
    pts = [(node.location.lat, node.location.lon) for node in way.nodes if node.location.valid()]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


class Extractor:
    def __init__(self):
        import osmium
        self.osmium = osmium
        self.camps = []
        self.town_rows = []

    def run(self, path):
        handler = self.osmium.SimpleHandler()
        handler.node = self.node
        handler.way = self.way
        handler.apply_file(path, locations=True)
        return self.camps, self.town_rows

    def node(self, node):
        if not node.location.valid():
            return
        lat, lon = node.location.lat, node.location.lon
        if not in_victoria(lat, lon):
            return
        tags = _tags(node)
        town = towns.town_record(tags, lat, lon)
        if town is not None:
            self.town_rows.append(town)
        self._camp("n", node.id, tags, lat, lon)

    def way(self, way):
        centre = _centroid(way)
        if not centre or not in_victoria(*centre):
            return
        self._camp("w", way.id, _tags(way), centre[0], centre[1])

    def _camp(self, kind, ident, tags, lat, lon):
        if not classify.is_candidate(tags):
            return
        info = classify.decide(tags)
        if not info:
            return
        info["lat"] = round(lat, 6)
        info["lon"] = round(lon, 6)
        info["osm_id"] = f"{kind}{ident}"
        info["tags"] = tags
        self.camps.append(info)


def write_outputs(camps, town_rows):
    os.makedirs(DATA, exist_ok=True)
    camps = sorted(camps, key=lambda camp: camp["name"].lower())
    doc = {
        "attribution": "© OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
        "count": len(camps),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sites": camps,
    }
    with open(PUBLISHED, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for camp in camps:
            row = dict(camp)
            row["needs_review"] = "true" if camp.get("needs_review") else "false"
            writer.writerow(row)
    town_rows = sorted(town_rows, key=lambda row: (row["rank"], row["name"].lower(), row["lat"]))
    with open(TOWNS_PATH, "w", encoding="utf-8") as handle:
        json.dump(town_rows, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    from collections import Counter
    print(f"Wrote {len(camps)} camps, {len(town_rows)} towns")
    for name, count in Counter(camp["category"] for camp in camps).most_common():
        print(f"  {count:4d}  {name}")
    print(f"  needs_review {sum(1 for camp in camps if camp['needs_review'])}")


def _public_row(camp):
    return {key: value for key, value in camp.items() if key != "tags"}


def filled_in(fields):
    """A correction with curated facts, rather than an exclusion or an empty note."""
    return isinstance(fields, dict) and not fields.get("exclude") and bool(_FILLED & set(fields))


def _pending_row(camp, note=""):
    row = {
        "id": camp.get("osm_id") or "",
        "name": camp.get("name") or "",
        "lat": camp.get("lat"),
        "lon": camp.get("lon"),
        "tags": camp.get("tags") or {},
    }
    if note:
        row["note"] = note
    return row


def _nearest_duplicate(camp, existing):
    best = None
    for other in existing:
        if not other.get("name") or other.get("osm_id") == camp.get("osm_id"):
            continue
        if camp.get("lat") is None or other.get("lat") is None:
            continue
        if not (toks(camp.get("name")) & toks(other.get("name"))):
            continue
        distance = metres(camp["lat"], camp["lon"], other["lat"], other["lon"])
        if distance <= DUPLICATE_M and (best is None or distance < best[0]):
            best = (distance, other)
    if not best:
        return ""
    distance, other = best
    return f"likely duplicate of {other.get('osm_id')} {other.get('name')}, {round(distance)} m"


def vet_camps(inside, outside, corrections, previous):
    """Choose published camps and the pending list. Does not write files.

    Published: a non-exclude correction, or a camp already in the published file
    that this run has not excluded. New ids stay in the pending list. An id that
    is outside the state boundary is not added unless it was already published or
    already has a keep record. A filled-in correction missing from the extract is
    kept when the previous file still has its coordinates, and always logged.
    """
    corrections = corrections or {}
    previous_by_id = {camp.get("osm_id"): camp for camp in previous or [] if camp.get("osm_id")}
    publish = []
    pending = []
    seen = set()

    def take(camps, outside_state):
        for camp in camps:
            osm_id = camp.get("osm_id")
            seen.add(osm_id)
            record = corrections.get(osm_id)
            if isinstance(record, dict) and record.get("exclude"):
                continue
            known = isinstance(record, dict) or osm_id in previous_by_id
            if outside_state and not known:
                pending.append(_pending_row(camp, OUTSIDE_NOTE))
                continue
            if not known:
                pending.append(_pending_row(camp))
                continue
            publish.append(_public_row(camp))

    take(inside or [], False)
    take(outside or [], True)
    publish = apply_corrections(publish, corrections)
    published_ids = {camp.get("osm_id") for camp in publish}
    for key, fields in corrections.items():
        if not isinstance(fields, dict) or str(key).startswith("new:") or fields.get("new") or not filled_in(fields):
            continue
        if key in seen:
            continue
        if key not in published_ids and key in previous_by_id:
            publish.append(_public_row(previous_by_id[key]))
            published_ids.add(key)
        kept = previous_by_id.get(key) or {}
        pending.append({
            "id": key,
            "name": kept.get("name") or fields.get("name") or "",
            "lat": kept.get("lat", fields.get("lat")),
            "lon": kept.get("lon", fields.get("lon")),
            "tags": {},
            "note": "missing id, needs remap",
        })
    for row in pending:
        if row.get("note") == "missing id, needs remap":
            continue
        flag = _nearest_duplicate(row, publish)
        if flag:
            row["duplicate"] = flag
    return publish, pending


def load_published(path=PUBLISHED):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if isinstance(doc, dict):
        return list(doc.get("sites") or [])
    return list(doc) if isinstance(doc, list) else []


def write_pending(entries, path=PENDING):
    entries = sorted(entries, key=lambda row: (row.get("note") or "", str(row.get("id") or "")))
    doc = {
        "note": "OpenStreetMap camps left off the map. A new id is published only after it has a record in manual-corrections.json.",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(entries),
        "sites": entries,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    print(f"Pending {len(entries)}")


def refresh(pbf_path=None):
    path = download_pbf(pbf_path or DEFAULT_PBF)
    official = fetch_datavic()
    extractor = Extractor()
    camps, town_rows = extractor.run(path)
    inside, outside = [], []
    for camp in camps:
        if in_state(camp["lat"], camp["lon"]):
            inside.append(camp)
        else:
            outside.append(camp)
    print(f"Classified camps {len(camps)}; inside {_STATE['name']} {len(inside)}; outside {len(outside)}; place points {len(town_rows)}")
    before = len(inside)
    inside = dedupe_internal(inside)
    after_internal = len(inside)
    inside = dedupe_datavic(inside, official)
    print(f"Internal dedupe {before} -> {after_internal}; DataVic wins, dropped {after_internal - len(inside)}")
    publish, pending = vet_camps(inside, outside, load_corrections(), load_published())
    write_outputs(publish, town_rows)
    write_pending(pending)


def main():
    try:
        refresh(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception as exc:
        print(f"WARN OSM refresh left the vetted files unchanged: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
