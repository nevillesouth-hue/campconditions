#!/usr/bin/env python3
"""Unit tests for scripts/seo.py. No build and no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seo

failures = []


def expect(cond, label):
    if not cond:
        failures.append(label)


edgar = seo.closed_meta(
    "Edgar Dam Camping Ground",
    "Tasmania",
    "Tasmania",
    "Southwest National Park",
    "Starts Tuesday 28 January 2025",
    start_spoken="Tuesday 28 January 2025",
)
expect(
    edgar == "Edgar Dam Camping Ground is closed in Southwest National Park, Tasmania. Closed from Tuesday 28 January 2025.",
    "edgar closed meta " + edgar,
)
expect(seo.OPEN_DISCLAIMER not in edgar, "edgar disclaimer")
expect("No Rating" not in edgar, "edgar rating")

plain_park = seo.closed_meta(
    "Edgar Dam Camping Ground",
    "Tasmania",
    "Tasmania",
    "",
    "Starts Tuesday 28 January 2025 This is not a confirmation the camp is open.",
    start_spoken="Tuesday 28 January 2025",
)
expect(plain_park.startswith("Edgar Dam Camping Ground is closed in Tasmania."), "edgar without park " + plain_park)
expect(seo.OPEN_DISCLAIMER not in plain_park, "stripped disclaimer")
expect("Closed from Tuesday 28 January 2025." in plain_park, "closed from date")

reopen = seo.closed_meta(
    "Parkers Pines",
    "Victoria",
    "High Country",
    "",
    "Closed for works",
    start_spoken="",
    end_spoken="Friday 18 December 2026",
)
expect(reopen.startswith("Parkers Pines is closed in High Country, Victoria."), reopen)
expect("Reopens Friday 18 December 2026." in reopen, reopen)
expect("Closed for works." in reopen, reopen)

sa_closed = seo.closed_meta(
    "Box Flat",
    "South Australia",
    "South Australia",
    "Mount Remarkable National Park",
    "From Wednesday 11 November 2026 until Wednesday 18 November 2026. Pest control.",
    start_spoken="Wednesday 11 November 2026",
    end_spoken="Wednesday 18 November 2026",
    end_label="Until",
)
expect(sa_closed.startswith("Box Flat is closed in Mount Remarkable National Park, South Australia."), sa_closed)
expect("Closed from Wednesday" not in sa_closed, "summary already has the window " + sa_closed)
expect("Pest control." in sa_closed, sa_closed)
expect(seo.OPEN_DISCLAIMER not in sa_closed, "sa closed disclaimer")

check = seo.with_disclaimer(
    "American River Campground",
    "South Australia",
    "No current closure notice applies to this camp",
)
expect(
    check == "American River Campground in South Australia. No current closure notice applies to this camp. " + seo.OPEN_DISCLAIMER,
    "check punctuation " + check,
)
expect("is closed" not in check, "check is not closed")

tas_check = seo.with_disclaimer("Some Camp", "Tasmania", "Starts Tuesday 28 January 2025")
expect(tas_check.endswith(seo.OPEN_DISCLAIMER), tas_check)
expect(". This is not a confirmation the camp is open." in tas_check, "tas check period " + tas_check)
expect("  " not in tas_check, "double space")

crumbs = seo.breadcrumb_list([
    ("Home", "/"),
    ("Victoria", "/vic/"),
    ("High Country", "/vic/high-country/"),
    ("Dandos", "/vic/camp/dandos/"),
])
expect(crumbs["@type"] == "BreadcrumbList", "type")
expect(crumbs.get("name") == "Dandos", "list name " + str(crumbs.get("name")))
items = crumbs["itemListElement"]
expect(len(items) == 4, "four crumbs")
for item in items:
    expect(item.get("name") and item["name"] != "Unnamed item", "name " + str(item))
    expect(isinstance(item.get("item"), str), "item url " + str(item))
    expect(str(item.get("item") or "").startswith("https://campconditions.au/"), "url " + str(item))
expect(items[0]["item"] == "https://campconditions.au/", items[0])
expect(items[3]["name"] == "Dandos", items[3])
expect(items[3]["item"] == "https://campconditions.au/vic/camp/dandos/", items[3])

unnamed = seo.breadcrumb_list([("", "/"), ("  Unnamed item  ", "/vic/high-country/")])
expect(unnamed["name"] == "Page", unnamed.get("name"))
expect(unnamed["itemListElement"][0]["name"] == "Home", unnamed)
expect(unnamed["itemListElement"][0]["item"] == "https://campconditions.au/", unnamed)
expect(unnamed["itemListElement"][1]["name"] == "Page", unnamed)
expect(unnamed["itemListElement"][1]["item"] == "https://campconditions.au/vic/high-country/", unnamed)

closed_camps = [{"name": "B", "status": "closed", "region": "a"}, {"name": "A", "status": "closed", "region": "a"}]
closed_camps += [{"name": "Open " + str(i), "status": "open", "region": "a"} for i in range(5)]
shown, mode, total = seo.pick_hub_camps(closed_camps, closed_cap=12, sample_cap=8)
expect(mode == "closed" and total == 2 and [c["name"] for c in shown] == ["A", "B"], "closed sort")
many = [{"name": f"C{i:02d}", "status": "closed", "region": "a"} for i in range(15)]
shown, mode, total = seo.pick_hub_camps(many, closed_cap=12)
expect(mode == "closed" and total == 15 and len(shown) == 12, "closed cap")

sample_camps = []
for region, source, names in (
    ("east", "parks_sa", ["E1", "E2"]),
    ("west", "osm", ["W1"]),
    ("north", "tas", ["N1", "N2"]),
):
    for name in names:
        sample_camps.append({"name": name, "status": "check", "region": region, "source": source})
shown, mode, total = seo.pick_hub_camps(sample_camps, sample_cap=4)
expect(mode == "sample" and total == 0 and len(shown) == 4, "sample count " + str(shown))
expect(len({c["region"] for c in shown}) >= 2, "sample spreads regions")
expect(all(c["status"] != "closed" for c in shown), "sample not closed")

home = seo.pick_home_camps([
    ("Victoria", "vic", [{"name": "V closed", "status": "closed", "region": "h"}, {"name": "V open", "status": "open", "region": "h"}]),
    ("South Australia", "sa", [{"name": "S1", "status": "check", "region": "sa", "source": "parks_sa"}, {"name": "S2", "status": "check", "region": "sa", "source": "parks_sa"}]),
])
expect([name for name, _camp in home] == ["Victoria", "South Australia", "South Australia"], "home order " + str(home))
expect(home[0][1]["status"] == "closed", "home closed first")
expect(all("/" not in pair[0] for pair in home), "names")

box = seo.national_disclaimer()
expect(box.count('<div class="warn">') == 1 and box.endswith("</div>"), "one national box " + box)
expect("<strong>Not an official warning service.</strong>" in box, "strong lead")
expect(
    'href="' + seo.BOM_WARNINGS_URL + '" target="_blank" rel="noopener noreferrer">Bureau of Meteorology warnings</a>' in box,
    "bom link",
)
expect('<a href="/about/">About</a>' in box and '<a href="tel:000">000</a>' in box, "about and 000")
expect("CampConditions does not republish live emergency warnings, and no listed alert does not mean a camp is open." in box, "core")
expect(box == seo.national_disclaimer(), "stable")
for state_name in (
    "Victoria", "New South Wales", "Queensland", "South Australia", "Tasmania",
    "Western Australia", "Northern Territory", "Australian Capital Territory",
):
    expect(state_name not in box, "national box names " + state_name)

vic_html = (
    '<div class="warn"><strong>Not an official warning service.</strong> '
    'Check <a href="https://emergency.vic.gov.au/respond/">VicEmergency</a> '
    'and warnings for Victoria. Call <a href="tel:000">000</a>.</div>'
)
expect(seo.about_warning({"name": "Victoria", "safety_html": vic_html}) == vic_html, "labelled state stays")
sa_html = '<div class="warn">No current notice does not mean the camp is open, so check before you travel.</div>'
sa_out = seo.about_warning({"name": "South Australia", "safety_html": sa_html})
expect(
    sa_out == '<div class="warn"><strong>South Australia.</strong> No current notice does not mean the camp is open, so check before you travel.</div>',
    "sa label " + sa_out,
)
tas_html = '<div class="warn">No current alert does not mean the camp is open, so check before you travel.</div>'
tas_out = seo.about_warning({"name": "Tasmania", "safety_html": tas_html})
expect(
    tas_out == '<div class="warn"><strong>Tasmania.</strong> No current alert does not mean the camp is open, so check before you travel.</div>',
    "tas label " + tas_out,
)
linked = '<div class="warn">Check <a href="https://example.test/warn">the agency</a> before you travel.</div>'
linked_out = seo.about_warning({"name": "Example", "safety_html": linked})
expect('href="https://example.test/warn"' in linked_out and "the agency" in linked_out, "label keeps the link " + linked_out)
expect(linked_out.startswith('<div class="warn"><strong>Example.</strong> '), "label position")
expect(seo.about_warning({"name": "Victoria", "safety_html": ""}) == "", "empty warning")

if failures:
    print("\n".join(failures))
    raise SystemExit(1)
print("seo ok")
