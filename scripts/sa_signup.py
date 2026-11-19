#!/usr/bin/env python3
"""South Australian digest signup.

The public form follows release.signup. SA_SIGNUP_MODE remains for the launch
gate. No South Australia segment is required, and none is created.
"""
import html
import os

import states

COMING_SOON = "SA weekly email coming soon"
MODES = ("coming_soon", "open")


def mode():
    raw = (os.environ.get("SA_SIGNUP_MODE") or "").strip().lower()
    segment = (os.environ.get("RESEND_SEGMENT_SA_ID") or "").strip()
    if raw == "open":
        return "open" if segment else "coming_soon"
    if raw in ("", "coming_soon"):
        return "coming_soon"
    raise SystemExit("SA_SIGNUP_MODE must be coming_soon or open")


def forms_allowed():
    """True when release.signup allows the public form. No segment id is required."""
    return states.signup_allowed(states.by_slug("sa"))


def coming_soon_html():
    return f'<p class="muted sa-signup-soon">{html.escape(COMING_SOON)}.</p>'
