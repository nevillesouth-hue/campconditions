#!/usr/bin/env python3
"""Tasmania fire is a link out. No rating is fetched and no BOM feed is used."""
import html

TFS_URL = "https://www.fire.tas.gov.au/total-fire-bans-fire-permits-burn-registrations/"
TASALERT_URL = "https://alert.tas.gov.au/"
LINE = "Total Fire Bans: check the Tasmania Fire Service. Warnings: check TasALERT."


def html_line(_camp=None):
    return (
        '<h2 class="fire-head" style="font-size:.95rem;line-height:1.25;margin:.45rem 0 0">Fire</h2>'
        f'<p class="muted fire-line fire-tas" style="margin:.05rem 0 .55rem">{html.escape(LINE)}</p>'
        f'<p><a class="btn-alert" href="{html.escape(TFS_URL)}">Tasmania Fire Service Total Fire Bans</a> '
        f'<a class="btn-alert" href="{html.escape(TASALERT_URL)}">TasALERT</a></p>'
    )
