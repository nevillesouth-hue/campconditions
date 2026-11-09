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
import act_sa_status as status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Write a disabled ACT/SA preview report")
    parser.add_argument("--out", required=True, help="Directory outside dist/")
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
    print("wrote %s" % dest)
    print("send=%s enrol=%s camps=%s" % (report["send"], report["enrol"], len(report["statuses"])))


if __name__ == "__main__":
    main()
