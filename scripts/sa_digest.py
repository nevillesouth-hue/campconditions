#!/usr/bin/env python3
"""Local South Australia weekly digest. It matches the other states' layout.

Nothing here sends mail or creates a Resend segment. The send decision reads
RESEND_SEGMENT_SA_ID and refuses while signup is disabled or the variable is
empty.
"""
import datetime as dt
import html
import json
import os

import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFS_CREDIT = "Fire danger: SA Country Fire Service (cfs.sa.gov.au)"


def send_decision(env=None, region_enabled=None):
    """Whether an SA digest could be sent. This does not call Resend."""
    if region_enabled is None:
        region_enabled = states.signup_allowed(states.by_slug("sa"))
    provided = env if env is not None else os.environ
    segment = str(provided.get("RESEND_SEGMENT_SA_ID") or "").strip()
    if not region_enabled:
        return {"send": False, "reason": "region_disabled", "segment_id": "", "called_resend": False}
    if not segment:
        return {"send": False, "reason": "segment_unset", "segment_id": "", "called_resend": False}
    return {"send": True, "reason": "", "segment_id": segment, "called_resend": False}


def perform_send(env=None, region_enabled=None):
    """Apply the decision and stop. Resend is never called."""
    decision = send_decision(env, region_enabled)
    decision["called_resend"] = False
    if decision["send"]:
        decision = dict(decision)
        decision["send"] = False
        decision["reason"] = "resend_not_called"
    return decision


def _esc(value):
    return html.escape(str(value or ""), quote=True)


def _groups(camps, previous):
    closed = [camp for camp in camps if camp.get("notice_status") == "closed" or camp.get("status") == "closed"]
    partial = [camp for camp in camps if camp.get("notice_status") == "partial"]
    upcoming = [camp for camp in camps if camp.get("notice_status") == "upcoming"]
    closed_ids = {camp.get("slug") for camp in closed}
    reopened = []
    for camp in previous or []:
        if camp.get("status") == "closed" and camp.get("slug") not in closed_ids:
            reopened.append(camp)
    return closed, partial, upcoming, reopened


def _link(camp):
    slug = camp.get("slug") or ""
    url = "https://campconditions.au/sa/camp/%s/" % slug
    return '<a href="%s" style="color:#2f5d3a;">%s</a>' % (_esc(url), _esc(camp.get("name") or slug))


def _lines(camps):
    rows = []
    for camp in sorted(camps, key=lambda camp: (camp.get("name") or "").lower()):
        note = camp.get("notice_summary") or ""
        rows.append(_link(camp) + (" — " + _esc(note) if note else ""))
    return "<br>".join(rows) or "None this week."


def fire_summary(camps):
    found = {}
    for camp in camps:
        fire = camp.get("fire") or {}
        if fire.get("authority") != "sa_cfs":
            continue
        key = (fire.get("district") or "", fire.get("rating") or "", fire.get("date") or "", bool(fire.get("ban")))
        found[key] = found.get(key, 0) + 1
    if not found:
        return "Fire danger: unknown. " + _esc(CFS_CREDIT) + "."
    lines = []
    for (district, rating, day, ban), count in sorted(found.items()):
        ban_text = "Total Fire Ban: fires banned" if ban else "Total Fire Ban: no"
        lines.append("%s: %s, %s. %s. %s camps." % (_esc(district), _esc(rating), _esc(day), _esc(ban_text), count))
    lines.append(_esc(CFS_CREDIT) + ".")
    return "<br>".join(lines)


def render(camps, generated, previous=None):
    """HTML and text for one local SA digest. No merge tags and no send."""
    copy = (states.by_slug("sa").get("copy") or {})
    closed, partial, upcoming, reopened = _groups(camps, previous)
    date = generated.strftime("%-d %B %Y")
    subject = copy["digest_subject"].format(closed=len(closed))
    style = "font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;color:#222222;"

    def h2(title):
        return '<tr><td style="%sfont-size:18px;line-height:26px;font-weight:bold;padding-top:18px;color:#2f5d3a;">%s</td></tr>' % (style, _esc(title))

    def para(body):
        return '<tr><td style="%spadding-top:8px;">%s</td></tr>' % (style, body)

    intro = copy["digest_intro"].format(date=_esc(date))
    rows = [
        para("%s<br><strong>%s</strong> closed, <strong>%s</strong> partial, <strong>%s</strong> upcoming, of %s camps." % (
            intro, len(closed), len(partial), len(upcoming), len(camps))),
        h2("Closed"),
        para(_lines(closed)),
        h2("Partial"),
        para(_lines(partial)),
        h2("Upcoming"),
        para(_lines(upcoming)),
        h2("Reopened"),
        para(_lines(reopened)),
        h2("Fire danger and Total Fire Ban"),
        para(fire_summary(camps)),
        para(copy.get("digest_warnings") or ""),
        para('<strong>Been somewhere lately?</strong> <a href="https://campconditions.au/report/" style="color:#2f5d3a;">Report conditions</a> — how full, road access, water and phone coverage.'),
        para('<strong>The digests stay free.</strong> If they’re useful and you want to chip in, a one-off tip helps cover the running costs — coffee money is plenty.<br><a href="https://campconditions.au/support" style="color:#2f5d3a;">Chip in</a> $5, $10 or $20<br>No pressure either way.'),
    ]
    foot = (copy.get("digest_footer") or "") + (
        'CampConditions.au · <a href="https://campconditions.au/privacy/" style="color:#666666;">Privacy</a> · '
        '<a href="https://campconditions.au/unsubscribe/" style="color:#666666;">Unsubscribe</a>'
    )
    body = "".join(rows) + '<tr><td style="%sfont-size:12px;line-height:18px;color:#666666;padding-top:24px;">%s</td></tr>' % (style, foot)
    doc = """<!DOCTYPE html><html lang="en-AU"><head><meta charset="utf-8"><title>%s</title></head>
<body style="margin:0;background:#fbfaf6;"><div style="display:none;max-height:0;overflow:hidden;">Do not send.</div>
<table role="presentation" width="100%%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;padding:8px 24px 24px;">
<tr><td style="padding-top:16px;"><img src="https://campconditions.au/assets/brand/logo-160.png" width="77" height="77" alt="CampConditions.au" style="display:block;border:0;"></td></tr>
<tr><td style="%sfont-size:22px;line-height:28px;font-weight:bold;color:#2f5d3a;padding-top:8px;">CampConditions.au</td></tr>
%s</table></td></tr></table></body></html>""" % (_esc(subject), style, body)
    text = doc[doc.index("<body"):]
    text = text.replace("<br>", "\n")
    text = html.unescape(__import__("re").sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>', r"\2 (\1)", text))
    text = __import__("re").sub(r"</tr>", "\n", text)
    text = __import__("re").sub(r"<[^>]+>", "", text)
    text = __import__("re").sub(r"\n\s*\n+", "\n\n", text).strip() + "\n"
    meta = {
        "subject": subject,
        "state": "sa",
        "send": False,
        "enrol": False,
        "reads_segment_env": False,
        "working_digest_coverage": False,
        "called_resend": False,
        "closed": len(closed),
        "partial": len(partial),
        "upcoming": len(upcoming),
        "reopened": len(reopened),
        "generated": generated.isoformat(),
    }
    return {"html": doc, "text": text, "meta": meta}


def write_preview(dest, camps, generated=None, previous=None):
    """Write digest.html, digest.txt and meta.json outside dist/."""
    dest = os.path.abspath(dest)
    dist = os.path.abspath(os.path.join(ROOT, "dist"))
    if dest == dist or dest.startswith(dist + os.sep):
        raise SystemExit("Refusing to write the SA digest inside dist/")
    generated = generated or dt.datetime.now(dt.timezone.utc)
    rendered = render(camps, generated, previous)
    if "{{{EMAIL}}}" in rendered["html"] or "{{{EMAIL}}}" in rendered["text"]:
        raise SystemExit("SA digest preview must not contain a send merge tag")
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "digest.html"), "w", encoding="utf-8") as handle:
        handle.write(rendered["html"])
    with open(os.path.join(dest, "digest.txt"), "w", encoding="utf-8") as handle:
        handle.write(rendered["text"])
    with open(os.path.join(dest, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(rendered["meta"], handle, indent=2)
        handle.write("\n")
    return rendered["meta"]
