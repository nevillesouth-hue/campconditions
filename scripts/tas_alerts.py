#!/usr/bin/env python3
"""Parks and Wildlife Service site alerts for Tasmania.

One fetch of the alerts page per build. The stored record is the headline,
the affected park names, and the link back to that page. The alert body is
not kept. A failed fetch reuses the last good record and is marked stale.
"""
import datetime as dt
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERTS_URL = "https://parks.tas.gov.au/explore-our-parks/know-before-you-go/alerts"
USER_AGENT = "CampConditions.au/1.0 (Tasmania park alerts; +https://campconditions.au)"
LINK_TEXT = "Parks and Wildlife Service alerts"
COUNCIL_SENTENCE = "Check with the council before you travel."
CAMPFIRE_NOTE = "Seasonal campfire ban."
AMBER_LABEL = "Alert in this park"
CLOSED_LABEL = "Closed"
NO_ALERT_LABEL = "No current alert"
COUNCIL_LABEL = "Check with the council"
STALE_MESSAGE = (
    "Park alerts could not be fetched for this update. These headlines are from the last check that succeeded. "
    "Check the Parks and Wildlife Service alerts page before you travel."
)
_RESERVE_TAIL = re.compile(
    r"[\s\-–—:]*((?:national park|conservation area|state reserve|nature reserve|regional reserve|"
    r"historic site|game reserve|forest reserve|marine nature reserve|marine reserve)\b)",
    re.I,
)
_NUM_AND = re.compile(r"(?:no\.?\s*)?(\d+)\s+and\s+(?:no\.?\s*)?(\d+)\b", re.I)


def allowed_url(url):
    """robots.txt allows the alerts path and disallows query strings and SharePoint plumbing."""
    if not url or "?" in url or url.lower().startswith(("http://",)):
        return False
    if not url.startswith("https://parks.tas.gov.au/"):
        return False
    path = url[len("https://parks.tas.gov.au"):]
    if path.startswith((
        "/_layouts/", "/_vti_bin/", "/_catalogs/", "/search", "/feedback",
        "/index.aspx", "/file.aspx",
    )):
        return False
    return path.rstrip("/") == "/explore-our-parks/know-before-you-go/alerts"


def norm_name(value):
    text = (value or "").lower().replace("&", " and ")
    text = text.replace("'", "").replace("’", "").replace("`", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_html(page):
    """Headlines and location names only. Body text is discarded."""
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else str(page or "")
    block = re.search(r"<h2\b[^>]*>\s*Site Alerts\s*</h2>(.*?)(?:<h2\b|$)", text, re.S | re.I)
    region = block.group(1) if block else ""
    alerts = []
    for part in re.split(r'<div class="section">', region)[1:]:
        title = re.search(r"<h3>(.*?)</h3>", part, re.S | re.I)
        if not title:
            continue
        headline = _text(title.group(1))
        if not headline:
            continue
        parks = []
        loc = re.search(r"<b>\s*Locations affected:\s*</b>(.*?)</p>", part, re.S | re.I)
        if loc:
            for raw in re.findall(r"<a\b[^>]*>(.*?)</a>", loc.group(1), re.S | re.I):
                name = _text(raw)
                if name and name not in parks:
                    parks.append(name)
        alerts.append({"headline": headline, "parks": parks, "link": ALERTS_URL})
    return alerts


def _text(fragment):
    cleaned = re.sub(r"<[^>]+>", " ", fragment or "")
    return " ".join(html.unescape(cleaned).replace("\xa0", " ").split())


def parks_match(camp_park, alert_park):
    """Exact match first, then case, ampersand and punctuation.

    A location sometimes prefixes a site and then names the reserve, as in
    "Lake St Clair (Cradle Mountain - Lake St Clair National Park)". The reserve
    name in that text matches. A shorter invented name does not.
    """
    left = (camp_park or "").strip()
    right = (alert_park or "").strip()
    if not left or not right:
        return False
    if left == right or left.casefold() == right.casefold():
        return True
    nleft, nright = norm_name(left), norm_name(right)
    if not nleft or not nright:
        return False
    if nleft == nright:
        return True
    return f" {nleft} " in f" {nright} "


def is_campfire(headline):
    text = (headline or "").strip()
    if not re.match(r"fire ban\s*:", text, re.I):
        return False
    return re.search(r"\bcampfire bans?\b", text, re.I) is not None


def is_closure(headline):
    return re.search(r"\b(?:closed|closure)\b", headline or "", re.I) is not None


def _phrase_in(phrase, headline):
    phrase = (phrase or "").strip()
    if len(phrase) < 3:
        return False
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", headline or "", re.I) is not None


def _park_titles(camp, extra):
    titles = []
    for value in (camp.get("pws_alert_name"), camp.get("reserve_name")):
        if value and value not in titles:
            titles.append(value)
    for value in extra or []:
        if value and value not in titles:
            titles.append(value)
    return titles


def is_park_leading_words(phrase, headline, park_names):
    """A park title in the headline is not the camp's name."""
    if not _phrase_in(phrase, headline):
        return False
    nphrase = norm_name(phrase)
    nhead = norm_name(headline)
    for park in park_names or []:
        npark = norm_name(park)
        if not nphrase or not npark:
            continue
        if npark == nphrase:
            return True
        if npark.startswith(nphrase + " ") and npark in nhead:
            return True
    for match in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(phrase.strip()) + r"(?![A-Za-z0-9])", headline or "", re.I):
        if _RESERVE_TAIL.match(headline[match.end():]):
            return True
    return False


def _phrases(camp):
    found = []
    for value in [camp.get("name")] + list(camp.get("aliases") or []):
        text = (value or "").strip()
        if text and text not in found:
            found.append(text)
    return found


def numbered_group_hit(headline, phrases):
    """'Name 1 and 2' covers aliases 'Name No 1' / 'Name 1' and the same for 2."""
    norms = [norm_name(phrase) for phrase in phrases]
    for match in _NUM_AND.finditer(headline or ""):
        words = re.findall(r"[A-Za-z][A-Za-z'’.-]*", headline[:match.start()])
        for length in range(1, 7):
            if len(words) < length:
                break
            base = norm_name(" ".join(words[-length:]))
            if not base:
                continue
            for number in (match.group(1), match.group(2)):
                options = {f"{base} {number}", f"{base} no {number}"}
                if any(got in options for got in norms):
                    return True
    return False


def names_camp(headline, camp, park_names):
    phrases = _phrases(camp)
    if numbered_group_hit(headline, phrases):
        return True
    titles = _park_titles(camp, park_names)
    for phrase in phrases:
        if not _phrase_in(phrase, headline):
            continue
        if is_park_leading_words(phrase, headline, titles):
            continue
        return True
    return False


def _unique(rows):
    found, seen = [], set()
    for row in rows:
        key = (row or "").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(row)
    return found


def classify(camp, alerts):
    """One camp's display. Council camps never take a PWS alert."""
    if camp.get("tas_council"):
        return {"display": "council", "closures": [], "ambers": [], "campfire": False}
    park = (camp.get("pws_alert_name") or "").strip()
    closures, ambers, campfire = [], [], False
    if not park:
        return {"display": "none", "closures": [], "ambers": [], "campfire": False}
    for alert in alerts or []:
        headline = alert.get("headline") or ""
        parks = alert.get("parks") or []
        if not any(parks_match(park, name) for name in parks):
            continue
        if is_campfire(headline):
            campfire = True
        elif is_closure(headline) and names_camp(headline, camp, parks):
            closures.append(headline)
        else:
            ambers.append(headline)
    closures, ambers = _unique(closures), _unique(ambers)
    if closures:
        display = "closed"
    elif ambers:
        display = "amber"
    else:
        display = "none"
    return {"display": display, "closures": closures, "ambers": ambers, "campfire": campfire}


def counts(camps):
    return {
        "amber": sum(camp.get("tas_display") == "amber" for camp in camps),
        "closed": sum(camp.get("tas_display") == "closed" for camp in camps),
        "campfire": sum(bool(camp.get("tas_campfire")) for camp in camps),
        "council": sum(camp.get("tas_display") == "council" for camp in camps),
        "published": len(camps),
    }


def apply_alerts(camps, alerts):
    for camp in camps:
        result = classify(camp, alerts)
        camp["tas_display"] = result["display"]
        camp["tas_closures"] = result["closures"]
        camp["tas_ambers"] = result["ambers"]
        camp["tas_campfire"] = result["campfire"]
        camp["alerts"] = []
        if result["display"] == "closed":
            camp["status"] = "closed"
            camp["status_label"] = CLOSED_LABEL
            joined = "; ".join(result["closures"])
            camp["closure"] = {
                "desc": joined,
                "reason": result["closures"][0],
                "source_url": ALERTS_URL,
                "status": "Closed",
            }
            camp["tas_list_note"] = result["closures"][0]
        elif result["display"] == "amber":
            camp["status"] = "check"
            camp["status_label"] = AMBER_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = result["ambers"][0]
            camp["alerts"] = [{"heading": headline, "url": ALERTS_URL} for headline in result["ambers"]]
        elif result["display"] == "council":
            camp["status"] = "check"
            camp["status_label"] = COUNCIL_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = COUNCIL_SENTENCE
        else:
            camp["status"] = "check"
            camp["status_label"] = NO_ALERT_LABEL
            camp["closure"] = None
            camp["tas_list_note"] = CAMPFIRE_NOTE if result["campfire"] else NO_ALERT_LABEL
        camp["open_inferred"] = False
    return counts(camps)


def html_block(camp):
    link = f'<a href="{html.escape(ALERTS_URL)}">{html.escape(LINK_TEXT)}</a>'
    bits = []
    if camp.get("tas_council"):
        url = str(camp.get("council_url") or "")
        sentence = html.escape(COUNCIL_SENTENCE)
        if url.startswith("https://"):
            bits.append(
                f'<p class="tas-council"><strong>{sentence}</strong> '
                f'<a href="{html.escape(url)}">Council information</a></p>'
            )
        else:
            bits.append(f'<p class="tas-council"><strong>{sentence}</strong></p>')
    elif camp.get("tas_display") == "closed":
        items = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp.get("tas_closures") or [])
        bits.append(f'<div class="warn" id="camp-closure"><strong>Closed.</strong><ul>{items}</ul><p>{link}</p></div>')
        if camp.get("tas_ambers"):
            extra = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp["tas_ambers"])
            bits.append(f'<div class="warn" id="camp-alert"><strong>Alert in this park.</strong><ul>{extra}</ul><p>{link}</p></div>')
    elif camp.get("tas_display") == "amber":
        items = "".join(f"<li>{html.escape(headline)}</li>" for headline in camp.get("tas_ambers") or [])
        bits.append(
            f'<div class="warn" id="camp-alert"><strong>Alert in this park.</strong><ul>{items}</ul><p>{link}</p></div>'
        )
    else:
        bits.append(
            "<p><strong>No current alert.</strong> No current alert does not mean the camp is open, so check before you travel.</p>"
        )
    if camp.get("tas_campfire"):
        bits.append(f'<p class="muted tas-campfire">{html.escape(CAMPFIRE_NOTE)} {link}</p>')
    park = (camp.get("pws_alert_name") or "").strip()
    if park and not camp.get("tas_council"):
        bits.append(f"<p>Park: {html.escape(park)}</p>")
    credit = camp.get("attribution") or ""
    if credit:
        bits.append(f'<p class="muted">{html.escape(credit)}</p>')
    source = str(camp.get("source_url") or "")
    if source.startswith("https://"):
        bits.append(f'<p>Campground record: <a href="{html.escape(source)}">theLIST</a></p>')
    return "".join(bits)


def last_good_path(directory):
    return os.path.join(directory, "pws-alerts.json")


def save_last_good(directory, alerts, fetched):
    os.makedirs(directory, exist_ok=True)
    path = last_good_path(directory)
    payload = {"url": ALERTS_URL, "fetched": fetched, "link": ALERTS_URL, "alerts": alerts}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, path)


def load_last_good(directory):
    path = last_good_path(directory)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    alerts = []
    for row in payload.get("alerts") or []:
        if not isinstance(row, dict):
            continue
        headline = str(row.get("headline") or "").strip()
        if not headline:
            continue
        parks = [str(name).strip() for name in row.get("parks") or [] if str(name).strip()]
        alerts.append({"headline": headline, "parks": parks, "link": ALERTS_URL})
    if not alerts:
        return None
    return {"alerts": alerts, "fetched": str(payload.get("fetched") or "")}


def fetch_alerts(fetch_text, directory, now=None):
    """One request. On failure, keep the last good headlines and mark them stale."""
    if not allowed_url(ALERTS_URL):
        raise SystemExit("PWS alerts URL is not allowed")
    now = now or dt.datetime.now(dt.timezone.utc)
    body = fetch_text("pws_alerts", ALERTS_URL, {"User-Agent": USER_AGENT, "Accept": "text/html"})
    if body:
        alerts = parse_html(body)
        fetched = now.isoformat()
        if alerts:
            save_last_good(directory, alerts, fetched)
        return {"alerts": alerts, "stale": False, "fetched": fetched, "fallback": False}
    cached = load_last_good(directory)
    if cached:
        return {"alerts": cached["alerts"], "stale": True, "fetched": cached["fetched"], "fallback": True}
    return {"alerts": [], "stale": True, "fetched": "", "fallback": False}


def stamp(result):
    """Feed line for the state page. Stale is set when this build reused the last good fetch."""
    info = {
        "label": "Park alerts",
        "agency": "Parks and Wildlife Service",
        "updated": result.get("fetched") or "",
        "feed": ALERTS_URL,
    }
    if result.get("stale"):
        info["stale"] = True
        info["stale_message"] = STALE_MESSAGE
    return info
