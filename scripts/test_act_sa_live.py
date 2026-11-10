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

INDEXES = [
    "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts",
    "https://www.parks.act.gov.au/before-you-go/alerts",
]
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
sa_index = html.fetch_public_html(INDEXES[0])
if sa_index["ok"]:
    discovered = html.discover_sa_notices(sa_index["body"])
    report = html.completeness(discovered, parsed)
    print("LIVE INDEX SA discovered=%s handled=%s all_supported=%s" % (
        report["discovered_detail_notices"], report["parsed_handled"], report["all_discovered_supported"]))
    if report["all_discovered_supported"] or report["camp_count"] is not None:
        failures.append("index discovery was treated as full coverage")
    if report["discovered_detail_notices"] < 2:
        failures.append("SA index did not expose detail links")
else:
    print("LIVE INDEX SA FAIL", sa_index.get("http_status"))
    if html.closure_failure(sa_index)["open_inferred"]:
        failures.append("SA index failure looked open")
act_index = html.fetch_public_html(INDEXES[1])
if act_index["ok"]:
    woods = html.parse_act_alerts_index(act_index["body"], act_index.get("headers") or {}, act_index["checked_at"], act_index["http_status"])
    print("LIVE INDEX ACT woods", woods.get("operating_status"), "age", (woods.get("source_health") or {}).get("cache_age_seconds"))
    if woods.get("reopen_at") or woods.get("open_inferred"):
        failures.append("ACT index inferred a reopen")
else:
    blocked = html.parse_act_alerts_index("", {}, act_index["checked_at"], act_index.get("http_status") or 403)
    print("LIVE INDEX ACT FAIL", act_index.get("http_status"), "retain", blocked.get("retain_known_closure"))
    if blocked.get("open_inferred") or blocked.get("reopen_at"):
        failures.append("ACT index failure reopened Woods")
print("live parsed %s of %s; failures recorded without an open status" % (len(parsed), len(PAGES)))
if failures:
    print("LIVE ASSERTIONS")
    for item in failures:
        print(" ", item)
    sys.exit(1)
sys.exit(0)
