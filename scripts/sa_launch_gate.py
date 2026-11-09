#!/usr/bin/env python3
"""One pass/fail gate for a South Australia launch. It does not enable the state.

fire_licence_resolved stays false, so the gate fails until that conflict is
resolved. The script does not send mail or create a Resend segment.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sa_digest
import sa_fire
import sa_inventory
import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADELAIDE = ZoneInfo("Australia/Adelaide")
FIRE_LICENCE_RESOLVED = False
NOTICE_FRESH = dt.timedelta(hours=48)
ATTRIBUTION = sa_inventory.ATTRIBUTION
OSM_MARK = "OpenStreetMap contributors (ODbL)"


def _check(name, ok, reason):
    return {"check": name, "pass": bool(ok), "reason": reason}


def _inventory():
    camps = sa_inventory.load_camps(set())
    counted = sa_inventory.summary(camps)
    needs = [camp["name"] for camp in camps if camp.get("needs_review")]
    ok = (
        counted["published"] == 268
        and counted["official_confident"] == 73
        and counted["official_approximate"] == 7
        and counted["eligible_osm"] == 34
        and counted["council"] == 43
        and counted["tourism"] == 22
        and counted["operator"] == 89
        and counted["duplicates_dropped"] == 1
        and len(needs) == 0
    )
    reason = (
        "268 camps: 73 Parks SA with confident coordinates, 7 Parks SA approximate "
        "(parks_sa_streetview_link), 34 from the earlier operator pass, 43 council, "
        "22 tourism, 89 operator. The three commercial parks inside reserves are operator "
        "camps, and Brownhill Creek's point is approximate. 1 duplicate dropped "
        "(Mount Gambier Central, east side). Pondalowie and Ippinitchie stay held. Needs a check: 0."
    )
    if not ok:
        reason = "expected 268 camps and no needs-check rows, found %s and %s (%s)" % (counted["published"], len(needs), "; ".join(needs))
    return _check("inventory", ok, reason), camps


def _notices(now):
    path = states.path(states.by_slug("sa"), "notices")
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    moment = dt.datetime.fromisoformat(doc["as_of_adelaide"])
    age = now.astimezone(moment.tzinfo) - moment
    ok = dt.timedelta(0) <= age <= NOTICE_FRESH
    reason = "notice windows scored at %s (%s hours ago)" % (moment.isoformat(), round(age.total_seconds() / 3600, 1))
    if not ok:
        reason += "; older than 48 hours" if age > NOTICE_FRESH else "; timestamp is in the future"
    return _check("notice_parser_freshness", ok, reason)


def _fire(now):
    sample = os.path.join(ROOT, "data", "act-sa", "fixtures", "fire", "cfs-sample.xml")
    with open(sample, "rb") as handle:
        parsed = sa_fire.parse_feed(handle.read())
    fresh = sa_fire.fresh(parsed.get("updated"), now)
    fresh_reason = "sample CFS feed updated %s" % (parsed.get("updated").isoformat() if parsed.get("updated") else "missing")
    if not parsed.get("ok"):
        fresh = False
        fresh_reason = "CFS sample did not parse"
    elif not fresh:
        fresh_reason += "; older than 36 hours or not yet valid"
    licence = _check(
        "fire_licence_resolved",
        FIRE_LICENCE_RESOLVED,
        "false. The data.sa.gov.au page and the zip licence file disagree, so the district geometry stays unpublished.",
    )
    return _check("fire_feed_freshness", fresh, fresh_reason), licence


def _digest():
    dest = tempfile.mkdtemp(prefix="sa-digest-gate-")
    camps = sa_inventory.load_camps(set())
    try:
        meta = sa_digest.write_preview(dest, camps, dt.datetime.now(ADELAIDE))
    except SystemExit as exc:
        return _check("digest_preview", False, str(exc))
    html_path = os.path.join(dest, "digest.html")
    text = open(html_path, encoding="utf-8").read()
    needed = ("Closed", "Partial", "Upcoming", "Reopened", "Fire danger and Total Fire Ban", "Chip in", CFS_FOOTER)
    missing = [item for item in needed if item not in text]
    ok = not missing and meta.get("send") is False and "{{{EMAIL}}}" not in text and not meta.get("called_resend")
    reason = "local digest rendered with send false" if ok else "missing " + ", ".join(missing or ["send flag"])
    return _check("digest_preview", ok, reason)


CFS_FOOTER = "Fire danger: SA Country Fire Service (cfs.sa.gov.au)"


def _public(dist):
    dist = os.path.abspath(dist)
    home = os.path.join(dist, "index.html")
    sa_dir = os.path.join(dist, "sa")
    if not os.path.isfile(home):
        return _check("public_build_without_sa", False, "public build is not in %s" % dist)
    page = open(home, encoding="utf-8").read()
    offered = ('value="vic"' in page and 'value="nsw"' in page and 'value="qld"' in page)
    hidden = 'value="sa"' not in page and not os.path.isdir(sa_dir)
    ok = offered and hidden
    reason = "homepage offers VIC, NSW and QLD only, and dist/sa is absent" if ok else "SA is visible in the public build or a public state checkbox is missing"
    return _check("public_build_without_sa", ok, reason)


def _links(preview):
    root = os.path.abspath(preview)
    sa_root = os.path.join(root, "sa")
    if not os.path.isdir(sa_root):
        return _check("sa_preview_links", False, "SA preview is not at %s" % sa_root)
    broken = []
    pages = 0
    for dirpath, _dirs, files in os.walk(sa_root):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            for href in re.findall(r'href="([^"]*)"', text):
                if not href.startswith("/") or href.startswith("//"):
                    continue
                target = href.split("?", 1)[0].split("#", 1)[0]
                if target in ("", "/"):
                    disk = os.path.join(root, "index.html")
                elif target.endswith("/"):
                    disk = os.path.join(root, target.strip("/"), "index.html")
                else:
                    disk = os.path.join(root, target.lstrip("/"))
                if not os.path.isfile(disk):
                    broken.append("%s -> %s" % (os.path.relpath(path, root), href))
                    if len(broken) >= 8:
                        break
            if len(broken) >= 8:
                break
    ok = pages > 0 and not broken
    reason = "%s SA pages, 0 broken internal links" % pages if ok else "broken: " + "; ".join(broken[:8])
    return _check("sa_preview_links", ok, reason)


def _attribution(preview):
    root = os.path.join(os.path.abspath(preview), "sa")
    if not os.path.isdir(root):
        return _check("sa_attribution", False, "SA preview is not at %s" % root)
    missing = []
    pages = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            text = open(os.path.join(dirpath, name), encoding="utf-8").read()
            if ATTRIBUTION not in text and OSM_MARK not in text:
                missing.append(os.path.relpath(os.path.join(dirpath, name), root))
    ok = pages > 0 and not missing
    reason = "attribution on %s SA pages" % pages if ok else "missing attribution: " + ", ".join(missing[:8])
    return _check("sa_attribution", ok, reason)


def evaluate(dist, preview, now=None):
    now = now or dt.datetime.now(ADELAIDE)
    inventory, _camps = _inventory()
    fresh, licence = _fire(now)
    checks = [
        inventory,
        _notices(now),
        fresh,
        licence,
        _digest(),
        _public(dist),
        _links(preview),
        _attribution(preview),
    ]
    return {
        "pass": all(item["pass"] for item in checks),
        "fire_licence_resolved": FIRE_LICENCE_RESOLVED,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="South Australia launch gate")
    parser.add_argument("--dist", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--preview", default="/tmp/sa-preview")
    args = parser.parse_args()
    report = evaluate(args.dist, args.preview)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
