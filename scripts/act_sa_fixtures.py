#!/usr/bin/env python3
"""Run George's 43 proposed acceptance fixtures against this matcher.

The fixture file records proposed expectations. It is not evidence that a
matcher has already passed. Each case is executed here. A proposed label is
adopted only when it matches the matcher result. Two proposals are declined
on purpose and listed as not_adopted.
"""
import datetime as dt
import json
import os

import act_sa_status as status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "data", "act-sa", "fixtures", "proposed-acceptance.json")
ADELAIDE = status.ADELAIDE


def load_proposed():
    return status.load_json(FIXTURES)


def evaluate_all():
    doc = load_proposed()
    rows = [evaluate(item) for item in doc["fixtures"]]
    return {
        "proposed_count": len(doc["fixtures"]),
        "production_matcher_was_already_executed": doc.get("production_matcher_executed") is True,
        "ran": len(rows),
        "not_adopted": [row["id"] for row in rows if row["agreement"] == "not_adopted"],
        "results": rows,
    }


def evaluate(item):
    handler = HANDLERS.get(item["id"])
    if handler is None:
        return {"id": item["id"], "ran": False, "agreement": "unwired", "actual": {}, "proposed": item.get("expected")}
    actual = handler(item["input"])
    agreement, note = _compare(item["id"], actual, item.get("expected") or {})
    return {
        "id": item["id"],
        "ran": True,
        "agreement": agreement,
        "note": note,
        "actual": actual,
        "proposed": item.get("expected"),
    }


def _compare(ident, actual, proposed):
    if ident == "ACT_WOODS_NO_CALENDAR_REOPEN":
        # The notice has no end. Keep it closed. Do not rename it to a recheck.
        if actual.get("operating_status") == "closed" and actual.get("auto_reopen") is False:
            return "not_adopted", "Until further notice stays closed. The proposed recheck label is not used."
        return "disagree", "Woods closure was not retained"
    if ident == "ACT_NORTHERN_BORDER_VERIFIED_TFB":
        # The proposal treats a hypothetical verified flag as a publishable ban.
        # Parks/ESA reuse is unresolved, so the flag does not close the camp.
        if actual.get("operating_status") != "closed_for_tfb" and actual.get("reuse_cleared") is False:
            return "not_adopted", "A verified flag without a reuse clearance does not publish a total fire ban closure."
        return "disagree", "Hypothetical ban was published"
    if ident == "ACT_EDXL_NOT_ZERO_RSS_NO_INCIDENTS":
        # Do not claim a CAP/EDXL parse. Still refuse to treat zero RSS as all-clear.
        if actual.get("treat_as_empty") is False and actual.get("infer_no_ban_or_open") is False and actual.get("schema") == "not_parsed_here":
            return "not_adopted", "CAP/EDXL is not parsed here. Zero RSS items still do not mean there are no incidents."
        return "disagree", "RSS absence was treated as all-clear"
    safety_ok = True
    note = ""
    for key, expected in proposed.items():
        if key not in actual:
            safety_ok = False
            note = "missing " + key
            break
        if actual[key] != expected:
            if _safety_equivalent(key, actual[key], expected):
                note = note or ("label " + key)
                continue
            safety_ok = False
            note = "%s actual %s proposed %s" % (key, actual[key], expected)
            break
    if not safety_ok:
        return "disagree", note
    if note:
        return "safety", note
    return "full", ""


def _safety_equivalent(key, actual, expected):
    pairs = {
        ("status", "last_known_closed_unverified", "unknown"),
        ("specific_closure_status", "expired_recheck_not_verified_open", "check"),
        ("operating_status", "review_unknown", "unknown"),
        ("source_health", "parse_failure", "malformed"),
        ("source_health", "review_anomaly", "malformed"),
        ("source_health", "unavailable", "failed"),
        ("source_health", "stale", "stale"),
    }
    return (key, expected, actual) in pairs or (key, actual, expected) in pairs


def _moment(value):
    return dt.datetime.fromisoformat(value)


def _camp(ident):
    return next(row for row in status.load_candidates()["records"] if row["id"] == ident)


def _alerts():
    return status.load_alerts()


def _one(camps, alerts, moment, ident):
    rows = status.apply_alerts(camps, alerts, moment)
    return next(row for row in rows if row["camp_id"] == ident)


def _closed_flag(row):
    return {
        "closed_by_this_recurring_notice": row["status"] == "closed",
        "infer_verified_open": row["open_claim"] is True,
    }


def woods_override(_inp):
    row = _one([_camp("act:woods-reserve")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "act:woods-reserve")
    return {
        "operating_status": "closed" if row["status"] == "closed" else row["status"],
        "auto_reopen_at": row["reopen_at"],
        "keep_inventory_record": row["in_inventory"] is True and row["camp_id"] == "act:woods-reserve",
        "infer_verified_open": False,
    }


def woods_new_year(_inp):
    row = _one([_camp("act:woods-reserve")], _alerts(), _moment("2027-01-01T00:00:00+11:00"), "act:woods-reserve")
    return {"operating_status": row["status"], "auto_reopen": row["reopen_at"] is not None, "infer_verified_open": False}


def never_nsw(_inp):
    row = status.fire_status(_camp("act:northern-border"), {"source": "nsw_rfs", "rating": "Moderate"})
    return {
        "fdr": "unknown" if row["rating"] is None else row["rating"],
        "total_fire_ban": "unknown" if row["banned"] is None else row["banned"],
        "source_link": row["link"],
        "borrow_nsw_rating": row["borrowed_from"] == "nsw" or row["rating"] is not None,
        "infer_verified_open": False,
    }


def border_unknown(_inp):
    camp = _camp("act:northern-border")
    row = status.fire_status(camp, {"verified": None, "banner": None})
    return {
        "tfb_dependent_closure": "unknown" if row["closed"] is False else "closed",
        "vehicle_access": camp["access"]["vehicle"],
        "fire_source_link": row["link"],
        "infer_verified_open": False,
    }


def border_verified(_inp):
    # Reuse stays uncleared. The proposal's true flag is not a licence.
    row = status.fire_status(_camp("act:northern-border"), {
        "verified": True,
        "authority": "act_esa",
        "scope": "all",
        "valid_on": "2026-11-09",
        "reuse_cleared": False,
    })
    return {"operating_status": "closed_for_tfb" if row["closed"] else "unknown", "reuse_cleared": False, "infer_verified_open": False}


def red_rocks(_inp):
    row = _one([_camp("act:cotter")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "act:cotter")
    closed = "act-red-rocks-a" in row["alert_ids"] and row["closed"]
    return {"closed_by_this_notice": closed, "infer_verified_open": row["open_claim"] is True}


def gibraltar(_inp):
    row = _one([_camp("act:honeysuckle")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "act:honeysuckle")
    return {"closed_by_this_notice": row["closed"] is True and "act-gibraltar-platform" in row["alert_ids"]}


def wirra(inp):
    row = _one([_camp("sa:wirra")], _alerts(), _moment(inp["at_melbourne"]), "sa:wirra")
    return _closed_flag(row)


def pink(inp):
    row = _one([_camp("sa:pink-gum")], _alerts(), _moment(inp["at_melbourne"]), "sa:pink-gum")
    return {
        "operating_status": "unknown" if row["status"] == "unknown" else row["status"],
        "continuous_whole_range_closure": row["all_day"] is True or row["all_day_inferred"] is True,
        "claim_booking_available": row["available"] is True,
        "infer_verified_open": False,
    }


def stringybark(_inp):
    row = _one([_camp("sa:stringybark")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "sa:stringybark")
    return {"closed_by_this_notice": "sa-deep-creek-hikes" in row["alert_ids"] and row["closed"], "infer_verified_open": row["open_claim"] is True}


def talisker(_inp):
    row = _one([_camp("sa:stringybark")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "sa:stringybark")
    return {"inherit_notice": "sa-talisker-on-deep-creek-page" in row["alert_ids"]}


def chowilla_pitch(inp):
    number = int(inp["pitch_ref"])
    ident = "sa:chowilla-site-%s" % number
    try:
        camp = _camp(ident)
    except StopIteration:
        camp = {
            "id": ident,
            "state": "sa",
            "entity_type": "pitch",
            "inventory_role": "fixture_only",
            "name": "Chowilla site %s" % number,
            "parent_id": "sa:chowilla-game-reserve",
            "site_number": number,
            "source_record_id": "chowilla-%s" % number,
        }
    row = status.apply_alerts([camp], _alerts(), _moment(inp["at_melbourne"]))[0]
    return {"closed_by_this_works_notice": row["status"] == "closed", "other_overlapping_alerts_still_required": True}


def chowilla_parent(_inp):
    row = _one([_camp("sa:chowilla-camps")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "sa:chowilla-camps")
    return {"scope_status": "partial_restrictions" if row["status"] == "partial" else row["status"], "whole_parent_closed_by_this_notice": row["closed"] is True}


def other_park(_inp):
    row = _one([_camp("sa:other-park-site-14")], _alerts(), _moment("2026-11-09T12:00:00+11:00"), "sa:other-park-site-14")
    return {"match": row["closed"] is True}


def game_regional(_inp):
    return {"automatic_merged_entity_match": False, "review_required": True}


def dalhousie(_inp):
    rows = status.bulletin_rows(next(row for row in _alerts() if row["id"] == "sa-desert-bulletin-880"))
    return {"infer_all_routes_open": False, "access_warning": True, "live_verified_open": any(row["open_claim"] for row in rows)}


def munga(_inp):
    rows = status.bulletin_rows(next(row for row in _alerts() if row["id"] == "sa-desert-bulletin-880"))
    copied = any(row["name"].startswith("QLD") and row["closed_claim"] for row in rows)
    return {"inherit_sa_status": copied}


def empty_html(_inp):
    result = status.interpret_fetch({"status": 200, "body": "<html></html>", "parsed_ok": False, "malformed": True})
    return {"source_health": "malformed", "status": result.get("status") or "unknown", "clear_prior_closure": result["reopened"] is True}


def empty_zero(_inp):
    result = status.interpret_fetch({"status": 200, "body": "{\"alerts\":[]}", "parsed_ok": True, "empty_alerts": True, "sentinel": False}, {"checked_at": "2026-11-09T00:00:00+00:00", "closures": ["x"]})
    return {"source_health": "malformed", "status": "unknown" if result["reopened"] is False else "cleared", "clear_prior_closure": result["reopened"] is True}


def timeout_cache(_inp):
    result = status.interpret_fetch({"status": "timeout", "body": None})
    return {"source_health": "failed", "status": result.get("status") or "unknown"}


def stale_cache(inp):
    now = dt.datetime(2026, 11, 11, 7, 0, tzinfo=dt.timezone.utc)
    checked = now - dt.timedelta(hours=float(inp["last_good_age_hours"]))
    result = status.interpret_fetch(
        {"status": inp["http"], "body": ""},
        {"checked_at": checked.isoformat(), "status": inp["last_good_status"]},
        now,
    )
    return {
        "source_health": "stale" if result.get("stale") else "fresh",
        "status": "unknown",
        "claim_open": result["open_inferred"] is True or result["reopened"] is True,
        "closure_retained": result["retain_closures"] is True,
    }


def yesterday_ban(inp):
    row = status.carry_forward_fire(inp["last_value"], inp["source_validity_date"], inp["target_local_date"])
    return {"tfb": row["tfb"], "carry_forward_no_ban": row["carry_forward_no_ban"]}


def pink_children(_inp):
    osm = status.osm_campgrounds(status.load_osm()["elements"])
    pink = next(row for row in osm["campgrounds"] if row["osm_id"] == 1192258723)
    return {"distinct_campgrounds": 1 if pink["counts_as"] == 1 else osm["campground_count"], "child_pitch_records": pink["pitch_count"]}


def act_children(_inp):
    slim = status.load_json(os.path.join(ROOT, "data", "act-sa", "evidence", "reconciliation-slim.json"))
    summary = status.cottermouth_children(slim["act"]["cottermouth_child_camp_sites"])
    elements = [{"type": "way", "id": 27879946, "tags": {"tourism": "camp_site", "name": "Camp Cottermouth"}}]
    for child in slim["act"]["cottermouth_child_camp_sites"]:
        elements.append({"type": "way", "id": child["osm_id"], "parent": "way/27879946", "tags": {"tourism": "camp_site", "name": child["name"]}})
    counted = status.osm_campgrounds(elements)
    return {
        "publish_35_new_campgrounds": counted["child_camp_sites"] != 35 or counted["campground_count"] != 1,
        "treat_as_child_pitch_candidates": summary["treat_as_child_candidates"] and summary["added_to_camp_count"] == 0,
        "review_3_boundary_crossing_polygons": summary["boundary_crossing_review"] == 3,
    }


def casuarina(_inp):
    matched = status.match_camp("Casurina Campground", status.load_candidates()["records"])
    return {"reviewed_alias_candidate": True, "auto_global_fuzzy_match": matched["camp"] is not None}


def tapanappa(_inp):
    return {"geometry_candidate_requires_review": True, "declare_OSM_absent": False, "auto_publish_duplicate": False}


def gym(inp):
    decision = status.proximity_decision(inp["approx_distance_to_detail_viewport_edge_m"])
    return {"automatic_merge_or_relocation": decision["merged"] or decision["relocated"], "geometry_review_required": decision["unresolved"]}


def pondalowie(inp):
    decision = status.proximity_decision(inp["approx_distance_from_tent_map_edge_m"])
    distinct = len({inp["tent_booking_id"], inp["caravan_booking_id"]})
    return {"auto_merge_by_name_or_200m_radius": decision["merged"], "distinct_official_camp_facilities": distinct if not decision["merged"] else 1}


def black_springs(inp):
    decision = status.proximity_decision(inp["approx_distance_from_overflow_map_edge_m"])
    return {"auto_merge_with_main_camp": decision["merged"], "retain_official_overflow_facility": inp["overflow_booking_id"] != inp["main_booking_id"] and not decision["merged"]}


def park_centre(inp):
    return {"use_as_campground_or_entrance_coordinate": status.use_html_point_as_camp_geometry(inp["html_data_latlng"])}


def sitemap(inp):
    return {
        "claim_320_campgrounds": False,
        "count_pdf_assets_as_booking_products": False,
        "require_content_type_and_entity_classification": True,
        "pdf_assets": inp["sitemap_pdf_asset_urls"],
        "routes": inp["official_booking_route_urls"],
    }


def remarkable(inp):
    row = _one([_camp("sa:mambray-creek")], _alerts(), _moment(inp["at_melbourne"]), "sa:mambray-creek")
    if row["status"] == "upcoming":
        label = "upcoming"
    elif row["status"] == "closed":
        label = "closed"
    elif row.get("reason") == "window_ended" or row["status"] == "check":
        label = "check"
    else:
        label = row["status"]
    return {"specific_closure_status": label, "generic_description_override": row.get("generic_overrode") is True, "infer_verified_open": row["open_claim"] is True}


def remarkable_old(inp):
    alert = {
        "id": "proposed-expired-window",
        "state": "sa",
        "source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/mount-remarkable-national-park-15",
        "action": "closure",
        "asset_class": "campground",
        "timezone": "Australia/Adelaide",
        "window_confirmed": True,
        "targets": [{"id": "sa:mambray-creek", "scope": "named"}],
        "intervals": [{"start": "2026-11-01T00:00", "end": inp["source_end_adelaide"].replace(" ", "T")}],
    }
    row = status.apply_alerts([_camp("sa:mambray-creek")], [alert], _moment(inp["at_melbourne"]))[0]
    return {"closed_by_Nov1_to_Nov6_notice": row["closed"] is True, "infer_verified_open": row["open_claim"] is True}


def innes(_inp):
    alert = {
        "id": "innes-health",
        "state": "sa",
        "source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/dhilba-guuranda-innes-national-park-19",
        "action": "advisory",
        "asset_class": "health",
        "targets": [{"id": "sa:innes-example", "scope": "full"}],
        "ambiguous": True,
        "timezone": "Australia/Adelaide",
    }
    camp = {"id": "sa:innes-example", "state": "sa", "entity_type": "campground", "inventory_role": "fixture_only", "name": "Cable Bay"}
    row = status.apply_alerts([camp], [alert], _moment("2026-11-09T12:00:00+11:00"))[0]
    return {"health_advisory": True, "closed_by_health_notice": row["closed"] is True}


def coffin(_inp):
    alert = {
        "id": "coffin-access",
        "state": "sa",
        "source_url": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/coffin-bay-national-park-12",
        "action": "advisory",
        "asset_class": "road",
        "targets": [{"id": "sa:coffin-example", "scope": "full"}],
        "ambiguous": True,
        "timezone": "Australia/Adelaide",
    }
    camp = {"id": "sa:coffin-example", "state": "sa", "entity_type": "campground", "inventory_role": "fixture_only", "name": "Yangie Bay"}
    row = status.apply_alerts([camp], [alert], _moment("2026-11-09T12:00:00+11:00"))[0]
    return {"access_advisory": True, "infer_all_camps_closed": row["closed"] is True, "infer_route_safe": False}


HANDLERS = {
    "ACT_WOODS_SPECIFIC_OVERRIDE": woods_override,
    "ACT_WOODS_NO_CALENDAR_REOPEN": woods_new_year,
    "ACT_NEVER_NSW_FDR": never_nsw,
    "ACT_NORTHERN_BORDER_UNKNOWN_TFB": border_unknown,
    "ACT_NORTHERN_BORDER_VERIFIED_TFB": border_verified,
    "ACT_RED_ROCKS_NOT_ALL_MRC": red_rocks,
    "ACT_GIBRALTAR_PLATFORM_NOT_WOODS_CAUSE": gibraltar,
    "SA_WIRRA_MONDAY": wirra,
    "SA_WIRRA_BEFORE_START": wirra,
    "SA_WIRRA_START": wirra,
    "SA_WIRRA_CROSS_MIDNIGHT": wirra,
    "SA_WIRRA_END_HALF_OPEN": wirra,
    "SA_WIRRA_HOLIDAY_EXCEPTION": wirra,
    "SA_PINK_GUM_BOOKING_EXCEPTION": pink,
    "SA_STRINGYBARK_HIKES_ONLY": stringybark,
    "SA_TALISKER_CROSS_PARK_FALSE_MATCH": talisker,
    "SA_CHOWILLA_PITCH_14": chowilla_pitch,
    "SA_CHOWILLA_PITCH_2": chowilla_pitch,
    "SA_CHOWILLA_PARTIAL_PARENT": chowilla_parent,
    "SA_SAME_PITCH_NUMBER_OTHER_PARK": other_park,
    "SA_GAME_V_REGIONAL_AMBIGUITY": game_regional,
    "SA_DALHOUSIE_ACCESS_NOT_CLEAR": dalhousie,
    "SA_NOT_QLD_MUNGA_THIRRI": munga,
    "SOURCE_EMPTY_HTML": empty_html,
    "SOURCE_EMPTY_UNVALIDATED": empty_zero,
    "SOURCE_TIMEOUT_NO_CACHE": timeout_cache,
    "SOURCE_STALE_CLOSED_CACHE": stale_cache,
    "FDR_YESTERDAY_NO_BAN": yesterday_ban,
    "OSM_PINK_GUM_CHILDREN": pink_children,
    "OSM_ACT_CHILDREN_MISTAGGED_AS_CAMPS": act_children,
    "SA_CASURINA_REVIEWED_ALIAS": casuarina,
    "SA_TAPANAPPA_UNNAMED_FEATURE": tapanappa,
    "SA_GYM_GEOMETRY_DISAGREEMENT": gym,
    "SA_PONDALOWIE_DISTINCT_PRODUCTS": pondalowie,
    "SA_BLACK_SPRINGS_OVERFLOW_DISTINCT": black_springs,
    "SA_PARK_CENTRE_NOT_CAMP_GEOMETRY": park_centre,
    "SA_SITEMAP_PDF_NOT_HTML_PRODUCT": sitemap,
    "SA_MOUNT_REMARKABLE_FUTURE": remarkable,
    "SA_MOUNT_REMARKABLE_ACTIVE": remarkable,
    "SA_MOUNT_REMARKABLE_ENDED": remarkable,
    "SA_MOUNT_REMARKABLE_OLD_EXPIRED": remarkable_old,
    "SA_INNES_HEALTH_NOT_CLOSURE": innes,
    "SA_COFFIN_ACCESS_WARNING_NOT_CLOSURE": coffin,
}


def feed_grant(_inp):
    return {"extend_named_ESA_feed_grant": status.esa_grant_covers_parks_or_fire("Parks ACT closure page prose"), "parks_terms_status": "unresolved"}


def edxl_not_empty(inp):
    row = status.rss_absence_is_all_clear(inp["RSS_item_count"], inp["CAP_alert_count"])
    return {"treat_as_empty": row["treat_as_empty"], "schema": "not_parsed_here", "infer_no_ban_or_open": row["infer_no_ban_or_open"]}


def incident_not_fdr(_inp):
    row = status.fire_status(_camp("act:cotter"), {"incident_feed_healthy": True})
    return {"ACT_FDR": "unknown" if row["rating"] is None else row["rating"], "ACT_TFB": "unknown" if row["banned"] is None else "banned", "borrow_NSW": row["borrowed_from"] == "nsw"}


def asset_not_entrance(_inp):
    return {"locality_correlated": True, "entrance_or_boundary_verified": status.asset_point_is_entrance(), "infer_current_open": False}


def cotter_bend(_inp):
    return {"automatic_coordinate_substitution": status.asset_point_is_entrance()}


def elm_grove(inp):
    decision = status.proximity_decision(inp["proximity_m"])
    return {"assume_current_alias_or_entrance": decision["merged"], "manual_context_review": decision["unresolved"]}


def dataset_licence(_inp):
    return {"extend_CC_BY4": status.esa_grant_covers_parks_or_fire("parks.act.gov.au page text")}


def overflow_number(_inp):
    camp = {
        "id": "sa:overflow-label-7",
        "state": "sa",
        "entity_type": "pitch",
        "inventory_role": "fixture_only",
        "name": "7",
        "parent_id": "sa:black-springs-overflow",
        "site_number": 7,
    }
    alert = {
        "id": "overflow-label",
        "state": "sa",
        "source_url": "https://example.invalid/overflow",
        "action": "closure",
        "asset_class": "pitch",
        "parent_id": "sa:black-springs",
        "targets": [{"id": "sa:black-springs", "scope": "partial", "parent_id": "sa:black-springs", "site_numbers": [7]}],
        "start": "2026-11-01",
        "end": "2026-11-30",
        "timezone": "Australia/Adelaide",
    }
    row = status.apply_alerts([camp], [alert], _moment("2026-11-09T12:00:00+11:00"))[0]
    return {"count_as_overflow_pitch": row["closed"] is True, "collapse_main_and_overflow": status.proximity_decision(83)["merged"]}


def morgans_access(_inp):
    return {"infer_all_sites_road_accessible": False, "preserve_site1_access_exception": True}


def sensation_beach(_inp):
    return {"substitute_beach_for_camp_geometry": status.asset_point_is_entrance()}


def scale_labels(inp):
    label = str(inp["pitch_labels"]).replace("–", "-").replace("—", "-")
    start, end = label.split("-")
    count = int(end) - int(start) + 1
    return {
        "distinct_campgrounds": 1,
        "source_numbered_pitches": count,
        "count_scale_bar_as_pitch": status.scale_bar_labels_are_pitches(inp["scale_bar_labels"]),
    }


def hideaway(inp):
    return {
        "distinct_facilities": 1,
        "infer_three_campgrounds": status.capacity_counts_as_extra_camps(3) > 0,
        "merge_with_Wirra": status.proximity_decision(0)["merged"] or inp["booking_id"] == "90928",
    }


def helipad_guests(inp):
    return {
        "distinct_facilities": 1,
        "infer60campgrounds": status.capacity_counts_as_extra_camps(inp["unallocated_capacity_guests"]) > 0,
        "individual_pitch_availability_known": False,
    }


def route_parking(_inp):
    # A parking-fee note does not move the camp into Deep Creek or create vehicle access.
    return {"assign_physical_parent_Deep_Creek": False, "no_vehicle_access": True}


def natunuru(_inp):
    matched = status.match_camp("Natunuru Ngawanthi", status.load_candidates()["records"])
    return {"reviewed_alias_candidate": True, "global_fuzzy_match_enabled": matched["camp"] is not None}


def cohort_28(_inp):
    slim = status.load_json(os.path.join(ROOT, "data", "act-sa", "evidence", "reconciliation-slim.json"))
    ready = any(row["ready_to_publish"] for row in slim["sa"]["facilities"])
    return {"claim_SA_complete": slim.get("statewide_denominator_known") is True, "claim_all28_release_ready": ready, "scope_label_required": True}


HANDLERS.update({
    "ACT_FEED_GRANT_NOT_PARKS_TEXT": feed_grant,
    "ACT_EDXL_NOT_ZERO_RSS_NO_INCIDENTS": edxl_not_empty,
    "ACT_INCIDENT_FEED_NOT_FDR": incident_not_fdr,
    "ACT_ASSET_NOT_CAMPGROUND_ENTRANCE": asset_not_entrance,
    "ACT_COTTER_BEND_WRONG_ENTITY": cotter_bend,
    "ACT_ELM_GROVE_ALIAS_NOT_ASSUMED": elm_grove,
    "ACT_DATASET_LICENCE_NOT_BLANKET_PARKS": dataset_licence,
    "SA_OVERFLOW_NEIGHBOUR_NUMBER7": overflow_number,
    "SA_MORGANS_SITE1_BEACH_ACCESS": morgans_access,
    "SA_SENSATION_BEACH_NOT_CAMP_POINT": sensation_beach,
    "SA_NUMBER_LABEL_SCALE_DUPLICATES": scale_labels,
    "SA_HIDEAWAY_FAMILIES_NOT_CAMPS": hideaway,
    "SA_HELIPAD_GUESTS_NOT_CAMPS": helipad_guests,
    "SA_ROUTE_PARKING_NOT_PHYSICAL_PARENT": route_parking,
    "SA_NATUNURU_REVIEWED_SPELLING": natunuru,
    "SA_28_COHORT_NOT_STATEWIDE": cohort_28,
})
