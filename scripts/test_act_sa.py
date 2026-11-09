#!/usr/bin/env python3
"""Regressions for the disabled ACT and SA foundations.

Runs without a site build. When dist/status.json exists, also checks that the
public digest and homepage still omit ACT and SA.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.chdir(ROOT)

import act_sa_eligibility
import act_sa_fixtures
import act_sa_html
import act_sa_notices
import act_sa_status as status
import states

ADELAIDE = ZoneInfo("Australia/Adelaide")
FAILURES = []
CHECKS = 0


def expect(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(label)


def at(year, month, day, hour, minute, zone=ADELAIDE):
    return dt.datetime(year, month, day, hour, minute, tzinfo=zone)


def camp(doc, ident):
    return next(row for row in doc["records"] if row["id"] == ident)


def one(rows, ident):
    return next(row for row in rows if row["camp_id"] == ident)


def main():
    doc = status.load_candidates()
    alerts = status.load_alerts()
    summary = status.summarise_inventory(doc)
    moment = dt.datetime(2026, 11, 11, 7, 30, tzinfo=dt.timezone.utc)
    selectable = status.selectable_camps(doc["records"])
    statuses = status.apply_alerts(selectable, alerts, moment)
    examples = status.apply_alerts(
        [row for row in doc["records"] if row.get("inventory_role") == "fixture_only"],
        alerts,
        moment,
    )

    expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld"], "enabled states")
    for slug in ("vic", "nsw", "qld"):
        state = states.by_slug(slug)
        expect(state.get("enabled") is True, slug + " enabled")
        expect(states.public_build_allowed(state) is True, slug + " public build")
        expect(states.digest_allowed(state) is True, slug + " digest")
        expect(states.signup_allowed(state) is True, slug + " signup")
        expect("release" not in state, slug + " has no hold block")

    saved = os.environ.get("CAMPCONDITIONS_ENABLE")
    try:
        os.environ["CAMPCONDITIONS_ENABLE"] = "act,sa"
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld"], "env cannot enable held states")
        os.environ["CAMPCONDITIONS_ENABLE"] = "nsw"
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld"], "existing preview env")
    finally:
        if saved is None:
            os.environ.pop("CAMPCONDITIONS_ENABLE", None)
        else:
            os.environ["CAMPCONDITIONS_ENABLE"] = saved

    act = states.by_slug("act")
    sa = states.by_slug("sa")
    expect(act.get("enabled") is False and sa.get("enabled") is False, "config flags stay false")
    expect(states.public_build_allowed(act) is False and states.digest_allowed(act) is False, "act held")
    expect(states.signup_allowed(sa) is False and states.public_build_allowed(sa) is False, "sa held")
    opened = dict(act)
    opened["enabled"] = True
    opened["release"] = dict(act["release"])
    opened["release"]["public"] = True
    opened["release"]["digest"] = True
    opened["release"]["signup"] = True
    expect(states.public_build_allowed(opened) is False, "open flags without gates")
    opened["release"]["gates"] = []
    expect(states.gates_pass(opened) is False, "empty gate list fails")
    expect(all(gate.get("ok") is False for gate in act["release"]["gates"]), "act gates closed")
    expect(all(gate.get("ok") is False for gate in sa["release"]["gates"]), "sa gates closed")
    expect(act["licence"]["status"] == "unresolved", "act licence unresolved")
    expect(sa["licence"]["current_site"] == "CC BY 3.0 AU", "sa site licence")
    expect(sa["licence"]["legacy_dataset"] == "CC BY 4.0", "sa legacy licence")
    expect(sa["licence"]["current_site"] != sa["licence"]["legacy_dataset"], "licences stay distinct")
    expect(sa["licence"]["osm"] == "ODbL", "osm licence")
    expect(sa["licence"]["photos"] is False and sa["licence"]["booking_prose"] is False, "no photos or booking prose")
    expect(act["fire"]["borrow_nsw_rfs"] is False and sa["fire"]["tfb_equals_park_closure"] is False, "fire flags")
    expect(not status.contains_no_rating(act["fire"]) and not status.contains_no_rating(sa["fire"]), "fire config wording")
    expect(act["sources"]["parks_act_stays"]["live_fetch"] is False, "act not fetched")
    expect(sa["sources"]["sitemap_index"]["live_fetch"] is False, "sa not fetched")

    expect(summary["act_headings"] == 10, "act headings")
    expect(summary["act_camp_candidates"] == 8, "act candidates")
    expect(summary["act_excluded_ids"] == ["act:nil-desperandum", "act:ready-cut-cottage"], "excluded stays")
    expect(summary["act_statewide"] is False and summary["act_audited"] is False, "act not a census")
    expect(summary["sa_pilot_ids"] == ["sa:pink-gum", "sa:wirra", "sa:stringybark"], "sa pilot ids")
    expect(summary["sa_statewide"] is False, "sa not statewide")
    expect("act:woods-reserve" in summary["act_camp_ids"], "woods kept")
    expect(camp(doc, "sa:helipad").get("alias_of") is None, "helipad is not wirra")
    expect(camp(doc, "act:northern-border")["access"]["vehicle"] is False, "northern border no vehicles")
    expect(camp(doc, "act:northern-border")["jurisdiction"] == "act", "northern border stays act")
    expect(camp(doc, "sa:pink-gum")["geometry"] is None, "pink gum geometry withheld")
    expect(camp(doc, "act:cotter")["geometry"] is None, "cotter point not republished")
    expect(camp(doc, "act:cotter")["official_geometry_test_executed"] is False, "no official coordinate test")

    legacy = status.load_legacy()
    expect(legacy["reported_record_count"] == 127, "legacy count recorded")
    expect(len(legacy["records"]) != 127, "fixture is not the full 2017 file")
    expect(status.campgrounds_from_legacy(legacy) == [], "legacy yields no camps")
    expect(status.excluded_ids_from_legacy(legacy, summary["sa_pilot_ids"]) == [], "flags do not drop camps")
    aliases = status.legacy_alias_candidates(legacy)
    expect(all(row["camping_flags_applied"] is False and row["auto_merge"] is False for row in aliases), "legacy aliases only")
    expect(status.campground_count_from_discovery(doc["discovery_observations"]) is None, "discovery is not a count")
    expect(doc["discovery_observations"]["campground_count"] is None, "stored count empty")
    expect(doc["discovery_observations"]["booking_page_urls"] == 320, "booking urls stay urls")
    sitemap = status.direct_url_locs(status.load_sitemap_xml())
    expect(sitemap["ok"] is True and sitemap["page_url_count"] == 2, "sitemap ignores image loc")
    expect(all("example.jpg" not in loc for loc in sitemap["locs"]), "image url excluded")
    expect(sitemap["campground_count"] is None, "sitemap count is not camps")
    expect(status.direct_url_locs("<not xml")["malformed"] is True, "bad sitemap")

    osm = status.osm_campgrounds(status.load_osm()["elements"])
    expect(osm["campground_count"] == 2, "two osm camps")
    expect(osm["pitch_promoted"] == 0 and osm["orphan_pitches"] == 0, "pitches not promoted")
    pink_osm = next(row for row in osm["campgrounds"] if row["osm_id"] == 1192258723)
    expect(pink_osm["pitch_count"] == 11 and pink_osm["counts_as"] == 1, "eleven pitches one camp")
    merged = status.merge_official_osm(
        [camp(doc, "act:cotter"), camp(doc, "sa:pink-gum")],
        osm["campgrounds"],
        doc["crosswalk"],
    )
    expect(merged["public_count"] == 2 and merged["extra_unmerged"] == [], "reviewed osm ids do not duplicate")
    track = [{"osm_type": "way", "osm_id": 999, "name": "Pink Gum Track"}]
    unmerged = status.merge_official_osm([camp(doc, "sa:pink-gum")], osm["campgrounds"] + track, doc["crosswalk"])
    expect(unmerged["public_count"] == 1, "track does not merge")
    expect(any(row.get("osm_id") == 999 for row in unmerged["extra_unmerged"]), "track stays separate")
    expect(status.match_camp("woods-reserve", doc["records"])["unresolved"] is False, "woods slug")
    expect(status.match_camp("woods-reserve-renamed", doc["records"])["guessed"] is False, "renamed slug not guessed")
    expect(status.match_camp("woods-reserve-renamed", doc["records"])["camp"] is None, "renamed slug unresolved")
    expect(status.match_camp("Centenary Trail Northern Border Campground", doc["records"])["camp"]["id"] == "act:northern-border", "reviewed alias")

    woods = one(statuses, "act:woods-reserve")
    expect(woods["status"] == "closed" and woods["closed"] is True and woods["open_claim"] is False, "woods closed")
    expect(woods["reopen_at"] is None and woods["expected_note"] == "early 2027", "early 2027 is not a date")
    expect(woods["date_inferred"] is False and woods["generic_overrode"] is False, "generic text loses")
    later = status.apply_alerts([camp(doc, "act:woods-reserve")], alerts, at(2027, 1, 1, 9, 0, ZoneInfo("Australia/Canberra")))
    expect(later[0]["status"] == "closed" and later[0]["reopen_at"] is None, "no new year reopen")
    forged = dict(next(row for row in alerts if row["id"] == "act-woods-closed"))
    forged["reopen_at"] = "2027-01-01"
    forged["reopen_at_source"] = "expected_wording"
    parsed = status.normalise_alert(forged)
    expect(parsed["ok"] is True and parsed["alert"]["reopen_at"] is None, "forged reopen dropped")
    expect(one(statuses, "act:cotter")["status"] != "closed", "cotter not closed by climbing or platform")
    deduped = status.dedupe_notices([status.normalise_alert(row)["alert"] for row in alerts if row.get("content_hash") == "act-red-rocks"])
    expect(len(deduped) == 1 and deduped[0]["merged_count"] == 2, "red rocks deduped")
    expect(sorted(deduped[0]["listing_contexts"]) == ["Canberra Nature Park", "Kambah Pool", "Murrumbidgee River Corridor", "The Pinnacle"], "contexts kept")

    pink = one(statuses, "sa:pink-gum")
    expect(pink["status"] == "unknown" and pink["closed"] is False and pink["open_claim"] is False, "pink gum unknown")
    expect(pink["available"] is None and pink["all_day"] is False and pink["all_day_inferred"] is False, "not all-day or available")
    expect(len(pink.get("intervals") or []) == 2, "overnight intervals kept")
    expect(all(status.window_is_all_day(interval) is False for interval in pink["intervals"]), "intervals are overnight")
    daytime = status.apply_alerts([camp(doc, "sa:pink-gum")], alerts, at(2026, 11, 9, 12, 0))
    expect(daytime[0]["status"] == "unknown" and daytime[0]["closed"] is False, "daytime not closed all day")

    def wirra(when):
        return status.apply_alerts([camp(doc, "sa:wirra")], alerts, when)[0]

    active = wirra(at(2026, 11, 11, 18, 0))
    expect(active["status"] == "closed" and active["all_day"] is False, "wirra wednesday evening")
    expect(active["melbourne"]["start_melbourne"].startswith("2026-11-11T18:30"), "6pm adelaide is 6:30pm melbourne")
    expect(active["melbourne"]["end_melbourne"].startswith("2026-11-12T00:30"), "midnight adelaide is 12:30am melbourne")
    expect(wirra(at(2026, 11, 11, 17, 59))["closed"] is False, "before 6pm")
    expect(wirra(at(2026, 11, 12, 0, 0))["closed"] is False, "midnight ends the window")
    expect(wirra(at(2026, 11, 9, 20, 0))["closed"] is False, "monday not closed")
    expect(wirra(at(2026, 11, 10, 20, 0))["closed"] is False, "tuesday not a year-long closure")
    expect(wirra(at(2026, 9, 30, 19, 0))["closed"] is False, "september holiday")
    expect(wirra(at(2026, 12, 16, 19, 0))["closed"] is False, "december holiday")
    expect(wirra(at(2027, 7, 7, 19, 0))["closed"] is False, "july holiday")
    winter = wirra(at(2027, 7, 28, 18, 0))
    expect(winter["closed"] is True and winter["melbourne"]["start_melbourne"].startswith("2027-07-28T18:30"), "winter offset still 30 minutes")
    before_dst = dt.datetime(2027, 4, 4, 1, 30, tzinfo=ADELAIDE)
    after_dst = dt.datetime(2027, 4, 4, 3, 30, tzinfo=ADELAIDE)
    expect(before_dst.utcoffset() != after_dst.utcoffset(), "adelaide dst fold")

    bark = one(statuses, "sa:stringybark")
    expect(bark["status"] == "check" and bark["closed"] is False and bark["open_claim"] is False, "stringybark stays check")
    expect(bark.get("advisory") == "unknown", "unnamed parts are an advisory")
    expect("sa-talisker-on-deep-creek-page" not in bark["alert_ids"], "related park does not inherit")
    expect("sa-deep-creek-hikes" not in bark["alert_ids"], "trail closure is not the camp")

    site14 = one(examples, "sa:chowilla-site-14")
    site1 = one(examples, "sa:chowilla-site-1")
    aggregate = one(examples, "sa:chowilla-camps")
    border = one(examples, "sa:border-cliffs")
    other = one(examples, "sa:other-park-site-14")
    foleys = one(examples, "sa:foleys")
    expect(site14["status"] == "closed" and site14["reopen_instant_known"] is False, "named pitch closed, end not an instant")
    expect(site14.get("end_precision") == "date", "date-only end")
    expect(site1["closed"] is False and border["closed"] is False and other["closed"] is False, "partial does not spread")
    expect(aggregate["status"] == "partial" and aggregate["closed"] is False, "parent is partial")
    expect(foleys["status"] == "closed", "named chowilla camp")
    outside = status.apply_alerts(
        [camp(doc, "sa:chowilla-site-14")],
        alerts,
        at(2026, 12, 1, 12, 0),
    )[0]
    expect(outside["status"] == "check" and outside["open_claim"] is False, "after the date range is not open")
    prose = {
        "id": "prose-only",
        "state": "sa",
        "source_url": "https://example.invalid/prose",
        "action": "closure",
        "asset_class": "pitch",
        "parent_id": "sa:chowilla-game-reserve",
        "targets": [{
            "id": "sa:chowilla-game-reserve",
            "scope": "partial",
            "parent_id": "sa:chowilla-game-reserve",
            "body": "campsites 14-32",
        }],
        "start": "2026-05-18",
        "end": "2026-11-30",
        "timezone": "Australia/Adelaide",
    }
    prose_hit = status.apply_alerts([camp(doc, "sa:chowilla-site-14")], [prose], moment)[0]
    expect(prose_hit["closed"] is False, "prose range is not parsed")

    bulletin = status.bulletin_rows(next(row for row in alerts if row["id"] == "sa-desert-bulletin-880"))
    expect(all(row["transfers_across_states"] is False and row["open_claim"] is False and row["becomes_campground"] is False for row in bulletin), "bulletin rows")
    expect(any(row["name"] == "QLD Munga-Thirri" and row["closed_claim"] is False for row in bulletin), "qld status not copied")
    expect(any(row["entity_type"] == "airstrip" and row["reason"] == "not_a_campground" for row in bulletin), "airstrip excluded")

    overlap = [
        {
            "id": "overlap-continuous",
            "state": "sa",
            "source_url": "https://example.invalid/a",
            "action": "closure",
            "asset_class": "campground",
            "targets": [{"id": "sa:pink-gum", "scope": "full"}],
            "start": "2026-11-01",
            "until_further_notice": True,
            "published": "2026-11-01",
            "timezone": "Australia/Adelaide",
        },
        {
            "id": "overlap-overnight",
            "state": "sa",
            "source_url": "https://example.invalid/b",
            "action": "closure",
            "asset_class": "campground",
            "targets": [{"id": "sa:pink-gum", "scope": "full"}],
            "intervals": [{"start": "2026-11-11T20:30", "end": "2026-11-12T05:00"}],
            "published": "2026-11-12",
            "timezone": "Australia/Adelaide",
        },
    ]
    conflict = status.apply_alerts([camp(doc, "sa:pink-gum")], overlap, at(2026, 11, 11, 21, 0))[0]
    expect(conflict["status"] == "unknown" and conflict["review"] is True and conflict["latest_wins"] is False, "conflict stays review")
    expect(conflict["closed"] is False and set(conflict["alert_ids"]) == {"overlap-continuous", "overlap-overnight"}, "both notices kept")
    exception_alert = {
        "id": "remain-open",
        "state": "sa",
        "source_url": "https://example.invalid/exception",
        "action": "closure",
        "asset_class": "park",
        "targets": [{"id": "sa:deep-creek-national-park", "scope": "full"}],
        "exceptions": [{"id": "sa:stringybark", "kind": "remain_open"}],
        "start": "2026-01-01",
        "until_further_notice": True,
        "timezone": "Australia/Adelaide",
    }
    other_camp = {
        "id": "sa:deep-creek-other",
        "state": "sa",
        "entity_type": "campground",
        "inventory_role": "fixture_only",
        "name": "Other Camp",
        "parent_id": "sa:deep-creek-national-park",
    }
    held_open = status.apply_alerts([camp(doc, "sa:stringybark"), other_camp], [exception_alert], moment)
    expect(held_open[0]["status"] == "check" and held_open[0]["open_claim"] is False and held_open[0]["closed"] is False, "named exception")
    expect(held_open[1]["status"] == "closed", "the other camp still closes")
    undated = {
        "id": "missing-date",
        "state": "act",
        "source_url": "https://example.invalid/missing",
        "action": "closure",
        "asset_class": "campground",
        "targets": [{"id": "act:woods-reserve", "scope": "full"}],
    }
    expect(status.normalise_alert(undated)["reason"] == "missing_date", "missing date rejected")
    untouched = status.apply_alerts([camp(doc, "act:woods-reserve")], [undated], moment)[0]
    expect(untouched["status"] == "check" and untouched["closed"] is False, "bad alert closes nothing")

    previous_recent = {"checked_at": "2026-11-11T05:30:00+00:00", "closures": ["act:woods-reserve"]}
    previous_day = {"checked_at": "2026-11-10T19:30:00+00:00"}
    previous_old = {"checked_at": "2026-11-09T19:30:00+00:00"}
    now = dt.datetime(2026, 11, 11, 7, 30, tzinfo=dt.timezone.utc)
    for case in status.load_failures():
        result = status.interpret_fetch(case["result"], now=now)
        expect(result["camps_removed"] is False and result["open_inferred"] is False, case["name"] + " safe")
        expect(result["no_ban_inferred"] is False and result["reopened"] is False, case["name"] + " not reopened")
        if case["name"] == "empty_sentinel":
            expect(result["operational_claim"] is False and result["status"] == "unknown", "empty sentinel")
        else:
            expect(result.get("status") == "unknown" and result["retain_closures"] is False, case["name"] + " no cache")
    fresh = status.interpret_fetch({"status": 403, "body": ""}, previous_recent, now)
    expect(fresh["degraded"] is False and fresh["retain_closures"] is True and fresh["checked_at"] == previous_recent["checked_at"], "under 6h keeps cache")
    stale = status.interpret_fetch({"status": 500, "body": ""}, previous_day, now)
    expect(stale["stale"] is True and stale["degraded"] is True and stale["retain_closures"] is True and stale["operational_claim"] is True, "6h to 24h degraded")
    dropped = status.interpret_fetch({"status": "timeout", "body": None}, previous_old, now)
    expect(dropped["operational_claim"] is False and dropped["retain_closures"] is True and dropped["uncertainty"] is True and dropped["reopened"] is False, "after 24h uncertain")

    border_camp = camp(doc, "act:northern-border")
    cotter = camp(doc, "act:cotter")
    quiet = status.fire_status(border_camp)
    expect(quiet["status"] == "unknown" and quiet["rating"] is None and quiet["banned"] is None, "fire unknown")
    expect(quiet["label"] == status.FIRE_UNKNOWN_LABEL and quiet["state_wide_closure"] is False, "fire label")
    expect(quiet["closed"] is False, "unknown fire does not close")
    nsw = status.fire_status(border_camp, {"source": "nsw_rfs", "rating": "Moderate", "ban_today": "No"})
    expect(nsw["ignored_reason"] == "no_nsw_fdr_fallback" and nsw["rating"] is None and nsw["closed"] is False, "no nsw fallback")
    missing = status.fire_status(border_camp, {"banner": None})
    expect(missing["banned"] is None and missing["ignored_reason"] == "missing_banner_is_not_no_ban", "missing banner")
    unverified = status.fire_status(border_camp, {"verified": True, "authority": "act_esa", "scope": "all", "valid_on": "2026-11-11"})
    expect(unverified["closed"] is False and unverified["ignored_reason"] == "unverified_fire_value", "reuse not cleared")
    verified = {
        "verified": True,
        "reuse_cleared": True,
        "authority": "act_esa",
        "scope": "all",
        "valid_on": "2026-11-11",
    }
    banned = status.fire_status(border_camp, verified)
    spared = status.fire_status(cotter, verified)
    expect(banned["status"] == "conditional_closure" and banned["rating"] is None and banned["state_wide_closure"] is False, "northern border rule")
    expect(spared["closed"] is False and spared["state_wide_closure"] is False, "tfb is not every act camp")
    partial = dict(verified, scope="partial", area_ids=["somewhere-else"])
    expect(status.fire_status(border_camp, partial)["closed"] is False, "partial ban misses the camp")
    covered = dict(verified, scope="partial", area_ids=["act:northern-border"])
    expect(status.fire_status(border_camp, covered)["closed"] is True, "partial ban can name the camp")
    expect(status.fire_status(cotter, covered)["closed"] is False, "partial ban stays local")
    cfs = status.fire_status(camp(doc, "sa:wirra"), {"verified": True, "reuse_cleared": True, "authority": "sa_cfs", "kind": "total_fire_ban"})
    expect(cfs["closed"] is False and cfs["banned"] is None and cfs["ignored_reason"] == "tfb_is_not_universal_park_closure", "sa tfb is not closure")
    expect(not status.contains_no_rating([quiet, nsw, banned, cfs]), "no No Rating label")

    report = status.build_preview_report(moment)
    expect(report["send"] is False and report["enrol"] is False and report["public"] is False, "preview not live")
    expect(report["live_fetch"] is False, "preview did not fetch")
    preview_woods = one(report["statuses"], "act:woods-reserve")
    expect(preview_woods["status"] == "closed", "preview woods")
    expect(not status.contains_no_rating(report), "preview wording")
    expect(any("403" in item for item in report["not_implemented"]), "act fetch limit listed")
    expect("RESEND_SEGMENT_ACT_ID" in [item["name"] for item in report["resend"]["variables"]], "act segment named")
    expect(all(item["read_by_signup"] is False for item in report["resend"]["variables"]), "segment vars unread")
    expect("licence_parks_esa" in report["blockers"]["act"], "act licence blocker")
    expect("licence_split" in report["blockers"]["sa"], "sa licence blocker")

    preview_dir = tempfile.mkdtemp(prefix="act-sa-preview-")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "act_sa_preview.py"), "--out", preview_dir], cwd=ROOT, capture_output=True, text=True)
    expect(proc.returncode == 0, "preview cli")
    written = open(os.path.join(preview_dir, "preview.txt"), encoding="utf-8").read()
    expect("Do not send" in written and "Do not enrol" in written, "preview banner")
    expect("No Rating" not in written and "{{{EMAIL}}}" not in written, "preview is not a send file")
    sa_digest = open(os.path.join(preview_dir, "digest", "sa", "digest.txt"), encoding="utf-8").read()
    sa_meta = json.load(open(os.path.join(preview_dir, "digest", "sa", "meta.json"), encoding="utf-8"))
    expect("Do not send" in sa_digest and "{{{EMAIL}}}" not in sa_digest, "sa preview digest")
    expect(sa_meta.get("send") is False and sa_meta.get("reads_segment_env") is False and sa_meta.get("working_digest_coverage") is False, "preview digest is not coverage")
    ingest = json.load(open(os.path.join(preview_dir, "ingest.json"), encoding="utf-8"))
    by_camp = {row["camp_id"]: row for row in ingest["statuses"]}
    expect(by_camp["sa:wirra"]["status"] == "closed" and by_camp["sa:pink-gum"]["status"] == "unknown", "fixture html reaches the matcher")
    expect(by_camp["sa:mambray-creek"]["status"] == "upcoming" and ingest["open_inferred"] is False, "mambray upcoming from html")
    empty = act_sa_html.parse_closure_html(open(os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "empty.html"), encoding="utf-8").read(), "https://www.parks.sa.gov.au/example", "2026-11-09T00:00:00+00:00")
    expect(empty["ok"] is False and empty["open_inferred"] is False and empty["status"] == "unknown", "empty html is unknown")
    blocked = act_sa_html.fetch_public_html("https://example.com/secret")
    expect(blocked["ok"] is False and blocked["error"] == "host_not_allowed" and blocked["open_inferred"] is False, "other hosts are not fetched")
    refused = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "act_sa_preview.py"), "--out", os.path.join(ROOT, "dist", "act-sa-preview")],
        cwd=ROOT, capture_output=True, text=True,
    )
    expect(refused.returncode != 0, "preview refuses dist")

    token_js = open(os.path.join(ROOT, "functions", "_lib", "token.js"), encoding="utf-8").read()
    confirm_js = open(os.path.join(ROOT, "functions", "api", "confirm.js"), encoding="utf-8").read()
    unsub_js = open(os.path.join(ROOT, "functions", "api", "unsubscribe.js"), encoding="utf-8").read()
    expect('export const HELD_SIGNUP_STATES = ["act", "sa"];' in token_js, "signup hold")
    expect("env.RESEND_SEGMENT_ACT_ID" not in confirm_js and "env.RESEND_SEGMENT_SA_ID" not in confirm_js, "confirm ignores held env")
    expect("env.RESEND_SEGMENT_ACT_ID" not in unsub_js and "env.RESEND_SEGMENT_SA_ID" not in unsub_js, "unsubscribe ignores held env")

    node = subprocess.run(["node", "--input-type=module", "-e", NODE], cwd=ROOT, capture_output=True, text=True)
    expect(node.returncode == 0, "signup hold node: " + (node.stderr or node.stdout)[-300:])

    home = os.path.join(ROOT, "dist", "index.html")
    if os.path.isfile(home):
        page = open(home, encoding="utf-8").read()
        expect('value="act"' not in page and 'value="sa"' not in page, "homepage checkboxes")
        expect("Australian Capital Territory" not in page and "South Australia" not in page, "homepage names")
    status_path = os.path.join(ROOT, "dist", "status.json")
    if os.path.isfile(status_path):
        out = tempfile.mkdtemp(prefix="act-sa-digest-")
        env = os.environ.copy()
        env["CAMPCONDITIONS_ENABLE"] = "act,sa"
        digest = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "digest.py"), "--current", status_path, "--out", out],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        expect(digest.returncode == 0, "digest still drafts")
        expect(not os.path.isdir(os.path.join(out, "act")) and not os.path.isdir(os.path.join(out, "sa")), "no held digest")
        meta = json.load(open(os.path.join(out, "meta.json"), encoding="utf-8"))
        expect(meta.get("state") == "vic", "top digest stays victoria")

    slim = status.load_json(os.path.join(ROOT, "data", "act-sa", "evidence", "reconciliation-slim.json"))
    expect(slim["ready_to_publish"] is False, "reconciliation not publishable")
    expect(all(row["ready_to_publish"] is False for row in slim["act"]["official_index_campgrounds"]), "act rows unpublished")
    expect(all(row["ready_to_publish"] is False and row["official_geometry_test_executed"] is False for row in slim["sa"]["facilities"]), "sa rows unpublished")
    expect(len(slim["sa"]["facilities"]) == 28 and len({row["booking_id"] for row in slim["sa"]["facilities"]}) == 28, "28 booking ids")
    expect(slim["statewide_denominator_known"] is False, "statewide denominator unknown")
    gym = slim["sa"]["gym_beach"]
    expect(gym["resolved"] is False and gym["viewport_edge_m"] != gym["pitch3_label_to_osm_point_m"], "gym beach methods stay unresolved")
    expect(status.proximity_decision(gym["viewport_edge_m"])["merged"] is False and status.proximity_decision(gym["pitch3_label_to_osm_point_m"])["merged"] is False, "neither gym distance merges")
    expect(slim["esa_feed_grant"]["covers_parks_text"] is False and slim["esa_feed_grant"]["covers_fdr_tfb"] is False, "esa feed grant is narrow")
    expect(slim["esa_feed_grant"]["cap_support_implemented"] is False and slim["esa_feed_grant"]["zero_rss_means_no_incidents"] is False, "cap feed not implemented")
    expect(status.eligible_count_from_tag_totals(slim["act_raw_camping_tag_features"]) is None, "act 126 is not a camp count")
    expect(status.eligible_count_from_tag_totals({"features": slim["sa_raw_camping_tag_features"]}) is None, "sa 1385 is not a camp count")
    kids = status.cottermouth_children(slim["act"]["cottermouth_child_camp_sites"])
    expect(kids["child_features"] == 35 and kids["representative_points_inside_parent"] == 35, "35 child points")
    expect(kids["entire_polygons_inside_parent"] == 32 and kids["boundary_crossing_review"] == 3, "three polygons need review")
    expect(kids["publish_as_new_campgrounds"] is False and kids["added_to_camp_count"] == 0, "children do not inflate")
    sample_rows = [
        {"source_kind": "pdf_asset_not_HTML", "error": ""},
        {"source_kind": "official_alerts_HTML", "error": ""},
        {"source_kind": "fetch_error", "error": "HTTP Error 404: Not Found"},
        {"source_kind": "fetch_error", "error": "HTTP Error 500: Internal Server Error"},
    ]
    classified = status.classify_manifest(sample_rows)
    expect(classified["campground_count"] is None and classified["pdf_assets_are_camps"] is False, "sample manifest is not camps")
    expect(classified["fetch_errors"] == 2 and classified["alert_pages_are_active_closures"] is False, "errors and alerts are not camp counts")
    observed = slim.get("manifest_observation") or {}
    expect(observed.get("url_count") == 516 and observed.get("campground_count") is None and observed.get("recounted_in_repo") is False, "516 is a labelled observation")
    expect(slim["licences"]["sa_html"] != slim["licences"]["sa_legacy_json"], "html and legacy licences differ")
    expect(slim["licences"]["geopdf_explicit_map_or_derived_geometry_grant"] is False, "geopdf grant absent")
    expect(slim["licences"]["act_gov_general_licence_covers_parks_or_esa"] is False, "act.gov.au is not the parks grant")
    expect(slim["licences"]["licences_flattened"] is False and slim["licences"]["osm"] == "ODbL", "osm stays separate")
    selectable_ids = {row["id"] for row in selectable}
    research_ids = {row["booking_id"] for row in slim["sa"]["facilities"]}
    expect({"67592", "67453", "69782", "73101", "85012", "92322"} <= research_ids, "distinct facilities stay in the research file")
    expect("sa:mambray-creek" not in selectable_ids, "mambray not in the test cohort")
    cohort = status.summarise_inventory(doc)["sa_pilot_ids"]
    expect(cohort == ["sa:pink-gum", "sa:wirra", "sa:stringybark"], "three-camp set is still only a test cohort")
    evaluated = act_sa_fixtures.evaluate_all()
    expect(evaluated["ran"] == 59 and evaluated["production_matcher_was_already_executed"] is False, "59 proposals executed, none were already passed")
    declined = set(evaluated["not_adopted"])
    expect(declined == {"ACT_WOODS_NO_CALENDAR_REOPEN", "ACT_NORTHERN_BORDER_VERIFIED_TFB", "ACT_EDXL_NOT_ZERO_RSS_NO_INCIDENTS"}, "declined proposals")
    for row in evaluated["results"]:
        expect(row["ran"] is True, row["id"] + " ran")
        expect(row["actual"].get("infer_verified_open") is not True, row["id"] + " not verified open")
        expect(row["actual"].get("claim_open") is not True, row["id"] + " not claimed open")
        expect(row["actual"].get("borrow_nsw_rating") is not True, row["id"] + " no nsw rating")
        if row["id"] in declined:
            expect(row["agreement"] == "not_adopted", row["id"] + " declined")
        else:
            expect(row["agreement"] in {"full", "safety"}, row["id"] + " " + row["agreement"] + " " + row.get("note", ""))
    mambray = one(examples, "sa:mambray-creek")
    expect(mambray["status"] == "upcoming" and mambray["closed"] is False and mambray["open_claim"] is False, "mambray upcoming on 11 nov")
    active_window = status.apply_alerts([camp(doc, "sa:mambray-creek")], alerts, at(2026, 11, 15, 18, 0))[0]
    expect(active_window["status"] == "closed" and active_window["melbourne"]["start_melbourne"].startswith("2026-11-15T18:30"), "6pm adelaide is 6:30pm melbourne")
    expect(active_window["melbourne"]["end_melbourne"].startswith("2026-11-20T14:30"), "2pm adelaide is 2:30pm melbourne")
    ended_window = status.apply_alerts([camp(doc, "sa:mambray-creek")], alerts, at(2026, 11, 20, 14, 0))[0]
    expect(ended_window["closed"] is False and ended_window["open_claim"] is False, "window end is not verified open")
    unnamed = one(examples, "sa:mount-remarkable-unnamed-example")
    expect(unnamed["status"] == "unknown" and unnamed["closed"] is False, "unnamed mount remarkable camp not closed")
    expect(status.proximity_decision(200)["merged"] is False and status.proximity_decision(444.3)["merged"] is False, "proximity does not merge")
    expect(status.use_html_point_as_camp_geometry("-35.145477,138.5785801") is False, "park html point rejected")

    holds = status.load_json(os.path.join(ROOT, "data", "act-sa", "evidence", "eligibility-holds.json"))
    classified = [act_sa_eligibility.classify(row) for row in holds["rows"]]
    by_hold = {row["record_id"]: row for row in classified}
    expect(act_sa_eligibility.camp_count(holds["rows"]) is None, "ledger rows are not a camp count")
    expect(holds["ledger_rows_not_camps"] == 1358, "1358 is the hold size")
    expect(holds["excluded_counts_from_ledger"]["act_child_camp_site"] == 35, "35 cottermouth children")
    expect(holds["excluded_counts_from_ledger"]["sa_allocated_children"] == 57, "57 allocated children")
    expect(by_hold["way/1567012314"]["excluded"] and by_hold["node/3107057998"]["excluded"], "child sites are not camps")
    expect(by_hold["node/8441973436"]["excluded"] and by_hold["way/280952772"]["eligible_camp"], "epic is one identity")
    expect(by_hold["way/265761463"]["excluded"] and by_hold["way/265761467"]["excluded"] and by_hold["node/1811199869"]["eligible_camp"], "trig sectors are not camps")
    expect(by_hold["node/775893673"]["excluded"] and by_hold["way/315306819"]["eligible_camp"], "trezona duplicate dropped")
    expect(by_hold["way/1015330682"]["excluded"] and by_hold["node/1811173346"]["eligible_camp"], "engine point subarea dropped")
    expect(all(by_hold[item]["excluded"] for item in ("node/1956246563", "node/9738925392", "node/11182471275", "way/265146867")), "out of state excluded")
    woods_hold = by_hold["woods"]
    expect(woods_hold["operating_status"] == "closed" and woods_hold["reopen_at"] is None and woods_hold["open_inferred"] is False, "woods is the closed hold")
    expect(all(row["open_inferred"] is False and row["operating_status"] != "open" for row in classified), "no hold is open")
    rodeo = next(row for row in holds["rows"] if row["record_id"] == "node/1811160487")
    cliffs = next(row for row in holds["rows"] if row["record_id"] == "node/1811163200")
    rest = next(row for row in holds["rows"] if row["record_id"] == "way/495027493")
    springs = next(row for row in holds["rows"] if row["record_id"] == "node/3439215546")
    expect(act_sa_eligibility.same_camp(rodeo, {"record_id": "sa:baroota-ruins"}, 50)["merged"] is False, "rodeo is not baroota ruins")
    expect("140962" in cliffs["rejected_match_urls"] and act_sa_eligibility.same_camp(cliffs, {"record_id": "sa:yapari"}, 200)["merged"] is False, "border cliffs is not yapari")
    expect("67320" in rest["rejected_match_urls"], "rest area is not mambray camp")
    expect("85012" in springs["rejected_match_urls"], "main black springs is not the overflow")
    expect(sum(1 for row in classified if row["eligible_camp"]) != 1358, "eligible set is not the ledger")

    index_html = open(os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "act-alerts-index.html"), encoding="utf-8").read()
    index_record = act_sa_html.parse_act_alerts_index(index_html, {"Age": "21772"}, "2026-11-09T02:00:21+00:00", 200)
    expect(index_record["operating_status"] == "closed" and index_record["reopen_at"] is None and index_record["expected_note"] == "early 2027", "act index woods stays closed")
    expect(index_record["source_health"]["cache_age_seconds"] == 21772 and index_record["source_health"]["origin_freshness_known"] is False, "cache age is not origin freshness")
    drifted = act_sa_html.parse_act_alerts_index("<h1>Alerts</h1><p>Nothing listed</p>", {}, "2026-11-09T02:00:21+00:00", 200)
    expect(drifted["ok"] is False and drifted["retain_known_closure"] is True and drifted["open_inferred"] is False, "schema drift does not reopen")
    blocked_index = act_sa_html.parse_act_alerts_index("", {}, "2026-11-09T02:00:21+00:00", 403)
    expect(blocked_index["status"] == "unknown" and blocked_index["retain_known_closure"] is True and blocked_index["reopen_at"] is None, "index 403 keeps the known closure")
    sa_index = open(os.path.join(ROOT, "data", "act-sa", "fixtures", "html", "sa-alerts-index.html"), encoding="utf-8").read()
    discovered = act_sa_html.discover_sa_notices(sa_index)
    expect("park-closure-descriptions" not in " ".join(discovered) and len(discovered) == 4, "help anchors are not notices")
    report_complete = act_sa_html.completeness(discovered, [{"source_url": discovered[0], "handled": True}])
    expect(report_complete["all_discovered_supported"] is False and report_complete["camp_count"] is None, "parsed notices are not full coverage")
    expect(report_complete["discovered_detail_notices"] > report_complete["parsed_handled"], "discovery stays ahead of handled parses")

    notices = act_sa_notices.load_notices(os.path.join(ROOT, "data", "act-sa", "fixtures", "sa-notices.json"))
    as_of = dt.datetime.fromisoformat("2026-11-09T11:46:51+10:30")
    scored = act_sa_notices.evaluate_all(notices, as_of)
    expect(len(notices) == 49 and scored["handled"] + scored["held_unknown"] == 49, "every notice is handled or held")
    expect(scored["open_inferred"] is False and all(row["camp_status"] != "open" for row in scored["notices"]), "no notice is open")
    expect(scored["geometry_exported"] is False, "notice 48 geometry is not exported")
    by_notice = scored["by_index"]
    expect(by_notice[3]["booking_ids"] == [] and "67710" not in by_notice[41]["booking_ids"], "aroona is not the ikara camp")
    expect("72075" not in by_notice[44]["booking_ids"] and by_notice[44]["booking_ids"] == ["87314"], "acraman creek keeps its own id")
    expect(by_notice[35]["booking_ids"] == [] and "Anstey" not in " ".join(notices[18]["parks"]), "tapanappa and anstey are not attached")
    expect(by_notice[27]["camp_status"] == "unknown" and by_notice[28]["camp_status"] == "unknown" and scored["bookings"]["73201"] == "unknown", "morgan conflict is unknown")
    expect(by_notice[30]["camp_status"] == "unknown" and scored["bookings"]["73194"] == "unknown", "chowilla site conflict is unknown")
    expect(by_notice[30]["child_sites_emitted"] is False, "numbered sites stay on the parent")
    night = dt.datetime(2026, 11, 11, 21, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    pink_night = act_sa_notices.evaluate(by_notice and notices[5], night)
    expect(act_sa_notices._night_blocks(notices[5]["recurrence"]["night_blocks"], night) is True, "last listed night counts as closure")
    expect(pink_night["camp_status"] == "unknown" and pink_night["open_inferred"] is False, "pink gum stays unknown on a closure night")
    during = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    during_score = act_sa_notices.evaluate_all(notices, during)
    expect(during_score["bookings"]["67320"] == "closed" and during_score["by_index"][45]["camp_status"] != "open", "notice 45 does not clear notice 38")
    after = dt.datetime(2026, 11, 21, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    after_score = act_sa_notices.evaluate_all(notices, after)
    expect(after_score["bookings"]["67320"] != "open" and after_score["by_index"][20]["camp_status"] == "expired_not_open", "expired notice is not open")
    expect(len(by_notice[8]["unmapped_names"]) + len(by_notice[45]["unmapped_names"]) >= 1, "camps without ids stay unmapped")
    null_names = [name for row in scored["notices"] for name in row["unmapped_names"]]
    expect(len(null_names) == 9 and all(name for name in null_names), "nine named camps have no booking id")

    if FAILURES:
        print("ACT/SA foundation failures: %s" % len(FAILURES))
        for label in FAILURES:
            print(" FAIL", label)
        return 1
    print("ACT/SA foundation checks passed: %s" % CHECKS)
    return 0


NODE = r"""
import { chosenStates, heldSignupStates, heldSignupPreview, makeToken, readToken } from "./functions/_lib/token.js";
import { signupChoice } from "./functions/api/subscribe.js";
import { confirmSubscription, segmentPlan } from "./functions/api/confirm.js";

const email = "reader@example.com";
if (chosenStates(["act", "sa", "vic", "qld"]).join(",") !== "vic,qld") process.exit(1);
if (heldSignupStates(["sa", "act", "vic"]).join(",") !== "act,sa") process.exit(2);
const preview = heldSignupPreview("act");
if (!preview || preview.enrol || preview.send || preview.readsSegmentEnv || preview.requiredEnv !== "RESEND_SEGMENT_ACT_ID") process.exit(13);
if (heldSignupPreview("vic")) process.exit(14);
const held = signupChoice(["act", "sa"], true);
if (held.ok || held.reason !== "not_open" || held.enrol.length) process.exit(3);
const mixed = signupChoice(["vic", "act"], true);
if (!mixed.ok || mixed.states.join(",") !== "vic" || mixed.enrol.join(",") !== "vic") process.exit(4);
if (signupChoice(["bogus"], true).reason !== "pick_state") process.exit(5);
if (signupChoice([], false).states.join(",") !== "vic") process.exit(6);
const secret = "test-secret";
if (await makeToken(email, secret, 3600, ["act"])) process.exit(7);
const token = await makeToken(email, secret, 3600, ["vic", "act"]);
const parsed = await readToken(token, secret);
if (!parsed || parsed.states.join(",") !== "vic") process.exit(8);
let calls = 0;
const env = {
  RESEND_API_KEY: "test",
  CONFIRM_SECRET: secret,
  RESEND_SEGMENT_ID: "vic-segment",
  RESEND_SEGMENT_NSW_ID: "nsw-segment",
  RESEND_SEGMENT_ACT_ID: "act-segment",
  RESEND_SEGMENT_SA_ID: "sa-segment",
};
const refused = await confirmSubscription(env, email, async () => { calls += 1; return new Response("{}", { status: 201 }); }, ["act"], true);
if (refused.ok || refused.data.name !== "signup_not_open" || calls !== 0) process.exit(9);
const urls = [];
await confirmSubscription(env, email, async (url) => { urls.push(String(url)); return new Response("{}", { status: 201 }); }, ["vic", "act"], true);
if (urls.some((url) => url.includes("act-segment") || url.includes("sa-segment"))) process.exit(10);
if (!urls.some((url) => url.endsWith("/segments/vic-segment"))) process.exit(11);
const plan = segmentPlan(env, ["sa"], true);
if (plan.refuse !== "not_open" || plan.segmentIds.length) process.exit(12);
"""


if __name__ == "__main__":
    sys.exit(main())
