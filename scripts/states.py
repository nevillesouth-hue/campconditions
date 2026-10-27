"""Load per-state configuration. Only enabled states are built.

Victoria and New South Wales are both enabled. Victoria stays first so the
shared map script and the top-level digest draft remain Victorian.
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config", "states")


def _load(path):
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict) or not doc.get("slug"):
        raise ValueError(f"state config missing slug: {path}")
    return doc


def all_states():
    """Every state file, enabled or not, in slug order."""
    found = []
    if not os.path.isdir(CONFIG_DIR):
        return found
    for name in sorted(os.listdir(CONFIG_DIR)):
        if name.endswith(".json"):
            found.append(_load(os.path.join(CONFIG_DIR, name)))
    return found


def enabled():
    """States the build should emit.

    A state with enabled true is always included. Production does not set
    CAMPCONDITIONS_ENABLE; that variable only adds extra slugs for a preview
    and does not change the flag stored in the config file. Victoria is
    ordered first. Later states follow by slug.
    """
    chosen = [state for state in all_states() if state.get("enabled")]
    have = {state.get("slug") for state in chosen}
    extra = os.environ.get("CAMPCONDITIONS_ENABLE") or ""
    for slug in extra.split(","):
        slug = slug.strip()
        if not slug or slug in have:
            continue
        chosen.append(by_slug(slug))
        have.add(slug)
    chosen.sort(key=lambda state: (state.get("slug") != "vic", state.get("slug") or ""))
    return chosen


def by_slug(slug):
    for state in all_states():
        if state.get("slug") == slug:
            return state
    raise KeyError(slug)


def path(state, key):
    rel = (state.get("files") or {}).get(key) or ""
    if not rel:
        return ""
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def _ring_contains(lon, lat, ring):
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            denom = (yj - yi) or 1e-15
            if lon < (xj - xi) * (lat - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def _prepare_region(row):
    rings = []
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for ring in row.get("rings") or []:
        if not ring or len(ring) < 3:
            continue
        rings.append(ring)
        for lon, lat in ring:
            minx, maxx = min(minx, lon), max(maxx, lon)
            miny, maxy = min(miny, lat), max(maxy, lat)
    if not rings or not row.get("id"):
        return None
    return {
        "id": row["id"],
        "rings": rings,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "area": max(0.0, (maxx - minx) * (maxy - miny)),
    }


def _contains_region(prep, lon, lat):
    if lon < prep["minx"] or lon > prep["maxx"] or lat < prep["miny"] or lat > prep["maxy"]:
        return False
    hits = 0
    for ring in prep["rings"]:
        if _ring_contains(lon, lat, ring):
            hits += 1
    return hits % 2 == 1


_REGION_POLYGONS = {}


def _tourism_regions(state):
    """Official polygon regions, loaded once. None when this state has no file."""
    slug = state.get("slug") or ""
    if slug in _REGION_POLYGONS:
        return _REGION_POLYGONS[slug]
    rel = (state.get("files") or {}).get("tourism_regions") or ""
    if not rel:
        _REGION_POLYGONS[slug] = None
        return None
    path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    rows = []
    for row in doc.get("regions") or []:
        prep = _prepare_region(row)
        if prep:
            rows.append(prep)
    grid = {}
    for prep in rows:
        x0, y0 = int(math.floor(prep["minx"])), int(math.floor(prep["miny"]))
        x1, y1 = int(math.floor(prep["maxx"])), int(math.floor(prep["maxy"]))
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                grid.setdefault((x, y), []).append(prep)
    packed = {"rows": rows, "grid": grid}
    _REGION_POLYGONS[slug] = packed
    return packed


def _nearest_region(rows, lon, lat):
    best = None
    best_d = math.inf
    for prep in rows:
        dx = 0.0 if prep["minx"] <= lon <= prep["maxx"] else min(abs(lon - prep["minx"]), abs(lon - prep["maxx"]))
        dy = 0.0 if prep["miny"] <= lat <= prep["maxy"] else min(abs(lat - prep["miny"]), abs(lat - prep["maxy"]))
        dist = dx * dx + dy * dy
        if best is None or dist < best_d or (dist == best_d and prep["area"] < best["area"]):
            best, best_d = prep, dist
    return best["id"] if best else ""


def region_id(state, lon, lat):
    """Polygon region when this state has an official boundary file, else the first matching rule."""
    packed = _tourism_regions(state)
    if packed and packed["rows"]:
        hits = []
        for prep in packed["grid"].get((int(math.floor(lon)), int(math.floor(lat))), []):
            if _contains_region(prep, lon, lat):
                hits.append(prep)
        if hits:
            hits.sort(key=lambda prep: prep["area"])
            return hits[0]["id"]
        return _nearest_region(packed["rows"], lon, lat)
    for rule in state.get("region_rules") or []:
        if "lat_gt" in rule and not lat > rule["lat_gt"]:
            continue
        if "lat_lt" in rule and not lat < rule["lat_lt"]:
            continue
        if "lon_lt" in rule and not lon < rule["lon_lt"]:
            continue
        if "lon_gte" in rule and not lon >= rule["lon_gte"]:
            continue
        if "lat_gte" in rule and not lat >= rule["lat_gte"]:
            continue
        if "lon_gt" in rule and not lon > rule["lon_gt"]:
            continue
        return rule.get("id") or ""
    return ""


def regions(state):
    """Ordered (slug, name, blurb) rows for pages and the digest."""
    rows = []
    for key, value in (state.get("regions") or {}).items():
        rows.append((key, value.get("name") or key, value.get("blurb") or ""))
    return rows


def public_file(state, key):
    """Site path for a built file, such as /vic-towns.json."""
    rel = (state.get("files") or {}).get(key) or ""
    if not rel:
        return ""
    return "/" + os.path.basename(rel)


def _js_num(value):
    if isinstance(value, float) and value.is_integer():
        return f"{value:.1f}"
    return str(value)


_JS_OP = {
    "lat_gt": "lat > ",
    "lat_lt": "lat < ",
    "lon_lt": "lon < ",
    "lon_gte": "lon >= ",
    "lat_gte": "lat >= ",
    "lon_gt": "lon > ",
}


def js_region_function(state):
    """Town-search region names. Same cuts as region_id, in the map script's shape."""
    names = {key: (value.get("name") or key) for key, value in (state.get("regions") or {}).items()}
    rules = list(state.get("region_rules") or [])
    lines = ["  function regionName(lat, lon) {"]
    if not rules:
        lines.append('    return "";')
        lines.append("  }")
        return "\n".join(lines)
    body = rules[:-1] if len(rules) > 1 else []
    for rule in body:
        conds = []
        for key, value in rule.items():
            if key == "id" or key not in _JS_OP:
                continue
            conds.append(_JS_OP[key] + _js_num(value))
        lines.append(f'    if ({" && ".join(conds)}) return "{names.get(rule.get("id") or "", "")}";')
    if rules:
        lines.append(f'    return "{names.get(rules[-1].get("id") or "", "")}";')
    lines.append("  }")
    return "\n".join(lines)
