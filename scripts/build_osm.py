#!/usr/bin/env python3
"""Rebuild data/osm-camps-vic.json, data/osm-camps-vic.csv and data/vic-towns.json.

Uses the Geofabrik Victoria extract and classify.decide(), which drops unnamed sites,
commercial caravan parks, big chains, hiker/group/scout/school camps, rest areas with
no overnight indication, and private or disused sites. DataVic wins: drop an OSM site
within 300 m, or within 3 km when the names share a word.

data/manual-corrections.json is only read. A missing file is an empty overlay and is
never created. The overlay is a dict keyed by osm_id: exclusions remove sites,
other records override fields, and keys starting with "new:" add sites (they carry
their own lat/lon). A legacy {"drop", "overrides"} object is still accepted.
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
import towns

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CORRECTIONS = os.path.join(DATA, "manual-corrections.json")
PBF_URL = "https://download.geofabrik.de/australia-oceania/australia/victoria-latest.osm.pbf"
DEFAULT_PBF = os.environ.get("OSM_PBF") or "/tmp/osm/victoria-latest.osm.pbf"
WFS = "https://opendata.maps.vic.gov.au/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=open-data-platform:recweb_site&outputFormat=application/json&CQL_FILTER=camping='Y'"
BBOX = (140.90, -39.30, 150.10, -33.90)
UA = "CampConditions.au/0.1 (+https://campconditions.au)"
STOP = {"camp", "camping", "ground", "area", "site", "reserve", "the", "park", "caravan", "campground"}
FIELDS = ["name", "lat", "lon", "category", "suits", "self_contained_only", "max_nights", "dogs", "dump_point",
          "showers", "toilets", "phone", "email", "website", "operator", "label", "osm_id", "needs_review",
          "description", "source_url", "checked_date", "water_tap", "fee_type", "booking", "access"]


def metres(lat1, lon1, lat2, lon2):
    return 6371000 * math.hypot(math.radians(lat2 - lat1), math.radians(lon2 - lon1) * math.cos(math.radians(lat1)))


def in_victoria(lat, lon):
    west, south, east, north = BBOX
    return west <= lon <= east and south <= lat <= north


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
    with open(os.path.join(DATA, "osm-camps-vic.json"), "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    with open(os.path.join(DATA, "osm-camps-vic.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for camp in camps:
            row = dict(camp)
            row["needs_review"] = "true" if camp.get("needs_review") else "false"
            writer.writerow(row)
    town_rows = sorted(town_rows, key=lambda row: (row["rank"], row["name"].lower(), row["lat"]))
    with open(os.path.join(DATA, "vic-towns.json"), "w", encoding="utf-8") as handle:
        json.dump(town_rows, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    from collections import Counter
    print(f"Wrote {len(camps)} camps, {len(town_rows)} towns")
    for name, count in Counter(camp["category"] for camp in camps).most_common():
        print(f"  {count:4d}  {name}")
    print(f"  needs_review {sum(1 for camp in camps if camp['needs_review'])}")


def main():
    path = download_pbf(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PBF)
    official = fetch_datavic()
    extractor = Extractor()
    camps, town_rows = extractor.run(path)
    print(f"Classified camps {len(camps)}; place points {len(town_rows)}")
    before = len(camps)
    camps = dedupe_internal(camps)
    after_internal = len(camps)
    camps = dedupe_datavic(camps, official)
    print(f"Internal dedupe {before} -> {after_internal}; DataVic wins, dropped {after_internal - len(camps)}")
    camps = apply_corrections(camps, load_corrections())
    write_outputs(camps, town_rows)


if __name__ == "__main__":
    main()
