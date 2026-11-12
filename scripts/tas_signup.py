#!/usr/bin/env python3
"""Tasmania digest signup. One line, no form, and no Resend segment."""
import html

COMING_SOON = "Tas weekly email coming soon"


def forms_allowed():
    return False


def coming_soon_html():
    return f'<p class="muted tas-signup-soon">{html.escape(COMING_SOON)}.</p>'
