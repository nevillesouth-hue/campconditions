#!/usr/bin/env python3
"""Write a local ACT/SA preview. Nothing is fetched, enrolled or sent.

Refuses to write under dist/ so the public site build cannot pick the files up.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import act_sa_html
import act_sa_status as status
import sa_digest
import sa_inventory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Write a disabled ACT/SA preview report")
    parser.add_argument("--out", required=True, help="Directory outside dist/")
    parser.add_argument("--live", action="store_true", help="Fetch the public allowlist. Default uses saved HTML fixtures.")
    args = parser.parse_args()
    dest = os.path.abspath(args.out)
    dist = os.path.abspath(os.path.join(ROOT, "dist"))
    if dest == dist or dest.startswith(dist + os.sep):
        raise SystemExit("Refusing to write the ACT/SA preview inside dist/")
    report = status.build_preview_report()
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    lines = [
        "PREVIEW ONLY. Do not send. Do not enrol.",
        "ACT and SA are not open for signup and are not on the public site.",
        "Evidence check date: %s. This file is not a live fetch." % report["evidence_checked"],
        "",
        "Inventory: %s" % json.dumps(report["inventory"], ensure_ascii=False),
        "",
    ]
    by_id = {row["camp_id"]: row for row in report["statuses"]}
    for camp_id in sorted(by_id):
        row = by_id[camp_id]
        lines.append("%s: %s closed=%s open_claim=%s" % (camp_id, row["status"], row["closed"], row["open_claim"]))
    lines.append("")
    lines.append("Blockers ACT: %s" % ", ".join(report["blockers"]["act"]))
    lines.append("Blockers SA: %s" % ", ".join(report["blockers"]["sa"]))
    lines.append("")
    lines.append("Resend variables not read by signup: %s" % ", ".join(item["name"] for item in report["resend"]["variables"]))
    lines.append("Generated %s" % dt.datetime.now(dt.timezone.utc).isoformat())
    text = "\n".join(lines) + "\n"
    if status.contains_no_rating(text):
        raise SystemExit("preview text used the No Rating label")
    with open(os.path.join(dest, "preview.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    html = (
        "<!DOCTYPE html><html lang=\"en-AU\"><head><meta charset=\"utf-8\"><title>ACT/SA preview — do not send</title></head>"
        "<body><h1>PREVIEW ONLY. Do not send. Do not enrol.</h1><pre>%s</pre></body></html>\n"
        % text.replace("&", "&amp;").replace("<", "&lt;")
    )
    with open(os.path.join(dest, "preview.html"), "w", encoding="utf-8") as handle:
        handle.write(html)
    moment = dt.datetime(2026, 11, 11, 7, 30, tzinfo=dt.timezone.utc)
    camps = [row for row in status.load_candidates()["records"] if row.get("entity_type") == "campground" or row.get("id") == "sa:helipad"]
    pages = live_pages() if args.live else fixture_pages()
    ingested = act_sa_html.ingest_pages(pages, camps, moment)
    digest_dir = os.path.join(dest, "digest")
    os.makedirs(digest_dir, exist_ok=True)
    for slug in ("act", "sa"):
        rows = [row for row in ingested["statuses"] if str(row.get("camp_id") or "").startswith(slug + ":")]
        draft = act_sa_html.preview_digest(slug, rows, report["moment"])
        folder = os.path.join(digest_dir, slug)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "digest.txt"), "w", encoding="utf-8") as handle:
            handle.write(draft["text"])
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(draft["meta"], handle, indent=2)
            handle.write("\n")
    sa_digest.write_preview(
        os.path.join(digest_dir, "sa"),
        sa_inventory.load_camps(set()),
        dt.datetime.now(dt.timezone.utc),
    )
    with open(os.path.join(dest, "ingest.json"), "w", encoding="utf-8") as handle:
        json.dump({
            "live": bool(args.live),
            "failures": ingested["failures"],
            "alert_count": len(ingested["alerts"]),
            "open_inferred": ingested["open_inferred"],
            "statuses": ingested["statuses"],
        }, handle, indent=2)
        handle.write("\n")
    print("wrote %s" % dest)
    print("send=%s enrol=%s camps=%s alerts=%s failures=%s" % (
        report["send"], report["enrol"], len(report["statuses"]), len(ingested["alerts"]), len(ingested["failures"])))


def fixture_pages():
    folder = os.path.join(ROOT, "data", "act-sa", "fixtures", "html")
    urls = {
        "mount-remarkable.html": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/mount-remarkable-national-park-15",
        "para-wirra.html": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/para-wirra-conservation-park-23",
        "onkaparinga.html": "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/onkaparinga-river-national-park-6",
    }
    pages = []
    for name, url in urls.items():
        with open(os.path.join(folder, name), encoding="utf-8") as handle:
            pages.append({"ok": True, "source_url": url, "body": handle.read(), "checked_at": "2026-11-09T01:40:00+00:00"})
    return pages


def live_pages():
    pages = []
    for url in (
        "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/mount-remarkable-national-park-15",
        "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/para-wirra-conservation-park-23",
        "https://www.parks.sa.gov.au/know-before-you-go/closures-and-alerts/onkaparinga-river-national-park-6",
        "https://www.parks.act.gov.au/find-a-nature-park/namadgi-national-park/woods-reserve",
    ):
        pages.append(act_sa_html.fetch_public_html(url))
    return pages


if __name__ == "__main__":
    main()
