#!/usr/bin/env python3
"""Shared weekly-digest layout helpers.

These rules are for the Thursday drafts that go to Micky for preview.
Nothing here sends email to subscribers.

- Subjects are plain text: never HTML entities such as &amp;.
- Broadcasts must use Resend's tokenised merge tag, not the site form at
  /unsubscribe/. Resend Broadcasts also add List-Unsubscribe and
  List-Unsubscribe-Post: List-Unsubscribe=One-Click automatically. Do not
  change live Resend account or domain settings to add those headers.
- Show the Chip in ask once (the tip block), not also in the top grey line.
- Open with a short 3-line "What matters this weekend" summary. Keep the
  later weather and Coming up sections tight. Do not add extra rows that
  only pad the email.
"""
import html
import re

RESEND_UNSUBSCRIBE_URL = "{{{RESEND_UNSUBSCRIBE_URL}}}"
SUPPORT_URL = "https://campconditions.au/support/"
PRIVACY_URL = "https://campconditions.au/privacy/"
FORM_UNSUBSCRIBE_URL = "https://campconditions.au/unsubscribe/"

# Official Parks and Wildlife Service one-line camper action for the Bookeasy
# incident, taken from the PWS alerts page (last reviewed 24 Nov 2026).
BOOKEASY_CAMPER_ACTION = (
    "Do not click links in unexpected email, text or WhatsApp messages about a "
    "booking; existing bookings stay confirmed, and the new PWS Parks Online "
    "Booking System is not affected."
)

_ENTITY = re.compile(r"&(?:[a-zA-Z]+|#\d+|#x[0-9A-Fa-f]+);")


def plain_subject(text):
    """Return a plain-text subject. HTML entities such as &amp; become &."""
    value = str(text or "")
    # Unescape repeatedly in case a subject was escaped twice.
    for _ in range(3):
        if not _ENTITY.search(value):
            break
        value = html.unescape(value)
    return value


def subject_is_plain(text):
    return not _ENTITY.search(str(text or ""))


def unsubscribe_href():
    """Broadcast footer href. Never the site form page."""
    return RESEND_UNSUBSCRIBE_URL


def uses_resend_unsubscribe(html_doc):
    hrefs = re.findall(r'href="([^"]*unsub[^"]*)"', html_doc or "", flags=re.I)
    hrefs += re.findall(r'href="(\{\{\{RESEND_UNSUBSCRIBE_URL\}\}\})"', html_doc or "")
    if FORM_UNSUBSCRIBE_URL in (html_doc or "") and RESEND_UNSUBSCRIBE_URL not in (html_doc or ""):
        return False
    return RESEND_UNSUBSCRIBE_URL in (html_doc or "")


def chip_in_ask_count(html_doc):
    """Count visible Chip in asks (top-line optional link plus the tip block)."""
    return len(re.findall(r"chip in", html_doc or "", flags=re.I))


def top_line_html(share_href, include_chip_in=False):
    """Grey line under the greeting. Chip in stays out unless explicitly requested."""
    mate = (
        f'<a href="{share_href}" style="color:#666666;text-decoration:underline;">'
        "Tell a mate about CampConditions</a>"
    )
    if include_chip_in:
        chip = (
            f' · <a href="{SUPPORT_URL}" style="color:#666666;text-decoration:underline;">'
            "Chip in</a> (optional)"
        )
        return f"Free every Thursday. {mate}{chip}"
    return f"Free every Thursday. {mate}."


GIFT_LINE = "As a thank-you, supporters get the Supporter Pack — an All-Year Trip-Prep Kit and a printable Camp Logbook. It's our way of saying thanks."

def tip_block_html():
    """The single Chip in ask for the digest, with Lex's approved gift line."""
    return (
        "<strong>The digests stay free.</strong> If they’re useful and you want to chip in, "
        "a one-off tip helps cover the running costs — coffee money is plenty.<br>"
        f'<a href="{SUPPORT_URL}" style="color:#2f5d3a;">Chip in</a> $5, $10 or $20<br>'
        f"{GIFT_LINE}<br>"
        "No pressure either way."
    )


def what_matters_heading():
    return "What matters this weekend"


def format_alert_line(alert):
    """Headline plus official dates and detail for a PWS alert."""
    if not isinstance(alert, dict):
        return ""
    headline = str(alert.get("headline") or "").strip()
    if not headline:
        return ""
    parks = [str(name).strip() for name in (alert.get("parks") or []) if str(name).strip()]
    href = str(alert.get("link") or "https://parks.tas.gov.au/explore-our-parks/know-before-you-go/alerts")
    bits = [headline]
    if parks:
        bits.append(", ".join(parks))
    dates = []
    if alert.get("start"):
        dates.append("from %s" % alert["start"])
    if alert.get("end"):
        dates.append("until %s" % alert["end"])
    if alert.get("reviewed"):
        dates.append("reviewed %s" % str(alert["reviewed"])[:10])
    if dates:
        bits.append("(" + ", ".join(dates) + ")")
    detail = str(alert.get("detail") or "").strip()
    if detail:
        bits.append(detail)
    if "bookeasy" in headline.lower() and BOOKEASY_CAMPER_ACTION.lower() not in detail.lower():
        bits.append(BOOKEASY_CAMPER_ACTION)
    bits.append(href)
    return " ".join(bits)


def collapse_weather_lines(lines):
    """Merge region weather lines that share the same outlook.

    Each line should look like "Region: outlook" (plain text). Consecutive or
    later lines with the same outlook are combined: "Adelaide, Fleurieu and
    Kangaroo Island: outlook". Use this when drafting Weekend weather so the
    same sentence is not repeated under every region.
    """
    import re
    groups = []
    for raw in lines or []:
        line = str(raw or "").strip()
        if not line:
            continue
        if ":" in line:
            region, outlook = line.split(":", 1)
            region, outlook = region.strip(), outlook.strip()
        else:
            region, outlook = line, ""
        if groups and groups[-1]["outlook"] == outlook:
            groups[-1]["regions"].append(region)
        else:
            groups.append({"regions": [region], "outlook": outlook})
    out = []
    for group in groups:
        names = group["regions"]
        if len(names) == 1:
            label = names[0]
        elif len(names) == 2:
            label = "%s and %s" % (names[0], names[1])
        else:
            label = "%s and %s" % (", ".join(names[:-1]), names[-1])
        out.append("%s: %s" % (label, group["outlook"]) if group["outlook"] else label)
    return out


# SA Innamincka flood caveat belongs with the closures / "what matters" block,
# before the regional Weekend weather list — not under "Check before you go".
SA_FLOOD_CAVEAT_SLOT = "after_closures_before_weather"
