#!/usr/bin/env python3
"""Live HTML checks. Separate from the offline fixture suite.

A network or HTTP failure is reported and is not turned into an open status.
A 200 page that loses its published date fails this script.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import act_sa_html as html

PAGES = [
    "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/mount-remarkable-national-park-15",
    "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/para-wirra-conservation-park-23",
    "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/onkaparinga-river-national-park-6",
    "https://www.parks.act.gov.au/find-a-nature-park/namadgi-national-park/woods-reserve",
]
failures = []
parsed = []
for url in PAGES:
    fetched = html.fetch_public_html(url)
    if not fetched["ok"]:
        record = html.closure_failure(fetched)
        print("LIVE FAIL %s %s" % (fetched.get("http_status"), url))
        if record["open_inferred"] or record["status"] != "unknown":
            failures.append(url + " failure looked open")
        continue
    record = html.parse_closure_html(fetched["body"], url, fetched["checked_at"])
    print("LIVE OK %s published=%s ambiguous=%s camps=%s" % (url.rsplit("/", 1)[-1], record.get("published"), record.get("ambiguous"), record.get("camp_ids")))
    if not record.get("ok") or record.get("open_inferred") or not record.get("published"):
        failures.append(url + " unreadable 200")
        continue
    parsed.append(record)

if not any(row.get("published") == "2025-12-31" for row in parsed):
    failures.append("Mount Remarkable published date was not read")
if not any(row.get("recurrence") for row in parsed):
    failures.append("Wirra Wednesday recurrence was not read")
if not any(row.get("ambiguous") for row in parsed):
    failures.append("Pink Gum booking exception was not flagged")
act_blocked = "https://www.parks.act.gov.au/find-a-nature-park/namadgi-national-park/woods-reserve"
# Printed above. Absence of an ACT success is the current source limit, not an open camp.
print("live parsed %s of %s; failures recorded without an open status" % (len(parsed), len(PAGES)))
if failures:
    print("LIVE ASSERTIONS")
    for item in failures:
        print(" ", item)
    sys.exit(1)
sys.exit(0)
