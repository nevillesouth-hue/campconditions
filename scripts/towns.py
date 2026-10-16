#!/usr/bin/env python3
"""Rank Victorian place points from OpenStreetMap. No I/O.

Towns (city, town, village) sort above localities (hamlet, locality, suburb).
"""

# Lower rank is a better match. Towns stay above localities.
PLACE_RANK = {
    "city": 0,
    "town": 0,
    "village": 0,
    "hamlet": 1,
    "locality": 1,
    "suburb": 1,
}


def place_rank(tags):
    """Return 0 for a town, 1 for a locality, or None if this is not a place we list."""
    place = (tags.get("place") or "").strip().lower()
    if place not in PLACE_RANK:
        return None
    if not (tags.get("name") or "").strip():
        return None
    return PLACE_RANK[place]


def town_record(tags, lat, lon):
    rank = place_rank(tags)
    if rank is None:
        return None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return {
        "name": tags["name"].strip(),
        "lat": round(lat_f, 5),
        "lon": round(lon_f, 5),
        "place": (tags.get("place") or "").strip().lower(),
        "rank": rank,
    }
