#!/usr/bin/env python3
"""Northern Territory fire is a link out. No rating is fetched and no BOM feed is used."""
import html

import states

FIRE_URL = "https://www.pfes.nt.gov.au/fire-and-rescue-service"
LINE = "Fire danger: check NT Fire and Rescue before you travel."


def source_resolved():
    fire = (states.by_slug("nt").get("fire") or {})
    return (
        fire.get("source_resolved") is True
        and fire.get("borrow_bom") is False
        and fire.get("url") == FIRE_URL
        and fire.get("mode") == "link_out"
    )


def html_line(_camp=None):
    if not source_resolved():
        return ""
    return (
        '<h2 class="fire-head" style="font-size:.95rem;line-height:1.25;margin:.45rem 0 0">Fire</h2>'
        f'<p class="muted fire-line fire-nt" style="margin:.05rem 0 .55rem">{html.escape(LINE)}</p>'
        f'<p><a class="btn-alert" href="{html.escape(FIRE_URL)}">NT Fire and Rescue</a></p>'
    )
