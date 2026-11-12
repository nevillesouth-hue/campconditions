#!/usr/bin/env python3
"""Choose the segment and topic for one state digest.

This module does not call Resend and does not send. With ONE_LIST_MODE off,
each state keeps its own segment and the body has no topic_id. With the flag
on, every state uses the all-subscribers segment plus that state's topic.

A body aimed at the all-subscribers segment with no topic_id is refused.
South Australia is refused: there is no SA topic.
"""
import os

STATE_ORDER = ("vic", "nsw", "qld")
TOPIC_ENV = {
    "vic": "RESEND_TOPIC_VIC_ID",
    "nsw": "RESEND_TOPIC_NSW_ID",
    "qld": "RESEND_TOPIC_QLD_ID",
}
SEGMENT_ENV = {
    "vic": "RESEND_SEGMENT_ID",
    "nsw": "RESEND_SEGMENT_NSW_ID",
    "qld": "RESEND_SEGMENT_QLD_ID",
}
# Same fallback as functions/api/confirm.js. A segment id is not a secret.
QLD_SEGMENT_FALLBACK = "2488900b-f026-44e8-9d74-098d38ef3468"
_ON = {"1", "true", "on", "yes"}


class BroadcastRefused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def one_list_mode(env=None):
    provided = env if env is not None else os.environ
    return str(provided.get("ONE_LIST_MODE") or "").strip().lower() in _ON


def _topic_id(env, slug):
    return str(env.get(TOPIC_ENV[slug]) or "").strip()


def _all_segment(env):
    return str(env.get("RESEND_SEGMENT_ALL_ID") or "").strip()


def target(slug, env=None):
    """Segment and topic for one state. topic_id is empty while the flag is off."""
    provided = env if env is not None else os.environ
    state = str(slug or "").strip().lower()
    if state not in STATE_ORDER:
        return {"ok": False, "reason": "state_not_open", "segment_id": "", "topic_id": ""}
    if not one_list_mode(provided):
        segment = str(provided.get(SEGMENT_ENV[state]) or "").strip()
        if state == "qld" and not segment:
            segment = QLD_SEGMENT_FALLBACK
        if not segment:
            return {"ok": False, "reason": "segment_unset", "segment_id": "", "topic_id": ""}
        return {"ok": True, "reason": "", "segment_id": segment, "topic_id": ""}
    segment = _all_segment(provided)
    topic = _topic_id(provided, state)
    if not segment or not topic:
        return {"ok": False, "reason": "missing_one_list_ids", "segment_id": segment, "topic_id": topic}
    return {"ok": True, "reason": "", "segment_id": segment, "topic_id": topic}


def guard_broadcast(body, all_segment_id):
    """Refuse a broadcast to the all-subscribers segment that has no topic."""
    segment = str((body or {}).get("segment_id") or "")
    topic = str((body or {}).get("topic_id") or "").strip()
    all_id = str(all_segment_id or "").strip()
    if all_id and segment == all_id and not topic:
        raise BroadcastRefused("all_segment_requires_topic")
    return body


def broadcast_body(slug, env, subject, html, from_email, text=None):
    """Draft create-broadcast body. send is omitted, so Resend keeps it as a draft."""
    provided = env if env is not None else os.environ
    found = target(slug, provided)
    if not found["ok"]:
        raise BroadcastRefused(found["reason"])
    body = {
        "from": from_email,
        "subject": subject,
        "segment_id": found["segment_id"],
        "html": html,
    }
    if text is not None:
        body["text"] = text
    if found["topic_id"]:
        body["topic_id"] = found["topic_id"]
    return guard_broadcast(body, _all_segment(provided))


def broadcast_meta(slug, env=None):
    """Extra digest meta while one-list mode is on. Empty while the flag is off."""
    provided = env if env is not None else os.environ
    if not one_list_mode(provided):
        return {}
    found = target(slug, provided)
    if not found["ok"]:
        return {"broadcast": {"ok": False, "reason": found["reason"], "state": str(slug or "")}}
    return {
        "broadcast": {
            "ok": True,
            "state": str(slug or ""),
            "segment_id": found["segment_id"],
            "topic_id": found["topic_id"],
        }
    }
