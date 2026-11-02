#!/usr/bin/env python3
"""Write data/osm-camps-qld.json from the Geofabrik Queensland extract.

This is a data prep step, not the site build. The site reads the file only
when Queensland is included in the build.

classify.decide() is the same published rule set used for Victoria and New
South Wales. The site build applies data/manual-corrections-qld.json and the
permit-only area exclusion in config/states/qld.json when it reads this
extract, so the exclusion can change without rebuilding this file.

A candidate is kept when it is inside a Queensland Local Government area
(data/qld-lgas.json, QSpatial). Every council area together is the state
outline, including the islands that councils cover.

A fee is stored only when OpenStreetMap has a fee or donation tag. A missing
fee is not labelled free: the category is Camp and the site stays unverified.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_osm
import build_osm_nsw
import classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "osm-camps-qld.json")
PBF = os.environ.get("QLD_OSM_PBF") or "/tmp/osm/queensland-latest.osm.pbf"
LGAS = os.path.join(ROOT, "data", "qld-lgas.json")


def load_outline(path=LGAS):
    """Bounding boxes and rings of every council area. Each LGA ring list is one polygon set."""
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    indexed = []
    for row in doc.get("regions") or []:
        rings = [ring for ring in row.get("rings") or [] if ring and len(ring) >= 4]
        if not rings:
            continue
        xs = [point[0] for ring in rings for point in ring]
        ys = [point[1] for ring in rings for point in ring]
        indexed.append((min(xs), min(ys), max(xs), max(ys), rings))
    if not indexed:
        raise SystemExit(f"no council areas in {path}")
    return indexed


def inside(indexed, lon, lat):
    for west, south, east, north, rings in indexed:
        if not (west <= lon <= east and south <= lat <= north):
            continue
        # Esri rings: an odd number of containing rings means inside (holes cancel).
        if sum(1 for ring in rings if build_osm._pip(lon, lat, ring)) % 2 == 1:
            return True
    return False


class Extractor(build_osm_nsw.Extractor):
    def __init__(self, outline):
        super().__init__([], [])
        self.outline = outline

    def _place(self, lat, lon):
        return inside(self.outline, lon, lat)

    def _camp(self, kind, ident, tags, lat, lon):
        self.seen += 1
        if not classify.is_candidate(tags):
            return
        if not self._place(lat, lon):
            return
        info = classify.decide(tags, state_slug="qld")
        if not info or not build_osm_nsw.keep_name(info.get("name")):
            return
        row = build_osm_nsw._public(info, tags)
        row["lat"] = round(lat, 6)
        row["lon"] = round(lon, 6)
        row["osm_id"] = f"{kind}{ident}"
        self.camps.append(row)


def main():
    camps = Extractor(load_outline()).run(PBF)
    camps = build_osm.dedupe_internal(camps)
    camps = sorted(camps, key=lambda camp: (camp.get("name") or "").lower())
    doc = {
        "attribution": "© OpenStreetMap contributors, ODbL 1.0 (openstreetmap.org/copyright)",
        "boundary": "Queensland Local Government areas (QSpatial, CC BY 4.0), all 78 areas together.",
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
    print(f"Wrote {len(camps)} QLD OSM camps to {OUT}")
    for name, count in Counter(camp.get("category") for camp in camps).most_common():
        print(f"  {count:4d}  {name}")
    print(f"  fee_type {sum(1 for camp in camps if camp.get('fee_type'))}")
    print(f"  needs_review {sum(1 for camp in camps if camp.get('needs_review'))}")


if __name__ == "__main__":
    main()
