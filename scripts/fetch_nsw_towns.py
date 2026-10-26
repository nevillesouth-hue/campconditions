#!/usr/bin/env python3
"""Write data/nsw-towns.json from the NSW Spatial Services suburb layer.

Source: Suburb layer of NSW Administrative Boundaries (multiCRS, GDA2020),
published by Spatial Services, Department of Customer Service NSW. The
Geographical Names Board gazettes these suburb and locality boundaries.
Terms: Creative Commons Attribution 4.0.
Attribution: © State of New South Wales (Spatial Services, a business unit of
the Department of Customer Service NSW). For current information go to
spatial.nsw.gov.au.

Each coordinate is the layer's polygon centroid in WGS84. Names are the
gazetted suburbname field, capitalised for display. Nothing is guessed.
"""
import json
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "nsw-towns.json")
QUERY = "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/2/query"


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


def fetch():
    offset = 0
    rows = []
    while True:
        params = {
            "where": "state=2",
            "outFields": "suburbname,urbanity,state",
            "returnGeometry": "false",
            "returnCentroid": "true",
            "outSR": "4326",
            "resultOffset": str(offset),
            "resultRecordCount": "2000",
            "f": "json",
        }
        req = urllib.request.Request(QUERY + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "CampConditions.au"})
        with urllib.request.urlopen(req, timeout=180) as res:
            doc = json.load(res)
        if doc.get("error"):
            raise SystemExit(doc["error"])
        feats = doc.get("features") or []
        rows.extend(feats)
        if not feats or not doc.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return rows


def records(feats):
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
    out.sort(key=lambda row: (row["rank"], row["name"].casefold(), row["lat"], row["lon"]))
    return out


def main():
    towns = records(fetch())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(towns, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    print(f"Wrote {len(towns)} towns to {OUT}")


if __name__ == "__main__":
    main()
