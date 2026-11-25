"""On-page SEO helpers used by the static build.

Breadcrumb JSON-LD, closed-camp meta descriptions, which camps a hub
lists as real HTML links, and the shared warning lines. No network.
"""
import html
import re

OPEN_DISCLAIMER = "This is not a confirmation the camp is open."
_DATE_WORD = re.compile(r"\b(?:from|until|reopens|starts|closed from)\b", re.I)
_STARTS = re.compile(r"starts\b", re.I)


def sentence(text):
    """One line, no open-disclaimer, ending in punctuation when there is text."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace(OPEN_DISCLAIMER, " ")
    text = re.sub(r"\s+", " ", text).strip(" ")
    text = re.sub(r"\s+([.!?])", r"\1", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _clip(text, limit):
    text = sentence(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    if len(cut) < 40:
        cut = text[:limit].rstrip(" ,;:")
    return (cut or text[:limit]).rstrip(" ,;:") + "."


def where_phrase(state_name, region_name, park, name):
    """Park and state, or region and state. Skip a region that repeats the state."""
    state = re.sub(r"\s+", " ", str(state_name or "")).strip()
    region = re.sub(r"\s+", " ", str(region_name or "")).strip()
    park_name = re.sub(r"\s+", " ", str(park or "")).strip()
    camp = str(name or "")
    if park_name and park_name.casefold() in camp.casefold():
        park_name = ""
    if region.casefold() == state.casefold():
        region = ""
    if park_name and state:
        return f"{park_name}, {state}"
    if park_name:
        return park_name
    if region and state:
        return f"{region}, {state}"
    return state or region


def park_label(camp):
    """A park or reserve name, when this camp actually has one."""
    camp = camp or {}
    parks = camp.get("parks") or []
    if isinstance(parks, str):
        parks = [parks]
    for value in parks:
        text = str(value or "").strip()
        if text:
            return text
    for key in ("reserve_name", "pws_alert_name"):
        text = str(camp.get(key) or "").strip()
        if text:
            return text
    if camp.get("source") == "parks_sa":
        return str(camp.get("managed_by") or "").strip()
    return ""


def _clean_summary(summary):
    """Drop sentences that contradict a closed camp or only restate the rule."""
    text = sentence(summary)
    if not text:
        return ""
    kept = []
    for part in re.split(r"(?<=[.!?])\s+", text):
        low = part.casefold()
        if "not a confirmation the camp is open" in low:
            continue
        if "check with the operator" in low:
            continue
        if low.startswith("is ") and "open?" in low:
            continue
        if "closed only where" in low:
            continue
        if "no current notice" in low or "no current alert" in low:
            continue
        if low in {"this campground is recorded as closed.", "full closure.", "closed."}:
            continue
        kept.append(part)
    return " ".join(kept).strip()


def closed_summary(camp):
    """The closure sentence already stored on the camp, before meta formatting."""
    camp = camp or {}
    source = camp.get("source") or ""
    if source == "tas":
        headline = str(((camp.get("closure") or {}).get("desc")) or "").strip()
        note = str(camp.get("tas_list_note") or "").strip()
        if _STARTS.match(note) and headline:
            return headline
        return note or headline
    if source in ("parks_sa", "sa_operator", "council", "tourism", "operator"):
        return str(camp.get("notice_summary") or "").strip()
    text = str(((camp.get("closure") or {}).get("desc")) or "").strip()
    if source == "osm" and camp.get("category"):
        typed = "Type: " + str(camp["category"]).strip() + "."
        text = (text + " " + typed).strip() if text else typed
    return text


def closed_meta(name, state_name, region_name, park, summary, start_spoken="", end_spoken="", end_label="Reopens", weekly=""):
    """Lead with closed status, then park or region, state, and the dates or summary.

    Never includes the open-disclaimer sentence.
    """
    name = re.sub(r"\s+", " ", str(name or "")).strip() or "This campground"
    where = where_phrase(state_name, region_name, park, name)
    lead = f"{name} is closed in {where}." if where else f"{name} is closed."
    extra = _clean_summary(summary)
    dates = []
    weekly_text = str(weekly or "").strip().rstrip(".")
    if weekly_text:
        dates.append(weekly_text)
    else:
        if start_spoken:
            dates.append("Closed from " + str(start_spoken).strip())
        if end_spoken:
            dates.append(str(end_label or "Reopens").strip() + " " + str(end_spoken).strip())
    date_text = ". ".join(dates)
    if date_text and not date_text.endswith("."):
        date_text += "."
    if date_text and extra and _STARTS.match(extra):
        extra = ""
    if extra and date_text and _DATE_WORD.search(extra):
        date_text = ""
    if extra:
        extra = _clip(extra, 180)
    parts = [lead]
    if date_text:
        parts.append(date_text)
    if extra:
        parts.append(extra)
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    text = text.replace(OPEN_DISCLAIMER, "").strip()
    text = re.sub(r"\s+([.!?])", r"\1", text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def with_disclaimer(name, place, summary):
    """Check-operator and no-notice descriptions. The disclaimer is its own sentence."""
    name = re.sub(r"\s+", " ", str(name or "")).strip() or "This campground"
    place = re.sub(r"\s+", " ", str(place or "")).strip()
    lead = f"{name} in {place}." if place else f"{name}."
    extra = sentence(summary)
    if extra:
        return f"{lead} {extra} {OPEN_DISCLAIMER}"
    return f"{lead} {OPEN_DISCLAIMER}"


def breadcrumb_list(items, site="https://campconditions.au"):
    """BreadcrumbList where every ListItem has its own name.

    Google's URL Inspection labels a crumb "Unnamed item" when that ListItem
    has no name of its own. Nesting the name on a WebPage does not give the
    ListItem a name. `item` is the absolute page URL, which is the shape
    Google's breadcrumb docs require, and the list itself is named after the
    last crumb so the list is not an unnamed item either.
    """
    site = str(site or "").rstrip("/")
    elements = []
    for index, pair in enumerate(items or [], start=1):
        raw_name, raw_url = pair
        label = re.sub(r"\s+", " ", str(raw_name or "")).strip()
        path = str(raw_url or "").strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        if not label or label.casefold() == "unnamed item":
            label = "Home" if path == "/" else "Page"
        absolute = site + path
        elements.append({
            "@type": "ListItem",
            "position": index,
            "name": label,
            "item": absolute,
        })
    list_name = elements[-1]["name"] if elements else "Home"
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "name": list_name,
        "itemListElement": elements,
    }


def _camp_sort_name(camp):
    return str(camp.get("page_name") or camp.get("name") or "").casefold()


def pick_hub_camps(camps, closed_cap=12, sample_cap=8):
    """Closed camps first, capped. With none closed, a short stable sample.

    Returns (camps, mode, closed_total). mode is "closed" or "sample".
    """
    camps = list(camps or [])
    closed = sorted((camp for camp in camps if camp.get("status") == "closed"), key=_camp_sort_name)
    if closed:
        return closed[:closed_cap], "closed", len(closed)
    by_region = {}
    for camp in camps:
        by_region.setdefault(camp.get("region") or "", []).append(camp)
    for rows in by_region.values():
        rows.sort(key=lambda camp: (0 if camp.get("source") != "osm" else 1, _camp_sort_name(camp)))
    keys = sorted(by_region)
    picked = []
    index = {key: 0 for key in keys}
    while len(picked) < sample_cap:
        moved = False
        for key in keys:
            rows = by_region[key]
            at = index[key]
            if at < len(rows):
                picked.append(rows[at])
                index[key] = at + 1
                moved = True
                if len(picked) >= sample_cap:
                    break
        if not moved:
            break
    return picked, "sample", 0


def pick_home_camps(groups, per=2, cap=12):
    """A few camps per state. Closed camps come before samples from states with none.

    groups is (state_name, state_slug, camps). The slug is unused; camp URLs
    already carry the state. Returns (state_name, camp) pairs.
    """
    closed_rows, sample_rows = [], []
    for state_name, _slug, camps in groups or []:
        shown, mode, _total = pick_hub_camps(camps, closed_cap=per, sample_cap=per)
        dest = closed_rows if mode == "closed" else sample_rows
        for camp in shown:
            dest.append((state_name, camp))
    return (closed_rows + sample_rows)[:cap]


BOM_WARNINGS_URL = "https://www.bom.gov.au/weather-and-climate/warnings-and-alerts"


def national_disclaimer():
    """One homepage warning. It names no state, so a new launch adds no box."""
    return (
        '<div class="warn"><strong>Not an official warning service.</strong> '
        "CampConditions does not republish live emergency warnings, and no listed alert does not mean a camp is open. "
        "Always check your state's official fire, emergency, parks and road agencies and "
        f'<a href="{BOM_WARNINGS_URL}" target="_blank" rel="noopener noreferrer">Bureau of Meteorology warnings</a> '
        'before you travel. See each state page or <a href="/about/">About</a> for state agency links. '
        'In an emergency call <a href="tel:000">000</a>.</div>'
    )


def about_warning(state):
    """Keep a state's own warning. Name the state when the box never does."""
    block = str((state or {}).get("safety_html") or "")
    name = re.sub(r"\s+", " ", str((state or {}).get("name") or "")).strip()
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block))
    if not block or not name or name.casefold() in visible.casefold():
        return block
    prefix = '<div class="warn">'
    if not block.startswith(prefix):
        return block
    label = "<strong>" + html.escape(name) + ".</strong> "
    return prefix + label + block[len(prefix):]
