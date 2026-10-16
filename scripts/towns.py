#!/usr/bin/env python3
"""Rank Victorian place points. Towns (city, town, village) sort above localities."""

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
