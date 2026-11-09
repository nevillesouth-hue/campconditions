#!/usr/bin/env python3
"""Eligibility holds for the omissions ledger.

The 1358 ledger rows are not a camp count. Exclusion and review dispositions
stay out. A represented identity with unknown status is not open. Rejected
URLs are not aliases. Distance does not merge two records.
"""
import act_sa_status as status

EXCLUDED_PREFIX = "exclude_"
REVIEW_PREFIX = "review_"
REPRESENT_PREFIX = "represent_"


def camp_count(_rows):
    """Raw ledger length is never a campground total."""
    return None


def classify(row):
    disposition = row.get("disposition") or ""
    current = row.get("current_status") or "unknown"
    excluded = disposition.startswith(EXCLUDED_PREFIX)
    review = disposition.startswith(REVIEW_PREFIX)
    represented = disposition.startswith(REPRESENT_PREFIX) and not excluded
    closed = current == "closed_until_further_notice"
    rejected = [part.strip() for part in str(row.get("rejected_match_urls") or "").split() if part.strip()]
    return {
        "record_id": row.get("record_id") or "",
        "eligible_camp": represented,
        "excluded": excluded,
        "needs_review": review,
        "operating_status": "closed" if closed and represented else "unknown",
        "open_inferred": False,
        "reopen_at": None,
        "rejected_urls": rejected,
        "proximity_merged": False,
    }


def same_camp(left, right, metres=0):
    """Identity is the reviewed record id, not a distance."""
    if left.get("record_id") and left.get("record_id") == right.get("record_id"):
        return {"merged": True, "reason": "same_record"}
    decision = status.proximity_decision(metres)
    rejected = set(classify(left)["rejected_urls"]) | set(classify(right)["rejected_urls"])
    return {"merged": False, "reason": decision["reason"], "rejected_urls_blocked": bool(rejected)}


def summary(rows):
    classified = [classify(row) for row in rows]
    closed = [row for row in classified if row["operating_status"] == "closed"]
    return {
        "rows": len(rows),
        "camp_count": camp_count(rows),
        "eligible": sum(1 for row in classified if row["eligible_camp"]),
        "excluded": sum(1 for row in classified if row["excluded"]),
        "needs_review": sum(1 for row in classified if row["needs_review"]),
        "closed_ids": [row["record_id"] for row in closed],
        "open_inferred": False,
    }
