#!/usr/bin/env python3
"""Tasmania is public. Signup and the digest stay off, and ACT stays off."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.chdir(ROOT)

import contacts
import tas_alerts
import tas_fire
import tas_inventory
import tas_launch_gate
import tas_signup
import states

FAILURES = []
CHECKS = 0


def expect(condition, label):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(label)


def main():
    tas = states.by_slug("tas")
    act = states.by_slug("act")
    expect(tas.get("enabled") is True, "tas enabled")
    expect(tas["release"]["public"] is True, "tas public")
    expect(tas["release"]["signup"] is False and tas["release"]["digest"] is False, "no signup and no digest")
    expect(states.public_build_allowed(tas) is True, "public build allowed")
    expect(states.signup_allowed(tas) is False and states.digest_allowed(tas) is False, "signup and digest refused")
    blocking = [gate for gate in tas["release"]["gates"] if gate.get("blocks_public", True) is not False]
    expect(blocking and all(gate.get("ok") is True for gate in blocking), "blocking tas gates are open")
    segment = next(gate for gate in tas["release"]["gates"] if gate.get("id") == "digest_segment")
    expect(segment.get("ok") is False and segment.get("blocks_public") is False, "tas signup segment stays off")
    expect(act.get("enabled") is False and states.public_build_allowed(act) is False, "act stays off")
    expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "enabled states include tas")

    saved_enable = os.environ.get("CAMPCONDITIONS_ENABLE")
    saved_preview = os.environ.get("CAMPCONDITIONS_PREVIEW")
    saved_out = os.environ.get("CAMPCONDITIONS_OUT")
    try:
        os.environ["CAMPCONDITIONS_ENABLE"] = "tas"
        expect([state["slug"] for state in states.enabled()] == ["vic", "nsw", "qld", "sa", "tas"], "enable flag does not add another tas")
        os.environ["CAMPCONDITIONS_ENABLE"] = "act"
        expect("act" not in [state["slug"] for state in states.enabled()], "enable flag cannot add act")
        os.environ.pop("CAMPCONDITIONS_ENABLE", None)
        os.environ["CAMPCONDITIONS_PREVIEW"] = "tas"
        os.environ["CAMPCONDITIONS_OUT"] = "/tmp/tas-preview-unit"
        preview = [state["slug"] for state in states.page_states()]
        expect("tas" in preview and preview[0] == "vic", "preview flag adds tas outside dist")
        os.environ["CAMPCONDITIONS_OUT"] = os.path.join(ROOT, "dist")
        try:
            states.page_states()
            expect(False, "preview refuses dist")
        except SystemExit:
            expect(True, "preview refuses dist")
    finally:
        if saved_enable is None:
            os.environ.pop("CAMPCONDITIONS_ENABLE", None)
        else:
            os.environ["CAMPCONDITIONS_ENABLE"] = saved_enable
        if saved_preview is None:
            os.environ.pop("CAMPCONDITIONS_PREVIEW", None)
        else:
            os.environ["CAMPCONDITIONS_PREVIEW"] = saved_preview
        if saved_out is None:
            os.environ.pop("CAMPCONDITIONS_OUT", None)
        else:
            os.environ["CAMPCONDITIONS_OUT"] = saved_out

    refused = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "tas_preview.py"), os.path.join(ROOT, "dist", "tas")],
        cwd=ROOT, capture_output=True, text=True,
    )
    expect(refused.returncode != 0, "preview script refuses dist")

    counted = tas_inventory.summary()
    expect(counted["source_rows"] == 691, "691 source records")
    expect(counted["eligible"] == 189 and counted["published"] == 178, "189 eligible, 178 published")
    expect(counted["collapsed"] == [
        "TAS-LIST-CS-29405", "TAS-LIST-CS-62066", "TAS-LIST-CS-62067", "TAS-LIST-CS-62068",
        "TAS-LIST-CS-62186", "TAS-LIST-CS-62187", "TAS-LIST-CS-62188", "TAS-LIST-CS-62190",
        "TAS-LIST-CS-62192",
    ], "nine theLIST points collapse")
    expect(counted["collapsed_kept"] == {
        "New Pelion Hut": "TAS-LIST-CS-62194",
        "Waterfall Valley Hut": "TAS-LIST-CS-62191",
        "Wild Dog Creek campsite": "TAS-LIST-CS-62069",
        "Windermere Hut": "TAS-LIST-CS-62189",
    }, "the public or anchor record is kept")
    expect(counted["decisions"].get("hold") == 199 and counted["decisions"].get("exclude") == 303, "held and excluded stay in the source file")
    expect(not counted["held_published"] and not counted["excluded_published"], "source held and excluded records are not published")
    expect({row["name"]: row["reason"] for row in counted["park_excluded"]} == {
        "Lake St Clair Tourist Park": "commercial tourist park",
        "BIG4 Buttons Creek Summer Campground": "commercial chain: BIG4",
    }, "two commercial parks are excluded")
    expect(not counted["park_held"] and not counted["park_kept"], "no park is held or kept")
    expect(counted["council"] == 11, "11 camps outside a reserve")
    camps = tas_inventory.load_camps(set())
    by_id = {camp["id"]: camp for camp in camps}
    expect(all(ident not in by_id for ident in counted["collapsed"]), "collapsed points are not separate camps")
    for name, ident in counted["collapsed_kept"].items():
        camp = by_id[ident]
        expect(camp["name"] == name and camp["pws_alert_name"] and camp["slug"] == tas_inventory._slug(name), "kept camp keeps the PWS park and the clean url: " + name)
    expect(sum(camp["name"] == "Richardsons Beach Campground" for camp in camps) == 2, "Richardsons Beach stays two camps")
    expect(any(camp["id"] == "TAS-OSM-node12441267806" and camp["name"] == "Campe Elsewhere PWS Camping Area" for camp in camps), "Campe Elsewhere stays")
    redirects = tas_inventory.load_camps.slug_redirects
    expect(redirects["new-pelion-hut-tas-list-cs-62194"] == "new-pelion-hut", "old New Pelion url redirects")
    expect(redirects["waterfall-valley-hut-tas-list-cs-62192"] == "waterfall-valley-hut", "old Waterfall Valley url redirects")
    expect(redirects["windermere-hut-tas-list-cs-62186"] == "windermere-hut", "old Windermere url redirects")
    expect(redirects["wild-dog-creek-campsite-tas-list-cs-62066"] == "wild-dog-creek-campsite", "old Wild Dog url redirects")
    expect(all(old != new and new in {camp["slug"] for camp in camps} for old, new in redirects.items()), "redirects land on a published camp")
    expect("richardsons-beach-campground" not in redirects and "campe-elsewhere-pws-camping-area" not in redirects, "review camps are not redirected")
    expect(tas_inventory.parks_without_keep(camps) == [], "published list has no park without a keep decision")
    expect(tas_inventory.parks_without_keep([{"name": "Sample Holiday Park", "category": "Campground"}]) == ["Sample Holiday Park"], "a holiday park with no keep decision fails")
    expect(tas_inventory.is_caravan_holiday_or_tourist_park({"name": "Sample Tourist Park", "category": "Campground"}), "a tourist park fails")
    expect(tas_inventory.is_caravan_holiday_or_tourist_park({"name": "BIG4 Buttons Creek Summer Campground", "category": "Campground"}), "a BIG4 site fails")
    expect(tas_inventory.parks_without_keep([{"name": "Council Caravan Park", "category": "Campground", "park_decision": "keep"}]) == [], "a council caravan park with a keep decision stays")

    sample_html = open(os.path.join(ROOT, "data", "tas", "fixtures", "alerts-sample.html"), encoding="utf-8").read()
    parsed = tas_alerts.parse_html(sample_html)
    expect("SECRET" not in json.dumps(parsed), "alert body is not stored")
    expect(all(set(row) <= tas_alerts.STORED_FIELDS for row in parsed), "stored fields are headline, parks, link and dates")
    bay = {
        "name": "Sample Bay Campground No 1",
        "aliases": ["Sample Bay 1", "Sample Bay No 1"],
        "pws_alert_name": "Example National Park",
        "reserve_name": "Example National Park",
        "tas_council": False,
    }
    bay2 = dict(bay, name="Sample Bay Campground No 2", aliases=["Sample Bay No 2"])
    example = {
        "name": "Example Campground",
        "aliases": ["Example"],
        "pws_alert_name": "Example National Park",
        "reserve_name": "Example National Park",
        "tas_council": False,
    }
    expect(tas_alerts.classify(bay, parsed)["display"] == "closed", "numbered group closes camp 1")
    expect(tas_alerts.classify(bay2, parsed)["display"] == "closed", "numbered group closes camp 2")
    example_result = tas_alerts.classify(example, parsed)
    expect(example_result["display"] == "amber" and example_result["campfire"] is True, "park title is not a camp closure, and the campfire ban is a note")
    expect(not tas_alerts.allowed_url(tas_alerts.ALERTS_URL + "?x=1"), "query string is refused")
    expect(not tas_alerts.allowed_url("https://parks.tas.gov.au/_layouts/secret"), "sharepoint path is refused")
    expect(tas_alerts.allowed_url(tas_alerts.ALERTS_URL), "alerts path is allowed")

    calls = []

    def fetch_text(name, url, headers=None):
        calls.append((name, url, headers or {}))
        return sample_html.encode("utf-8")

    cache = tempfile.mkdtemp(prefix="tas-alerts-")
    fetched = tas_alerts.fetch_alerts(fetch_text, cache)
    expect(len(calls) == 1 and "?" not in calls[0][1], "one request and no query string")
    expect("Tasmania park alerts" in (calls[0][2].get("User-Agent") or ""), "descriptive user agent")
    expect(fetched["stale"] is False and fetched["alerts"], "fresh parse")
    cached_text = open(tas_alerts.last_good_path(cache), encoding="utf-8").read()
    expect("SECRET" not in cached_text, "last good copy has no body")

    def failed(name, url, headers=None):
        calls.append((name, url, headers or {}))
        return None

    again = tas_alerts.fetch_alerts(failed, cache)
    expect(len(calls) == 2 and again["stale"] is True and again["fallback"] is True, "failed fetch is stale")
    expect(again["alerts"] == fetched["alerts"], "last good headlines are kept")

    fixture = json.load(open(os.path.join(ROOT, "data", "tas", "fixtures", "alerts-2026-11-10.json"), encoding="utf-8"))
    live = fixture["alerts"]
    expect(len(live) == 29, "29 alerts")
    expect(all("SECRET" not in json.dumps(row) and set(row) <= tas_alerts.STORED_FIELDS for row in live), "fixture has no body")
    review = dt.datetime(2026, 11, 10, 15, 0, tzinfo=tas_alerts.HOBART)
    tas_alerts.apply_alerts(camps, live, now=review)
    tally = tas_alerts.counts(camps)
    expect(tally["amber"] == 75 and tally["closed"] == 1 and tally["upcoming"] == 2 and tally["campfire"] == 102, "10 Nov: 75 amber, 1 closed, 2 upcoming, 102 campfire notes")
    by_name = {camp["name"]: camp for camp in camps}
    stumpys = by_name["Stumpys Bay Campground No 1"]
    ben = by_name["Ben Lomond Campground"]
    falls = by_name["Falls Park Rest Area"]
    expect(stumpys["tas_display"] == "upcoming" and stumpys["status"] != "closed", "Stumpys Bay No 1 is upcoming on 10 Nov")
    expect(by_name["Stumpys Bay Campground No 2"]["tas_display"] == "upcoming", "Stumpys Bay No 2 is upcoming on 10 Nov")
    expect((stumpys.get("upcoming_closure") or {}).get("start") == "2026-12-10" and stumpys["upcoming_closure"].get("start_time") == "10:00", "Stumpys starts 10am 10 Dec")
    expect(stumpys["upcoming_closure"].get("reopen") == "2026-12-15" and stumpys["upcoming_closure"].get("reopen_time") == "14:00", "Stumpys reopens 2pm 15 Dec")
    during = dt.datetime(2026, 12, 10, 10, 0, tzinfo=tas_alerts.HOBART)
    after = dt.datetime(2026, 12, 15, 14, 0, tzinfo=tas_alerts.HOBART)
    expect(tas_alerts.classify(stumpys, live, during)["display"] == "closed", "Stumpys is closed once the closure has started")
    expect(tas_alerts.classify(stumpys, live, after)["display"] != "closed", "Stumpys is not closed after it reopens")
    dated = (
        "<h2>Site Alerts</h2><div class=\"section\"><h3>Planned event: Sample Bay 1 and 2 campgrounds closed</h3>"
        "<p>Applies from 10/12/2026</p><div class=\"alert-listing\"><p>Sample Bay campgrounds 1 and 2 are closed "
        "from 10am Thursday 10 December. They will reopen at 2pm Tuesday 15 December.</p>"
        "<p><b>Locations affected:</b> <a href=\"/Pages/Example.aspx\">Example National Park</a></p></div></div>"
    )
    dated_alerts = tas_alerts.parse_html(dated)
    expect(dated_alerts[0]["start"] == "2026-12-10" and dated_alerts[0]["start_time"] == "10:00" and dated_alerts[0]["end"] == "2026-12-15" and dated_alerts[0]["end_time"] == "14:00", "parser reads start and end")
    expect("Thursday" not in json.dumps(dated_alerts), "the sentence is not stored")
    reviewed_html = dated.replace(
        "</p></div></div>",
        "</p><p>Last reviewed 8/11/2026 09:16 AM</p></div></div>",
        1,
    )
    reviewed_alerts = tas_alerts.parse_html(reviewed_html)
    expect(reviewed_alerts[0].get("reviewed") == "2026-11-08T09:16:00+11:00", "last reviewed is a Hobart instant and the sentence is not stored")
    fresh = tas_alerts.stamp({"alerts": reviewed_alerts, "fetched": "2026-11-11T06:14:00+11:00", "stale": False})
    copy = tas_alerts.checked_copy(fresh, dt.datetime(2026, 11, 11, 7, 0, tzinfo=tas_alerts.HOBART))
    expect(copy and copy["line"].startswith("Park alerts checked ") and "updated" not in copy["line"].lower(), "the line says the feed was checked")
    expect(copy["stale"] is True and "last reviewed more than 2 days ago" in copy["warning"] and "checked at" in copy["warning"], "an old newest alert is named separately from the check")
    recent = dict(fresh, updated="2026-11-10T14:20:00+11:00")
    recent_copy = tas_alerts.checked_copy(recent, dt.datetime(2026, 11, 11, 7, 0, tzinfo=tas_alerts.HOBART))
    expect(recent_copy["stale"] is False, "a review from yesterday is not a two-day warning")
    expect(by_name["Stumpys Bay Campground No 3"]["tas_display"] == "amber", "Stumpys Bay No 3 is a park alert")
    expect(by_name["Edgar Dam Camping Ground"]["tas_display"] == "closed", "Edgar Dam is closed")
    expect(ben["tas_display"] == "amber" and ben["status"] != "closed" and ben["tas_campfire"] is True, "Ben Lomond is amber, with a campfire note")
    expect(falls["tas_display"] == "council" and not falls["tas_ambers"] and not falls["tas_closures"] and not falls["tas_campfire"], "Falls Park has no PWS alert")
    stumpys_html = tas_alerts.html_block(stumpys)
    ben_html = tas_alerts.html_block(ben)
    falls_html = tas_alerts.html_block(falls)
    expect("Upcoming closure." in stumpys_html and "10am Thursday 10 December 2026" in stumpys_html and "2pm Tuesday 15 December 2026" in stumpys_html and "Stumpys Bay 1 and 2" in stumpys_html and tas_alerts.ALERTS_URL in stumpys_html, "upcoming camp shows the dates, the headline and the PWS link")
    expect("Closed." not in stumpys_html.split("Upcoming closure.", 1)[-1][:80], "the planned closure is not labelled Closed")
    expect("Alert in this park." in ben_html and "Jacobs Ladder" in ben_html and 'id="camp-closure"' not in ben_html, "Ben Lomond is not closed")
    expect("Seasonal campfire ban." in ben_html and "Seasonal campfire ban." in stumpys_html, "campfire note")
    expect("Check with the council before you travel." in falls_html and falls["council_url"] in falls_html, "council sentence and link")
    expect("Alert in this park" not in falls_html and tas_alerts.ALERTS_URL not in falls_html, "council camp has no PWS alert")
    expect(falls.get("website") == falls.get("council_url") and falls["website"].startswith("https://"), "falls keeps its council page as the website")
    expect('class="btn" href="%s">Website</a>' % falls["website"] in falls_html, "falls renders a website button")
    expect('href="tel:1300827727"' in ben_html and contacts.PWS_LABEL in ben_html, "pws camp renders the general info line")
    expect("1300 827 727" not in falls_html and ">Call " not in falls_html, "council camp does not get the PWS line")
    expect(not ben.get("phone") and not falls.get("phone"), "the info line is not stored as the camp phone")
    expect(">Book</a>" not in ben_html and ">Email</a>" not in ben_html, "empty email and booking stay hidden")
    expect(">Website</a>" not in ben_html and "Campground record:" in ben_html and ">theLIST</a>" in ben_html, "a PWS page keeps theLIST as the campground record")
    council_sites = [camp for camp in camps if camp.get("tas_council")]
    pws_sites = [camp for camp in camps if not camp.get("tas_council")]
    with_button = 0
    with_website = 0
    for camp in council_sites:
        page = tas_alerts.html_block(camp)
        if camp.get("website"):
            with_website += 1
            with_button += 1
            expect('class="btn" href="%s">Website</a>' % camp["website"] in page, "council website button " + camp["name"])
            expect("thelist" not in camp["website"].lower(), "council website is not theLIST " + camp["name"])
        else:
            expect(">Website</a>" not in page and ">Call " not in page and ">Email</a>" not in page and ">Book</a>" not in page, "unknown council camp has no contact button " + camp["name"])
        expect("1300 827 727" not in page and ">theLIST</a>" in page, "council page keeps theLIST and has no PWS line " + camp["name"])
    for camp in pws_sites:
        page = tas_alerts.html_block(camp)
        expect('href="tel:1300827727"' in page and contacts.PWS_LABEL in page, "pws info line " + camp["name"])
        expect(not camp.get("phone"), "pws phone field stays empty " + camp["name"])
        with_button += 1
    expect(len(council_sites) == 11 and len(pws_sites) == 167, "11 council camps and 167 PWS camps")
    expect(with_website == 7, "7 council or Hydro websites")
    expect(with_button == 174, "174 Tasmania pages show a contact button")
    expect(tas_inventory.load_pws_links(os.path.join(ROOT, "missing-tas-pws-links.csv")) == {}, "a missing PWS link file adds nothing")
    link_file = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    link_file.write("camp_id,url\n")
    link_file.write("%s,https://parks.tas.gov.au/explore-our-parks/ben-lomond-national-park\n" % ben["id"])
    link_file.write("TAS-LIST-EXAMPLE,https://data.thelist.tas.gov.au/example\n")
    link_file.write("TAS-INSECURE,http://parks.tas.gov.au/not-secure\n")
    link_file.close()
    try:
        mapped = tas_inventory.load_pws_links(link_file.name)
        expect(mapped.get(ben["id"]) == "https://parks.tas.gov.au/explore-our-parks/ben-lomond-national-park", "PWS file keeps an official park URL")
        expect("TAS-LIST-EXAMPLE" not in mapped and "TAS-INSECURE" not in mapped, "theLIST and insecure URLs are refused")
        copied = dict(ben)
        copied["website"] = ""
        tas_inventory.assign_website(copied, mapped)
        mapped_html = tas_alerts.html_block(copied)
        expect('class="btn" href="https://parks.tas.gov.au/explore-our-parks/ben-lomond-national-park">Website</a>' in mapped_html, "PWS mapping renders a website button")
        expect(">theLIST</a>" in mapped_html and "thelist.tas.gov.au" not in mapped_html.split(">Website</a>")[0][-160:].lower(), "theLIST stays a source credit")
    finally:
        os.remove(link_file.name)
    bare = {"source": "qpws", "category": "QPWS camping area"}
    qld_rest = {"source": "osm", "category": "Rest area"}
    phoned = {"source": "osm", "category": "Camp", "phone": "07 5550 1234"}
    booked = {"source": "osm", "category": "Camp", "booking_url": "https://example.com/book"}
    catalogued = {"source": "osm", "category": "Camp", "website": "https://data.thelist.tas.gov.au/x"}
    nsw_park = {"source": "npws", "category": "Camping Area"}
    nsw_rest = {"source": "osm", "category": "Rest area", "website": "https://example.com/directory"}
    nsw_osm = {"source": "osm", "category": "Free", "phone": "02 9999 0000"}
    vic_rest = {"source": "osm", "category": "Rest area", "phone": "13 1963"}
    contacts.apply_state_contacts({
        "qld": [bare, qld_rest, phoned, booked, catalogued],
        "nsw": [nsw_park, nsw_rest, nsw_osm],
        "vic": [vic_rest],
    })
    expect(bare.get("info_line", {}).get("phone") == "13 74 68" and bare.get("info_line", {}).get("label") == contacts.QGOV_LABEL and not bare.get("phone"), "13 QGOV is a labelled fallback, not the camp phone")
    expect(not qld_rest.get("info_line") and qld_rest.get("road_line", {}).get("phone") == "13 23 80" and qld_rest.get("website") == contacts.TMR_WEBSITE, "Queensland rest area gets the road-authority contact")
    expect("not camping" in qld_rest.get("rest_note", "") and "20 hours" in qld_rest.get("rest_note", ""), "Queensland rest-area note follows the official page")
    expect(not phoned.get("info_line") and not booked.get("info_line"), "a phone or booking URL suppresses 13 QGOV")
    expect(catalogued.get("info_line", {}).get("phone") == "13 74 68", "a catalogue link does not count as a contact")
    expect(">Book</a>" in contacts.specific_html(booked) and "https://example.com/book" in contacts.specific_html(booked), "book button when a booking URL is set")
    expect(nsw_park.get("info_line", {}).get("phone") == "1300 072 757" and nsw_park.get("info_line", {}).get("label") == contacts.NPWS_LABEL and not nsw_park.get("phone"), "NPWS line is labelled and is not the camp phone")
    expect(nsw_rest.get("website") == contacts.TFNSW_WEBSITE and nsw_rest.get("road_line", {}).get("phone") == "13 22 13", "NSW rest area gets the Transport for NSW contact")
    expect("not camping" in nsw_rest.get("rest_note", "") and "overnight stay is allowed" not in nsw_rest.get("rest_note", "").lower(), "NSW rest-area note does not allow camping")
    expect(not nsw_osm.get("info_line") and not nsw_osm.get("road_line") and nsw_osm.get("phone") == "02 9999 0000", "other NSW camps keep their own phone")
    expect(not vic_rest.get("info_line") and not vic_rest.get("road_line") and not vic_rest.get("rest_note") and vic_rest.get("phone") == "13 1963", "Victoria rest areas are unchanged")
    expect(tas_inventory.LIST_CREDIT in stumpys_html, "LIST attribution")
    osm = next(camp for camp in camps if camp.get("coordinate_source") == "OSM")
    listed = next(camp for camp in camps if camp.get("coordinate_source") != "OSM")
    expect(tas_inventory.OSM_CREDIT in tas_alerts.html_block(osm), "OSM attribution where coordinates come from OpenStreetMap")
    expect(tas_inventory.OSM_CREDIT not in tas_alerts.html_block(listed), "LIST coordinates are not labelled as OpenStreetMap")
    for fragment in (stumpys_html, ben_html, falls_html, tas_signup.coming_soon_html(), tas_fire.html_line({})):
        visible = fragment.lower()
        expect(not any(word in visible.split() or f" {word} " in f" {visible} " for word in ("held", "disabled", "preview")), "public fragment wording")
    expect("rows" not in falls_html.lower() and "rows" not in ben_html.lower(), "no internal row wording")

    fire = tas_fire.html_line({})
    expect(tas_fire.TFS_URL in fire and tas_fire.TASALERT_URL in fire and "bom.gov.au" not in fire.lower(), "fire links and no BOM")
    soon = tas_signup.coming_soon_html()
    os.environ["RESEND_SEGMENT_TAS_ID"] = "do-not-create"
    try:
        expect(tas_signup.forms_allowed() is False, "a segment variable does not open signup")
    finally:
        os.environ.pop("RESEND_SEGMENT_TAS_ID", None)
    expect(tas_signup.COMING_SOON in soon and "<form" not in soon and "/api/subscribe" not in soon, "coming soon line has no form")
    roads = (tas.get("links") or {}).get("roads") or ""
    expect(roads.startswith("https://www.transport.tas.gov.au/") and (tas.get("sources") or {})["roads"]["ingest"] is False, "roads are a link out")

    fake = tempfile.mkdtemp(prefix="tas-dist-")
    with open(os.path.join(fake, "index.html"), "w", encoding="utf-8") as handle:
        handle.write('<input name="states" value="vic"><input name="states" value="nsw"><input name="states" value="qld"><a href="/tas/">Tasmania</a>')
    os.makedirs(os.path.join(fake, "tas"))
    gate = tas_launch_gate.evaluate(fake)
    by_check = {item["check"]: item for item in gate["checks"]}
    expect(by_check["inventory"]["pass"] and by_check["alerts"]["pass"], "inventory and alert checks")
    expect(by_check["fire_linkout"]["pass"] and by_check["roads_linkout"]["pass"] and by_check["tas_signup"]["pass"], "fire, roads and signup checks")
    expect(by_check["public_tas"]["pass"], "public build lists Tasmania and leaves ACT off")
    expect(by_check["caravan_park_keep"]["pass"] is True, "caravan park check passes")
    expect(gate["pass"] is True and gate["published"] == 178 and gate["alerts"]["amber"] == 75 and gate["alerts"]["campfire"] == 102, "launch checks pass")

    home = os.path.join(ROOT, "dist", "index.html")
    if os.path.isfile(home):
        page = open(home, encoding="utf-8").read()
        expect('href="/tas/"' in page and "Tasmania" in page, "built homepage lists Tasmania")
        expect('value="tas"' not in page and 'value="act"' not in page, "signup does not offer tas or act")
        expect(os.path.isdir(os.path.join(ROOT, "dist", "tas")), "built site has Tasmania pages")
        expect(not os.path.isdir(os.path.join(ROOT, "dist", "act")), "built site has no ACT pages")

    node = subprocess.run(["node", "--input-type=module", "-e", NODE], cwd=ROOT, capture_output=True, text=True)
    expect(node.returncode == 0, "signup hold node: " + (node.stderr or node.stdout)[-300:])

    if FAILURES:
        print("TAS failures: %s" % len(FAILURES))
        for label in FAILURES:
            print(" FAIL", label)
        return 1
    print("TAS checks passed: %s" % CHECKS)
    alerts = gate["alerts"]
    print("Published camps: 178. Alerts: %s amber, %s closed, %s upcoming, %s campfire notes." % (alerts["amber"], alerts["closed"], alerts["upcoming"], alerts["campfire"]))
    return 0


NODE = r"""
import { chosenStates, heldSignupStates, heldSignupPreview, makeToken } from "./functions/_lib/token.js";
import { signupChoice } from "./functions/api/subscribe.js";

if (chosenStates(["tas", "vic"]).join(",") !== "vic") process.exit(1);
if (heldSignupStates(["tas", "act"]).join(",") !== "act,tas") process.exit(2);
const preview = heldSignupPreview("tas");
if (!preview || preview.enrol || preview.send || preview.readsSegmentEnv || preview.requiredEnv !== "RESEND_SEGMENT_TAS_ID") process.exit(3);
const held = signupChoice(["tas"], true);
if (held.ok || held.reason !== "not_open" || held.enrol.length) process.exit(4);
if (await makeToken("reader@example.com", "test-secret", 3600, ["tas"])) process.exit(5);
"""


if __name__ == "__main__":
    sys.exit(main())
