#!/usr/bin/env python3
"""SA and TAS signup and digest stay off until the release flags are turned on."""
import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import digest
import sa_signup
import states
import tas_signup

FAILURES = []


def expect(cond, label):
    if cond:
        return
    FAILURES.append(label)
    print(" FAIL", label)


def test_region_line():
    expect(
        states.weekend_closures_line("South Australia", "South Australia")
        == "Get the weekend closures for South Australia free each Thursday.",
        "SA region line does not repeat the state",
    )
    expect(
        states.weekend_closures_line("Tasmania", "Tasmania")
        == "Get the weekend closures for Tasmania free each Thursday.",
        "TAS region line does not repeat the state",
    )
    expect(
        "Camping in South Australia? " + states.weekend_closures_line("South Australia", "South Australia")
        == "Camping in South Australia? Get the weekend closures for South Australia free each Thursday.",
        "SA inline sentence",
    )
    expect(
        "Camping in Tasmania? " + states.weekend_closures_line("Tasmania", "Tasmania")
        == "Camping in Tasmania? Get the weekend closures for Tasmania free each Thursday.",
        "TAS inline sentence",
    )
    expect(
        states.weekend_closures_line("Gippsland", "Victoria")
        == "Get the weekend closures for Gippsland and the rest of Victoria free each Thursday.",
        "multi-region states keep the rest of the state",
    )
    expect(
        states.weekend_closures_line("Gold Coast", "Queensland")
        == "Get the weekend closures for Gold Coast and the rest of Queensland free each Thursday.",
        "Queensland regions keep the rest of the state",
    )


def test_flags_off():
    expect(sa_signup.COMING_SOON == "SA weekly email coming soon", "SA coming soon line")
    expect(tas_signup.COMING_SOON == "Tas weekly email coming soon", "TAS coming soon line")
    sa_on = states.by_slug("sa")["release"].get("signup") is True
    tas_on = states.by_slug("tas")["release"].get("signup") is True
    offered = [state["slug"] for state in states.signup_states()]
    if not sa_on and not tas_on:
        expect(sa_signup.forms_allowed() is False, "SA form stays off")
        expect(tas_signup.forms_allowed() is False, "TAS form stays off")
        expect(offered == ["vic", "nsw", "qld"], "signup offers three states")
        form = states.signup_fieldset(states.signup_states(), "")
        for slug in ("vic", "nsw", "qld"):
            expect('value="%s"' % slug in form and 'value="%s" checked' % slug not in form, slug + " is offered unticked")
        expect('value="sa"' not in form and 'value="tas"' not in form, "flags off omit SA and TAS")
        expect(states.digest_allowed(states.by_slug("sa")) is False, "SA digest flag is off")
        expect(states.digest_allowed(states.by_slug("tas")) is False, "TAS digest flag is off")
        home = os.path.join(ROOT, "dist", "index.html")
        if os.path.isfile(home):
            page = open(home, encoding="utf-8").read()
            expect('name="states" value="vic"' in page and 'name="states" value="nsw"' in page and 'name="states" value="qld"' in page, "built home offers the three states")
            expect('name="states" value="sa"' not in page and 'name="states" value="tas"' not in page, "built home does not offer SA or TAS")
            summer = open(os.path.join(ROOT, "dist", "summer", "index.html"), encoding="utf-8").read()
            expect("(The email covers VIC, NSW and QLD for now.)" in summer, "summer coverage line stays as it is")
            for slug, line in (("sa", "SA weekly email coming soon."), ("tas", "Tas weekly email coming soon.")):
                state_page = open(os.path.join(ROOT, "dist", slug, "index.html"), encoding="utf-8").read()
                expect(line in state_page and 'action="/api/subscribe"' not in state_page, slug + " page still says coming soon")
    else:
        expect(sa_on and tas_on, "switch-on opens both states together")
        expect(sa_signup.forms_allowed() is True and tas_signup.forms_allowed() is True, "forms follow release.signup")
        expect(offered == ["vic", "nsw", "qld", "sa", "tas"], "switch-on config offers five states")


def _opened(slug):
    state = json.loads(json.dumps(states.by_slug(slug)))
    state["release"]["signup"] = True
    state["release"]["digest"] = True
    for gate in state["release"]["gates"]:
        if gate.get("id") == "digest_segment":
            gate["id"] = "digest_topic"
            gate["ok"] = True
            gate["detail"] = "SA/TAS use the all-subscribers segment plus a private opt_out topic"
    return state


def test_switch_on_shape():
    real = states.signup_allowed
    def allow(state):
        if state.get("slug") in ("sa", "tas"):
            return True
        return real(state)
    states.signup_allowed = allow
    try:
        offered = states.signup_states()
        expect([state["slug"] for state in offered] == ["vic", "nsw", "qld", "sa", "tas"], "switch-on offers five states")
        home = states.signup_fieldset(offered, "")
        expect('value="sa"' in home and 'value="tas"' in home and 'value="sa" checked' not in home and 'value="tas" checked' not in home, "home leaves SA and TAS unticked")
        expect("> SA</label>" in home and "> TAS</label>" in home, "checkbox labels are the abbreviations")
        sa_form = states.signup_fieldset(offered, "sa")
        tas_form = states.signup_fieldset(offered, "tas")
        expect('value="sa" checked' in sa_form and 'value="tas" checked' not in sa_form, "SA pages pre-tick SA")
        expect('value="tas" checked' in tas_form and 'value="sa" checked' not in tas_form, "TAS pages pre-tick TAS")
    finally:
        states.signup_allowed = real
    sa = _opened("sa")
    tas = _opened("tas")
    expect(states.digest_allowed(sa) and states.digest_allowed(tas), "digest flag opens the draft")
    expect((sa.get("copy") or {})["newsletter_h2"] == "Get the free weekly South Australia digest", "SA heading")
    expect((tas.get("copy") or {})["newsletter_h2"] == "Get the free weekly Tasmania digest", "TAS heading")
    when = dt.datetime(2026, 11, 19, 9, tzinfo=dt.timezone.utc)
    rows = [{
        "name": "Sample Camp",
        "slug": "sample-camp",
        "url": "https://campconditions.au/sa/camp/sample-camp/",
        "status": "closed",
        "region": "south-australia",
        "closure": {"desc": "Closed for works"},
        "upcoming_closure": {"desc": "Track works", "start": "2026-12-01"},
    }]
    dest = tempfile.mkdtemp(prefix="sa-digest-open-")
    digest.write_digest(sa, rows, None, when, when.isoformat(), dest)
    html = open(os.path.join(dest, "digest.html"), encoding="utf-8").read()
    text = open(os.path.join(dest, "digest.txt"), encoding="utf-8").read()
    for bit in ("Newly closed", "Reopened", "Closed, by region", "Coming up", "Chip in", "Tell a mate about CampConditions", "{{{RESEND_UNSUBSCRIBE_URL}}}"):
        expect(bit in html, "SA digest has " + bit)
    expect("Do not send" not in html and "Do not send" not in text, "SA digest has no do-not-send line")
    expect("Fire danger and Total Fire Ban" not in html and "cfs.sa.gov.au" in html, "SA digest links out and does not list a rating")
    expect("South Australia camps this week: 1 closed" in html, "SA subject")
    expect("South Australian camps and campgrounds" in html, "SA intro")
    tas_rows = [{
        "name": "Sample Tas Camp",
        "slug": "sample-tas",
        "url": "https://campconditions.au/tas/camp/sample-tas/",
        "status": "closed",
        "region": "tasmania",
        "closure": {"desc": "Closed"},
    }]
    alerts = [{"headline": "Road closed", "parks": ["Freycinet National Park"], "link": "https://parks.tas.gov.au/explore-our-parks/know-before-you-go/alerts"}]
    tas_dest = tempfile.mkdtemp(prefix="tas-digest-open-")
    digest.write_digest(tas, tas_rows, None, when, when.isoformat(), tas_dest, alerts)
    tas_html = open(os.path.join(tas_dest, "digest.html"), encoding="utf-8").read()
    tas_text = open(os.path.join(tas_dest, "digest.txt"), encoding="utf-8").read()
    for bit in ("Newly closed", "Reopened", "Closed, by region", "Park alerts this week", "Road closed", "Freycinet National Park", "Parks and Wildlife Service alerts", "{{{RESEND_UNSUBSCRIBE_URL}}}", "Chip in"):
        expect(bit in tas_html, "TAS digest has " + bit)
    expect("Do not send" not in tas_html and "Do not send" not in tas_text, "TAS digest has no do-not-send line")
    expect("fire.tas.gov.au" in tas_html and "alert.tas.gov.au" in tas_html, "TAS warnings are links")
    expect("Tasmania camps this week: 1 closed" in tas_html, "TAS subject")
    open(os.path.join(dest, "snippet.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(tas_dest, "snippet.html"), "w", encoding="utf-8").write(tas_html)
    print("SA_SNIPPET", os.path.join(dest, "digest.html"))
    print("TAS_SNIPPET", os.path.join(tas_dest, "digest.html"))


def main():
    test_region_line()
    test_flags_off()
    test_switch_on_shape()
    if FAILURES:
        print("SA/TAS signup failures: %s" % len(FAILURES))
        return 1
    print("SA/TAS signup checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
