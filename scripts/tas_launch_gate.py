#!/usr/bin/env python3
"""Pass/fail checks for a Tasmania launch. They do not enable the state.

The caravan, holiday and tourist park check fails when one of those parks is
in the published list. The script does not send mail or create a segment.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tas_alerts
import tas_fire
import tas_inventory
import tas_signup
import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_WORDS = ("held", "disabled", "preview", "rows")


def _check(name, ok, reason):
    return {"check": name, "pass": bool(ok), "reason": reason}


def _inventory():
    counted = tas_inventory.summary()
    ok = (
        counted["source_rows"] == 691
        and counted["eligible"] == 189
        and counted["published"] == 189
        and counted["map_rows"] == 189
        and not counted["held_published"]
        and not counted["excluded_published"]
        and not counted["missing_eligible"]
        and counted["council"] == 11
    )
    reason = "691 records, 189 eligible published, 0 held, 0 excluded, 11 camps outside a reserve"
    if not ok:
        reason = "inventory counts were %s" % json.dumps(counted, sort_keys=True)
    return _check("inventory", ok, reason)


def _caravan():
    camps = tas_inventory.load_camps(set())
    published = tas_inventory.commercial_published(camps)
    sample = {"name": "Sample Holiday Park", "category": "Campground"}
    tourist = {"name": "Sample Tourist Park", "category": "Campground"}
    plain = {"name": "Sample Campground", "category": "PWS campground"}
    catches = (
        tas_inventory.is_caravan_holiday_or_tourist_park(sample)
        and tas_inventory.is_caravan_holiday_or_tourist_park(tourist)
        and not tas_inventory.is_caravan_holiday_or_tourist_park(plain)
    )
    ok = catches and not published
    reason = "no published caravan, holiday or tourist park"
    if published:
        reason = "published caravan, holiday or tourist park: " + "; ".join(published)
    elif not catches:
        reason = "the park check did not catch a holiday park or a tourist park"
    return _check("caravan_park_keep", ok, reason)


def _alerts():
    path = states.path(states.by_slug("tas"), "alerts_fixture")
    if not path or not os.path.isfile(path):
        return _check("alerts", False, "alert fixture is missing"), {"amber": 0, "closed": 0, "campfire": 0}
    with open(path, encoding="utf-8") as handle:
        fixture = json.load(handle)
    alerts = fixture.get("alerts") or []
    camps = tas_inventory.load_camps(set())
    tas_alerts.apply_alerts(camps, alerts)
    by_name = {camp["name"]: camp for camp in camps}
    stumpys = by_name.get("Stumpys Bay Campground No 1")
    second = by_name.get("Stumpys Bay Campground No 2")
    third = by_name.get("Stumpys Bay Campground No 3")
    ben = by_name.get("Ben Lomond Campground")
    falls = by_name.get("Falls Park Rest Area")
    edgar = by_name.get("Edgar Dam Camping Ground")
    named = all(camp is not None for camp in (stumpys, second, third, ben, falls, edgar))
    rules = named and (
        stumpys["tas_display"] == "closed"
        and second["tas_display"] == "closed"
        and third["tas_display"] == "amber"
        and ben["tas_display"] == "amber"
        and ben["status"] != "closed"
        and falls["tas_display"] == "council"
        and not falls.get("tas_ambers")
        and not falls.get("tas_closures")
        and edgar["tas_display"] == "closed"
        and all("SECRET" not in json.dumps(alert) for alert in alerts)
        and all(set(alert) <= {"headline", "parks", "link"} for alert in alerts)
    )
    tally = tas_alerts.counts(camps)
    ok = rules and tally == {"amber": 84, "closed": 3, "campfire": 103, "council": 11, "published": 189}
    reason = "amber %s, closed %s, campfire note %s" % (tally["amber"], tally["closed"], tally["campfire"])
    if not ok:
        reason = "alert rules failed (" + reason + ")"
    return _check("alerts", ok, reason), tally


def _fire():
    page = tas_fire.html_line({})
    ok = (
        tas_fire.TFS_URL in page
        and tas_fire.TASALERT_URL in page
        and "bom.gov.au" not in page.lower()
        and "no rating" not in page.lower()
    )
    reason = "link out to the Tasmania Fire Service and TasALERT"
    if not ok:
        reason = "fire line is missing a link or includes a rating"
    return _check("fire_linkout", ok, reason)


def _roads():
    state = states.by_slug("tas")
    roads = (state.get("links") or {}).get("roads") or ""
    source = (state.get("sources") or {}).get("roads") or {}
    ok = roads.startswith("https://www.transport.tas.gov.au/") and source.get("ingest") is False and source.get("live_fetch") is False
    reason = "roadworks link only"
    if not ok:
        reason = "roads are not a link out"
    return _check("roads_linkout", ok, reason)


def _signup():
    page = tas_signup.coming_soon_html()
    token = open(os.path.join(ROOT, "functions", "_lib", "token.js"), encoding="utf-8").read()
    confirm = open(os.path.join(ROOT, "functions", "api", "confirm.js"), encoding="utf-8").read()
    unsubscribe = open(os.path.join(ROOT, "functions", "api", "unsubscribe.js"), encoding="utf-8").read()
    ok = (
        tas_signup.COMING_SOON in page
        and "<form" not in page
        and "/api/subscribe" not in page
        and not tas_signup.forms_allowed()
        and '"tas"' in token
        and "env.RESEND_SEGMENT_TAS_ID" not in confirm
        and "env.RESEND_SEGMENT_TAS_ID" not in unsubscribe
        and "RESEND_SEGMENT_TAS_ID" not in confirm
        and "RESEND_SEGMENT_TAS_ID" not in unsubscribe
    )
    reason = "weekly email line, no form, no segment"
    if not ok:
        reason = "signup still has a form or reads a segment"
    return _check("tas_signup", ok, reason)


def _public(dist):
    dist = os.path.abspath(dist)
    home = os.path.join(dist, "index.html")
    tas_dir = os.path.join(dist, "tas")
    if not os.path.isfile(home):
        return _check("public_tas", False, "public build is not in %s" % dist)
    page = open(home, encoding="utf-8").read()
    ok = not os.path.isdir(tas_dir) and 'href="/tas/"' not in page and 'value="tas"' not in page
    reason = "public pages do not include Tasmania"
    if not ok:
        reason = "Tasmania is in the public build"
    return _check("public_tas", ok, reason)


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
    root = os.path.join(os.path.abspath(preview), "tas")
    if not os.path.isdir(root):
        return _check("tas_pages", False, "Tasmania pages are not at %s" % root)
    missing_line, missing_credit, forms, wording, pages = [], [], [], [], 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, root)
            if tas_signup.COMING_SOON not in text or "<form" in text and 'action="/api/subscribe"' in text:
                if tas_signup.COMING_SOON not in text:
                    missing_line.append(rel)
                if 'action="/api/subscribe"' in text:
                    forms.append(rel)
            if tas_inventory.LIST_CREDIT not in text:
                missing_credit.append(rel)
            bad = _wording(text)
            if bad:
                wording.append("%s (%s)" % (rel, ", ".join(bad)))
    ok = pages > 0 and not missing_line and not missing_credit and not forms and not wording
    reason = "%s Tasmania pages, signup line, attribution, no subscribe form" % pages
    if not ok:
        reason = "pages missing a line, a credit, or showing a form or internal wording: " + "; ".join((missing_line + forms + missing_credit + wording)[:8])
    return _check("tas_pages", ok, reason)


def evaluate(dist, preview=None):
    alerts, tally = _alerts()
    checks = [
        _inventory(),
        _caravan(),
        alerts,
        _fire(),
        _roads(),
        _signup(),
        _public(dist),
    ]
    if preview:
        checks.append(_pages(preview))
    return {
        "pass": all(item["pass"] for item in checks),
        "published": 189,
        "alerts": tally,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="Tasmania launch gate")
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--preview", default="")
    args = parser.parse_args()
    report = evaluate(args.dist, args.preview or None)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
