#!/usr/bin/env python3
"""Build data/osm-camps-vic.json, data/osm-camps-vic.csv and data/vic-towns.json.

Reads the Geofabrik Victoria/Australia extract (cached under /tmp, never committed)
and the DataVic Recreation Sites feed. DataVic wins: an OSM site within 250 m of a
DataVic site, or with the same name within 2 km, is dropped.

data/manual-corrections.json is an overlay. This script only reads it. A missing
file is treated as an empty overlay and is never created.
"""
import csv, json, math, os, re, sys, urllib.request, gzip
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
# Victoria, with a small margin so border bleed from the extract can be dropped.
BBOX = (140.90, -39.30, 150.10, -33.90)  # west, south, east, north
NEAR_M = 250
NAME_M = 2000
UA = "CampConditions.au/0.1 (+https://campconditions.au)"


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def km(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def in_victoria(lat, lon):
    west, south, east, north = BBOX
    return west <= lon <= east and south <= lat <= north


def download_pbf(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
        print(f"Using cached extract {path}")
        return path
    print(f"Downloading {PBF_URL}")
    req = urllib.request.Request(PBF_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as response, open(path, "wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return path


def fetch_datavic():
    req = urllib.request.Request(WFS, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    doc = json.loads(raw)
    points = []
    for feature in doc.get("features") or []:
        props = feature.get("properties") or {}
        if props.get("published") != "Y":
            continue
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        points.append({"name": _norm(props.get("name")), "lat": lat, "lon": lon})
    print(f"DataVic camping sites: {len(points)}")
    return points


def _cell(lat, lon, size):
    return (int(math.floor(lat / size)), int(math.floor(lon / size)))


def _index(points, size):
    grid = {}
    for point in points:
        grid.setdefault(_cell(point["lat"], point["lon"], size), []).append(point)
    return grid


def _near(grid, lat, lon, size, radius_m, name=None):
    here = _cell(lat, lon, size)
    span = int(math.ceil((radius_m / 1000) / (size * 111))) + 1
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            for other in grid.get((here[0] + dy, here[1] + dx), []):
                if name is not None and other["name"] != name:
                    continue
                if km(lat, lon, other["lat"], other["lon"]) * 1000 <= radius_m:
                    return True
    return False


def load_corrections(path=CORRECTIONS):
    """Read the overlay. Never creates or writes the file."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def apply_corrections(camps, corrections):
    """Drop and override by osm_id. Returns a new list; does not touch the file."""
    drop = set(corrections.get("drop") or [])
    overrides = corrections.get("overrides") or {}
    kept = []
    for camp in camps:
        osm_id = camp.get("osm_id")
        if osm_id in drop:
            continue
        extra = overrides.get(osm_id)
        if extra:
            camp = dict(camp)
            camp.update(extra)
            camp["osm_id"] = osm_id
        kept.append(camp)
    return kept


def _richness(camp):
    score = 0
    for key in ("phone", "email", "website", "max_nights", "operator"):
        if camp.get(key):
            score += 2
    if camp.get("needs_review") is False:
        score += 1
    return score


def dedupe_osm(camps):
    """Drop node/way duplicates of the same camp. Keeps the richer record."""
    camps = sorted(camps, key=_richness, reverse=True)
    kept = []
    grid = {}
    size = 0.01
    for camp in camps:
        name = _norm(camp["name"])
        if _near(grid, camp["lat"], camp["lon"], size, 80) or _near(grid, camp["lat"], camp["lon"], size, 200, name=name):
            continue
        kept.append(camp)
        grid.setdefault(_cell(camp["lat"], camp["lon"], size), []).append({"name": name, "lat": camp["lat"], "lon": camp["lon"]})
    return kept


def dedupe_datavic(camps, official):
    grid = _index(official, 0.05)
    name_grid = _index([p for p in official if p["name"]], 0.05)
    kept = []
    for camp in camps:
        if _near(grid, camp["lat"], camp["lon"], 0.05, NEAR_M):
            continue
        name = _norm(camp["name"])
        if name and _near(name_grid, camp["lat"], camp["lon"], 0.05, NAME_M, name=name):
            continue
        kept.append(camp)
    return kept


def _way_points(way):
    pts = []
    for node in way.nodes:
        if node.location.valid():
            pts.append((node.location.lat, node.location.lon))
    return pts


def _centroid_of(pts):
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def camp_record(osm_id, tags, lat, lon):
    name = (tags.get("name") or "").strip()
    info = classify.classify(tags, name)
    return {
        "osm_id": osm_id,
        "name": info["name"],
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "category": info["category"],
        "phone": info["phone"],
        "email": info["email"] if "@" in info["email"] else "",
        "website": info["website"],
        "max_nights": info["max_nights"],
        "dogs": info["dogs"],
        "dump": info["dump"],
        "showers": info["showers"],
        "tents": info["tents"],
        "caravans": info["caravans"],
        "motorhomes": info["motorhomes"],
        "self_contained": info["self_contained"],
        "needs_review": bool(info["needs_review"]),
        "operator": info["operator"],
    }


def _too_big(pts):
    """Skip park-sized polygons. About 5 km on a side."""
    if len(pts) < 2:
        return False
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return (max(lats) - min(lats) > 0.05) or (max(lons) - min(lons) > 0.05)


def _tags(obj):
    return {tag.k: tag.v for tag in obj.tags}


class Extractor:
    def __init__(self, need_nodes, need_ways):
        import osmium
        self.osmium = osmium
        self.need_nodes = need_nodes
        self.need_ways = need_ways
        self.camps = []
        self.town_rows = []
        self.member_xy = {}
        self.skipped_big = 0

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
        if node.id in self.need_nodes:
            self.member_xy[("n", node.id)] = (lat, lon)
        if not in_victoria(lat, lon):
            return
        self._keep("node", node.id, _tags(node), lat, lon)

    def way(self, way):
        pts = _way_points(way)
        centre = _centroid_of(pts)
        if not centre:
            return
        if way.id in self.need_ways and not _too_big(pts):
            self.member_xy[("w", way.id)] = centre
        if _too_big(pts):
            self.skipped_big += 1
            return
        lat, lon = centre
        if not in_victoria(lat, lon):
            return
        self._keep("way", way.id, _tags(way), lat, lon)

    def _keep(self, kind, ident, tags, lat, lon):
        town = towns.town_record(tags, lat, lon)
        if town is not None:
            self.town_rows.append(town)
        if not classify.accept_feature(tags) or not (tags.get("name") or "").strip():
            return
        self.camps.append(camp_record(f"{kind}/{ident}", tags, lat, lon))


def dedupe_towns(rows):
    """Same name and place within about 1 km collapses to the higher rank."""
    rows = sorted(rows, key=lambda r: (r["rank"], r["name"].lower()))
    kept = []
    seen = {}
    for row in rows:
        key = (_norm(row["name"]), row["place"])
        prev = seen.get(key)
        if prev and km(prev["lat"], prev["lon"], row["lat"], row["lon"]) < 1:
            continue
        # A second spelling at the same spot (suburb + locality) still both stay
        # unless the name and rounded coordinate already exist.
        spot = (_norm(row["name"]), round(row["lat"], 3), round(row["lon"], 3))
        if spot in seen:
            continue
        seen[key] = row
        seen[spot] = row
        kept.append(row)
    kept.sort(key=lambda r: (r["rank"], r["name"].lower(), r["lat"]))
    return kept


def write_outputs(camps, town_rows):
    os.makedirs(DATA, exist_ok=True)
    camps = sorted(camps, key=lambda c: c["name"].lower())
    doc = {
        "source": "OpenStreetMap",
        "licence": "ODbL",
        "attribution": "Campground and town data © OpenStreetMap contributors (ODbL)",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "camps": camps,
    }
    json_path = os.path.join(DATA, "osm-camps-vic.json")
    csv_path = os.path.join(DATA, "osm-camps-vic.csv")
    towns_path = os.path.join(DATA, "vic-towns.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    fields = ["osm_id", "name", "category", "lat", "lon", "phone", "email", "website", "max_nights",
              "dogs", "dump", "showers", "tents", "caravans", "motorhomes", "self_contained", "needs_review", "operator"]
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for camp in camps:
            row = dict(camp)
            for key in ("dogs", "dump", "showers", "tents", "caravans", "motorhomes", "self_contained"):
                value = row.get(key)
                row[key] = "" if value is None else ("yes" if value else "no")
            row["max_nights"] = "" if row.get("max_nights") is None else row["max_nights"]
            row["needs_review"] = "yes" if row.get("needs_review") else "no"
            writer.writerow(row)
    with open(towns_path, "w", encoding="utf-8") as handle:
        json.dump(town_rows, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    from collections import Counter
    counts = Counter(c["category"] for c in camps)
    print(f"Wrote {len(camps)} camps, {len(town_rows)} towns")
    for name, count in counts.most_common():
        print(f"  {count:4d}  {name}")
    print(f"  needs_review {sum(1 for c in camps if c['needs_review'])}")


def scan_relations(path):
    """First pass, no node locations: camping relations and the members we need for a centroid."""
    import osmium
    found = []
    need_nodes, need_ways = set(), set()

    class Scan(osmium.SimpleHandler):
        def relation(self, relation):
            tags = _tags(relation)
            if not classify.accept_feature(tags) or not (tags.get("name") or "").strip():
                return
            members = [(m.type, m.ref) for m in relation.members if m.type in ("n", "w")]
            if not members:
                return
            found.append((relation.id, tags, members))
            for kind, ref in members:
                if kind == "n":
                    need_nodes.add(ref)
                elif kind == "w":
                    need_ways.add(ref)

    Scan().apply_file(path)
    print(f"Camping relations {len(found)}")
    return found, need_nodes, need_ways


def camps_from_relations(found, member_xy):
    camps = []
    skipped = 0
    for ident, tags, members in found:
        pts = [member_xy[key] for key in members if key in member_xy]
        centre = _centroid_of(pts)
        if not centre or not in_victoria(*centre):
            skipped += 1
            continue
        lat, lon = centre
        camps.append(camp_record(f"relation/{ident}", tags, lat, lon))
    print(f"Relation camps {len(camps)}; relations without a centroid {skipped}")
    return camps


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PBF
    path = download_pbf(path)
    official = fetch_datavic()
    relations, need_nodes, need_ways = scan_relations(path)
    extractor = Extractor(need_nodes, need_ways)
    camps, town_rows = extractor.run(path)
    camps.extend(camps_from_relations(relations, extractor.member_xy))
    print(f"Raw camping features {len(camps)}; place points {len(town_rows)}; oversized ways skipped {extractor.skipped_big}")
    raw = len(camps)
    camps = dedupe_osm(camps)
    after_osm = len(camps)
    camps = dedupe_datavic(camps, official)
    print(f"OSM self-dedupe {raw} -> {after_osm}; DataVic wins, dropped {after_osm - len(camps)}")
    corrections = load_corrections()
    camps = apply_corrections(camps, corrections)
    town_rows = dedupe_towns(town_rows)
    write_outputs(camps, town_rows)


if __name__ == "__main__":
    main()
