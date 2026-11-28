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


# Camp page titles: town within 40 km, else region, else state. Never cut the name.
horseshoe = seo.camp_page_title("Horseshoe Beach", "VIC", town="Cobram", region="Murray & Mallee", state_name="Victoria")
expect(horseshoe == "Horseshoe Beach, near Cobram VIC | CampConditions.au", "horseshoe town " + horseshoe)
expect(len(horseshoe) <= 65, "horseshoe length " + str(len(horseshoe)))
region_only = seo.camp_page_title("Horseshoe Beach", "VIC", town="", region="Murray & Mallee", state_name="Victoria")
expect(region_only == "Horseshoe Beach, Murray & Mallee VIC | CampConditions.au", "horseshoe region " + region_only)
# A locality must not be passed in as town; the caller uses nearest_title_town.
no_locality = seo.camp_page_title("Horseshoe Beach", "VIC", town="", region="Murray & Mallee", state_name="Victoria")
expect("Scotts Beach" not in no_locality and "near " not in no_locality, "no locality " + no_locality)
# SA/TAS: region is the state, so use ", ST camping" unless the name already has Camp.
sa_retreat = seo.camp_page_title("Nutbush Retreat", "SA", town="", region="South Australia", state_name="South Australia")
expect(sa_retreat == "Nutbush Retreat, SA camping | CampConditions.au", "sa camping " + sa_retreat)
expect(sa_retreat.lower().count("south australia") == 0, "sa no repeated state " + sa_retreat)
tas_camp = seo.camp_page_title("Musselroe Bay Campground", "TAS", town="", region="Tasmania", state_name="Tasmania")
expect(tas_camp == "Musselroe Bay Campground, TAS | CampConditions.au", "tas no extra camping " + tas_camp)
expect("camping" not in tas_camp.lower().replace("campground", ""), "tas camp word " + tas_camp)
sa_town = seo.camp_page_title("Nutbush Retreat", "SA", town="Port Lincoln", region="South Australia", state_name="South Australia")
expect(sa_town == "Nutbush Retreat, near Port Lincoln SA | CampConditions.au", "sa town " + sa_town)
# Don't repeat a town already in the display name.
named = seo.camp_page_title("Foreshore Reserve, near Cobram", "VIC", town="Cobram", region="Murray & Mallee", state_name="Victoria")
expect(named == "Foreshore Reserve, near Cobram VIC | CampConditions.au", "existing near " + named)
expect(named.lower().count("near cobram") == 1, "near once " + named)
# Long official names are never cut. Town/region is dropped first if the title is long.
long_name = (
    "Great South West Walk - Simsons Camping Area to Lake Mombeong Camping Area "
    "(Nelson Streamside Reserve, Glenelg River Heritage River, Discovery Bay Coastal Park, Lower Glenelg National Park)"
)
full = seo.camp_page_title(long_name, "VIC", town="Heywood", region="Grampians & South West", state_name="Victoria")
expect(long_name in full, "full name kept " + full)
expect(full.endswith(seo.TITLE_BRAND), "full brand " + full)
expect(full.startswith(long_name + " VIC") or ", near Heywood" in full, "state or town kept " + full)
# Numbered sites keep the number and the rest of the official name.
farley_name = "Farley Bend Camping Area Site 2 (River Murray Reserve)"
farley = seo.camp_page_title(
    "Farley Bend Camping Area Site 2  (River Murray Reserve)",
    "VIC", town="Echuca", region="Goldfields & Central Victoria", state_name="Victoria",
)
expect(farley_name in farley, "farley full name " + farley)
# A short name still keeps the town when the title fits.
macarthur = seo.camp_page_title(
    "Macarthur Recreation Reserve", "VIC", town="Penshurst",
    region="Grampians & South West", state_name="Victoria",
)
expect("Macarthur Recreation Reserve" in macarthur, "macarthur name " + macarthur)
expect("Macarthur Recreation," not in macarthur, "macarthur not clipped " + macarthur)
# Acheron with a town fits; the long region is allowed to run a little over so the name stays readable.
acheron_town = seo.camp_page_title("Acheron Campground", "VIC", town="Healesville", region="Yarra Ranges & Central Highlands", state_name="Victoria")
expect(acheron_town == "Acheron Campground, near Healesville VIC | CampConditions.au", "acheron town " + acheron_town)
expect(len(acheron_town) <= 65, "acheron town length")
# Closed wording is not part of the new title shape.
expect("check with the operator" not in horseshoe and "is it open?" not in horseshoe, "no old stock phrases")

# nearest_title_town: city/town within 40 km only, no locality fallback.
import towns as town_mod
_places = [
    {"name": "Scotts Beach", "lat": -35.93, "lon": 145.70, "place": "locality"},
    {"name": "Cobram", "lat": -35.92, "lon": 145.65, "place": "town"},
    {"name": "Emita", "lat": -39.94, "lon": 147.88, "place": "hamlet"},
]
_town, _dist = town_mod.nearest_title_town(-35.928, 145.696, _places)
expect(_town == "Cobram" and _dist is not None and _dist <= 40, "title town cobram " + str((_town, _dist)))
_none, _none_d = town_mod.nearest_title_town(-39.94, 147.88, _places)
expect(_none == "" and _none_d is None, "no hamlet fallback " + str((_none, _none_d)))
# A town 50 km away is also ignored.
_far = [{"name": "Gregory", "lat": -18.65, "lon": 139.25, "place": "town"}]
_far_name, _far_d = town_mod.nearest_title_town(-18.0, 139.25, _far)
expect(_far_name == "" and _far_d is None, "town beyond 40 km " + str((_far_name, _far_d)))



# Distinctive bits already in the official name split a title clash. Clip must
# keep Site N, short parentheticals, and an existing ", near" town, and must not
# leave a stray closing parenthesis.
def _titles_for(camps, **kwargs):
    def retry(camp, extra="", with_region=False):
        name = camp.get("page_name") or camp.get("name") or ""
        return seo.camp_page_title(name, extra=extra, with_region=with_region, **kwargs)
    return seo.resolve_title_collisions(camps, lambda camp: retry(camp), retry)

_ganguddy = _titles_for(
    [
        {"name": "Camping Area - Ganguddy (The Point)"},
        {"name": "Camping Area - Ganguddy (Kookaburra Bch)"},
        {"name": "Camping Area - Ganguddy (Ngurang)"},
    ],
    abbrev="NSW", town="Kandos", region="Central NSW", state_name="New South Wales",
)
expect(len(set(title.casefold() for title in _ganguddy)) == 3, "ganguddy unique " + str(_ganguddy))
_joined = " ".join(_ganguddy)
expect("The Point" in _joined and "Kookaburra Bch" in _joined and "Ngurang" in _joined, "ganguddy bits " + _joined)
expect(all("(" in title or ")" not in title.split("|")[0] for title in _ganguddy), "ganguddy parens " + str(_ganguddy))

_ranch = _titles_for(
    [
        {"name": "The Ranch Camping Area Site 2 (River Murray Reserve, Proposed Murray River Park (part))"},
        {"name": "The Ranch Camping Area Site 3 (River Murray Reserve, Proposed Murray River Park (part))"},
    ],
    abbrev="VIC", town="Barmah", region="Goldfields & Central Victoria", state_name="Victoria",
)
expect(len(set(_ranch)) == 2 and "Site 2" in _ranch[0] and "Site 3" in _ranch[1], "ranch sites " + str(_ranch))

_richards = _titles_for(
    [
        {"page_name": "Richardsons Beach Campground, near Dolphin Sands", "name": "Richardsons Beach Campground"},
        {"page_name": "Richardsons Beach Campground, near Coles Bay", "name": "Richardsons Beach Campground"},
    ],
    abbrev="TAS", region="Tasmania", state_name="Tasmania",
)
# The H1 already has ", near …"; the title must keep that full name.
expect("Richardsons Beach Campground, near Dolphin Sands" in _richards[0], "richards dolphin " + str(_richards))
expect("Richardsons Beach Campground, near Coles Bay" in _richards[1], "richards coles " + str(_richards))
expect(len(set(title.casefold() for title in _richards)) == 2, "richards unique")



_cunningham = _titles_for(
    [
        {"name": "Cunningham Weir camping area"},
        {"name": "Cunningham Weir Campsite"},
        {"name": "Cunningham Weir Free Camp"},
    ],
    abbrev="NSW", region="New England North West", state_name="New South Wales",
)
expect(len(set(title.casefold() for title in _cunningham)) == 3, "cunningham unique " + str(_cunningham))
_cjoin = " ".join(_cunningham).casefold()
expect("campsite" in _cjoin and "free camp" in _cjoin, "cunningham bits " + str(_cunningham))

_ravens = _titles_for(
    [
        {"name": "Ravenswood Showground Camping & Public"},
        {"name": "Ravenswood Showground (Recreation Reserve)"},
    ],
    abbrev="QLD", town="Ravenswood", region="Townsville", state_name="Queensland",
)
expect(len(set(title.casefold() for title in _ravens)) == 2, "ravens unique " + str(_ravens))



# Fact-only summaries: only when there is no real description and at least two
# recorded facts. NPWS, QPWS, SA and TAS are skipped. No invented distances or ratings.
_sum_ok = seo.fact_summary(
    {"name": "Horseshoe Beach", "slug": "horseshoe-beach", "source": "osm", "state_slug": "vic",
     "cost": "free", "fac_caravans": True, "fac_dogs": True},
    "Gippsland", "Victoria",
)
expect(_sum_ok and "Horseshoe Beach" in _sum_ok and "Gippsland" in _sum_ok and "Victoria" in _sum_ok, "summary place " + repr(_sum_ok))
expect("free" in _sum_ok and "caravans" in _sum_ok and "dogs" in _sum_ok, "summary facts " + repr(_sum_ok))
expect("No Rating" not in _sum_ok and "km" not in _sum_ok.lower(), "summary invented " + repr(_sum_ok))
expect(seo.fact_summary(
    {"name": "Has prose", "slug": "has-prose", "source": "osm", "state_slug": "vic",
     "cost": "free", "fac_dogs": True, "description": "A shady riverside camp."},
    "Gippsland", "Victoria",
) == "", "skip real description")
expect(seo.fact_summary(
    {"name": "NPWS camp", "slug": "npws-camp", "source": "npws", "state_slug": "nsw",
     "cost": "free", "fac_dogs": True, "fac_caravans": True},
    "North Coast", "New South Wales",
) == "", "skip npws")
expect(seo.fact_summary(
    {"name": "QPWS camp", "slug": "qpws-camp", "source": "qpws", "state_slug": "qld",
     "cost": "free", "fac_dogs": True, "fac_caravans": True},
    "Capricorn", "Queensland",
) == "", "skip qpws")
expect(seo.fact_summary(
    {"name": "SA camp", "slug": "sa-camp", "source": "osm", "state_slug": "sa",
     "cost": "free", "fac_dogs": True, "fac_caravans": True},
    "South Australia", "South Australia",
) == "", "skip sa")
expect(seo.fact_summary(
    {"name": "TAS camp", "slug": "tas-camp", "source": "tas", "state_slug": "tas",
     "cost": "free", "fac_dogs": True, "fac_caravans": True},
    "Tasmania", "Tasmania",
) == "", "skip tas")
expect(seo.fact_summary(
    {"name": "Thin", "slug": "thin", "source": "osm", "state_slug": "nsw", "cost": "free"},
    "New South Wales", "New South Wales",
) == "", "need two facts")
_variants = {
    seo.fact_summary(
        {"name": "Alpha Camp", "slug": slug, "source": "osm", "state_slug": "vic",
         "cost": "free", "fac_caravans": True, "fac_dogs": True},
        "High Country", "Victoria",
    )
    for slug in ("aaa", "alpha", "bravo")
}
expect(len(_variants) >= 2 and all(_variants), "deterministic variants " + repr(_variants))
# Same slug always yields the same wording.
_first = seo.fact_summary(
    {"name": "Alpha Camp", "slug": "alpha", "source": "osm", "state_slug": "vic",
     "cost": "free", "fac_caravans": True, "fac_dogs": True},
    "High Country", "Victoria",
)
_again = seo.fact_summary(
    {"name": "Alpha Camp", "slug": "alpha", "source": "osm", "state_slug": "vic",
     "cost": "free", "fac_caravans": True, "fac_dogs": True},
    "High Country", "Victoria",
)
expect(_first == _again and _first, "stable wording " + repr(_first))
# Donation fee type is worded as donation, never as free.
_don = seo.fact_summary(
    {"name": "Macarthur Recreation Reserve", "slug": "macarthur-recreation-reserve",
     "source": "osm", "state_slug": "vic", "cost": "free", "category": "Donation",
     "fee_type": "donation", "fee_label": "Donation", "fac_caravans": True},
    "Grampians & South West", "Victoria",
)
expect(_don and "Macarthur Recreation Reserve" in _don, "donation name " + repr(_don))
expect("donation camping area" in _don and "free camping area" not in _don, "donation wording " + repr(_don))
# Summary uses the full recorded name, including a leading 150.
_mer = seo.fact_summary(
    {"name": "150 Meridian Rest Area", "slug": "150-meridian-rest-area",
     "source": "osm", "state_slug": "nsw", "cost": "free", "fac_caravans": True},
    "New England North West", "New South Wales",
)
expect(_mer.startswith("150 Meridian Rest Area"), "meridian name " + repr(_mer))

if failures:
    print("\n".join(failures))
    raise SystemExit(1)
print("seo ok")
