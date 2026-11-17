#!/usr/bin/env python3
"""Tasmania digest signup. The form is on only when release.signup is true."""
import html

import states

COMING_SOON = "Tas weekly email coming soon"


def forms_allowed():
    return states.signup_allowed(states.by_slug("tas"))


def coming_soon_html():
    return f'<p class="muted tas-signup-soon">{html.escape(COMING_SOON)}.</p>'
