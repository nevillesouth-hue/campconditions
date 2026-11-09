#!/usr/bin/env python3
"""Town landing pages: camps near a city, town or village.

Distances are haversine kilometres from the place coordinate already in the
state's place file to the camp coordinate already on the site. They are
straight-line distances, not road distances. A page is published only for a
name on PREFERRED when that place has at least MIN_CAMPS camps inside
RADIUS_KM, and it is not closer than SEPARATION_KM to a place already chosen.
"""
import json
import math
import os
import re

# 30 km is far enough to include park camps around a touring town, and tight
# enough that the list is still "near" that town. The camp-page "Near …"
# label stays at 40 km (towns.LABEL_KM); these pages use the tighter radius.
RADIUS_KM = 30
# Fewer than this is a short list the region page already covers.
MIN_CAMPS = 6
# A village a few kilometres from a busier town would repeat the same camps.
SEPARATION_KM = 12
# Camp pages name this many other camps, closest first. The town page lists all.
CAMP_NEARBY_LIMIT = 8
PLACE_TYPES = frozenset({"city", "town", "village"})
# Starter set of camping and touring towns. A name is published only when the
# place file has a point and at least MIN_CAMPS camps fall inside RADIUS_KM.
# Earlier names win when two are closer than SEPARATION_KM. Counts are checked
# at build time from the camp coordinates, not stored here.
PREFERRED = {
    "vic": (
        "Bright", "Mansfield", "Jamieson", "Halls Gap", "Apollo Bay", "Lorne",
        "Lakes Entrance", "Dargo", "Foster", "Marysville", "Healesville", "Eildon",
        "Daylesford", "Echuca", "Mildura", "Yarrawonga",
    ),
    "nsw": (
        "Jindabyne", "Batemans Bay", "Merimbula", "Nowra", "Kangaroo Valley",
        "Byron Bay", "Coffs Harbour", "Port Macquarie", "Nelson Bay", "Katoomba",
        "Narrandera", "Mathoura", "Menindee", "Bathurst", "Tamworth", "Gosford",
        "Bundanoon",
    ),
    "qld": (
        "Cairns", "Port Douglas", "Cape Tribulation", "Mission Beach", "Townsville",
        "Airlie Beach", "Eungella", "Yeppoon", "Agnes Water", "Bundaberg",
        "Hervey Bay", "K'gari", "Rainbow Beach", "Maleny", "Springbrook", "Canungra",
        "Stanthorpe",
    ),
}
# Localities the place class would otherwise skip. Still dropped when they
# have fewer than MIN_CAMPS camps inside the radius. Coordinates come from
# the place file; only the name is listed here.
EXTRA_LOCALITIES = frozenset({
    "airlie beach",
    "cape tribulation",
    "k'gari",
})
_CELL = 0.35


def km(lat1, lon1, lat2, lon2):
    radius = math.pi / 180
    dlat = (lat2 - lat1) * radius
    dlon = (lon2 - lon1) * radius
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1 * radius) * math.cos(lat2 * radius) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(hav)))


def km_text(dist):
    """One decimal is about 100 metres. The wording says it is not by road."""
    return f"{dist:.1f} km in a straight line"


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _keep_place(row, allow_extra):
    name = (row.get("name") or "").strip()
    place = (row.get("place") or "").strip().lower()
    if not name or row.get("lat") is None or row.get("lon") is None:
        return None
    if place not in PLACE_TYPES:
        if not (allow_extra and place in ("locality", "hamlet") and name.casefold() in EXTRA_LOCALITIES):
            return None
    return {"name": name, "lat": float(row["lat"]), "lon": float(row["lon"]), "place": place}


def candidate_rows(state):
    """City, town and village points, plus the named camping localities."""
    import states as statecfg
    places_path = statecfg.path(state, "places")
    towns_path = statecfg.path(state, "towns")
    primary = places_path if places_path and os.path.isfile(places_path) else towns_path
    rows = []
    seen = set()

    def add(path, extras_only):
        if not path or not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for row in data:
            item = _keep_place(row, allow_extra=True)
            if not item:
                continue
            if extras_only and item["place"] in PLACE_TYPES:
                continue
            key = (item["name"].casefold(), round(item["lat"], 3), round(item["lon"], 3))
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)

    add(primary, extras_only=False)
    if towns_path and os.path.abspath(towns_path) != os.path.abspath(primary or ""):
        add(towns_path, extras_only=True)
    return rows


class CampIndex:
    """Grid of camps so a radius query does not scan the whole state."""

    def __init__(self, camps, cell=_CELL):
        self.camps = list(camps)
        self.cell = cell
        self.buckets = {}
        for index, camp in enumerate(self.camps):
            key = (int(math.floor(camp["lat"] / cell)), int(math.floor(camp["lon"] / cell)))
            self.buckets.setdefault(key, []).append(index)

    def within(self, lat, lon, radius):
        dlat = radius / 111.0
        dlon = radius / (111.0 * max(0.2, math.cos(math.radians(lat))))
        lat0 = int(math.floor((lat - dlat) / self.cell))
        lat1 = int(math.floor((lat + dlat) / self.cell))
        lon0 = int(math.floor((lon - dlon) / self.cell))
        lon1 = int(math.floor((lon + dlon) / self.cell))
        hits = []
        for lat_i in range(lat0, lat1 + 1):
            for lon_i in range(lon0, lon1 + 1):
                for index in self.buckets.get((lat_i, lon_i), ()):
                    camp = self.camps[index]
                    dist = km(lat, lon, camp["lat"], camp["lon"])
                    if dist <= radius:
                        hits.append((dist, index))
        hits.sort(key=lambda item: (item[0], (self.camps[item[1]].get("name") or "").casefold()))
        return hits


def _with_slugs(chosen):
    used = set()
    for item in chosen:
        base = slugify(item["name"]) or "town"
        slug = base
        if slug in used and item["region"]:
            slug = f"{base}-{item['region']}"
        n = 2
        orig = slug
        while slug in used:
            slug = f"{orig}-{n}"
            n += 1
        used.add(slug)
        item["slug"] = slug
    return chosen


def choose_named(places, index, region_of, names, radius=RADIUS_KM, minimum=MIN_CAMPS, separation=SEPARATION_KM):
    """Publish preferred towns that clear the camp minimum and the separation."""
    by_name = {}
    for place in places:
        by_name.setdefault(place["name"].casefold(), []).append(place)
    chosen = []
    skipped = []
    for name in names:
        rows = by_name.get(name.casefold()) or []
        if not rows:
            skipped.append({"name": name, "why": "no place point on file"})
            continue
        best = None
        best_hits = None
        for row in rows:
            hits = index.within(row["lat"], row["lon"], radius)
            better = best is None or len(hits) > len(best_hits)
            if not better and len(hits) == len(best_hits) and row["place"] in PLACE_TYPES and best["place"] not in PLACE_TYPES:
                better = True
            if better:
                best, best_hits = row, hits
        if len(best_hits) < minimum:
            skipped.append({"name": name, "why": f"{len(best_hits)} camps within {radius:g} km"})
            continue
        blocker = None
        gap = None
        for other in chosen:
            dist = km(best["lat"], best["lon"], other["lat"], other["lon"])
            if dist < separation:
                blocker, gap = other, dist
                break
        if blocker:
            skipped.append({"name": name, "why": f"{gap:.1f} km from {blocker['name']}"})
            continue
        item = dict(best)
        item["nearby"] = best_hits
        item["count"] = len(best_hits)
        item["region"] = region_of(best["lon"], best["lat"]) or ""
        item["reason"] = (
            f"{item['count']} camps within {radius:g} km in a straight line of the place point; "
            f"on the starter list of camping and touring towns, and at least {separation:g} km from a town already chosen"
        )
        chosen.append(item)
    chosen = _with_slugs(chosen)
    chosen.sort(key=lambda item: (item["region"], item["name"].casefold()))
    return chosen, skipped


def choose(places, index, region_of, radius=RADIUS_KM, minimum=MIN_CAMPS, separation=SEPARATION_KM, per_state=16):
    """Places with enough camps, spread across regions, busiest first in each."""
    scored = []
    for place in places:
        hits = index.within(place["lat"], place["lon"], radius)
        if len(hits) < minimum:
            continue
        item = dict(place)
        item["nearby"] = hits
        item["count"] = len(hits)
        item["region"] = region_of(place["lon"], place["lat"]) or ""
        scored.append(item)
    by_region = {}
    for item in scored:
        by_region.setdefault(item["region"], []).append(item)
    for rows in by_region.values():
        rows.sort(key=lambda item: (-item["count"], item["name"].casefold(), item["lat"], item["lon"]))
    chosen = []
    cursors = {key: 0 for key in by_region}
    while len(chosen) < per_state:
        progressed = False
        for key in sorted(by_region):
            rows = by_region[key]
            cursor = cursors[key]
            while cursor < len(rows):
                cand = rows[cursor]
                cursor += 1
                if any(km(cand["lat"], cand["lon"], other["lat"], other["lon"]) < separation for other in chosen):
                    continue
                cand["reason"] = (
                    f"{cand['count']} camps within {radius:g} km in a straight line of the place point; "
                    f"busiest remaining place in {cand['region'] or 'this area'} "
                    f"that is at least {separation:g} km from a town already chosen"
                )
                chosen.append(cand)
                progressed = True
                break
            cursors[key] = cursor
            if len(chosen) >= per_state:
                break
        if not progressed:
            break
    chosen = _with_slugs(chosen)
    chosen.sort(key=lambda item: (item["region"], item["name"].casefold()))
    return chosen


def attach(camps, towns, radius=RADIUS_KM):
    """Point each camp at the nearest chosen town within the radius, if any."""
    for camp in camps:
        best = None
        best_d = None
        for town in towns:
            dist = km(camp["lat"], camp["lon"], town["lat"], town["lon"])
            if dist <= radius and (
                best is None or dist < best_d or (dist == best_d and town["name"].casefold() < best["name"].casefold())
            ):
                best, best_d = town, dist
        if best:
            camp["town_page"] = best["url"]
            camp["town_page_name"] = best.get("label") or best["name"]
            camp["town_page_km"] = best_d


def nearest(index, camp, radius=RADIUS_KM, limit=CAMP_NEARBY_LIMIT):
    """Other camps within the radius, closest first. Skips this camp."""
    out = []
    for dist, index_i in index.within(camp["lat"], camp["lon"], radius):
        other = index.camps[index_i]
        if other is camp:
            continue
        out.append((dist, other))
        if len(out) >= limit:
            break
    return out


def _clip(text, limit):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(".,; ") + "…"


def closure_text(camp, limit=220):
    """Closure wording already stored on the camp. Empty when there is none."""
    if camp.get("status") == "closed":
        record = camp.get("closure") or {}
        text = str(record.get("desc") or record.get("reason") or "").strip()
        reopen = str(record.get("reopen") or "")[:10]
        if reopen:
            text = (text + " · Reopens " + reopen).strip(" ·")
        return _clip(text, limit)
    upcoming = camp.get("upcoming_closure") or {}
    if upcoming.get("desc") or upcoming.get("start"):
        bits = [str(upcoming.get("desc") or "").strip() or "Upcoming closure"]
        if upcoming.get("start"):
            bits.append("Starts " + str(upcoming["start"])[:10])
        if upcoming.get("reopen"):
            bits.append("Reopens " + str(upcoming["reopen"])[:10])
        return _clip(" · ".join(bits), limit)
    return ""
