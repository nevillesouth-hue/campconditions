#!/usr/bin/env python3
"""Prepare the Queensland reference files. A data prep step, not the site build.

Writes, from official sources only:
  data/qld-tourism-regions.json  ABS ASGS Edition 3 Tourism Regions 2021, Queensland (CC BY 4.0)
  data/qld-lgas.json             QSpatial Local Government area polygons, generalised (CC BY 4.0)
  data/qld-towns.json            QSpatial locality boundary centroids, pinned on a population
                                 centre point where the name is the same (town search)
  data/qld-place-points.json     QSpatial population centres (nearest town on camp pages)
  data/qpws-estates.json        QSpatial protected areas and state forests (QPWS managed estate),
                                 generalised (CC BY 4.0). Matches camps to park alerts.
  data/qld-fire-districts.json  Queensland fire weather district polygons, Public Safety Business
                                 Agency (Queensland Fire Department) layer New_Fire_Districts.
                                 DIST_NAME matches the BoM IDQ13016 area descriptions.
  data/qpws-permit-areas.json    QPWS camping permits CSV (data.qld.gov.au, CC BY 4.0): the
                                 park and camping area names only, used to cross-check
                                 QSpatial camping grounds. No permit counts or postcodes are kept.

Names are the published fields. Nothing is guessed.
"""
import csv
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (compatible; CampConditions.au; +https://campconditions.au)"}
TR = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/TR/FeatureServer/0/query"
LGA = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdminBoundariesFramework/FeatureServer/11/query"
LOCALITY = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdminBoundariesFramework/FeatureServer/26/query"
PLACES = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Location/Places/FeatureServer/20/query"
ESTATES = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdminBoundariesFramework/FeatureServer/77/query"
FIRE_DISTRICTS = "https://services1.arcgis.com/vkTwD8kHw2woKBqV/arcgis/rest/services/New_Fire_Districts/FeatureServer/2/query"
PERMITS_PACKAGE = "https://www.data.qld.gov.au/api/3/action/package_show?id=camping-and-vehicle-permits"
OFFSET = "0.002"


def _get(url, params=None, raw=False):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as res:
        body = res.read()
    if raw:
        return body
    doc = json.loads(body)
    if isinstance(doc, dict) and doc.get("error"):
        raise SystemExit(f"{url}: {doc['error']}")
    return doc


def _pages(url, params):
    rows, offset = [], 0
    while True:
        page = dict(params, resultOffset=str(offset), resultRecordCount="1000")
        doc = _get(url, page)
        feats = doc.get("features") or []
        rows.extend(feats)
        if not feats or not doc.get("exceededTransferLimit"):
            return rows
        offset += len(feats)


def _rings(geom):
    out = []
    for ring in (geom or {}).get("rings") or []:
        pts = [[round(x, 5), round(y, 5)] for x, y in ring]
        if len(pts) >= 4:
            out.append(pts)
    return out


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _write(name, doc):
    path = os.path.join(DATA, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    print(f"Wrote {path} ({os.path.getsize(path):,} bytes)")


def tourism_regions():
    feats = _pages(TR, {"where": "state_name_2021='Queensland'", "outFields": "tr_code_2021,tr_name_2021",
                        "returnGeometry": "true", "outSR": "4326", "maxAllowableOffset": OFFSET, "f": "json"})
    regions = []
    for feat in feats:
        a = feat["attributes"]
        rings = _rings(feat.get("geometry"))
        if rings:
            regions.append({"code": a["tr_code_2021"], "name": a["tr_name_2021"], "rings": rings, "id": _slug(a["tr_name_2021"])})
    regions.sort(key=lambda row: row["code"])
    _write("qld-tourism-regions.json", {
        "attribution": "Australian Bureau of Statistics, Australian Statistical Geography Standard (ASGS) Edition 3 Tourism Regions 2021. Licensed CC BY 4.0.",
        "source_url": "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files",
        "service_url": TR.rsplit("/query", 1)[0],
        "queried": "state_name_2021='Queensland'",
        "generalised": f"ArcGIS maxAllowableOffset {OFFSET} degrees, coordinates rounded to 5 decimal places.",
        "note": "These are the ABS approximation of Tourism Research Australia tourism regions. They are not Tourism and Events Queensland boundaries and they are not legal boundaries.",
        "regions": regions,
    })
    return regions


def lgas():
    feats = _pages(LGA, {"where": "1=1", "outFields": "lga,lga_code,abbrev_name", "returnGeometry": "true",
                         "outSR": "4326", "maxAllowableOffset": OFFSET, "f": "json"})
    rows = []
    for feat in feats:
        a = feat["attributes"]
        rings = _rings(feat.get("geometry"))
        if rings:
            rows.append({"id": _slug(a["lga"]), "name": a["lga"], "code": a.get("lga_code"), "rings": rings})
    rows.sort(key=lambda row: row["name"])
    _write("qld-lgas.json", {
        "attribution": "Local Government area, Queensland Spatial Catalogue (QSpatial), State of Queensland (Department of Resources). Licensed CC BY 4.0.",
        "service_url": LGA.rsplit("/query", 1)[0],
        "generalised": f"ArcGIS maxAllowableOffset {OFFSET} degrees, coordinates rounded to 5 decimal places.",
        "note": "Used to name the council area of each camp, to plan council checks, and to leave out permit-only areas listed in config/states/qld.json. The union of these polygons is also the Queensland outline for OpenStreetMap camps.",
        "regions": rows,
    })
    return rows


def places():
    feats = _pages(PLACES, {"where": "operational_status='Operational'", "outFields": "name,population,local_government",
                            "returnGeometry": "true", "outSR": "4326", "f": "json"})
    best = {}
    for feat in feats:
        a, g = feat["attributes"], feat.get("geometry") or {}
        name = (a.get("name") or "").strip()
        if not name or "x" not in g:
            continue
        row = {"name": name, "lat": round(g["y"], 5), "lon": round(g["x"], 5), "place": "town"}
        key = name.casefold()
        if key not in best or (a.get("population") or 0) > best[key][1]:
            best[key] = (row, a.get("population") or 0)
    rows = sorted((row for row, _pop in best.values()), key=lambda row: (row["name"].casefold(), row["lat"]))
    _write("qld-place-points.json", rows)
    return rows


def towns(place_rows):
    feats = _pages(LOCALITY, {"where": "1=1", "outFields": "locality", "returnGeometry": "false",
                              "returnCentroid": "true", "outSR": "4326", "f": "json"})
    pins = {row["name"].casefold(): row for row in place_rows}
    rows, seen = [], set()
    for feat in feats:
        name = (feat["attributes"].get("locality") or "").strip()
        centre = feat.get("centroid") or {}
        if not name or "x" not in centre:
            continue
        display = " ".join(part.capitalize() if part.isupper() else part for part in name.split(" "))
        key = display.casefold()
        if key in seen:
            continue
        seen.add(key)
        pin = pins.get(key)
        if pin:
            rows.append({"name": display, "lat": pin["lat"], "lon": pin["lon"], "place": "town", "rank": 0})
        else:
            rows.append({"name": display, "lat": round(centre["y"], 5), "lon": round(centre["x"], 5), "place": "locality", "rank": 1})
    rows.sort(key=lambda row: (row["rank"], row["name"].casefold(), row["lat"], row["lon"]))
    _write("qld-towns.json", rows)


def estates():
    feats = _pages(ESTATES, {"where": "1=1", "outFields": "estatename,esttype,qpwsreg", "returnGeometry": "true",
                             "outSR": "4326", "maxAllowableOffset": "0.0005", "f": "json"})
    rows = []
    for feat in feats:
        a = feat["attributes"]
        rings = _rings(feat.get("geometry"))
        if rings and (a.get("estatename") or "").strip():
            rows.append({"name": a["estatename"].strip(), "type": a.get("esttype") or "", "region": a.get("qpwsreg") or "", "rings": rings})
    rows.sort(key=lambda row: row["name"])
    _write("qpws-estates.json", {
        "attribution": "Protected areas and state forests of Queensland, Queensland Spatial Catalogue (QSpatial), State of Queensland. Licensed CC BY 4.0.",
        "service_url": ESTATES.rsplit("/query", 1)[0],
        "generalised": "ArcGIS maxAllowableOffset 0.0005 degrees, coordinates rounded to 5 decimal places.",
        "note": "Park and state forest names (estatename) match the 'Affected parks' list in the QPWS park alerts RSS. A camp is matched to the estate that contains it, or one within 100 m.",
        "estates": rows,
    })
    print(f"  {len(rows)} estates")


def fire_districts():
    feats = _pages(FIRE_DISTRICTS, {"where": "1=1", "outFields": "DIST_NO,DIST_NAME", "returnGeometry": "true",
                                    "outSR": "4326", "maxAllowableOffset": OFFSET, "f": "json"})
    rows = []
    for feat in feats:
        a = feat["attributes"]
        rings = _rings(feat.get("geometry"))
        if rings and (a.get("DIST_NAME") or "").strip():
            rows.append({"name": a["DIST_NAME"].strip(), "number": a.get("DIST_NO"), "rings": rings})
    rows.sort(key=lambda row: row["name"])
    _write("qld-fire-districts.json", {
        "attribution": "Queensland fire weather districts (New_Fire_Districts), Public Safety Business Agency for the Queensland Fire Department, State of Queensland.",
        "service_url": FIRE_DISTRICTS.rsplit("/query", 1)[0],
        "context": "Published with the Queensland Fire Department story map 'Queensland Fire Weather District changes 19 August'.",
        "generalised": f"ArcGIS maxAllowableOffset {OFFSET} degrees, coordinates rounded to 5 decimal places.",
        "note": "DIST_NAME is matched by name to the area description in the Bureau of Meteorology fire danger forecast IDQ13016. DIST_NO is not the BoM area code.",
        "districts": rows,
    })
    print(f"  {len(rows)} districts")


def permit_areas():
    pkg = _get(PERMITS_PACKAGE)["result"]
    camping = [r for r in pkg["resources"] if "camping" in (r.get("name") or "").lower() and (r.get("format") or "").upper() == "CSV"]
    if not camping:
        raise SystemExit("no camping permits CSV in the package")
    newest = camping[0]
    body = _get(newest["url"], raw=True).decode("utf-8-sig", errors="replace")
    parks = {}
    for row in csv.DictReader(io.StringIO(body)):
        park = (row.get("Park Name") or "").strip()
        area = (row.get("Camping Area") or "").strip()
        if park and area:
            parks.setdefault(park, set()).add(area)
    out = {park: sorted(areas) for park, areas in sorted(parks.items())}
    _write("qpws-permit-areas.json", {
        "attribution": "Camping and vehicle permits, Queensland Parks and Wildlife Service, data.qld.gov.au. Licensed CC BY 4.0.",
        "dataset": "https://www.data.qld.gov.au/dataset/camping-and-vehicle-permits",
        "resource": newest["name"].strip(),
        "resource_url": newest["url"],
        "note": "Park and camping area names only. Used to cross-check QSpatial camping grounds and to name the QPWS park for each matched camp.",
        "parks": out,
    })
    print(f"  {len(out)} parks, {sum(len(v) for v in out.values())} camping areas")


def main():
    which = set(sys.argv[1:]) or {"regions", "lgas", "places", "permits", "estates", "fire"}
    if "regions" in which:
        tourism_regions()
    if "lgas" in which:
        lgas()
    if "places" in which:
        towns(places())
    if "permits" in which:
        permit_areas()
    if "estates" in which:
        estates()
    if "fire" in which:
        fire_districts()


if __name__ == "__main__":
    main()
