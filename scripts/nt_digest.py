#!/usr/bin/env python3
"""Northern Territory digest decision. This does not send mail or create a topic."""
import states


def send_decision(env=None, region_enabled=False):
    """Whether an NT digest could be sent. Resend is never called.

    The region flag defaults to off. Turning the argument on still does not
    send, because the release flag is off and no topic exists.
    """
    state = states.by_slug("nt")
    if region_enabled is not True or (state.get("release") or {}).get("region_enabled") is not True:
        return {"send": False, "reason": "region_disabled", "called_resend": False}
    if not states.digest_allowed(state):
        return {"send": False, "reason": "digest_disabled", "called_resend": False}
    return {"send": False, "reason": "not_wired", "called_resend": False}


def perform_send(env=None, region_enabled=False):
    decision = send_decision(env, region_enabled)
    decision["called_resend"] = False
    decision["send"] = False
    return decision
