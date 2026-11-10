#!/usr/bin/env python3
"""South Australian digest signup. No form unless a Resend segment exists.

SA_SIGNUP_MODE=open shows the existing signup and reopen boxes only when
release.signup is allowed and RESEND_SEGMENT_SA_ID is set. Any other case
shows one line and no form, so a page cannot enrol a list that does not exist.
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
    """True only for an open mode that names a segment and whose signup gate is on."""
    if mode() != "open":
        return False
    if not (os.environ.get("RESEND_SEGMENT_SA_ID") or "").strip():
        return False
    return states.signup_allowed(states.by_slug("sa"))


def coming_soon_html():
    return f'<p class="muted sa-signup-soon">{html.escape(COMING_SOON)}.</p>'
