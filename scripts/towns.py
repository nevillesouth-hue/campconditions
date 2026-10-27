#!/usr/bin/env python3
"""Rank place points. Towns (city, town, village) sort above localities.

The place file for a state lives in that state's config (data/vic-towns.json for Victoria).
"""

PLACE_RANK = {
    "city": 0,
    "town": 0,
    "village": 0,
    "hamlet": 1,
    "locality": 1,
    "suburb": 1,
}


def place_rank(tags):
    place = (tags.get("place") or "").strip().lower()
    if place not in PLACE_RANK or not (tags.get("name") or "").strip():
        return None
    return PLACE_RANK[place]


def data_path(slug="vic"):
    import states
    return states.path(states.by_slug(slug), "towns")


def load(slug="vic"):
    import json
    with open(data_path(slug), encoding="utf-8") as handle:
        return json.load(handle)


# Camp-page "Near …" labels. City and town are the PlacePoint classes.
# A nearer locality is used only when no city or town is within this distance.
LABEL_KM = 40
LABEL_PLACES = frozenset({"city", "town"})


def _km(lat1, lon1, lat2, lon2):
    import math
    radius = math.pi / 180
    dlat, dlon = (lat2 - lat1) * radius, (lon2 - lon1) * radius
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1 * radius) * math.cos(lat2 * radius) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(hav)))


def nearest_label(lat, lon, places, limit_km=LABEL_KM):
    """Nearest city or town within limit_km, otherwise the nearest place.

    `places` rows need name, lat, lon, and place (city, town, village,
    locality, or suburb). Ties use the name so the choice is stable.
    """
    best = None
    best_d = None
    best_town = None
    best_town_d = None
    for place in places:
        dist = _km(lat, lon, place["lat"], place["lon"])
        name = place.get("name") or ""
        if best_d is None or dist < best_d or (dist == best_d and name.casefold() < best["name"].casefold()):
            best, best_d = place, dist
        if place.get("place") in LABEL_PLACES and (
            best_town_d is None or dist < best_town_d or (dist == best_town_d and name.casefold() < best_town["name"].casefold())
        ):
            best_town, best_town_d = place, dist
    if best_town is not None and best_town_d <= limit_km:
        return best_town["name"], best_town_d
    if best is None:
        return "", None
    return best["name"], best_d


def town_record(tags, lat, lon):
    rank = place_rank(tags)
    if rank is None:
        return None
    return {
        "name": tags["name"].strip(),
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "place": (tags.get("place") or "").strip().lower(),
        "rank": rank,
    }
