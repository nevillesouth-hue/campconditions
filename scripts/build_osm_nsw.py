#!/usr/bin/env python3
"""Write data/osm-camps-nsw.json from the Geofabrik New South Wales extract.

This is a data prep step, not the site build. The site reads the file only
when New South Wales is included in the build.

classify.decide() is the same published rule set used for Victoria. The
Victoria pending list and manual-corrections.json are not applied, so a
site is not held back for a second review pass.

A candidate is kept when it is inside the Natural Earth 1:10m New South
Wales polygon (the mainland and Lord Howe Island) and outside the Geoscape
Victoria boundary. The Australian Capital Territory is left out.

A fee is stored only when OpenStreetMap has a fee or donation tag. A missing
fee is not labelled free: the category is Camp and the site stays unverified.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_osm
import classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "osm-camps-nsw.json")
PBF = os.environ.get("NSW_OSM_PBF") or "/tmp/osm/new-south-wales-latest.osm.pbf"
BOUNDARY = os.environ.get("NSW_ADMIN_GEOJSON") or "/tmp/nsw/ne_admin1.geojson"
KEEP_ISO = "AU-NSW"
DROP_ISO = "AU-ACT"
# A showground road or a parking bay matches the camping rules on its name alone.
NOT_A_CAMP = re.compile(r"\b(parking|office|locked)\b|\broad$", re.I)


def keep_name(name):
    return not NOT_A_CAMP.search(name or "")


def _rings(geometry):
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coords]
    if kind == "MultiPolygon":
        return list(coords)
    return []


def _index(features):
    indexed = []
    for feature in features:
        for poly in _rings(feature.get("geometry") or {}):
            if not poly or len(poly[0]) < 4:
                continue
            xs = [point[0] for point in poly[0]]
            ys = [point[1] for point in poly[0]]
            indexed.append((min(xs), min(ys), max(xs), max(ys), poly))
    return indexed


def _inside(index, lon, lat):
    for west, south, east, north, poly in index:
        if not (west <= lon <= east and south <= lat <= north):
            continue
        if not build_osm._pip(lon, lat, poly[0]):
            continue
        if any(build_osm._pip(lon, lat, ring) for ring in poly[1:]):
            continue
        return True
    return False


def load_outlines(path):
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    keep, drop = [], []
    for feature in doc.get("features") or []:
        iso = ((feature.get("properties") or {}).get("iso_3166_2") or "")
        if iso == KEEP_ISO:
            keep.append(feature)
        elif iso == DROP_ISO:
            drop.append(feature)
    if not keep:
        raise SystemExit(f"no {KEEP_ISO} polygon in {path}")
    return _index(keep), _index(drop)


def _public(info, tags):
    """Copy a classified site. Do not turn a missing fee tag into Free."""
    row = dict(info)
    fee = (tags.get("fee") or "").strip().lower()
    blob = json.dumps(tags).lower()
    if row.get("category") == "free" and row.get("needs_review"):
        row["category"] = "osm_camp"
    elif row.get("category") == "free" and fee == "no":
        row["fee_type"] = "free"
    elif row.get("category") == "donation" or "donation" in blob:
        if row.get("category") == "donation":
            row["fee_type"] = "donation"
    elif fee == "yes" or fee.startswith("$") or fee.startswith("aud"):
        row["fee_type"] = "paid"
    row.pop("tags", None)
    return row


class Extractor:
    def __init__(self, keep, drop):
        import osmium
        self.osmium = osmium
        self.keep = keep
        self.drop = drop
        self.camps = []
        self.seen = 0

    def _place(self, lat, lon):
        if build_osm.in_state(lat, lon):
            return False
        if not _inside(self.keep, lon, lat):
            return False
        if _inside(self.drop, lon, lat):
            return False
        return True

    def _camp(self, kind, ident, tags, lat, lon):
        self.seen += 1
        if not classify.is_candidate(tags):
            return
        if not self._place(lat, lon):
            return
        info = classify.decide(tags, state_slug="nsw")
        if not info or not keep_name(info.get("name")):
            return
        row = _public(info, tags)
        row["lat"] = round(lat, 6)
        row["lon"] = round(lon, 6)
        row["osm_id"] = f"{kind}{ident}"
        self.camps.append(row)

    def node(self, node):
        if not node.location.valid():
            return
        self._camp("n", node.id, {tag.k: tag.v for tag in node.tags}, node.location.lat, node.location.lon)

    def way(self, way):
        pts = [(node.location.lat, node.location.lon) for node in way.nodes if node.location.valid()]
        if not pts:
            return
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        self._camp("w", way.id, {tag.k: tag.v for tag in way.tags}, lat, lon)

    def run(self, path):
        handler = self.osmium.SimpleHandler()
        handler.node = self.node
        handler.way = self.way
        handler.apply_file(path, locations=True)
        return self.camps


def main():
    keep, drop = load_outlines(BOUNDARY)
    camps = Extractor(keep, drop).run(PBF)
    camps = build_osm.dedupe_internal(camps)
    camps = sorted(camps, key=lambda camp: (camp.get("name") or "").lower())
    doc = {
        "attribution": "© OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
        "boundary": "Natural Earth 1:10m admin-1, New South Wales (AU-NSW), excluding the Australian Capital Territory. Points inside the Geoscape Victoria boundary are left out.",
        "fee_note": "fee_type is set only from an OpenStreetMap fee or donation tag. A missing fee is category Camp, not Free.",
        "count": len(camps),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sites": camps,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    from collections import Counter
    print(f"Wrote {len(camps)} NSW OSM camps to {OUT}")
    for name, count in Counter(camp.get("category") for camp in camps).most_common():
        print(f"  {count:4d}  {name}")
    print(f"  fee_type {sum(1 for camp in camps if camp.get('fee_type'))}")
    print(f"  needs_review {sum(1 for camp in camps if camp.get('needs_review'))}")


if __name__ == "__main__":
    main()
