"""Load per-state configuration. Only enabled states are built.

Victoria is the only enabled state. New South Wales is present so the next
step can fill its sources without another structural change.
"""
import json
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

    A state with enabled true is always included, in config-file order.
    CAMPCONDITIONS_ENABLE may name extra slugs for a preview. That does not
    change the enabled flag stored in the config file. Production does not
    set the variable.
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


def region_id(state, lon, lat):
    """First matching region rule. A rule with only an id is the fallback."""
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
