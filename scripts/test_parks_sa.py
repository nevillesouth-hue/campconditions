#!/usr/bin/env python3
"""Parks SA closures reader. Fixtures only: this file does not use the network."""
import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.chdir(ROOT)

import act_sa_notices
import parks_sa
import sa_inventory

FAILURES = []
CHECKS = 0
FIXTURE = os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "parks-sa-closures.html")
EMPTY = os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "parks-sa-closures-empty.html")
BROKEN = os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "parks-sa-closures-broken.html")
SAMPLE = os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "parks-sa-closures-sample.html")
ADELAIDE = parks_sa.ADELAIDE


def expect(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(label)


def at(year, month, day, hour, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=ADELAIDE)


def bookings_at(live_rows, moment):
    notices = act_sa_notices.load_notices(os.path.join(ROOT, "data", "act-sa", "fixtures", "sa-notices.json"))
    current = parks_sa.catalogue_for(notices, live_rows)
    scored = act_sa_notices.evaluate_all(current, moment)
    parks_sa.adjust_scores(scored, current)
    return scored["bookings"], current


def main():
    page = open(FIXTURE, encoding="utf-8").read()
    moment = at(2026, 11, 18, 10, 0)
    parsed = parks_sa.parse_html(page, moment)
    expect(len(parsed) == 51, "the closures page lists 51 notices")
    raw = json.dumps(parsed)
    expect("sand covering" not in raw and "<img" not in raw and "img src" not in raw, "body text and photos are not stored")
    expect(all(set(row) <= parks_sa.STORED_FIELDS for row in parsed), "stored fields are title, park, window and link")
    expect(all(row["title"] and row["park"] and row["link"].startswith("https://") and "?" not in row["link"] for row in parsed), "each notice has a title, park and link")
    expect("park-closure-descriptions" not in raw, "the help anchor is not a notice")
    by_link = {row["link"].rstrip("/").split("/")[-1]: row for row in parsed}
    mambray = by_link["mount-remarkable-national-park-15"]
    expect(mambray["start"] == "2026-11-15T18:00:00+10:30" and mambray["end"] == "2026-11-20T14:00:00+10:30", "mambray window is 6pm 15 Nov until 2pm 20 Nov")
    box = by_link["ngarkat-conservation-park-15"]
    expect(box["start"] == "2026-11-11T06:00:00+10:30" and box["end"] == "2026-11-18T06:00:00+10:30", "box flat window ends 6am 18 Nov")
    expect("vulkathunha-gammon-ranges-national-park-23" not in by_link, "the grindells notice is no longer listed")
    expect(by_link["171231-vivonne-bay-conservation-park"]["start"] == "", "an annual notice keeps its reviewed recurrence")
    expect(parks_sa.parse_html(open(EMPTY, encoding="utf-8").read(), moment) == [], "an empty listing parses as no notices")
    expect(parks_sa.parse_html(open(BROKEN, encoding="utf-8").read(), moment) == [], "a broken page parses as no notices")

    during, _current = bookings_at(parsed, moment)
    pines = by_link["ngarkat-conservation-park-16"]
    expect(not pines.get("camp_ids"), "the pines and the gums are held, so the notice does not attach them")
    expect("73212" in parks_sa.held_booking_ids() and "73213" in parks_sa.held_booking_ids() and "73195" in parks_sa.held_booking_ids(), "ngarkat pines and gums, and danggali, have no coordinates")
    expect(pines["start"].startswith("2026-11-01") and pines["end"].startswith("2027-04-01"), "the seasonal window is outside 1 April to 31 October")
    expect(by_link["morialta-conservation-park-53"].get("camp_ids") is None, "a morialta walk and track closure names no campground")
    expect(by_link["blackwood-forest-recreation-park"].get("camp_ids") is None, "a blackwood plantation closure names no campground")
    chowilla = by_link["chowilla-regional-reserve-and-danggali-conservation-park-and-wilderness-protection-area"]
    expect(chowilla.get("camp_ids") is None and chowilla["start"].startswith("2026-11-20") and chowilla["end"].startswith("2026-11-27"), "chowilla and danggali pest closure is 20 to 26 Nov and names no campground")
    expect(during.get("67320") == "closed" and during.get("69837") == "closed", "mambray and baroota are closed during the window")
    expect(during.get("73212") != "closed" and during.get("73213") != "closed", "the pines and the gums stay held")
    expect(during.get("73195") != "closed", "danggali stays held")
    expect(during.get("71627") is None, "little dip's gums is not the ngarkat gums")
    published_ids = {
        item
        for camp in sa_inventory.load_camps(set(), moment=moment, live_notices=parsed)
        for item in camp.get("booking_ids") or []
    }
    expect("73212" not in published_ids and "73213" not in published_ids and "73195" not in published_ids, "held ngarkat and danggali camps are not published")
    expect(during.get("73218") == "expired_not_open", "box flat is not closed after 6am on 18 Nov")
    expect(during.get("73157") is None, "grindells is not closed once its notice leaves the page")
    expect(during.get("67710") is None and during.get("72075") is None, "aroona and acraman traps stay off the wrong parks")
    expect(during.get("90928") == "not_in_window", "wirra is not closed at 10am on a Wednesday")
    night, _current = bookings_at(parsed, at(2026, 11, 18, 18, 30))
    expect(night.get("90928") == "closed" and night.get("143123") == "closed", "wirra closes at 6pm on Wednesday")
    before_end, _current = bookings_at(parsed, at(2026, 11, 17, 12, 0))
    expect(before_end.get("73218") == "closed", "box flat is closed on 17 Nov")
    ended, _current = bookings_at(parsed, at(2026, 11, 20, 14, 0))
    expect(ended.get("67320") == "expired_not_open", "mambray is not closed once the window ends")
    road = next(row for row in _current if str(row.get("source_url") or "").endswith("brownhill-creek-recreation-park-2"))
    road_score = act_sa_notices.evaluate(road, moment)
    expect(road_score["camp_status"] == "not_a_camp_closure" and road_score["booking_ids"] == [], "a road closure does not close a campground")

    sample = parks_sa.parse_html(open(SAMPLE, encoding="utf-8").read(), moment)
    by_sample = {row["link"].split("/")[-1]: row for row in sample}
    expect(by_sample["sample-trail"].get("camp_ids") is None, "a walking trail is not a campground closure")
    expect(by_sample["sample-mambray"]["camp_ids"] == ["67320"], "a named campground maps to its booking id")
    expect(by_sample["sample-aroona"].get("camp_ids") is None, "aroona sanctuary does not take the ikara booking id")
    named, _rows = bookings_at(sample, at(2026, 12, 1, 10, 0))
    expect(named.get("67320") == "closed", "the named campground is closed inside its window")
    outside, _rows = bookings_at(sample, at(2026, 11, 18, 10, 0))
    expect(outside.get("67320") != "closed", "the named campground is not closed before its window")
    expect(outside.get("67710") is None, "the trap booking is not closed")

    expect(parks_sa.allowed_url(parks_sa.CLOSURES_URL), "the closures path is allowed")
    expect(not parks_sa.allowed_url(parks_sa.CLOSURES_URL + "?page=2"), "a query string is refused")
    expect(not parks_sa.allowed_url("https://www.parks.sa.gov.au/cpresources/secret"), "a disallowed path is refused")

    calls = []

    def fetch(url, timeout, user_agent):
        calls.append((url, timeout, user_agent))
        return 200, page

    cache = tempfile.mkdtemp(prefix="parks-sa-")
    fresh = parks_sa.load_for_build(cache, now=moment, fetch=fetch)
    expect(len(calls) == 1 and "?" not in calls[0][0] and calls[0][0] == parks_sa.CLOSURES_URL, "one request and no query string")
    expect(calls[0][1] == 20 and "CampConditions.au" in calls[0][2] and "campconditions@outlook.com" in calls[0][2], "20s timeout and the CampConditions user agent")
    expect(fresh["ok"] is True and fresh["fallback"] is False and len(fresh["notices"]) == 51, "a good page is stored")
    expect(fresh["fetched"] == moment.isoformat(), "fetched is the time of this read")
    saved = open(parks_sa.last_good_path(cache), encoding="utf-8").read()
    expect("sand covering" not in saved and "<img" not in saved, "the last good copy has no body or photo")

    def failed(url, timeout, user_agent):
        calls.append((url, timeout, user_agent))
        raise TimeoutError("timed out")

    again = parks_sa.load_for_build(cache, now=at(2026, 11, 18, 11, 0), fetch=failed)
    expect(again["ok"] is False and again["fallback"] is True and again["fetched"] == moment.isoformat(), "a timeout keeps the last good fetched time")
    expect(again["notices"] == fresh["notices"] and again["use_snapshot"] is False, "a timeout keeps the last good notices")
    expect(json.load(open(parks_sa.last_good_path(cache), encoding="utf-8"))["fetched"] == moment.isoformat(), "the last good file is not rewritten")

    def empty(url, timeout, user_agent):
        calls.append((url, timeout, user_agent))
        return 200, open(EMPTY, encoding="utf-8").read()

    before = open(parks_sa.last_good_path(cache), encoding="utf-8").read()
    changed = parks_sa.load_for_build(cache, now=at(2026, 11, 18, 12, 0), fetch=empty)
    expect(changed["ok"] is False and changed["reason"] == "structure change", "zero notices after a full page is a structure change")
    expect(open(parks_sa.last_good_path(cache), encoding="utf-8").read() == before, "a structure change does not replace the last good file")
    expect(changed["fetched"] == moment.isoformat(), "a structure change keeps the old fetched time")

    def denied(url, timeout, user_agent):
        calls.append((url, timeout, user_agent))
        return 503, ""

    denied_result = parks_sa.load_for_build(cache, now=at(2026, 11, 18, 13, 0), fetch=denied)
    expect(denied_result["ok"] is False and denied_result["reason"] == "http 503" and denied_result["fetched"] == moment.isoformat(), "a non-200 keeps the last good copy")

    def slow(url, timeout, user_agent):
        calls.append((url, timeout, user_agent))
        return 200, page

    ticks = iter([0, 61])

    def clock():
        return next(ticks)

    before_calls = len(calls)
    limited = parks_sa.load_for_build(cache, now=moment, fetch=slow, clock=clock, step_limit=60)
    expect(len(calls) == before_calls and limited["ok"] is False and limited["reason"] == "step limit", "the step limit does not start the request")
    expect(limited["fetched"] == moment.isoformat() and limited["fallback"] is True, "the step limit keeps the last good copy")

    def pages(url, timeout, user_agent):
        calls.append(url)
        return 200, page + '<a rel="next" href="https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts?page=2">Next</a>'

    paged = parks_sa.read_index(pages, now=moment)
    expect(paged["ok"] is False and paged["reason"] == "paginated" and len(calls) == before_calls + 1, "a paginated page is reported and not followed")

    copy = parks_sa.checked_copy(parks_sa.stamp(fresh), moment)
    expect(copy and copy["line"].startswith("Parks SA closures checked ") and copy["stale"] is False, "a fresh read is shown as checked")
    old = parks_sa.checked_copy(parks_sa.stamp(again), at(2026, 11, 21, 12, 0))
    expect(old and old["stale"] is True and "more than 2 days old" in old["warning"], "a check older than two days is stale")

    if FAILURES:
        print("%s checks, %s failed" % (CHECKS, len(FAILURES)))
        for item in FAILURES:
            print("FAIL", item)
        return 1
    print("%s checks passed" % CHECKS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
