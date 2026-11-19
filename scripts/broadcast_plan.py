#!/usr/bin/env python3
"""Choose the segment and topic for one state digest.

This module does not call Resend and does not send. With ONE_LIST_MODE off,
each state keeps its own segment and the body has no topic_id. With the flag
on, every state uses the all-subscribers segment plus that state's topic.

A body aimed at the all-subscribers segment with no topic_id is refused.
South Australia and Tasmania are accepted only in one-list mode when the
all-subscribers segment and that state's topic are both set.
"""
import os

LEGACY_STATES = ("vic", "nsw", "qld")
TOPIC_STATES = ("sa", "tas")
TOPIC_ENV = {
    "vic": "RESEND_TOPIC_VIC_ID",
    "nsw": "RESEND_TOPIC_NSW_ID",
    "qld": "RESEND_TOPIC_QLD_ID",
    "sa": "RESEND_TOPIC_SA_ID",
    "tas": "RESEND_TOPIC_TAS_ID",
}
SEGMENT_ENV = {
    "vic": "RESEND_SEGMENT_ID",
    "nsw": "RESEND_SEGMENT_NSW_ID",
    "qld": "RESEND_SEGMENT_QLD_ID",
}
# Deleted 19 Nov 2026. Kept only so old references resolve; sends never use it.
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
    key = TOPIC_ENV.get(slug) or ""
    if not key:
        return ""
    return str(env.get(key) or "").strip()


def _legacy_segment(env, slug):
    # Sends never use QLD_SEGMENT_FALLBACK: that segment was deleted on 19 Nov 2026.
    if slug == "qld":
        raw = str(env.get("RESEND_SEGMENT_QLD_ID") if env.get("RESEND_SEGMENT_QLD_ID") is not None else "").strip()
        if raw.lower() in ("none", "deleted"):
            return ""
        return raw
    return str(env.get(SEGMENT_ENV.get(slug) or "") or "").strip()


def _all_segment(env):
    return str(env.get("RESEND_SEGMENT_ALL_ID") or "").strip()


def target(slug, env=None):
    """Segment and topic for one state. topic_id is empty while the flag is off."""
    provided = env if env is not None else os.environ
    state = str(slug or "").strip().lower()
    if state in TOPIC_STATES:
        segment = _all_segment(provided)
        topic = _topic_id(provided, state)
        if not one_list_mode(provided) or not segment or not topic:
            return {"ok": False, "reason": "state_not_open", "segment_id": "", "topic_id": ""}
        return {"ok": True, "reason": "", "segment_id": segment, "topic_id": topic}
    if state not in LEGACY_STATES:
        return {"ok": False, "reason": "state_not_open", "segment_id": "", "topic_id": ""}
    if not one_list_mode(provided):
        segment = _legacy_segment(provided, state)
        if not segment:
            # No live legacy segment: use the all-subscribers segment plus the state topic, or refuse.
            all_id = _all_segment(provided)
            topic = _topic_id(provided, state)
            if all_id and topic:
                return {"ok": True, "reason": "", "segment_id": all_id, "topic_id": topic}
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
