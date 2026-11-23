#!/usr/bin/env python3
"""Northern Territory stays out of the public build."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import nt_digest
import nt_fire
import nt_inventory
import nt_launch_gate
import nt_signup
import states

FAILURES = []


def expect(cond, label):
    if cond:
        return
    FAILURES.append(label)
    print(" FAIL", label)


def test_flags():
    nt = states.by_slug("nt")
    expect(nt.get("enabled") is False, "nt enabled is false")
    expect(states.public_build_allowed(nt) is False, "public build stays off")
    expect(states.signup_allowed(nt) is False, "signup stays off")
    expect(states.digest_allowed(nt) is False, "digest stays off")
    expect((nt.get("release") or {}).get("region_enabled") is False, "region flag is off")
    expect("nt" not in [state["slug"] for state in states.enabled()], "enabled list omits nt")
    expect("nt" not in [state["slug"] for state in states.signup_states()], "signup list omits nt")
    saved = os.environ.get("CAMPCONDITIONS_ENABLE")
    os.environ["CAMPCONDITIONS_ENABLE"] = "nt"
    try:
        expect("nt" not in [state["slug"] for state in states.enabled()], "enable flag cannot add nt")
    finally:
        if saved is None:
            os.environ.pop("CAMPCONDITIONS_ENABLE", None)
        else:
            os.environ["CAMPCONDITIONS_ENABLE"] = saved


def test_inventory():
    camps = nt_inventory.load_camps()
    counted = nt_inventory.summary(camps)
    expect(counted["booking"] == 106, "booking count")
    expect(counted["published"] == 97, "published count")
    expect(counted["excluded"] == 5, "permit exclusions")
    expect(counted["held"] == 216, "held rest areas, council showground and booking camps")
    expect(counted["held_by_reason"].get("status_unconfirmed") == 211, "rest areas held for unconfirmed camping status")
    expect(counted["held_by_reason"].get("no_coordinates") == 5, "holds with no coordinates")
    expect(counted["by_type"]["NT Parks campground"] == 97, "type is NT Parks")
    expect(counted["by_type"]["Rest area"] == 0, "no rest area is published")
    expect(counted["by_type"]["Council showground"] == 0, "showground without coordinates stays out")
    expect(counted["by_type"]["Free"] == 0 and counted["by_type"]["Donation"] == 0, "no free or donation camps in this list")
    expect(counted["osm_only"] == 0, "no openstreetmap records")
    expect(counted["amended_matched"] == nt_launch_gate.EXPECTED_MATCHES, "amended matches")
    expect(counted["amended_missed"] == nt_launch_gate.EXPECTED_MISSES, "amended misses")
    by_name = {camp["name"]: camp for camp in camps}
    surprise = by_name["Surprise Creek Campground"]
    expect(surprise["lat"] == -13.402855 and surprise["lon"] == 130.784153, "amended surprise creek coordinates")
    expect(surprise["coord_source"] == "amended", "surprise creek marked amended")
    expect(by_name["Ormiston Gorge campground"]["coord_source"] == "booking", "ormiston keeps the booking coordinate")
    expect("Garig Gunak Barlu National Park" not in {camp["place"] for camp in camps}, "garig is not published")
    expect("Barranyi (North Island) National Park" not in {camp["place"] for camp in camps}, "barranyi is not published")
    expect(all(camp["status"] == "check" for camp in camps), "pages ask people to check")
    expect(nt_inventory.parks_without_keep(camps) == [], "no commercial park on the list")
    page = nt_inventory.html_block(surprise)
    expect(nt_inventory.ATTRIBUTION in page, "placeholder attribution")
    expect("TODO" not in page, "todo stays out of the camp block")
    expect("<form" not in page, "camp block has no form")


def test_signup_and_fire():
    soon = nt_signup.coming_soon_html()
    expect(nt_signup.forms_allowed() is False, "form stays off")
    expect("NT weekly email coming soon." in soon and "<form" not in soon, "coming soon line")
    line = nt_fire.html_line({})
    expect(nt_fire.FIRE_URL in line and "bom.gov.au" not in line.lower(), "fire link without bom")
    decision = nt_digest.perform_send()
    expect(decision["send"] is False and decision["called_resend"] is False, "digest does not send")
    forced = nt_digest.perform_send(region_enabled=True)
    expect(forced["send"] is False and forced["called_resend"] is False, "an on flag still does not send")


def test_gate():
    with tempfile.TemporaryDirectory() as folder:
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as handle:
            handle.write('<form><input name="states" value="vic"><input name="states" value="nsw"><input name="states" value="qld"></form>')
        gate = nt_launch_gate.evaluate(folder)
    by_name = {item["check"]: item for item in gate["checks"]}
    expect(gate["pass"] is False, "gate fails")
    expect(by_name["attribution_confirmed"]["pass"] is False, "attribution check fails")
    expect(by_name["amended_coordinates"]["pass"] is False, "amended name check fails")
    expect(by_name["inventory"]["pass"] and by_name["caravan_park_keep"]["pass"], "inventory and caravan checks pass")
    expect(by_name["extra_source_attribution"]["pass"], "new source attribution is recorded")
    expect(by_name["fire_source_resolved"]["pass"], "fire source check passes")
    expect(by_name["nt_signup"]["pass"] and by_name["public_nt"]["pass"], "signup and public checks pass")
    home = os.path.join(ROOT, "dist", "index.html")
    if os.path.isfile(home):
        page = open(home, encoding="utf-8").read()
        expect('href="/nt/"' not in page and 'value="nt"' not in page, "built home omits nt")
        expect(not os.path.isdir(os.path.join(ROOT, "dist", "nt")), "built site has no nt directory")


def test_token():
    token = open(os.path.join(ROOT, "functions", "_lib", "token.js"), encoding="utf-8").read()
    expect("nt: false" in token, "js region flag is off")
    node = subprocess.run(
        ["node", "--input-type=module", "-e", """
import { chosenStates, heldSignupStates, REGION_ENABLED } from "./functions/_lib/token.js";
if (REGION_ENABLED.nt !== false) process.exit(1);
if (chosenStates(["nt"], {}).length !== 0) process.exit(2);
if (heldSignupStates(["nt"], {}).join() !== "nt") process.exit(3);
if (chosenStates(["vic", "nt"], {}).join() !== "vic") process.exit(4);
"""],
        cwd=ROOT, capture_output=True, text=True,
    )
    expect(node.returncode == 0, "token hold: " + (node.stderr or node.stdout)[-300:])


def main():
    test_flags()
    test_inventory()
    test_signup_and_fire()
    test_gate()
    test_token()
    if FAILURES:
        print("%s failed" % len(FAILURES))
        return 1
    print("nt checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
