#!/usr/bin/env python3
"""Weekly digest from status.json. Closures only — emergency warnings are not read or listed.

Copy, region names and warning links come from the enabled state config.
Victoria is the only enabled state, so the draft is still the Victoria digest.

Writes draft files only (digest.html, digest.txt, meta.json). Nothing here sends email.
The scheduled site rebuild must not call a mail API; sending is a separate, manual step.
"""
import argparse, datetime as dt, html, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import states

_STATE = states.enabled()[0]
_COPY = _STATE.get("copy") or {}
REG = {key: name for key, name, _blurb in states.regions(_STATE)}
ap = argparse.ArgumentParser()
ap.add_argument("--current", default=os.path.join("dist", "status.json"))
ap.add_argument("--previous", default="")
ap.add_argument("--out", default=os.path.join("dist", "digest"))
a = ap.parse_args()
e = lambda s: html.escape(str(s or ""), quote=True)
def link(c):
    return f'<a href="{e(c["url"])}" style="color:#2f5d3a;">{e(c["name"])}</a>'
cur = json.load(open(a.current, encoding="utf-8"))
prev = json.load(open(a.previous, encoding="utf-8")) if a.previous and os.path.isfile(a.previous) else None
camps = cur["camps"]; closed = [c for c in camps if c["status"] == "closed"]
prev_closed = {c["slug"] for c in prev["camps"] if c["status"] == "closed"} if prev else set()
newly_closed = [c for c in closed if prev and c["slug"] not in prev_closed]
reopened = [c for c in (prev["camps"] if prev else []) if c["status"] == "closed" and c["slug"] not in {x["slug"] for x in closed}]
gen = dt.datetime.fromisoformat(cur["generated"]); date = gen.strftime("%-d %B %Y")
subject = _COPY["digest_subject"].format(closed=len(closed)) + (f", {len(newly_closed)} new" if prev else "")
preview = "Closures, reopenings and stale records — region by region."

F = "font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;color:#222222;"
def h2(t): return f'<tr><td style="{F}font-size:18px;line-height:26px;font-weight:bold;padding-top:18px;color:#2f5d3a;">{e(t)}</td></tr>'
def para(s): return f'<tr><td style="{F}padding-top:8px;">{s}</td></tr>'
rows = [para(f"{_COPY['digest_intro'].format(date=e(date))}<br>"
             f"<strong>{len(closed)}</strong> of {len(camps)} campgrounds are closed.")]
if prev: rows += [h2("Newly closed"), para("<br>".join(f"{link(c)} — {e((c['closure'] or {}).get('desc') or 'Closed')}" for c in newly_closed) or "None this week."),
                  h2("Reopened"), para("<br>".join(link(c) for c in reopened) or "None this week.")]
rows.append(para(_COPY["digest_warnings"]))
rows.append(h2("Closed, by region"))
for k, n in REG.items():
    cs = [c for c in closed if c["region"] == k]
    rows.append(para(f"<strong>{e(n)}</strong><br>" + ("<br>".join(link(c) + (" *" if (c.get("closure") or {}).get("outdated") else "") for c in sorted(cs, key=lambda c: c["name"].lower())) or "None.")))
rows.append(para('<span style="font-size:13px;color:#666666;">* Reopening date has passed — the closure record may be outdated.</span>'))
rows.append(para('Been somewhere lately? <a href="https://campconditions.au/report/" style="color:#2f5d3a;">Report conditions</a> — how full, road access, water and phone coverage.'))
UNSUB = "https://campconditions.au/api/unsubscribe?e={{{EMAIL}}}&t={{{unsubscribe_token}}}"
foot = (_COPY["digest_footer"]
        + f'CampConditions.au · <a href="https://campconditions.au/privacy/" style="color:#666666;">Privacy</a> · '
        + f'<a href="{UNSUB}" style="color:#666666;">Unsubscribe</a>')
body = "".join(rows) + f'<tr><td style="{F}font-size:12px;line-height:18px;color:#666666;padding-top:24px;">{foot}</td></tr>'
doc = f"""<!DOCTYPE html><html lang="en-AU"><head><meta charset="utf-8"><title>{e(subject)}</title></head>
<body style="margin:0;background:#fbfaf6;"><div style="display:none;max-height:0;overflow:hidden;">{e(preview)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;padding:8px 24px 24px;">
<tr><td style="padding-top:16px;"><img src="https://campconditions.au/assets/brand/logo-160.png" width="77" height="77" alt="CampConditions.au" style="display:block;border:0;"></td></tr>
<tr><td style="{F}font-size:22px;line-height:28px;font-weight:bold;color:#2f5d3a;padding-top:8px;">CampConditions.au</td></tr>
{body}</table></td></tr></table></body></html>"""
txt = re.sub(r"<br>", "\n", doc[doc.index("<body"):]); txt = re.sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>', r"\2 (\1)", txt)
txt = re.sub(r"</tr>", "\n", txt); txt = html.unescape(re.sub(r"<[^>]+>", "", txt)); txt = re.sub(r"\n\s*\n+", "\n\n", txt).strip()
os.makedirs(a.out, exist_ok=True)
open(os.path.join(a.out, "digest.html"), "w", encoding="utf-8").write(doc); open(os.path.join(a.out, "digest.txt"), "w", encoding="utf-8").write(txt)
json.dump({
    "subject": subject, "previewText": preview, "generated": cur["generated"], "closed": len(closed),
    "headers": {
        "List-Unsubscribe": f"<{UNSUB}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    },
}, open(os.path.join(a.out, "meta.json"), "w"), indent=1)
print(subject)
