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


TITLE_BRAND = " | CampConditions.au"
TITLE_TARGET = 65
TITLE_MIN_NAME = 18
_CAMP_WORD = re.compile(r"\b(camps?|campgrounds?|camping|campsites?)\b", re.I)
_NEAR_CLAUSE = re.compile(r",\s*near\s+", re.I)


def has_camp_word(name):
    """True when the name already says Camp, Camps, Campground or Camping."""
    return bool(_CAMP_WORD.search(name or ""))


def region_is_state(region_name, state_name="", abbrev=""):
    """True when the region is missing or just repeats the state."""
    region = re.sub(r"\s+", " ", str(region_name or "")).strip().casefold()
    if not region:
        return True
    names = {re.sub(r"\s+", " ", str(value or "")).strip().casefold() for value in (state_name, abbrev) if value}
    return region in names


def clip_title_name(name, limit):
    """Shorten a long camp name, keeping site numbers and (south)/(north)."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if len(name) <= limit:
        return name
    # Drop trailing park-style parentheticals. Keep short distinctive ones
    # such as (The Point) or (tent site), and (south)/(north)/(1).
    while len(name) > limit:
        match = re.search(r"\s*\(([^()]{2,})\)\s*$", name)
        if not match:
            break
        inner = match.group(1).strip()
        low = inner.casefold()
        if low in {"south", "north"} or inner.isdigit():
            break
        if (
            "national park" in low
            or "reserve" in low
            or "forest" in low
            or "river" in low
            or "murray" in low
            or len(inner.split()) >= 4
        ):
            name = name[: match.start()].rstrip(" ,-—")
            continue
        break
    if len(name) <= limit:
        return name
    if _NEAR_CLAUSE.search(name):
        left, right = re.split(r",\s*near\s+", name, maxsplit=1)
        keep_near = ", near " + right.strip()
        allowed_left = max(8, limit - len(keep_near))
        if len(left) > allowed_left:
            left = clip_title_name(left, allowed_left)
        return (left + keep_near).strip()
    keep = ""
    held = re.search(
        r"(\s*\((?:south|north|\d+)\)|\s*(?:-\s*)?(?:site|zone|area|river access)\s+\d+|\s+\d+)\s*$",
        name,
        re.I,
    )
    if held:
        keep = held.group(1)
        if keep.lstrip().startswith("-"):
            keep = " " + keep.lstrip(" -")
        head = name[: held.start()].rstrip(" ,-—")
        combined = (head + keep).strip()
        # Keep the site/zone label even if the name runs a little long.
        if len(combined) <= max(limit, 40):
            return combined
        name = head
        limit = max(TITLE_MIN_NAME, limit - len(keep))
    # Prefer keeping a short distinctive segment after the first dash.
    if " - " in name:
        left, right = name.split(" - ", 1)
        right = re.split(r"\s+-\s+", right)[0].strip()
        right = re.sub(r"\s*\([^)]*\)", " ", right).strip()
        words = [word for word in right.split() if word and not word.startswith("(") and not word.endswith(")")]
        # One or two words on the right is usually the site name (Trewalla, Ganguddy).
        for count in (2, 1):
            short_right = " ".join(words[:count])
            combo = f"{left} - {short_right}" if short_right else left
            if 12 <= len(combo) <= max(limit, 40):
                return (combo + keep).strip()
        if len(left) >= 12 and len(left) <= max(limit, 40):
            return (left + keep).strip()
    for sep in (",", " ("):
        if sep == "," and _NEAR_CLAUSE.search(name):
            continue
        cut = name.find(sep)
        if 12 <= cut <= limit:
            return (name[:cut].rstrip(" ,-—") + keep).strip()
    cut = name[:limit].rsplit(" ", 1)[0].rstrip(" ,-—")
    if len(cut) < 8:
        cut = name.split(" ", 1)[0]
    if "(" in cut and ")" not in cut[cut.rfind("("):]:
        cut = cut[: cut.rfind("(")].rstrip(" ,-—") or cut
    # A stray closing paren is left when a '(word' was stripped mid-clip.
    cut = re.sub(r"\s*\)(?=\s|$)", "", cut).strip()
    return (cut + keep).strip()


def region_phrase(region, abbrev, state_name):
    """Region plus state abbrev, without repeating the state name."""
    region = re.sub(r"\s+", " ", str(region or "")).strip()
    abbrev = re.sub(r"\s+", " ", str(abbrev or "")).strip()
    state_name = re.sub(r"\s+", " ", str(state_name or "")).strip()
    if not region:
        return abbrev
    if state_name and region.casefold().endswith(state_name.casefold()):
        stem = region[: -len(state_name)].strip(" ,-&")
        if stem and abbrev:
            return f"{stem} {abbrev}"
        return abbrev or region
    if abbrev and re.search(r"\b" + re.escape(abbrev) + r"\b", region, re.I):
        return region
    return f"{region} {abbrev}".strip() if abbrev else region


def _title_tail(name, abbrev, town, region, state_name, with_region=False):
    """Location and state clause after the camp name."""
    if town and town.casefold() in name.casefold():
        town = ""
    if region and (region_is_state(region, state_name, abbrev) or region.casefold() in name.casefold()):
        region = ""
    placed = region_phrase(region, abbrev, state_name) if region else (abbrev or "")
    if _NEAR_CLAUSE.search(name):
        if with_region and region and placed:
            return f", {placed}"
        return f" {abbrev}" if abbrev else ""
    if town:
        if with_region and region and placed:
            return f", near {town}, {placed}"
        return f", near {town} {abbrev}" if abbrev else f", near {town}"
    if region and placed:
        return f", {placed}"
    if has_camp_word(name):
        return f", {abbrev}" if abbrev else ""
    return f", {abbrev} camping" if abbrev else " camping"


_GENERIC_TITLE_WORDS = frozenset("""
    a an the and or of in on at to from for with camping camp campground campgrounds
    campsite campsites area areas site sites park parks national state forest reserve
    river murray proposed part walk beach beachfront common island lands section
    heritage free paid public recreation ground grounds crossing
""".split())


def distinctive_extra(camp, peers=None):
    """A short label already in the camp name, used to split a title clash."""
    full = re.sub(r"\s+", " ", str(camp.get("page_name") or camp.get("name") or "")).strip()
    if not full:
        return ""
    peer_texts = []
    if peers:
        for peer in peers:
            peer_texts.append(
                re.sub(r"\s+", " ", str(peer.get("page_name") or peer.get("name") or "")).strip()
            )

    def unique_among_peers(value):
        if not value:
            return False
        if not peer_texts:
            return True
        low = value.casefold()
        return all(low not in text.casefold() for text in peer_texts)

    if peer_texts:
        for match in re.finditer(r"\(([^)]+)\)", full):
            inner = re.sub(r"\s+", " ", match.group(1)).strip()
            low = inner.casefold()
            if "national park" in low or "reserve" in low or "forest" in low or "river" in low or "murray" in low:
                continue
            if 0 < len(inner.split()) <= 4 and unique_among_peers(inner):
                return inner
        match = re.search(r"\b((?:site|zone|area|camping area|river access)\s+\d+)\b", full, re.I)
        if match and unique_among_peers(match.group(1)):
            return match.group(1)
        match = re.search(r",\s*near\s+([^,]+)$", full, re.I)
        if match and unique_among_peers(match.group(1).strip()):
            return match.group(1).strip()
        other_toks = set()
        for text in peer_texts:
            other_toks.update(tok.casefold() for tok in re.findall(r"[A-Za-z0-9']+", text))
        unique = []
        for tok in re.findall(r"[A-Za-z0-9']+", full):
            if tok.casefold() in other_toks or tok.casefold() in _GENERIC_TITLE_WORDS:
                continue
            if tok not in unique:
                unique.append(tok)
        if unique:
            return " ".join(unique[:3])
        # Last resort: the part of the name after the shared prefix
        # (camping area vs Campsite vs Free Camp; Recreation Reserve vs Public).
        words = re.findall(r"[A-Za-z0-9']+", full)
        peer_word_lists = [re.findall(r"[A-Za-z0-9']+", text) for text in peer_texts]
        def _shared_prefix_len(left, right):
            index = 0
            while index < len(left) and index < len(right) and left[index].casefold() == right[index].casefold():
                index += 1
            return index
        if words and peer_word_lists:
            shared = min(_shared_prefix_len(words, other) for other in peer_word_lists)
            rest = words[shared:]
            if rest:
                return " ".join(rest[:4])

    for match in re.finditer(r"\(([^)]+)\)", full):
        inner = re.sub(r"\s+", " ", match.group(1)).strip()
        low = inner.casefold()
        if low in {"south", "north"} or inner.isdigit():
            return f"({low})"
        if "national park" in low or "reserve" in low or "forest" in low or "river" in low or "murray" in low:
            continue
        if 0 < len(inner.split()) <= 4:
            return inner
    match = re.search(r"\b((?:site|zone|area|camping area|river access)\s+\d+)\b", full, re.I)
    if match:
        return match.group(1)
    match = re.search(r",\s*near\s+([^,]+)$", full, re.I)
    if match:
        return match.group(1).strip()
    if " - " in full:
        right = re.sub(r"\s*\([^)]*\)\s*$", "", full.split(" - ", 1)[1]).strip()
        words = [word for word in right.split() if word and not word.startswith("(")]
        if words:
            return " ".join(words[:3])
    match = re.search(r"(\d+)\s*(?:\([^)]*\))?\s*$", full)
    if match:
        return match.group(1)
    return ""



def _join_extra(head, extra):
    """Append extra without repeating words already at the end of head."""
    head = re.sub(r"\s+", " ", str(head or "")).strip()
    extra = re.sub(r"\s+", " ", str(extra or "")).strip()
    if not extra:
        return head
    if extra.casefold() in head.casefold():
        return head
    head_words = head.split()
    extra_words = extra.split()
    overlap = 0
    for count in range(min(len(head_words), len(extra_words)), 0, -1):
        if [word.casefold() for word in head_words[-count:]] == [word.casefold() for word in extra_words[:count]]:
            overlap = count
            break
    rest = extra_words[overlap:]
    return (head + (" " + " ".join(rest) if rest else "")).strip()


def camp_page_title(name, abbrev, town="", region="", state_name="", extra="", with_region=False, target=TITLE_TARGET):
    """Camp <title>: full H1 name, then town or region, then the state.

    "{Name}, near {Town} {ST} | CampConditions.au" when town is set.
    Otherwise "{Name}, {Region} {ST} | CampConditions.au".
    When the region is just the state (SA and TAS): "{Name}, {ST} camping | ..."
    unless the name already contains Camp, Campground or Camping.
    The name is never clipped. If the title would run long, the town or
    region is dropped first, leaving "{Name} {ST} | CampConditions.au".
    A still-long name is left in full. extra and with_region are used only
    to disambiguate a title clash, still without cutting the name.
    """
    name = re.sub(r"\s+", " ", str(name or "")).strip() or "Campground"
    abbrev = re.sub(r"\s+", " ", str(abbrev or "")).strip()
    town = re.sub(r"\s+", " ", str(town or "")).strip()
    region = re.sub(r"\s+", " ", str(region or "")).strip()
    extra = re.sub(r"\s+", " ", str(extra or "")).strip()
    # A clash extra is only added when it is already implied by a longer official
    # name; it must not replace or shorten the H1. If it is not already in the
    # name, only with_region (the location tail) should disambiguate.
    if extra and extra.casefold() in name.casefold():
        extra = ""
    elif extra:
        # Keep it only as a last-resort suffix for a clash of identical names.
        pass
    else:
        extra = ""
    if town and town.casefold() == name.casefold():
        town = ""
    # If the H1 already has ", near X", do not add a second near-clause.
    # _title_tail already treats a name with ", near" as complete and only
    # appends the state (or region when with_region is set).

    def make(town, region, with_region, extra_suffix=""):
        shown = name if not extra_suffix or extra_suffix.casefold() in name.casefold() else f"{name} {extra_suffix}".strip()
        tail = _title_tail(shown, abbrev, town, region, state_name, with_region=with_region)
        return shown + tail + TITLE_BRAND

    preferred = make(town, region, with_region, extra if with_region or extra else "")
    if len(preferred) <= target:
        return preferred
    # Drop town and region; keep the full name and the state abbreviation.
    short_tail = f" {abbrev}" if abbrev else ""
    if abbrev and re.search(r"\b" + re.escape(abbrev) + r"\s*$", name):
        short_tail = ""
    shown = name
    if extra and extra.casefold() not in name.casefold() and (with_region or extra):
        # Only attach a clash suffix when the short form would still collide;
        # callers request that via extra. Prefer the bare name + state first.
        short = name + short_tail + TITLE_BRAND
        if len(preferred) > target:
            return short
    return name + short_tail + TITLE_BRAND



def resolve_title_collisions(camps, title_of, retry):
    """If two camps share a title, add a distinctive bit from the name, then the region."""
    titles = [title_of(camp) for camp in camps]

    def regroup():
        groups = {}
        for index, title in enumerate(titles):
            groups.setdefault(title.casefold(), []).append(index)
        return groups

    for rows in regroup().values():
        if len(rows) < 2:
            continue
        members = [camps[index] for index in rows]
        for index in rows:
            peers = [camp for camp in members if camp is not camps[index]]
            extra = distinctive_extra(camps[index], peers=peers) or distinctive_extra(camps[index])
            if extra:
                titles[index] = retry(camps[index], extra=extra)
    for rows in regroup().values():
        if len(rows) < 2:
            continue
        members = [camps[index] for index in rows]
        for index in rows:
            peers = [camp for camp in members if camp is not camps[index]]
            extra = distinctive_extra(camps[index], peers=peers) or distinctive_extra(camps[index])
            titles[index] = retry(camps[index], extra=extra, with_region=True)
    return titles


_SKIP_SUMMARY_SOURCES = frozenset({
    "npws", "qpws", "tas", "parks_sa", "sa_operator", "council", "tourism", "operator",
})
_SKIP_SUMMARY_STATES = frozenset({"sa", "tas", "act", "nt", "wa"})
_SUMMARY_BANNED = re.compile(r"\b(no rating|km\b|kilometres?|kilometers?|stars?\b|rated)\b", re.I)


def has_real_description(camp):
    """True when the camp already has official or tagged prose to show."""
    for key in ("description", "about", "camping", "caravans", "access"):
        if re.sub(r"\s+", " ", str(camp.get(key) or "")).strip():
            return True
    return False


def _distinctive_region(region, state_name):
    region = re.sub(r"\s+", " ", str(region or "")).strip()
    if not region or region_is_state(region, state_name):
        return ""
    return region


def recorded_facts(camp, region="", state_name=""):
    """Confirmed fee, dogs, caravans, motorhomes, and a distinctive region."""
    facts = {}
    cost = str(camp.get("cost") or "").strip().lower()
    if cost in {"free", "paid"}:
        facts["fee"] = cost
    for key, field in (("dogs", "fac_dogs"), ("caravans", "fac_caravans"), ("motorhomes", "fac_motorhomes")):
        value = camp.get(field)
        if value is True or value is False:
            facts[key] = value
    region = _distinctive_region(region, state_name)
    if region:
        facts["region"] = region
    return facts


def _place_clause(region, state_name):
    region = re.sub(r"\s+", " ", str(region or "")).strip()
    state_name = re.sub(r"\s+", " ", str(state_name or "")).strip()
    if region and state_name and region.casefold().endswith(state_name.casefold()):
        return f"in {region}"
    if region and state_name:
        return f"in {region}, {state_name}"
    if region:
        return f"in {region}"
    if state_name:
        return f"in {state_name}"
    return ""


def _and_list(items):
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _suit_labels(facts, wanted):
    order = (("caravans", "caravans"), ("motorhomes", "motorhomes"), ("dogs", "dogs"))
    return [label for label, key in order if facts.get(key) is wanted]


def is_donation_fee(camp):
    """True when the recorded fee type or category is donation."""
    fee = str(camp.get("fee_type") or "").strip().lower()
    cat = str(camp.get("category") or "").strip()
    label = str(camp.get("fee_label") or "").strip()
    return fee == "donation" or cat == "Donation" or label.casefold() == "donation"


def _fee_noun(camp, facts):
    if is_donation_fee(camp):
        return "a donation camping area"
    fee = facts.get("fee")
    if fee == "free":
        return "a free camping area"
    if fee == "paid":
        return "a paid camping area"
    return ""


def _variant(camp):
    key = str(camp.get("slug") or camp.get("name") or "")
    return sum(ord(ch) for ch in key) % 3


def _tidy(text):
    text = re.sub(r"\s+", " ", str(text or "")).replace(" .", ".").strip()
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r" ,", ",", text)
    text = re.sub(r"^It is \.", "", text).strip()
    if text and not text.endswith("."):
        text += "."
    return text


def fact_summary(camp, region="", state_name=""):
    """A short fact-only lead sentence, or empty when the camp is not eligible.

    Only VIC/NSW/QLD camps with no existing real description and at least two
    recorded facts (fee free/paid, confirmed dogs/caravans/motorhomes, or a
    distinctive region). NPWS, QPWS, SA and TAS records are skipped. Wording
    is tied to those facts only. Sentence shape is chosen deterministically
    from the slug so neighbouring pages are not all identical.
    """
    source = str(camp.get("source") or "").strip().lower()
    state = str(camp.get("state_slug") or "").strip().lower()
    if source in _SKIP_SUMMARY_SOURCES or state in _SKIP_SUMMARY_STATES:
        return ""
    if has_real_description(camp):
        return ""
    facts = recorded_facts(camp, region, state_name)
    if len(facts) < 2:
        return ""
    name = re.sub(r"\s+", " ", str(camp.get("name") or "").strip()) or "This camping area"
    place = _place_clause(facts.get("region") or "", state_name)
    fee = _fee_noun(camp, facts)
    suitable = _suit_labels(facts, True)
    unsuitable = _suit_labels(facts, False)
    suit_pos = ("recorded as suitable for " + _and_list(suitable)) if suitable else ""
    suit_neg = ("recorded as not suitable for " + _and_list(unsuitable)) if unsuitable else ""
    variant = _variant(camp)

    sentences = []
    if variant == 0:
        if fee and place:
            sentences.append(f"{name} is {fee} {place}.")
        elif fee:
            sentences.append(f"{name} is {fee}.")
        elif place:
            sentences.append(f"{name} is {place}.")
        else:
            sentences.append(f"{name}.")
        if suit_pos:
            sentences.append("It is " + suit_pos + ".")
        if suit_neg:
            sentences.append("It is " + suit_neg + ".")
    elif variant == 1 and place:
        sentences.append(f"{name} is {place}.")
        mid = []
        if fee:
            mid.append(fee)
        if suit_pos:
            mid.append(suit_pos)
        if mid:
            sentences.append("It is " + ", ".join(mid) + ".")
        if suit_neg:
            sentences.append("It is " + suit_neg + ".")
    else:
        if suit_pos:
            sentences.append(f"{name} is {suit_pos}.")
            if fee and place:
                sentences.append(f"It is {fee} {place}.")
            elif fee:
                sentences.append(f"It is {fee}.")
            elif place:
                sentences.append(f"It is {place}.")
        elif fee and place:
            sentences.append(f"{name} is {fee} {place}.")
        elif place:
            sentences.append(f"{name} is {place}.")
        elif fee:
            sentences.append(f"{name} is {fee}.")
        if suit_neg:
            if not sentences:
                sentences.append(f"{name} is {suit_neg}.")
            else:
                sentences.append("It is " + suit_neg + ".")
    text = _tidy(" ".join(sentences))
    if not text or _SUMMARY_BANNED.search(text):
        return ""
    return text
