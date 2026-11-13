#!/usr/bin/env python3
"""Contact buttons on camp pages.

A Website, Call, Email or Book button is shown only when that field has a
value. General agency and road-authority lines are labelled and are not stored
as the camp's own phone. Open-data catalogue links are not contacts.

Numbers and pages below were read once from the agency's own site on 13 Nov 2026:
- 1300 072 757: https://www.nationalparks.nsw.gov.au/about-npws/contact-us
- 1300 827 727: https://parks.tas.gov.au/about-us/contact-us
- 13 23 80: https://www.tmr.qld.gov.au/Contact-us
- QLD rest areas: https://www.qld.gov.au/transport/safety/holiday-travel/stops/rest
- 13 22 13: https://www.nsw.gov.au/departments-and-agencies/transport-for-nsw/contact-us/general-public/phone-contacts
- NSW rest areas: https://maps.transport.nsw.gov.au/egeomaps/rest-areas/
- 13 74 68: https://www.qld.gov.au/contact-us
- NSW rest-stop wording: https://www.service.nsw.gov.au/referral/find-rest-areas-in-nsw
"""
import html
import re
from urllib.parse import urlparse

NPWS_PHONE = "1300 072 757"
NPWS_LABEL = "NSW National Parks info line (general, not this campground)"
PWS_PHONE = "1300 827 727"
PWS_LABEL = "Tasmania Parks and Wildlife info line (general)"
TMR_PHONE = "13 23 80"
TMR_LABEL = "Queensland Transport and Main Roads (road authority, general)"
TMR_WEBSITE = "https://www.qld.gov.au/transport/safety/holiday-travel/stops/rest"
TFNSW_PHONE = "13 22 13"
TFNSW_LABEL = "Transport for NSW (road authority, general)"
TFNSW_WEBSITE = "https://maps.transport.nsw.gov.au/egeomaps/rest-areas/"
QGOV_PHONE = "13 74 68"
QGOV_LABEL = "Queensland Government general enquiries (13 QGOV, not this campground)"
QLD_REST_NOTE = (
    "Rest areas are for a rest stop, not camping. "
    "General and recreational vehicles can stop for up to 20 hours unless signed otherwise."
)
NSW_REST_NOTE = (
    "Rest areas are for a rest stop, not camping. "
    "For a longer rest, find a campsite, hotel or motel."
)


def esc(value):
    return html.escape(str(value or ""), quote=True)


def tel_href(phone):
    keep = re.sub(r"[^\d+]", "", phone or "")
    return "tel:%s" % keep if keep else ""


def _host(url):
    return (urlparse(url).hostname or "").lower()


def is_catalogue(url):
    """True for an open-data catalogue or map-service record, not an operator page."""
    text = (url or "").strip()
    if not text:
        return False
    host = _host(text)
    if not host:
        return False
    if host == "data.gov.au" or host.endswith(".data.gov.au"):
        return True
    if "thelist.tas.gov.au" in host:
        return True
    if host.endswith(".arcgis.com") or host == "arcgis.com":
        return True
    if "/arcgis/rest/" in text:
        return True
    return False


def specific_html(camp):
    """The same button row Victoria and South Australia already use.

    Call, then Email, then Website, then Book. Each one is omitted when its
    field is empty. A catalogue URL is not a Website or Book button.
    """
    buttons = []
    phone = str(camp.get("phone") or "").strip()
    href = tel_href(phone)
    if phone and href:
        buttons.append('<a class="btn" href="%s">Call %s</a>' % (esc(href), esc(phone)))
    email = str(camp.get("email") or "").strip()
    if email and "@" in email:
        buttons.append('<a class="btn" href="mailto:%s">Email</a>' % esc(email))
    website = str(camp.get("website") or "").strip()
    if website.startswith("http") and not is_catalogue(website):
        buttons.append('<a class="btn" href="%s">Website</a>' % esc(website))
    book = str(camp.get("booking_url") or camp.get("book_url") or "").strip()
    if book.startswith("https://") and not is_catalogue(book):
        buttons.append('<a class="btn" href="%s">Book</a>' % esc(book))
    if not buttons:
        return ""
    return "<p>" + " ".join(buttons) + "</p>"


def general_call_html(phone, label):
    href = tel_href(phone)
    if not phone or not href or not label:
        return ""
    return '<p><a class="btn" href="%s">Call %s</a> %s</p>' % (esc(href), esc(phone), esc(label))


def lines_html(camp):
    """Labelled general lines. These are not the camp's own phone."""
    bits = []
    for key in ("road_line", "info_line"):
        row = camp.get(key) or {}
        if not isinstance(row, dict):
            continue
        html_line = general_call_html(row.get("phone") or "", row.get("label") or "")
        if html_line:
            bits.append(html_line)
    return "".join(bits)


def has_specific_contact(camp):
    """True when the page already has a camp contact or a road-authority contact.

    A general info line is not counted here. Catalogue URLs are not contacts.
    """
    if camp.get("road_line"):
        return True
    phone = str(camp.get("phone") or "").strip()
    if phone and tel_href(phone):
        return True
    if "@" in str(camp.get("email") or ""):
        return True
    website = str(camp.get("website") or "").strip()
    if website.startswith("http") and not is_catalogue(website):
        return True
    book = str(camp.get("booking_url") or camp.get("book_url") or "").strip()
    if book.startswith("https://") and not is_catalogue(book):
        return True
    return False


def apply_state_contacts(by_state):
    """Fill labelled lines after every other contact source is on the camp.

    NSW NPWS records get the parks info line. Queensland and New South Wales
    rest areas get the road-authority website, call and rest-stop note.
    Queensland pages that still have no contact get 13 QGOV. Nothing is written
    into the camp phone field.
    """
    for slug, camps in by_state.items():
        for camp in camps:
            if slug == "nsw" and camp.get("source") == "npws" and not camp.get("info_line"):
                camp["info_line"] = {"phone": NPWS_PHONE, "label": NPWS_LABEL}
            if camp.get("category") == "Rest area" and slug in ("qld", "nsw") and not camp.get("road_line"):
                if slug == "qld":
                    website, phone, label, note = TMR_WEBSITE, TMR_PHONE, TMR_LABEL, QLD_REST_NOTE
                else:
                    website, phone, label, note = TFNSW_WEBSITE, TFNSW_PHONE, TFNSW_LABEL, NSW_REST_NOTE
                # The Website button is the road authority's rest-area page, not a
                # catalogue record or a third-party directory.
                camp["website"] = website
                camp["road_line"] = {"phone": phone, "label": label}
                camp["rest_note"] = note
        if slug != "qld":
            continue
        for camp in camps:
            if camp.get("info_line") or has_specific_contact(camp):
                continue
            camp["info_line"] = {"phone": QGOV_PHONE, "label": QGOV_LABEL}


def page_has_contact_button(camp):
    return bool(specific_html(camp) or lines_html(camp))
