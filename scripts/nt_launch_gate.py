#!/usr/bin/env python3
"""Pass/fail checks for a Northern Territory launch. They do not enable the state.

attribution_confirmed stays false until NT Parks confirms the credit, so this
gate fails. The script does not send mail or create a segment or a topic.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nt_digest
import nt_fire
import nt_inventory
import nt_signup
import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_WORDS = ("held", "disabled", "preview", "rows")
EXPECTED_MISSES = [
    "Ormiston Gorge (Walker) Campground",
    "Wallaby Gap (TG) Campground",
    "Wallaby Gap Campground",
    "Northern Campground",
    "Southern Campground",
    "Tjenya Falls Campground",
    "Big Horse Creek (TG) Campground",
    "Matt Wilson Campground",
]
EXPECTED_MATCHES = [
    "Surprise Creek Campground",
    "Oolloo Crossing Bush Campground",
    "Big Horse Creek Campground",
    "Lupayi Campground",
    "Butterfly Falls Campground",
    "Munbililla Campground",
]


def _check(name, ok, reason):
    return {"check": name, "pass": bool(ok), "reason": reason}


def _inventory():
    camps = nt_inventory.load_camps()
    counted = nt_inventory.summary(camps)
    types = counted["by_type"]
    ok = (
        counted["booking"] == 106
        and counted["published"] == 97
        and counted["excluded"] == 5
        and counted["held"] == 4
        and types["NT Parks campground"] == 97
        and types["Free"] == 0
        and types["Donation"] == 0
        and types["Council showground"] == 0
        and types["Council or community caravan park"] == 0
        and counted["in_season"] == 85
        and counted["out_of_season"] == 12
        and counted["osm_only"] == 0
        and not counted["commercial_published"]
        and all(camp.get("source") == "nt" and camp.get("lat") is not None for camp in camps)
        and {row["place"] for row in nt_inventory.load_camps.excluded} == {
            "Garig Gunak Barlu National Park",
            "Barranyi (North Island) National Park",
        }
    )
    reason = (
        "106 booking campgrounds. 97 published NT Parks campgrounds "
        "(85 in season, 12 out of season). 5 permit-only Aboriginal land campgrounds left out. "
        "4 left out because the booking response has no coordinates. "
        "Free 0, donation 0, council showground 0, council or community caravan park 0. "
        "No OpenStreetMap-only records."
    )
    if not ok:
        reason = "inventory counts were %s" % json.dumps(counted, sort_keys=True)
    return _check("inventory", ok, reason), counted


def _caravan():
    camps = nt_inventory.load_camps()
    published = nt_inventory.parks_without_keep(camps)
    sample = {"name": "Sample Holiday Park", "category": "Campground"}
    catches = nt_inventory.parks_without_keep([sample]) == ["Sample Holiday Park"]
    kept = {"name": "Council Caravan Park", "category": "Campground", "park_decision": "keep"}
    keeps = nt_inventory.parks_without_keep([kept]) == []
    plain = not nt_inventory.is_caravan_holiday_or_tourist_park({"name": "Surprise Creek Campground", "category": "NT Parks campground"})
    decisions = nt_inventory.load_decisions()
    commercial = [row for row in decisions.values() if "commercial" in (row.get("reason") or "").lower()]
    ok = catches and keeps and plain and not published and not commercial
    reason = "No commercial caravan, holiday or tourist park was in the booking list. A published one without a keep decision would fail."
    if published:
        reason = "published without a keep decision: " + "; ".join(published)
    elif not catches or not keeps or not plain:
        reason = "the park check did not catch a holiday park, or it caught an NT Parks campground"
    return _check("caravan_park_keep", ok, reason)


def _amended():
    report = nt_inventory.amended_report()
    matched = [row["name"] for row in report["matched"]]
    missed = report["missed"]
    missed_names = [row["name"] for row in missed]
    applied = [
        camp["name"] for camp in nt_inventory.load_camps()
        if camp.get("coord_source") == "amended"
    ]
    # The check fails while any amended name does not match. Matches that do
    # apply must be the six booking names, and the eight misses stay listed.
    names_ok = matched == EXPECTED_MATCHES and missed_names == EXPECTED_MISSES and set(applied) == set(EXPECTED_MATCHES)
    ok = names_ok and not missed
    lines = []
    for row in missed:
        lines.append("%s (%s)" % (row["name"], row["note"]))
    reason = "Unmatched amended coordinates, not applied: " + "; ".join(lines)
    if not names_ok:
        reason = "amended match report changed: matched %s; missed %s" % (matched, missed_names)
    return _check("amended_coordinates", ok, reason)


def _attribution():
    state = states.by_slug("nt")
    licence = state.get("licence") or {}
    confirmed = licence.get("attribution_confirmed") is True
    text = licence.get("attribution_form") or ""
    ok = confirmed and text == nt_inventory.ATTRIBUTION and "TODO" not in text
    reason = "attribution_confirmed is false. The credit is a placeholder until NT Parks confirms the wording."
    if confirmed and text != nt_inventory.ATTRIBUTION:
        reason = "attribution_confirmed is true but the credit text changed"
    return _check("attribution_confirmed", ok, reason)


def _fire():
    page = nt_fire.html_line({})
    ok = (
        nt_fire.source_resolved()
        and nt_fire.FIRE_URL in page
        and "bom.gov.au" not in page.lower()
        and "no rating" not in page.lower()
    )
    reason = (
        "Link out to NT Fire and Rescue at %s. "
        "Bushfires NT did not connect and SecureNT returned 403, so those were not used. "
        "No Bureau of Meteorology feed."
    ) % nt_fire.FIRE_URL
    if not ok:
        reason = "fire_source_resolved is false, or the fire line is missing or includes a rating"
    return _check("fire_source_resolved", ok, reason)


def _signup():
    page = nt_signup.coming_soon_html()
    token = open(os.path.join(ROOT, "functions", "_lib", "token.js"), encoding="utf-8").read()
    confirm = open(os.path.join(ROOT, "functions", "api", "confirm.js"), encoding="utf-8").read()
    unsubscribe = open(os.path.join(ROOT, "functions", "api", "unsubscribe.js"), encoding="utf-8").read()
    subscribe = open(os.path.join(ROOT, "functions", "api", "subscribe.js"), encoding="utf-8").read()
    state = states.by_slug("nt")
    decision = nt_digest.send_decision()
    forced = nt_digest.perform_send(region_enabled=True)
    ok = (
        nt_signup.COMING_SOON in page
        and "<form" not in page
        and "/api/subscribe" not in page
        and nt_signup.forms_allowed() is False
        and states.signup_allowed(state) is False
        and states.digest_allowed(state) is False
        and (state.get("release") or {}).get("region_enabled") is False
        and '"nt"' in token
        and "nt: false" in token
        and "RESEND_SEGMENT_NT_ID" not in confirm
        and "RESEND_TOPIC_NT_ID" not in confirm
        and "RESEND_SEGMENT_NT_ID" not in unsubscribe
        and "RESEND_TOPIC_NT_ID" not in unsubscribe
        and "RESEND_SEGMENT_NT_ID" not in subscribe
        and "RESEND_TOPIC_NT_ID" not in subscribe
        and decision["send"] is False
        and decision["reason"] == "region_disabled"
        and decision["called_resend"] is False
        and forced["send"] is False
        and forced["called_resend"] is False
    )
    reason = "Region flag off. Weekly email line, no form, no segment and no topic."
    if not ok:
        reason = "signup is open, or a page or API file would create an NT segment or topic"
    return _check("nt_signup", ok, reason)


def _public(dist):
    dist = os.path.abspath(dist)
    home = os.path.join(dist, "index.html")
    nt_dir = os.path.join(dist, "nt")
    if not os.path.isfile(home):
        return _check("public_nt", False, "public build is not in %s" % dist)
    page = open(home, encoding="utf-8").read()
    absent = 'href="/nt/"' not in page and "Northern Territory" not in page and not os.path.isdir(nt_dir)
    offered = 'value="vic"' in page and 'value="nsw"' in page and 'value="qld"' in page
    nt_off = 'value="nt"' not in page
    ok = absent and offered and nt_off and states.by_slug("nt").get("enabled") is False
    reason = "The public build does not list the Northern Territory."
    if not ok:
        reason = "Northern Territory is in the public build or the state flag is on"
    return _check("public_nt", ok, reason)


def _wording(text):
    visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", visible, flags=re.S | re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    found = []
    for word in FORBIDDEN_WORDS:
        if re.search(r"\b" + word + r"\b", visible, re.I):
            found.append(word)
    return found


def _pages(preview):
    root = os.path.join(os.path.abspath(preview), "nt")
    if not os.path.isdir(root):
        return _check("nt_pages", False, "Northern Territory pages are not at %s" % root)
    missing_line, missing_caution, missing_credit, forms, wording, crumbs, pages = [], [], [], [], [], [], 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, root)
            camp_page = f"{os.sep}camp{os.sep}" in path
            state_page = rel == "index.html"
            if nt_signup.COMING_SOON not in text:
                missing_line.append(rel)
            if 'action="/api/subscribe"' in text:
                forms.append(rel)
            if camp_page or state_page:
                if nt_inventory.CAUTION not in text:
                    missing_caution.append(rel)
            if camp_page and nt_inventory.ATTRIBUTION not in text:
                missing_credit.append(rel)
            if 'href="/nt/">Northern Territory</a> › <a href="/nt/northern-territory/">Northern Territory</a>' in text:
                crumbs.append(rel)
            bad = _wording(text)
            if bad:
                wording.append("%s (%s)" % (rel, ", ".join(bad)))
    ok = pages > 0 and not missing_line and not missing_caution and not missing_credit and not forms and not wording and not crumbs
    reason = "%s Northern Territory pages, caution, attribution, signup line, no subscribe form" % pages
    if not ok:
        reason = "pages missing a line or showing a form, a repeated breadcrumb, or internal wording: " + "; ".join((missing_line + missing_caution + missing_credit + forms + wording + crumbs)[:8])
    return _check("nt_pages", ok, reason)


def evaluate(dist, preview=None):
    inventory, counted = _inventory()
    checks = [
        inventory,
        _caravan(),
        _amended(),
        _attribution(),
        _fire(),
        _signup(),
        _public(dist),
    ]
    if preview:
        checks.append(_pages(preview))
    return {
        "pass": all(item["pass"] for item in checks),
        "published": counted["published"],
        "by_type": counted["by_type"],
        "amended_matched": counted["amended_matched"],
        "amended_missed": counted["amended_missed"],
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="Northern Territory launch gate")
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--preview", default="")
    args = parser.parse_args()
    report = evaluate(args.dist, args.preview or None)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
