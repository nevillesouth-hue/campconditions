#!/usr/bin/env python3
"""Write NSW search places and the place-point file used for camp labels.

Search file (data/nsw-towns.json): every gazetted suburb and locality from
the Spatial Services Suburb layer, plus any official city or town whose name
is not already a suburb. Where the same name is also a PlacePoint city or
town, the search pin is that official point, not the suburb-polygon centroid.
A large rural locality such as Broken Hill has a centroid tens of kilometres
from the city. Searching the centroid misses the camps in town.

Label file (data/nsw-place-points.json): PlacePoint features whose placetype
is in the published domain (city, town, village, locality, suburb). Camp pages
prefer a city or town within 40 km.

Both layers are NSW Spatial Services, GDA2020 multiCRS, read in WGS84.
Suburb boundaries: Creative Commons Attribution 4.0.
PlacePoint: Creative Commons, © State of New South Wales (Spatial Services,
Department of Customer Service). For current information go to
spatial.nsw.gov.au.

Names are the published name fields, capitalised for display. Nothing is guessed.
"""
import json
import math
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "nsw-towns.json")
PLACES_OUT = os.path.join(ROOT, "data", "nsw-place-points.json")
SUBURB_QUERY = "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/2/query"
PLACE_QUERY = "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Features_of_Interest_Category_multiCRS/FeatureServer/1/query"
# Published DmT_PlaceType codes. Codes outside this domain are left out.
PLACE_TYPES = {2: "city", 3: "town", 4: "village", 5: "locality", 6: "suburb"}
def inside_nsw_suburb(lat, lon):
    """True when the point falls in a gazetted NSW suburb polygon."""
    params = {
        "where": "state=2",
        "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    }
    doc = _get(SUBURB_QUERY, params)
    return bool(doc.get("count"))


def display_name(raw):
    def word(part):
        if part.startswith("MC") and not part.startswith("MAC") and len(part) > 2:
            return "Mc" + part[2:].capitalize()
        return part.capitalize()

    bits = []
    for chunk in (raw or "").strip().split(" "):
        if chunk:
            bits.append("-".join(word(part) for part in chunk.split("-") if part))
    return " ".join(bits)


def _get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "CampConditions.au"})
    with urllib.request.urlopen(req, timeout=180) as res:
        doc = json.load(res)
    if doc.get("error"):
        raise SystemExit(doc["error"])
    return doc


def _pages(url, params):
    offset = 0
    rows = []
    while True:
        page = dict(params)
        page["resultOffset"] = str(offset)
        page["resultRecordCount"] = "2000"
        doc = _get(url, page)
        feats = doc.get("features") or []
        rows.extend(feats)
        if not feats or not doc.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return rows


def fetch_suburbs():
    return _pages(SUBURB_QUERY, {
        "where": "state=2",
        "outFields": "suburbname,urbanity,state",
        "returnGeometry": "false",
        "returnCentroid": "true",
        "outSR": "4326",
        "f": "json",
    })


def fetch_places():
    return _pages(PLACE_QUERY, {
        "where": "operationalstatus=1",
        "outFields": "generalname,placetype,operationalstatus",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    })


def suburb_records(feats):
    out = []
    for feat in feats:
        attrs = feat.get("attributes") or {}
        centre = feat.get("centroid") or {}
        name = display_name(attrs.get("suburbname") or "")
        lat, lon = centre.get("y"), centre.get("x")
        if not name or lat is None or lon is None:
            continue
        if attrs.get("state") not in (None, 2):
            continue
        urban = (attrs.get("urbanity") or "").strip().upper()
        out.append({
            "name": name,
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "place": "suburb" if urban == "U" else "locality",
            "rank": 0 if urban == "U" else 1,
        })
    return out


def place_records(feats):
    """One row per name. City beats town, then village, suburb, locality."""
    order = {"city": 0, "town": 1, "village": 2, "suburb": 3, "locality": 4}
    best = {}
    for feat in feats:
        attrs = feat.get("attributes") or {}
        kind = PLACE_TYPES.get(attrs.get("placetype"))
        if attrs.get("operationalstatus") not in (None, 1) or not kind:
            continue
        name = display_name(attrs.get("generalname") or "")
        geom = feat.get("geometry") or {}
        lat, lon = geom.get("y"), geom.get("x")
        if not name or lat is None or lon is None:
            continue
        row = {"name": name, "lat": round(float(lat), 5), "lon": round(float(lon), 5), "place": kind}
        key = name.casefold()
        current = best.get(key)
        if current is None or order[kind] < order[current["place"]]:
            best[key] = row
    return sorted(best.values(), key=lambda row: (order[row["place"]], row["name"].casefold(), row["lat"], row["lon"]))


def _km(lat1, lon1, lat2, lon2):
    radius = math.pi / 180
    dlat, dlon = (lat2 - lat1) * radius, (lon2 - lon1) * radius
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1 * radius) * math.cos(lat2 * radius) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(hav)))


def merge_search(suburbs, places, inside):
    """Pin a suburb on its city or town point, and add a city or town inside NSW.

    A PlacePoint city that sits outside every NSW suburb (Canberra and the
    ACT districts are in this layer) is left out. `inside(lat, lon)` is the
    suburb-polygon test.
    """
    by_name = {}
    for row in suburbs:
        by_name.setdefault(row["name"].casefold(), row)
    moved = []
    added = []
    skipped = []
    extra = []
    anchors = [dict(row) for row in suburbs]
    towns = [place for place in places if place["place"] in ("city", "town")]
    for place in towns:
        current = by_name.get(place["name"].casefold())
        if current is None:
            extra.append(place)
            continue
        current["lat"] = place["lat"]
        current["lon"] = place["lon"]
        current["place"] = place["place"]
        current["rank"] = 0
        moved.append(place["name"])
    for place in extra:
        nearest = min(anchors, key=lambda row: _km(place["lat"], place["lon"], row["lat"], row["lon"]))
        gap = _km(place["lat"], place["lon"], nearest["lat"], nearest["lon"])
        if not inside(place["lat"], place["lon"]):
            skipped.append((place["name"], place["place"], round(gap, 1), nearest["name"]))
            continue
        row = {"name": place["name"], "lat": place["lat"], "lon": place["lon"], "place": place["place"], "rank": 0}
        suburbs.append(row)
        by_name[place["name"].casefold()] = row
        added.append((place["name"], round(gap, 1), nearest["name"]))
    suburbs.sort(key=lambda row: (row["rank"], row["name"].casefold(), row["lat"], row["lon"]))
    return moved, added, skipped


def _write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def main():
    suburbs = suburb_records(fetch_suburbs())
    places = place_records(fetch_places())
    moved, added, skipped = merge_search(suburbs, places, inside_nsw_suburb)
    outside = {name.casefold() for name, *_rest in skipped}
    places = [row for row in places if row["name"].casefold() not in outside]
    _write(PLACES_OUT, places)
    _write(OUT, suburbs)
    print(f"Wrote {len(places)} place points to {PLACES_OUT}")
    print(f"Wrote {len(suburbs)} search places to {OUT}")
    print(f"City or town pins moved onto the official point: {len(moved)}")
    print(f"City or town names added: {len(added)}")
    for name, gap, near in added:
        print(f"  added {name} ({gap} km from {near})")
    print(f"City or town names left out, outside every NSW suburb: {len(skipped)}")
    for name, kind, gap, near in skipped:
        print(f"  skipped {name} ({kind}, {gap} km from {near})")


if __name__ == "__main__":
    main()
