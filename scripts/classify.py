#!/usr/bin/env python3
"""Classify one OpenStreetMap camping feature using the curated rules.

Kept categories: free, donation, showground, council_park, council_park_leased, rest_area.
Dropped: unnamed sites, commercial caravan parks with no council or committee operator,
big chains, hiker/group/scout/school camps, rest areas with no overnight indication,
and private or disused sites.

decide(tags) returns a site dict, or None when the feature is dropped.
"""
import json
import re

CHAIN = re.compile(
    r"discovery|big ?4|nrma|ingenia|tasman holiday|g'?day|top parks?|holiday haven|aspen|reflections|"
    r"hampshire|breakfree|nature'?s? edge|family parks|lifestyle|resort|retirement|village|manufactured|over ?50",
    re.I,
)
EXCL = re.compile(
    r"hiker|walk-?in|group camp|group camping|scout|guide|school|youth|church|christian|campus|"
    r"outdoor education|education|ywca|ymca|lodge|cabin|hut$|retreat|bush ?walk|day visitor|picnic",
    re.I,
)
COUNCIL = re.compile(r"council|shire|city of|rural city|borough|committee|com\b|trust|foreshore|reserve|crown", re.I)
LEASED = {
    "marlo caravan park",
    "orbost caravan park",
    "bemm river caravan park",
    "eagle point caravan park",
    "omeo holiday park",
    "eastern beach holiday park",
    "bairnsdale riverside holiday park",
}
CATEGORIES = ("free", "donation", "showground", "council_park", "council_park_leased", "rest_area")
YES = ("yes", "designated", "leashed", "permissive")


def yn(value):
    if value is None or value == "":
        return "unknown"
    text = str(value).lower()
    if text in YES:
        return "yes"
    if text == "no":
        return "no"
    return text


def is_candidate(tags):
    """Raw features worth considering: camps, caravan sites, rest areas, showgrounds."""
    tourism = tags.get("tourism")
    name = (tags.get("name") or "").lower()
    if tourism in ("camp_site", "caravan_site"):
        return True
    if tags.get("highway") == "rest_area" or tags.get("amenity") == "rest_area":
        return True
    if "showground" in name or "show ground" in name:
        return True
    return False


def _overnight(tags):
    if any(tags.get(key) == "yes" for key in ("overnight", "camping", "caravans", "motorhome", "tents")):
        return True
    return "maxstay" in tags


def decide(tags, name=None):
    """Return the curated site fields, or None if this feature is excluded."""
    tags = dict(tags or {})
    name = (name if name is not None else tags.get("name") or "").strip()
    if not name or not re.search(r"[A-Za-z0-9]", name):
        return None
    low = name.lower()
    tourism = tags.get("tourism")
    operator = tags.get("operator") or ""
    if tags.get("access") in ("private", "no") or tags.get("disused") or tags.get("abandoned"):
        return None
    # "and" binds tighter than "or", matching the curated script.
    if (tags.get("backcountry") == "yes" or tags.get("group_only") == "yes"
            or (tags.get("camp_site") == "basic" and "hike" in low)
            or EXCL.search(name) or tags.get("scout") == "yes"):
        return None
    if CHAIN.search(name) or CHAIN.search(tags.get("brand") or "") or CHAIN.search(operator):
        return None
    rest = tags.get("highway") == "rest_area" or tags.get("amenity") == "rest_area"
    show = "showground" in low or "show ground" in low
    if rest and not show and tourism not in ("camp_site", "caravan_site"):
        if not _overnight(tags):
            return None
    fee = (tags.get("fee") or "").lower()
    donation = "donation" in json.dumps(tags).lower()
    review = False
    if show:
        category = "showground"
        review = tourism is None
    elif rest and tourism is None:
        category = "rest_area"
    elif low in LEASED:
        category = "council_park_leased"
    elif tourism == "caravan_site":
        if COUNCIL.search(operator) or re.search(r"foreshore|reserve|recreation|showground", low):
            category = "council_park"
            review = not bool(COUNCIL.search(operator))
        else:
            return None
    else:
        if donation:
            category = "donation"
        elif fee in ("no",):
            category = "free"
        elif fee in ("yes",) or fee.startswith("$") or fee.startswith("aud"):
            if COUNCIL.search(operator) or re.search(r"foreshore|reserve|recreation", low):
                category = "council_park"
            else:
                return None
        else:
            category = "free"
            review = True
    suits = [label for label, key in (("tent", "tents"), ("caravan", "caravans"), ("motorhome", "motorhome")) if tags.get(key) == "yes"]
    if category == "showground" and not suits:
        suits = ["tent", "caravan", "motorhome"]
    blob = json.dumps(tags).lower().replace("-", " ")
    self_contained = (tags.get("self_contained") or tags.get("self-contained") or "").lower()
    if self_contained in ("yes", "only") or "self contained" in blob:
        contained = "yes"
    elif tags.get("toilets") == "yes":
        contained = "no"
    else:
        contained = "unknown"
    return {
        "name": name,
        "category": category,
        "suits": "|".join(suits) if suits else "unknown",
        "self_contained_only": contained,
        "max_nights": tags.get("maxstay") or "",
        "dogs": yn(tags.get("dog")),
        "dump_point": yn(tags.get("sanitary_dump_station")),
        "showers": yn(tags.get("shower")),
        "toilets": yn(tags.get("toilets")),
        "phone": tags.get("phone") or tags.get("contact:phone") or "",
        "email": tags.get("email") or tags.get("contact:email") or "",
        "website": tags.get("website") or tags.get("contact:website") or "",
        "operator": operator,
        "label": "call first" if category == "showground" else "check with operator",
        "needs_review": bool(review or category == "council_park_leased"),
    }
