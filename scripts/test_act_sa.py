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
import sa_digest
import sa_fire
import sa_signup
import notice_phase
import sa_inventory
import sa_launch_gate
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

    expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "enabled states")
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
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "env cannot enable act")
        os.environ["CAMPCONDITIONS_ENABLE"] = "nsw"
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "existing preview env")
    finally:
        if saved is None:
            os.environ.pop("CAMPCONDITIONS_ENABLE", None)
        else:
            os.environ["CAMPCONDITIONS_ENABLE"] = saved

    act = states.by_slug("act")
    sa = states.by_slug("sa")
    expect(act.get("enabled") is False and sa.get("enabled") is True, "sa is on and act stays off")
    expect(states.public_build_allowed(act) is False and states.digest_allowed(act) is False, "act stays off")
    expect(states.public_build_allowed(sa) is True and states.signup_allowed(sa) is False and states.digest_allowed(sa) is False, "sa pages are public and signup stays off")
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
    blocking = [gate for gate in sa["release"]["gates"] if gate.get("blocks_public", True) is not False]
    expect(blocking and all(gate.get("ok") is True for gate in blocking), "blocking sa gates are open")
    segment = next(gate for gate in sa["release"]["gates"] if gate.get("id") == "digest_segment")
    expect(segment.get("ok") is False and segment.get("blocks_public") is False, "sa signup segment stays off")
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
    expect("licence_split" not in report["blockers"]["sa"], "sa licence split is accepted")
    expect("digest_segment" in report["blockers"]["sa"] and "official_source_parser" in report["blockers"]["sa"], "signup and the live parser stay off")

    preview_dir = tempfile.mkdtemp(prefix="act-sa-preview-")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "act_sa_preview.py"), "--out", preview_dir], cwd=ROOT, capture_output=True, text=True)
    expect(proc.returncode == 0, "preview cli")
    written = open(os.path.join(preview_dir, "preview.txt"), encoding="utf-8").read()
    expect("Do not send" in written and "Do not enrol" in written, "preview banner")
    expect("No Rating" not in written and "{{{EMAIL}}}" not in written, "preview is not a send file")
    sa_preview_text = open(os.path.join(preview_dir, "digest", "sa", "digest.txt"), encoding="utf-8").read()
    sa_meta = json.load(open(os.path.join(preview_dir, "digest", "sa", "meta.json"), encoding="utf-8"))
    expect("Do not send" in sa_preview_text and "{{{EMAIL}}}" not in sa_preview_text, "sa preview digest")
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
    expect('export const HELD_SIGNUP_STATES = ["act", "sa", "tas"];' in token_js, "signup hold")
    expect("env.RESEND_SEGMENT_ACT_ID" not in confirm_js and "env.RESEND_SEGMENT_SA_ID" not in confirm_js, "confirm does not read the segment id itself")
    expect("env.RESEND_SEGMENT_ACT_ID" not in unsub_js and "env.RESEND_SEGMENT_SA_ID" not in unsub_js, "unsubscribe ignores held env")

    node = subprocess.run(["node", "--input-type=module", "-e", NODE], cwd=ROOT, capture_output=True, text=True)
    expect(node.returncode == 0, "signup hold node: " + (node.stderr or node.stdout)[-300:])

    home = os.path.join(ROOT, "dist", "index.html")
    if os.path.isfile(home):
        page = open(home, encoding="utf-8").read()
        expect('value="vic"' in page and 'value="nsw"' in page and 'value="qld"' in page, "homepage signup offers the three states")
        expect('value="act"' not in page and 'value="sa"' not in page, "signup does not offer act or sa")
        expect("South Australia" in page and 'href="/sa/"' in page, "homepage lists sa")
        expect("Tasmania" in page and 'href="/tas/"' in page, "homepage lists tas")
        expect('value="tas"' not in page, "signup does not offer tas")
        expect("Australian Capital Territory" not in page, "homepage does not name act")
        expect(os.path.isdir(os.path.join(ROOT, "dist", "sa")), "public build has sa pages")
        expect(os.path.isdir(os.path.join(ROOT, "dist", "tas")), "public build has tas pages")
        expect(not os.path.isdir(os.path.join(ROOT, "dist", "act")), "public build has no act pages")
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
    expect(len(notices) == 50 and scored["handled"] + scored["held_unknown"] == 50, "every notice is handled or held")
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

    sa_camps = sa_inventory.load_camps(set())
    counted = sa_inventory.summary(sa_camps)
    before = counted["before_park_decisions"]
    expect(before["official_confident"] == 73 and before["official_approximate"] == 7 and before["eligible_osm"] == 34, "sa inventory base counts")
    expect(before["council"] == 43 and before["tourism"] == 22 and before["operator"] == 86 and before["published"] == 265, "counts before caravan park decisions")
    expect(counted["official_confident"] == 73 and counted["official_approximate"] == 7 and counted["eligible_osm"] == 13, "sa inventory base counts")
    expect(counted["council"] == 40 and counted["tourism"] == 5 and counted["operator"] == 22, "listing sources after caravan park decisions")
    expect(counted["published"] == 160 and counted["duplicates_dropped"] == 1, "sa inventory counts")
    expect(counted["duplicates"][0]["osm_id"] == "way/1485152213", "mount gambier east side dropped")
    expect(counted["open_inferred"] is False and counted["fire_rating_count"] == 0, "sa inventory not open and not rated")
    expect(all(row["status"] != "open" for row in sa_camps), "no confirmed open")
    booking = {}
    for row in sa_camps:
        expect(row["lat"] is not None and row["lon"] is not None, "coordinates present")
        expect("img" not in row and "image" not in row, "no copied image")
        for item in row["booking_ids"]:
            expect(item not in booking, "booking id is one camp")
            booking[item] = row
    expect("85012" not in booking and "73196" not in booking and "67592" not in booking and "67453" not in booking and "69782" not in booking, "held camps stay out")
    springs = booking["73101"]
    expect(springs["name"].startswith("Black Springs Campground") and springs["notice_status"] == "no_current_notice", "black springs separate")
    by_osm = {row["osm_id"]: row for row in sa_camps if row.get("osm_id")}
    park_excluded = {row["osm_id"]: row for row in counted["park_excluded"]}
    west = park_excluded["way/75460499"]
    waikerie = park_excluded["way/671003129"]
    kingston = park_excluded["way/943231647"]
    renmark = park_excluded["way/663118408"]
    expect(west["name"] == "Discovery Parks – West Beach Parks" and west["decision"] == "exclude" and "way/75460499" not in by_osm, "west beach chain park is excluded")
    expect(waikerie["name"] == "Echo Holiday Parks – Waikerie" and waikerie["decision"] == "exclude" and "way/671003129" not in by_osm, "waikerie chain park is excluded")
    expect(kingston["name"] == "BIG4 Kingston SE Foreshore Holiday Park" and kingston["decision"] == "exclude" and "way/943231647" not in by_osm, "kingston chain park is excluded")
    expect(renmark["name"] == "Echo Holiday Parks - Renmark" and renmark["slug"] != waikerie["slug"] and "way/663118408" not in by_osm, "echo renmark stays separate and excluded")
    expect("way/852240175" not in by_osm, "pondalowie stays out of the preview")
    for stayed in ("node/736398059", "way/201352992", "node/4682386296", "way/99841061", "way/321216861", "way/177930647"):
        expect(stayed not in by_osm, "open-question camp stays out")
    excluded = {row["osm_id"]: row for row in counted["commercial_excluded"]}
    expect(set(excluded) == {"way/99841061", "way/321216861", "way/177930647"}, "three commercial parks are recorded")
    expect(all(row["reason"] == "commercial caravan park" and row["source"] == "operator" for row in excluded.values()), "commercial parks excluded with that reason")
    expect(excluded["way/99841061"]["name"] == "Discovery Parks - Adelaide Beachfront", "adelaide beachfront excluded")
    expect(excluded["way/321216861"]["name"] == "Belair National Park Holiday Park", "belair holiday park excluded")
    expect(excluded["way/177930647"]["name"] == "Brownhill Creek Tourist Park", "brownhill creek excluded")
    kept_ids = {row["osm_id"] for row in counted["park_kept"]}
    expect(len(counted["park_excluded"]) == 86 and all(row["decision"] == "exclude" and row["reason"] for row in counted["park_excluded"]), "excluded parks stay unpublished with a reason")
    expect(len(counted["park_held"]) == 19 and all(row["decision"] == "hold" and row["reason"] and row["osm_id"] not in park_excluded for row in counted["park_held"]), "held parks are not excluded")
    expect(sa_inventory.published_parks_without_keep(sa_camps, kept_ids) == [], "published caravan holiday or tourist park needs a keep")
    expect(sa_inventory.published_parks_without_keep([{"name": "Sample Holiday Park", "category": "Campground", "osm_id": "way/sample"}], set()) == ["Sample Holiday Park"], "a holiday park with no keep decision fails")
    expect(sa_inventory.published_parks_without_keep([{"name": "Sample Tourist Park", "category": "Campground", "osm_id": "way/sample-2"}], kept_ids) == ["Sample Tourist Park"], "a tourist park with no keep decision fails")
    expect(sa_inventory.is_caravan_holiday_or_tourist_park({"name": "Burra Caravan & Camping Park", "category": "Caravan park"}), "caravan and camping park is in the check")
    expect(not sa_inventory.is_caravan_holiday_or_tourist_park({"name": "Balgowan Caravan & Camping Area", "category": "Campground"}), "a camping area is not a caravan park")
    adare = next(row for row in counted["park_excluded"] if row["name"] == "Adare Caravan Park")
    expect("conference" in adare["reason"] and adare["osm_id"] not in by_osm, "adare is excluded")
    showground = next(row for row in sa_camps if row["name"] == "Adelaide Showground Caravan Park")
    expect(showground["osm_id"] in kept_ids, "adelaide showground stays")
    expect(any(row["name"] == "Marion Bay Caravan Park" and row["osm_id"] in kept_ids for row in sa_camps), "council marion bay stays")
    expect(any(row["name"] == "Christies Beach Tourist Park" and row["osm_id"] in kept_ids for row in sa_camps), "onkaparinga christies beach stays")
    minlaton = next(row for row in counted["park_excluded"] if row["name"] == "Minlaton Caravan Park")
    expect("family-owned" in minlaton["reason"] and minlaton["osm_id"] not in by_osm, "minlaton is excluded")
    held_names = {row["name"] for row in counted["park_held"]}
    expect("Corny Point Caravan Park" in held_names and "Pine Point Caravan Park" in held_names, "corny point and pine point are held")
    unreviewed = sorted(row["name"] for row in counted["park_held"] if row.get("reviewed") != "yes")
    expect(unreviewed == ["Burra Caravan & Camping Park", "Eudunda Caravan & Camping Park", "William Creek Hotel camping ground"], "parks outside the review are held")
    expect("860167" not in booking, "ippinitchie stays held without a street view point")
    burra = [row for row in sa_camps if "burra creek" in row["name"].lower() or "world's end gorge" in row["name"].lower() or "worlds end" in row["name"].lower()]
    expect(len(burra) == 1 and burra[0]["osm_id"] == "node/1811163605" and "Mid point" in burra[0]["source_note"], "burra creek gorge is the west point")
    approximate = [row for row in sa_camps if row.get("coord_precision") == "approximate"]
    streetview = [row for row in approximate if row.get("inventory_group") == "official_approximate"]
    expect(len(streetview) == 7 and len(approximate) == 7 and all(row["coord_source"] == "parks_sa_streetview_link" and row["source"] == "parks_sa" for row in streetview), "seven approximate street view camps")
    by_booking = {item: row for row in sa_camps for item in row.get("booking_ids") or []}
    expect(by_booking["72081"]["osm_id"] == "node/775893673" and by_booking["73170"]["osm_id"] == "way/265761467", "trezona and trig candidates settled")
    expect(all(not row.get("osm_id") for row in streetview if row["id"] not in {"72081", "73170"}), "other street view camps do not invent an osm id")
    listings = [row for row in sa_camps if row.get("inventory_group") == "council_check"]
    expect(all(row["source"] in {"council", "tourism", "operator"} and row["listing_source"] == row["source"] for row in listings), "listing source is council, tourism or operator")
    expect(all("$" not in " ".join(str(row.get(key) or "") for key in ("phone", "email", "about", "access", "attribution", "source_note", "managed_by")) for row in sa_camps), "no fees on sa camps")
    expect(any(row.get("phone") and row.get("source_url", "").startswith("https://") for row in listings), "contacts and evidence urls kept")
    expect(booking["73157"]["notice_status"] == "closed" and booking["73157"]["status"] == "closed", "grindells closed")
    expect(booking["73157"]["notice_url"].startswith("https://www.parks.sa.gov.au/"), "closed camps link the notice")
    expect(all(not row["notice_url"] for row in sa_camps if row["notice_status"] == "no_current_notice"), "no-notice camps do not link a notice")
    expect(booking["72075"]["status_label"] == "No current notice" and booking["72075"]["notice_status"] == "no_current_notice" and not booking["72075"]["notice_url"], "ikara notice is not current")
    expect("ikara-flinders-ranges-national-park-35" in " ".join(sa_inventory.load_camps.dropped_notices), "404 and off-index notice is dropped")
    expect(booking["67320"]["status_label"] == "Upcoming closure" and (booking["67320"].get("upcoming_closure") or {}).get("start") == "2026-11-15", "mambray is upcoming from 15 Nov")
    expect((booking["67320"].get("upcoming_closure") or {}).get("reopen") == "2026-11-20" and booking["67320"]["upcoming_closure"].get("start_time") == "18:00", "mambray reopens 20 Nov")
    expect(booking["73157"]["closure"]["start"] == "2026-10-31" and booking["73157"]["closure"]["reopen"] == "2026-11-12" and booking["73157"]["closure"]["reopen_time"] == "21:00", "grindells records the gammon window")
    expect("9pm" in booking["73157"]["notice_summary"] and "pest animal" in booking["73157"]["notice_summary"], "grindells quotes the official hours and reason")
    expect(booking["73202"]["status_label"] == "Alert in this park" and booking["73202"]["status"] != "closed" and booking["73139"]["notice_status"] == "park_alert", "innamincka camps are a park alert")
    box = booking["73218"]
    expect(box["status_label"] == "Upcoming closure" and box["status"] != "closed" and box["notice_status"] == "upcoming", "box flat is upcoming before 11 nov")
    expect(box["notice_url"].endswith("ngarkat-conservation-park-15"), "box flat links the ngarkat notice")
    expect("11 November 2026" in box["notice_summary"] and "18 November 2026" in box["notice_summary"] and "pest control" in box["notice_summary"], "box flat quotes the dates and reason")
    expect((box.get("upcoming_closure") or {}).get("start") == "2026-11-11" and box["upcoming_closure"].get("start_time") == "06:00", "box flat starts 6am 11 nov")
    expect(box["upcoming_closure"].get("reopen") == "2026-11-18" and box["upcoming_closure"].get("reopen_time") == "06:00", "box flat reopens 6am 18 nov")
    window = notice_phase.notice_window(box)
    expect(window is not None and window[2] == "upcoming", "box flat page carries the build-time upcoming label")
    expect(window[0].isoformat() == "2026-11-11T06:00:00+10:30" and window[1].isoformat() == "2026-11-18T06:00:00+10:30", "box flat instants stay in Adelaide time")
    expect("data-notice-start=\"2026-11-11T06:00:00+10:30\"" in notice_phase.notice_attr(box), "box flat attributes name the start")
    before_phase = dt.datetime(2026, 11, 11, 5, 59, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    expect(notice_phase.phase_at(window[0], window[1], before_phase) == "upcoming", "view time is upcoming at 5:59am")
    at_open_phase = dt.datetime(2026, 11, 11, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    at_end_phase = dt.datetime(2026, 11, 18, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    just_before_end = dt.datetime(2026, 11, 18, 5, 59, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    expect(notice_phase.phase_at(window[0], window[1], at_open_phase) == "closed", "view time is closed at 6:00am")
    expect(notice_phase.phase_at(window[0], window[1], just_before_end) == "closed", "view time stays closed until 6:00am on the 18th")
    expect(notice_phase.phase_at(window[0], window[1], at_end_phase) == "ended", "view time ends at 6:00am on the 18th")
    phase_node = subprocess.run(
        ["node", "-e", notice_phase.PHASE_JS + """
        const at = (iso) => noticePhase("2026-11-11T06:00:00+10:30", "2026-11-18T06:00:00+10:30", Date.parse(iso));
        if (at("2026-11-11T05:59:00+10:30") !== "upcoming") process.exit(1);
        if (at("2026-11-11T06:00:00+10:30") !== "closed") process.exit(1);
        if (at("2026-11-18T05:59:00+10:30") !== "closed") process.exit(1);
        if (at("2026-11-18T06:00:00+10:30") !== "ended") process.exit(1);
        if (noticePhase("2026-11-11T06:00:00+10:30", "", Date.parse("2026-11-12T00:00:00+10:30")) !== "closed") process.exit(1);
        """],
        cwd=ROOT, capture_output=True, text=True,
    )
    expect(phase_node.returncode == 0, "browser phase matches Adelaide instants: " + (phase_node.stderr or phase_node.stdout)[-200:])
    for outside in ("73215", "73217", "86453", "73216", "73207", "73211"):
        row = booking[outside]
        expect(row["status_label"] == "No current notice" and row["notice_status"] == "no_current_notice" and not row["notice_url"] and row["status"] != "closed", "ngarkat camp outside the hatched blocks stays a no-notice camp: " + outside)
    before_open = dt.datetime(2026, 11, 11, 5, 59, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    at_open = dt.datetime(2026, 11, 11, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    during_ngarkat = dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    at_end = dt.datetime(2026, 11, 18, 6, 0, tzinfo=dt.timezone(dt.timedelta(hours=10, minutes=30)))
    expect(act_sa_notices.evaluate_all(notices, before_open)["bookings"]["73218"] == "upcoming", "box flat is not closed at 5:59am")
    expect(act_sa_notices.evaluate_all(notices, at_open)["bookings"]["73218"] == "closed", "box flat closes at 6am 11 nov")
    during_ng = act_sa_notices.evaluate_all(notices, during_ngarkat)
    expect(during_ng["by_index"][50]["camp_status"] == "partial" and during_ng["bookings"]["73218"] == "closed", "the park closure is partial and box flat is closed")
    expect(during_ng["bookings"].get("73215") is None and "73207" not in during_ng["bookings"], "camps outside the blocks are not attached")
    expect(act_sa_notices.evaluate_all(notices, at_end)["bookings"]["73218"] == "expired_not_open", "box flat is not open when the window ends")
    closed_box = sa_inventory.load_camps(set(), moment=during_ngarkat)
    closed_box = {item: row for row in closed_box for item in row.get("booking_ids") or []}["73218"]
    expect(closed_box["status"] == "closed" and closed_box["status_label"] == "Closed" and closed_box["closure"]["start"] == "2026-11-11", "box flat page is closed during the window")
    flood = "Parks SA says Malkumba-Coongie Lakes National Park and significant parts of Innamincka Regional Reserve are closed until further notice because of a major flood. This camp isn't named, so check before travelling."
    for innamincka in ("73202", "73138", "73139", "73142"):
        row = booking[innamincka]
        expect(row["status_label"] == "Alert in this park" and row["status"] != "closed" and row["notice_status"] == "park_alert", "innamincka camp stays an alert: " + innamincka)
        expect(row["notice_summary"] == flood and row["notice_url"].endswith("innamincka-regional-reserve-2"), "the flood notice is quoted and not treated as a camp closure: " + innamincka)
    council = next(row for row in sa_camps if row["source"] == "council" and row["notice_status"] == "no_current_notice")
    expect("Parks SA" not in council["notice_summary"], "council camps do not get Parks SA notice wording")
    expect(sa_inventory.notice_is_current({"source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example"}, {"urls": ["https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example"], "http_status": {}}) is True, "an indexed notice stays")
    expect(sa_inventory.notice_is_current({"source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example"}, {"urls": ["https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example"], "http_status": {"https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example": 404}}) is False, "a 404 notice is dropped")
    expect(sa_inventory.notice_is_current({"source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/missing"}, {"urls": ["https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/example"], "http_status": {}}) is False, "a notice off the index is dropped")
    quiet = next(row for row in sa_camps if row["notice_status"] == "no_current_notice")
    expect(quiet["status_label"] == "No current notice" and quiet["status"] != "open", "no notice is not open")
    expect(all(sa_inventory.ATTRIBUTION in row["attribution"] for row in sa_camps if row["source"] == "parks_sa"), "parks attribution")
    expect(all(row["fire_link"]["rating"] is None and row["fire_link"]["url"].startswith("https://www.cfs.sa.gov.au/") for row in sa_camps), "cfs link without a rating")
    expect(sum(1 for row in sa_camps if row["needs_review"]) == 0, "finished checks are no longer flagged")
    expect("district polygons" in " ".join(sa_inventory.FIRE_NEEDED), "fire gap named")
    saved_preview = os.environ.get("CAMPCONDITIONS_PREVIEW")
    saved_out = os.environ.get("CAMPCONDITIONS_OUT")
    try:
        os.environ.pop("CAMPCONDITIONS_PREVIEW", None)
        os.environ.pop("CAMPCONDITIONS_OUT", None)
        expect([state["slug"] for state in states.page_states()] == ["vic", "nsw", "qld", "sa", "tas"], "public pages include sa")
        os.environ["CAMPCONDITIONS_PREVIEW"] = "sa"
        os.environ["CAMPCONDITIONS_OUT"] = os.path.join(ROOT, "dist")
        try:
            states.page_states()
            expect(False, "preview refuses dist")
        except SystemExit:
            expect(True, "preview refuses dist")
        preview_out = tempfile.mkdtemp(prefix="sa-inventory-preview-")
        os.environ["CAMPCONDITIONS_OUT"] = preview_out
        expect([state["slug"] for state in states.page_states()] == ["vic", "nsw", "qld", "sa", "tas"], "preview does not duplicate sa")
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "sa stays enabled")
        expect("act" not in [state["slug"] for state in states.enabled()], "preview does not enable act")
    finally:
        if saved_preview is None:
            os.environ.pop("CAMPCONDITIONS_PREVIEW", None)
        else:
            os.environ["CAMPCONDITIONS_PREVIEW"] = saved_preview
        if saved_out is None:
            os.environ.pop("CAMPCONDITIONS_OUT", None)
        else:
            os.environ["CAMPCONDITIONS_OUT"] = saved_out

    sample = open(os.path.join(ROOT, "data", "act-sa", "fixtures", "fire", "cfs-sample.xml"), "rb").read()
    parsed_sample = sa_fire.parse_feed(sample)
    expect(parsed_sample["ok"] is True, "cfs sample parses")
    expect(parsed_sample["updated"].utcoffset() == dt.timedelta(hours=9, minutes=30), "updated keeps +09:30")
    lofty = parsed_sample["districts"].get("MOUNT LOFTY RANGES")
    expect(lofty and lofty["periods"][0]["date"] == "2026-11-09" and lofty["periods"][0]["rating"] == "Moderate" and lofty["periods"][0]["ban"] is False, "period date is Adelaide")
    expect("SOUTH AUSTRALIA" not in parsed_sample["districts"], "region row is not a district")
    expect(sa_fire.parse_feed(b"not xml")["ok"] is False, "bad xml is not a rating")
    cross = open(os.path.join(ROOT, "data", "act-sa", "fixtures", "fire", "district-crosswalk.csv"), encoding="utf-8").read().strip().splitlines()[1:]
    expect(len(cross) == 15, "15 fire districts")
    expect(all(line.split(",")[0].upper() == line.split(",")[1].upper() for line in cross), "district names join in upper case")

    def placed(lon, lat, status="check"):
        return {
            "lon": lon, "lat": lat, "status": status,
            "closure": {"desc": "notice"} if status == "closed" else None,
            "status_label": "Closed" if status == "closed" else "No current notice",
        }

    def box(name, west, south, east, north):
        return {
            "type": "Feature",
            "properties": {"firebandistrict": name},
            "geometry": {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]]},
        }

    zones = sa_fire.polygons_from_geojson({"features": [
        box("MOUNT LOFTY RANGES", 138, -35, 139, -34),
        box("WEST COAST", 133, -33, 134, -32),
        box("FLINDERS", 138, -32, 139, -31),
    ]})
    now = dt.datetime(2026, 11, 9, 20, 0, tzinfo=ADELAIDE)
    fresh_feed = {
        "ok": True,
        "updated": dt.datetime(2026, 11, 9, 16, 41, 24, tzinfo=dt.timezone(dt.timedelta(hours=9, minutes=30))),
        "districts": {
            "MOUNT LOFTY RANGES": {"name": "Mount Lofty Ranges", "periods": [
                {"date": "2026-11-09", "rating": "Moderate", "ban": False},
                {"date": "2026-11-09", "rating": "No Rating", "ban": False},
            ]},
            "WEST COAST": {"name": "West Coast", "periods": [{"date": "2026-11-09", "rating": "Extreme", "ban": True}]},
            "FLINDERS": {"name": "Flinders", "periods": [{"date": "2026-11-09", "rating": "Catastrophic", "ban": True}]},
        },
    }
    fresh_feed["districts"]["MOUNT LOFTY RANGES"]["periods"] = [{"date": "2026-11-09", "rating": "Moderate", "ban": False}]
    inside = placed(138.5, -34.5)
    banned = placed(133.5, -32.5, status="closed")
    catastrophic = placed(138.5, -31.5)
    outside = placed(139.03, -34.5)
    near = placed(139.004, -34.5)
    unrated = placed(133.5, -32.5)
    only_lofty = dict(fresh_feed, districts={"MOUNT LOFTY RANGES": fresh_feed["districts"]["MOUNT LOFTY RANGES"]})
    sa_fire.assign([inside, banned, catastrophic, outside, near], fresh_feed, zones, now)
    expect(inside["fire"]["district"] == "Mount Lofty Ranges" and inside["fire"]["rating"] == "Moderate" and inside["status"] == "check", "district join")
    expect(banned["fire"]["rating"] == "Extreme" and banned["status"] == "closed" and banned["closure"]["desc"] == "notice", "ban does not close")
    expect("rings" not in banned["fire"] and "prep" not in banned["fire"], "polygon geometry stays off the camp")
    banned_html = sa_fire.html_line(banned)
    expect("Total Fire Ban: fires banned" in banned_html and sa_fire.CATASTROPHIC_LINE not in banned_html, "extreme ban has no closure claim")
    cat_html = sa_fire.html_line(catastrophic)
    expect(sa_fire.CATASTROPHIC_LINE in cat_html and sa_fire.PARKS_FIRE_URL in cat_html and catastrophic["status"] == "check", "catastrophic wording")
    expect(sa_fire.CFS_CREDIT in cat_html, "cfs credit")
    expect(outside.get("fire_unmapped", {}).get("label") == "No fire district mapped" and not outside.get("fire"), "outside 1 km is unmapped")
    expect(near.get("fire", {}).get("rating") == "Moderate" and "fallback_km" in near.get("fire", {}), "within 1 km uses that district")
    sa_fire.assign([unrated], only_lofty, zones, now)
    expect(unrated.get("fire_link", {}).get("label") == "Fire danger: unknown." and not unrated.get("fire"), "missing district is not a neighbour rating")
    no_rating = placed(138.5, -34.5)
    rating_feed = dict(fresh_feed, districts={"MOUNT LOFTY RANGES": {"name": "Mount Lofty Ranges", "periods": [{"date": "2026-11-09", "rating": "No Rating", "ban": False}]}})
    sa_fire.assign([no_rating], rating_feed, zones, now)
    no_rating_html = sa_fire.html_line(no_rating)
    expect("No Rating" in no_rating_html and "No fire district mapped" not in no_rating_html, "official No Rating stays the category")
    stale_feed = dict(fresh_feed, updated=now - dt.timedelta(hours=36, minutes=1))
    stale_camp = placed(138.5, -34.5, status="closed")
    sa_fire.assign([stale_camp], stale_feed, zones, now)
    expect(stale_camp.get("fire_link", {}).get("label") == "Fire danger: unknown." and not stale_camp.get("fire") and stale_camp["status"] == "closed", "stale feed is unknown")
    missing = placed(138.5, -34.5)
    sa_fire.assign([missing], {"ok": False, "updated": None, "districts": {}}, zones, now)
    expect(missing.get("fire_link", {}).get("url") == sa_fire.CFS_PAGE and not missing.get("fire"), "missing feed is the link-out")
    expect(sa_fire.fresh(now - dt.timedelta(hours=36), now) is True, "36 hours is still fresh")
    link_camp = placed(138.5, -34.5, status="closed")
    os.environ["SA_FIRE_MODE"] = "linkout"
    try:
        def refuse_fetch(*_args):
            raise AssertionError("linkout fetched a CFS source")
        sa_fire.apply([link_camp], {"sources": {"cfs_fdr": {"url": "https://example.invalid/feed"}, "cfs_districts": {"url": "https://example.invalid/zip"}}}, refuse_fetch)
    finally:
        os.environ.pop("SA_FIRE_MODE", None)
    link_html = sa_fire.html_line(link_camp)
    expect(link_camp.get("sa_fire_mode") == "linkout" and not link_camp.get("fire") and not link_camp.get("fire_link"), "linkout stores no rating")
    expect(sa_fire.LINKOUT_LINE in link_html and sa_fire.CFS_PAGE in link_html and sa_fire.CATASTROPHIC_LINE in link_html, "linkout line and parks sentence")
    council_html = sa_fire.html_line(dict(link_camp, source="council"))
    expect(sa_fire.LINKOUT_LINE in council_html and sa_fire.CATASTROPHIC_LINE not in council_html and "fire-sa-other" in council_html, "council camps do not get the Parks SA fire sentence")
    expect("No Rating" not in link_html and "No rating" not in link_html and "Mount Lofty" not in link_html, "linkout names no rating and no district")
    expect(link_camp["status"] == "closed", "linkout leaves a closure alone")
    os.environ["SA_FIRE_MODE"] = "nope"
    try:
        sa_fire.mode()
        expect(False, "bad fire mode is rejected")
    except SystemExit:
        expect(True, "bad fire mode is rejected")
    finally:
        os.environ.pop("SA_FIRE_MODE", None)
    expect(sa_signup.mode() == "coming_soon" and sa_signup.forms_allowed() is False, "signup stays closed without a segment")
    os.environ["SA_SIGNUP_MODE"] = "open"
    try:
        expect(sa_signup.mode() == "coming_soon" and sa_signup.forms_allowed() is False, "open mode without a segment stays closed")
    finally:
        os.environ.pop("SA_SIGNUP_MODE", None)
    os.environ["SA_SIGNUP_MODE"] = "open"
    os.environ["RESEND_SEGMENT_SA_ID"] = "sa-segment"
    try:
        expect(sa_signup.mode() == "open" and sa_signup.forms_allowed() is False, "a segment does not open signup while the flag is off")
    finally:
        os.environ.pop("SA_SIGNUP_MODE", None)
        os.environ.pop("RESEND_SEGMENT_SA_ID", None)
    soon = sa_signup.coming_soon_html()
    expect(sa_signup.COMING_SOON in soon and "<form" not in soon and "/api/subscribe" not in soon, "coming soon has no form")

    expect([state["slug"] for state in states.signup_states()] == ["vic", "nsw", "qld"], "signup offers the three public states")
    refused = sa_digest.send_decision({"RESEND_SEGMENT_SA_ID": "abc"}, False)
    expect(refused["send"] is False and refused["reason"] == "region_disabled" and refused["called_resend"] is False, "disabled region refuses send")
    unset = sa_digest.send_decision({}, True)
    expect(unset["send"] is False and unset["reason"] == "segment_unset" and unset["called_resend"] is False, "unset segment refuses send")
    blocked = sa_digest.perform_send({"RESEND_SEGMENT_SA_ID": "abc"}, True)
    expect(blocked["send"] is False and blocked["reason"] == "resend_not_called" and blocked["called_resend"] is False, "send path does not call resend")
    digest_dir = tempfile.mkdtemp(prefix="sa-digest-")
    digest_meta = sa_digest.write_preview(digest_dir, sa_inventory.load_camps(set()), dt.datetime(2026, 11, 9, 12, tzinfo=ADELAIDE))
    digest_html = open(os.path.join(digest_dir, "digest.html"), encoding="utf-8").read()
    digest_text = open(os.path.join(digest_dir, "digest.txt"), encoding="utf-8").read()
    for heading in ("Closed", "Partial", "Upcoming", "Reopened", "Fire danger and Total Fire Ban", "Chip in"):
        expect(heading in digest_html and heading in digest_text, "digest heading " + heading)
    expect("Do not send" in digest_text and "{{{EMAIL}}}" not in digest_html and digest_meta.get("send") is False, "digest preview is local")
    expect(sa_digest.CFS_CREDIT in digest_html, "digest cfs credit")
    try:
        sa_digest.write_preview(os.path.join(ROOT, "dist", "sa-digest"), [])
        expect(False, "digest refuses dist")
    except SystemExit:
        expect(True, "digest refuses dist")
    gate_root = tempfile.mkdtemp(prefix="sa-gate-")
    gate_dist = os.path.join(gate_root, "dist")
    gate_preview = os.path.join(gate_root, "preview")
    os.makedirs(gate_dist)
    with open(os.path.join(gate_dist, "index.html"), "w", encoding="utf-8") as handle:
        handle.write('<input type="checkbox" name="states" value="vic"><input type="checkbox" name="states" value="nsw"><input type="checkbox" name="states" value="qld"><a href="/sa/">South Australia</a>')
    os.makedirs(os.path.join(gate_dist, "sa"))
    os.makedirs(os.path.join(gate_preview, "sa", "camp", "one"))
    coming = sa_signup.COMING_SOON
    fire_line = sa_fire.LINKOUT_LINE + " " + sa_fire.CFS_PAGE + " " + sa_fire.CATASTROPHIC_LINE
    with open(os.path.join(gate_preview, "sa", "index.html"), "w", encoding="utf-8") as handle:
        handle.write(sa_inventory.ATTRIBUTION + ' <a href="/sa/camp/one/">One</a> ' + coming)
    with open(os.path.join(gate_preview, "sa", "camp", "one", "index.html"), "w", encoding="utf-8") as handle:
        handle.write(sa_inventory.ATTRIBUTION + ' <a href="/sa/">Back</a> ' + coming + " " + fire_line)
    gate = sa_launch_gate.evaluate(gate_dist, gate_preview, dt.datetime(2026, 11, 9, 21, 0, tzinfo=ADELAIDE))
    gate_by = {item["check"]: item for item in gate["checks"]}
    expect(gate["pass"] is False and gate["fire_licence_resolved"] is False and gate["sa_fire_mode"] == "full", "gate fails on the licence flag")
    expect(gate_by["fire_licence_resolved"]["pass"] is False, "licence check is false")
    expect(gate_by["inventory"]["pass"] and gate_by["notice_parser_freshness"]["pass"] and gate_by["fire_feed_freshness"]["pass"], "inventory and freshness pass")
    expect(gate_by["sa_signup"]["pass"] and gate["sa_signup_mode"] == "coming_soon", "signup mode is coming soon")
    expect(gate_by["digest_preview"]["pass"] and gate_by["public_sa"]["pass"], "digest and public build checks")
    expect(gate_by["sa_preview_links"]["pass"] and gate_by["sa_attribution"]["pass"], "preview links and attribution")
    os.environ["SA_FIRE_MODE"] = "linkout"
    try:
        opened = sa_launch_gate.evaluate(gate_dist, gate_preview, dt.datetime(2026, 11, 9, 21, 0, tzinfo=ADELAIDE))
    finally:
        os.environ.pop("SA_FIRE_MODE", None)
    opened_by = {item["check"]: item for item in opened["checks"]}
    expect(opened["sa_fire_mode"] == "linkout" and opened["sa_signup_mode"] == "coming_soon", "gate records linkout and coming soon")
    expect(opened_by["fire_licence_resolved"]["pass"] and opened_by["fire_feed_freshness"]["pass"] and opened_by["sa_signup"]["pass"], "linkout passes the fire check")
    expect(opened["pass"] is True and opened["fire_licence_resolved"] is False, "linkout can pass while the licence conflict remains")

    if FAILURES:
        print("ACT/SA foundation failures: %s" % len(FAILURES))
        for label in FAILURES:
            print(" FAIL", label)
        return 1
    print("ACT/SA foundation checks passed: %s" % CHECKS)
    return 0


NODE = r"""
import { chosenStates, heldSignupStates, heldSignupPreview, makeToken, readToken, saDigestSend } from "./functions/_lib/token.js";
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
if (plan.refuse !== "not_open" || plan.segmentIds.length || plan.sa.send) process.exit(12);
const disabledSend = saDigestSend(env);
if (disabledSend.send || disabledSend.reason !== "region_disabled" || disabledSend.calledResend) process.exit(15);
const unsetSend = saDigestSend({ ...env, RESEND_SEGMENT_SA_ID: "" }, true);
if (unsetSend.send || unsetSend.reason !== "segment_unset") process.exit(16);
const readySend = saDigestSend(env, true);
if (!readySend.send || readySend.segmentId !== "sa-segment" || readySend.calledResend) process.exit(17);
"""


if __name__ == "__main__":
    sys.exit(main())
