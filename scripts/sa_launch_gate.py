#!/usr/bin/env python3
"""One pass/fail gate for a South Australia launch. It does not enable the state.

SA_FIRE_MODE=full still fails the fire check because the district licence
conflicts. SA_FIRE_MODE=linkout passes that check without downloading the
dataset or the rating feed. The script does not send mail or create a segment.
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
import sa_signup
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
    before = counted.get("before_park_decisions") or {}
    excluded = counted.get("park_excluded") or []
    held = counted.get("park_held") or []
    kept = counted.get("park_kept") or []
    kept_ids = {row.get("osm_id") for row in kept}
    unpublished = sa_inventory.published_parks_without_keep(camps, kept_ids)
    ok = (
        before.get("published") == 265
        and counted["published"] == 160
        and counted["official_confident"] == 73
        and counted["official_approximate"] == 7
        and counted["eligible_osm"] == 13
        and counted["council"] == 40
        and counted["tourism"] == 5
        and counted["operator"] == 22
        and counted["duplicates_dropped"] == 1
        and len(counted.get("commercial_excluded") or []) == 3
        and len(excluded) == 86
        and len(held) == 19
        and len(kept) == 21
        and all(row.get("decision") == "exclude" and row.get("reason") for row in excluded)
        and all(row.get("decision") == "hold" and row.get("reason") for row in held)
        and not unpublished
        and len(needs) == 0
    )
    reason = (
        "160 camps, down from 265. 73 Parks SA with confident coordinates, 7 Parks SA approximate "
        "(parks_sa_streetview_link), 13 from the earlier operator pass, 40 council, "
        "5 tourism, 22 operator. 86 commercial caravan, holiday and tourist parks are excluded "
        "and 19 are held. 21 council, community and showground parks stay. "
        "1 duplicate dropped (Mount Gambier Central, east side). Pondalowie and Ippinitchie stay out. Needs a check: 0."
    )
    if not ok:
        reason = "expected 160 camps and no needs-check camps, found %s and %s (%s)" % (counted["published"], len(needs), "; ".join(needs + unpublished))
    return _check("inventory", ok, reason), camps


def _caravan_parks():
    camps = sa_inventory.load_camps(set())
    counted = sa_inventory.summary(camps)
    kept_ids = {row.get("osm_id") for row in counted.get("park_kept") or []}
    missing = sa_inventory.published_parks_without_keep(camps, kept_ids)
    sample = {"name": "Sample Holiday Park", "category": "Campground", "osm_id": "way/sample"}
    catches_sample = sa_inventory.published_parks_without_keep([sample], set()) == ["Sample Holiday Park"]
    adare = next((row for row in counted.get("park_excluded") or [] if row.get("name") == "Adare Caravan Park"), None)
    showground = next((row for row in counted.get("park_kept") or [] if "Showground" in (row.get("name") or "")), None)
    ok = catches_sample and not missing and adare and adare.get("decision") == "exclude" and showground and showground.get("decision") == "keep"
    reason = "every published caravan, holiday or tourist park has a keep decision"
    if missing:
        reason = "published without a keep decision: " + "; ".join(missing)
    elif not catches_sample:
        reason = "the park check did not catch a holiday park with no keep decision"
    elif not adare or not showground:
        reason = "Adare must be excluded and Adelaide Showground must stay"
    return _check("caravan_park_keep", ok, reason)


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


def _fire_pages(preview):
    root = os.path.join(os.path.abspath(preview), "sa")
    if not os.path.isdir(root):
        return False, "SA preview is not at %s" % root
    missing = []
    rated = []
    pages = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".html"):
                continue
            pages += 1
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, root)
            if 'class="muted fire-line fire-sa"' in text or "No Rating" in text or "No rating" in text:
                rated.append(rel)
            if "data.eso.sa.gov.au" in text or "FireBanDistricts" in text:
                rated.append(rel)
            camp_page = f"{os.sep}camp{os.sep}" in path
            if camp_page and (sa_fire.LINKOUT_LINE not in text or sa_fire.CATASTROPHIC_LINE not in text or sa_fire.CFS_PAGE not in text):
                missing.append(rel)
    if not pages:
        return False, "SA preview has no pages"
    if rated or missing:
        return False, "linkout pages still show a rating or omit the CFS line: " + ", ".join((rated + missing)[:8])
    return True, "linkout shows the CFS ratings link and the Parks SA catastrophic line, with no district and no rating"


def _fire(now, preview):
    if sa_fire.mode() == "linkout":
        ok, reason = _fire_pages(preview)
        fresh = _check("fire_feed_freshness", ok, "SA_FIRE_MODE=linkout does not download the CFS rating feed. " + reason)
        licence = _check(
            "fire_licence_resolved",
            ok,
            "SA_FIRE_MODE=linkout does not download or use the SA Fire Ban Districts dataset. The licence conflict remains for SA_FIRE_MODE=full. " + reason,
        )
        return fresh, licence
    sample = os.path.join(ROOT, "data", "act-sa", "fixtures", "fire", "cfs-sample.xml")
    with open(sample, "rb") as handle:
        parsed = sa_fire.parse_feed(handle.read())
    fresh = sa_fire.fresh(parsed.get("updated"), now)
    fresh_reason = "SA_FIRE_MODE=full. Sample CFS feed updated %s" % (parsed.get("updated").isoformat() if parsed.get("updated") else "missing")
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


def _signup(preview):
    chosen = sa_signup.mode()
    root = os.path.join(os.path.abspath(preview), "sa")
    forms = []
    quiet = []
    pages = 0
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".html"):
                    continue
                pages += 1
                path = os.path.join(dirpath, name)
                text = open(path, encoding="utf-8").read()
                rel = os.path.relpath(path, root)
                if 'action="/api/subscribe"' in text or 'name="reopen_alert"' in text or 'class="signup inline-signup"' in text:
                    forms.append(rel)
                if sa_signup.COMING_SOON not in text:
                    quiet.append(rel)
    if chosen != "coming_soon":
        return _check("sa_signup", False, "SA_SIGNUP_MODE=%s but no Resend SA segment is set, so signup stays closed" % chosen)
    ok = pages > 0 and not forms and not quiet
    reason = "SA_SIGNUP_MODE=coming_soon. No Resend SA segment, no SA subscribe form and no reopen box. Pages say the weekly email is coming soon."
    if forms:
        reason = "SA pages still contain a signup or reopen form: " + ", ".join(forms[:8])
    elif quiet:
        reason = "SA pages omit the coming soon line: " + ", ".join(quiet[:8])
    elif not pages:
        reason = "SA preview has no pages to check for signup"
    return _check("sa_signup", ok, reason)


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
    act_dir = os.path.join(dist, "act")
    if not os.path.isfile(home):
        return _check("public_sa", False, "public build is not in %s" % dist)
    page = open(home, encoding="utf-8").read()
    offered = ('value="vic"' in page and 'value="nsw"' in page and 'value="qld"' in page)
    listed = 'href="/sa/"' in page and "South Australia" in page and os.path.isdir(sa_dir)
    signup_off = 'value="sa"' not in page and 'value="act"' not in page
    act_off = not os.path.isdir(act_dir) and "Australian Capital Territory" not in page
    ok = offered and listed and signup_off and act_off
    reason = "homepage lists South Australia, the signup form does not offer SA, and ACT is absent"
    if not ok:
        reason = "SA is missing from the public build, the signup form offers SA, or ACT is public"
    return _check("public_sa", ok, reason)


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
    fresh, licence = _fire(now, preview)
    checks = [
        inventory,
        _notices(now),
        fresh,
        licence,
        _caravan_parks(),
        _signup(preview),
        _digest(),
        _public(dist),
        _links(preview),
        _attribution(preview),
    ]
    return {
        "pass": all(item["pass"] for item in checks),
        "sa_fire_mode": sa_fire.mode(),
        "sa_signup_mode": sa_signup.mode(),
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
