#!/usr/bin/env python3
"""Classify an OpenStreetMap camping feature. No I/O.

Categories, in priority order:
  Showground, Rest area (overnight), Council park (leased), Council park,
  Free, Donation, Caravan park, Campground.

Facilities are tri-state: True, False, or None (unknown). Unknown must stay
unknown — callers show "Unknown" and must not treat it as a yes.
"""
import re

YES = {"yes", "designated", "permissive", "allowed", "leashed", "on", "true", "hot", "cold", "only", "required"}
NO = {"no", "none", "prohibited", "forbidden", "false", "off"}
GENERIC_NAMES = {
    "campground", "campsite", "camp site", "camping", "camping ground", "camping area",
    "free camp", "free camping", "rest area", "caravan park", "showgrounds", "showground", "park",
}
COUNCIL_RE = re.compile(r"\b(shire|borough|council|rural city|city of)\b", re.I)
HOURS_RE = re.compile(r"(\d+)")


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _tri(tags, keys):
    for key in keys:
        raw = (tags.get(key) or "").strip().lower()
        if not raw:
            continue
        head = raw.split(";", 1)[0].strip()
        if head in YES or head.startswith("yes"):
            return True
        if head in NO or head.startswith("no"):
            return False
    return None


def _blob(tags, keys):
    return " ".join(str(tags.get(k) or "") for k in keys).lower()


def councilish(*values):
    return any(COUNCIL_RE.search(v or "") for v in values)


def has_overnight(tags):
    if tags.get("tourism") in ("camp_site", "caravan_site"):
        return True
    for key in ("camping", "tents", "caravans", "caravan", "motorhome", "motorhomes", "motorcaravan"):
        head = (tags.get(key) or "").strip().lower().split(";", 1)[0]
        if head in YES or head.startswith("yes"):
            return True
    return False


def is_showground(tags, name):
    if (tags.get("amenity") or "") == "showground":
        return True
    low = (name or "").lower()
    return "showground" in low


def is_rest_area(tags, name):
    named = (tags.get("highway") == "rest_area") or ("rest area" in (name or "").lower())
    return named and has_overnight(tags)


def is_leased(tags):
    owner = tags.get("owner") or ""
    operator = tags.get("operator") or ""
    lease_blob = _blob(tags, ("operator:type", "ownership", "owner:type"))
    if "lease" in lease_blob and councilish(owner, operator):
        return True
    if councilish(owner) and operator and _norm(operator) != _norm(owner) and not councilish(operator):
        return True
    return False


def is_donation(tags):
    if (tags.get("payment:donation") or "").lower() in ("yes", "only"):
        return True
    return "donation" in _blob(tags, ("fee", "charge", "fee:conditional"))


def is_free(tags, name):
    fee = (tags.get("fee") or "").strip().lower()
    if fee in ("no", "none", "free", "0", "$0"):
        return True
    if fee in ("", "no", "none", "free") and re.search(r"\bfree\b", (name or "").lower()):
        return True
    return False


def category_for(tags, name):
    """One category. Earlier rules win so a free showground stays a showground."""
    if is_showground(tags, name):
        return "Showground"
    if is_rest_area(tags, name) and (tags.get("tourism") not in ("camp_site", "caravan_site") or tags.get("highway") == "rest_area" or "rest area" in (name or "").lower()):
        # Camp sites whose name or highway tag says rest area are rest areas.
        # A normal camp_site is not a rest area just because overnight is true.
        if tags.get("highway") == "rest_area" or "rest area" in (name or "").lower():
            return "Rest area (overnight)"
    if is_leased(tags):
        return "Council park (leased)"
    if councilish(tags.get("owner"), tags.get("operator"), tags.get("operator:type")):
        return "Council park"
    if is_free(tags, name):
        return "Free"
    if is_donation(tags):
        return "Donation"
    if tags.get("tourism") == "caravan_site":
        return "Caravan park"
    return "Campground"


def max_nights(tags):
    raw = (tags.get("maxstay") or tags.get("max_stay") or "").strip()
    match = HOURS_RE.search(raw)
    if not match:
        return None
    number = int(match.group(1))
    low = raw.lower()
    if "hour" in low:
        return max(1, int(round(number / 24.0))) or 1
    if "week" in low:
        return number * 7
    if number <= 0 or number > 365:
        return None
    return number


def _contact(tags, keys):
    for key in keys:
        value = (tags.get(key) or "").strip()
        if value:
            return value.split(";", 1)[0].strip()
    return ""


def website(tags):
    raw = _contact(tags, ("website", "contact:website", "url"))
    if not raw or raw.lower().startswith(("javascript:", "data:")):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if not re.match(r"https?://", raw, re.I):
        raw = "https://" + raw
    return raw


def needs_review(tags, name, category, inferred_free=False):
    """Flag uncertain records. A named camp or caravan site is kept without this flag."""
    if any(k == "fixme" or k.startswith("fixme:") for k in tags):
        return True
    low = _norm(name)
    if low in GENERIC_NAMES:
        return True
    if inferred_free and not (tags.get("fee") or "").strip():
        return True
    if category == "Showground" and not has_overnight(tags):
        return True
    if category == "Rest area (overnight)" and tags.get("highway") != "rest_area" and tags.get("tourism") not in ("camp_site", "caravan_site"):
        return True
    return False


def facilities(tags):
    self_contained = _tri(tags, ("self_contained",))
    if self_contained is None:
        sanitation = (tags.get("sanitation") or "").lower()
        if "self" in sanitation and "contain" in sanitation:
            self_contained = True
    return {
        "dogs": _tri(tags, ("dog", "dogs")),
        "dump": _tri(tags, ("sanitary_dump_station", "sanitary_dump", "dump_station")),
        "showers": _tri(tags, ("shower", "showers")),
        "tents": _tri(tags, ("tents", "tent")),
        "caravans": _tri(tags, ("caravans", "caravan")),
        "motorhomes": _tri(tags, ("motorhome", "motorhomes", "motorcaravan")),
        "self_contained": self_contained,
    }


def classify(tags, name=None):
    """Return a plain dict for one feature. tags is a str->str mapping."""
    name = (name if name is not None else tags.get("name") or "").strip()
    fee = (tags.get("fee") or "").strip()
    inferred_free = is_free(tags, name) and not fee
    category = category_for(tags, name)
    fac = facilities(tags)
    return {
        "name": name,
        "category": category,
        "max_nights": max_nights(tags),
        "phone": _contact(tags, ("phone", "contact:phone", "mobile", "contact:mobile")),
        "email": _contact(tags, ("email", "contact:email")),
        "website": website(tags),
        "operator": (tags.get("operator") or tags.get("owner") or "").strip(),
        "needs_review": needs_review(tags, name, category, inferred_free=inferred_free),
        **fac,
    }


def _showground_feature(tags, name):
    if (tags.get("amenity") or "") == "showground":
        return True
    if "showground" not in (name or "").lower():
        return False
    # A named showground that is a park, ground or camping feature — not a road name.
    if tags.get("leisure") in ("recreation_ground", "park", "sports_centre", "pitch", "stadium"):
        return True
    if tags.get("landuse") in ("recreation_ground", "commercial"):
        return True
    return has_overnight(tags)


def accept_feature(tags):
    """True for camping features worth listing. Day-use rest areas are not."""
    if (tags.get("disused") or "") == "yes" or (tags.get("abandoned") or "") == "yes":
        return False
    if (tags.get("ruins") or "") == "yes":
        return False
    if tags.get("boundary") or tags.get("place") or tags.get("natural"):
        return False
    amenity = tags.get("amenity") or ""
    tourism = tags.get("tourism") or ""
    if amenity in ("toilets", "fuel", "restaurant", "fast_food", "cafe", "parking", "shelter", "school"):
        return False
    if tourism in ("hotel", "motel", "guest_house", "hostel", "chalet", "apartment", "attraction", "viewpoint", "museum"):
        return False
    name = tags.get("name") or ""
    if tourism in ("camp_site", "caravan_site"):
        return True
    if _showground_feature(tags, name):
        return True
    if tags.get("highway") == "rest_area" and has_overnight(tags):
        return True
    if tourism == "picnic_site" and has_overnight(tags):
        return True
    return False
