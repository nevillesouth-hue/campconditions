#!/usr/bin/env python3
"""Northern Territory digest signup. The form stays off while the region flag is off."""
import html

import states

COMING_SOON = "NT weekly email coming soon"


def forms_allowed():
    """On only when the region flag and the release signup flag are both on."""
    state = states.by_slug("nt")
    if (state.get("release") or {}).get("region_enabled") is not True:
        return False
    return states.signup_allowed(state)


def coming_soon_html():
    return f'<p class="muted nt-signup-soon">{html.escape(COMING_SOON)}.</p>'
