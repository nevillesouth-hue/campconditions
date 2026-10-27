#!/usr/bin/env python3
"""Weekly digest from status.json. Closures only — emergency warnings are not read or listed.

Copy and region names come from each enabled state config.
One enabled state writes digest.html, digest.txt and meta.json in --out.
That file is the Victoria draft when Victoria is the enabled state.
Several enabled states write the same three files per state under --out/<slug>/,
and the top-level files stay the first enabled state (Victoria) so the existing
manual send is unchanged.

Writes draft files only. Nothing here sends email.
The scheduled site rebuild must not call a mail API; sending is a separate, manual step.
"""
import argparse, datetime as dt, html, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import states

ap = argparse.ArgumentParser()
ap.add_argument("--current", default=os.path.join("dist", "status.json"))
ap.add_argument("--previous", default="")
ap.add_argument("--out", default=os.path.join("dist", "digest"))
a = ap.parse_args()
e = lambda s: html.escape(str(s or ""), quote=True)

def link(c):
    return f'<a href="{e(c["url"])}" style="color:#2f5d3a;">{e(c["name"])}</a>'

def camps_for(state, rows):
    needle = f"/{state['slug']}/"
    return [c for c in rows if needle in str(c.get("url") or "")]

def write_digest(state, rows, prev_rows, generated, generated_text, dest):
    copy = state.get("copy") or {}
    reg = {key: name for key, name, _blurb in states.regions(state)}
    closed = [c for c in rows if c["status"] == "closed"]
    prev_closed = {c["slug"] for c in prev_rows if c["status"] == "closed"} if prev_rows is not None else set()
    newly_closed = [c for c in closed if prev_rows is not None and c["slug"] not in prev_closed]
    reopened = [c for c in (prev_rows or []) if c["status"] == "closed" and c["slug"] not in {x["slug"] for x in closed}]
    date = generated.strftime("%-d %B %Y")
    subject = copy["digest_subject"].format(closed=len(closed)) + (f", {len(newly_closed)} new" if prev_rows is not None else "")
    preview = "Closures, reopenings and stale records — region by region."
    style = "font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;color:#222222;"
    def h2(t): return f'<tr><td style="{style}font-size:18px;line-height:26px;font-weight:bold;padding-top:18px;color:#2f5d3a;">{e(t)}</td></tr>'
    def para(s): return f'<tr><td style="{style}padding-top:8px;">{s}</td></tr>'
    body_rows = [para(f"{copy['digest_intro'].format(date=e(date))}<br>"
                 f"<strong>{len(closed)}</strong> of {len(rows)} campgrounds are closed.")]
    if prev_rows is not None:
        body_rows += [h2("Newly closed"), para("<br>".join(f"{link(c)} — {e((c['closure'] or {}).get('desc') or 'Closed')}" for c in newly_closed) or "None this week."),
                      h2("Reopened"), para("<br>".join(link(c) for c in reopened) or "None this week.")]
    body_rows.append(para(copy["digest_warnings"]))
    body_rows.append(h2("Closed, by region"))
    for key, name in reg.items():
        group = [c for c in closed if c["region"] == key]
        body_rows.append(para(f"<strong>{e(name)}</strong><br>" + ("<br>".join(link(c) + (" *" if (c.get("closure") or {}).get("outdated") else "") for c in sorted(group, key=lambda c: c["name"].lower())) or "None.")))
    body_rows.append(para('<span style="font-size:13px;color:#666666;">* Reopening date has passed — the closure record may be outdated.</span>'))
    body_rows.append(para('Been somewhere lately? <a href="https://campconditions.au/report/" style="color:#2f5d3a;">Report conditions</a> — how full, road access, water and phone coverage.'))
    unsub = "https://campconditions.au/api/unsubscribe?e={{{EMAIL}}}&t={{{unsubscribe_token}}}"
    foot = (copy["digest_footer"]
            + f'CampConditions.au · <a href="https://campconditions.au/privacy/" style="color:#666666;">Privacy</a> · '
            + f'<a href="{unsub}" style="color:#666666;">Unsubscribe</a>')
    body = "".join(body_rows) + f'<tr><td style="{style}font-size:12px;line-height:18px;color:#666666;padding-top:24px;">{foot}</td></tr>'
    doc = f"""<!DOCTYPE html><html lang="en-AU"><head><meta charset="utf-8"><title>{e(subject)}</title></head>
<body style="margin:0;background:#fbfaf6;"><div style="display:none;max-height:0;overflow:hidden;">{e(preview)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;padding:8px 24px 24px;">
<tr><td style="padding-top:16px;"><img src="https://campconditions.au/assets/brand/logo-160.png" width="77" height="77" alt="CampConditions.au" style="display:block;border:0;"></td></tr>
<tr><td style="{style}font-size:22px;line-height:28px;font-weight:bold;color:#2f5d3a;padding-top:8px;">CampConditions.au</td></tr>
{body}</table></td></tr></table></body></html>"""
    txt = re.sub(r"<br>", "\n", doc[doc.index("<body"):]); txt = re.sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>', r"\2 (\1)", txt)
    txt = re.sub(r"</tr>", "\n", txt); txt = html.unescape(re.sub(r"<[^>]+>", "", txt)); txt = re.sub(r"\n\s*\n+", "\n\n", txt).strip()
    os.makedirs(dest, exist_ok=True)
    open(os.path.join(dest, "digest.html"), "w", encoding="utf-8").write(doc)
    open(os.path.join(dest, "digest.txt"), "w", encoding="utf-8").write(txt)
    json.dump({
        "subject": subject, "previewText": preview, "generated": generated_text, "closed": len(closed), "state": state["slug"],
        "headers": {
            "List-Unsubscribe": f"<{unsub}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }, open(os.path.join(dest, "meta.json"), "w"), indent=1)
    print(subject)
    return subject

cur = json.load(open(a.current, encoding="utf-8"))
prev = json.load(open(a.previous, encoding="utf-8")) if a.previous and os.path.isfile(a.previous) else None
generated = dt.datetime.fromisoformat(cur["generated"])
enabled = states.enabled()
primary = enabled[0]
prev_camps = prev["camps"] if prev else None
write_digest(primary, camps_for(primary, cur["camps"]), camps_for(primary, prev_camps) if prev_camps is not None else None, generated, cur["generated"], a.out)
if len(enabled) > 1:
    for state in enabled:
        write_digest(state, camps_for(state, cur["camps"]), camps_for(state, prev_camps) if prev_camps is not None else None, generated, cur["generated"], os.path.join(a.out, state["slug"]))
