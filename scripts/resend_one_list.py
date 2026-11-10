#!/usr/bin/env python3
"""Plan the move to one CampConditions segment with state topics.

Default is a dry run. It reads Resend and writes a report. It does not change
contacts unless both an apply flag and RESEND_ONE_LIST_CONFIRM are set:

  RESEND_ONE_LIST_CONFIRM=apply-topics  python3 scripts/resend_one_list.py --apply topics
  RESEND_ONE_LIST_CONFIRM=apply-segment python3 scripts/resend_one_list.py --apply segment

--apply-topics and --apply-segment are the same two phases. The confirmation
value has to match the phase. Setting the variable without the flag does nothing.

The script never sends mail, never creates a broadcast, never opts a contact
out, and never changes unsubscribed. A second apply, once the first one has
landed, plans zero writes.

Dry-run stdout (one field a line, in this order; reason and expected appear
only when set):

  mode: dry-run
  phase: plan
  live_writes: 0
  opt_outs_sent: 0
  broadcasts_called: 0
  emails_called: 0
  contacts: <n>
  skipped_unsubscribed: <n>
  skipped_no_segment: <n>
  segment_subscribed: vic=<n> nsw=<n> qld=<n>
  topic_opt_in_before: vic=<n> nsw=<n> qld=<n>
  planned_topic_opt_ins: vic=<n> nsw=<n> qld=<n>
  planned_segment_adds: <n|unset|missing>
  states_mismatches: <n>
  api_errors: <n>
  diffs_after: n/a
  report_json: out/one-list-report.json
  report_csv: out/one-list-report.csv
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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
# Existing segments. Overridable. A segment id is not a secret.
DEFAULT_SEGMENTS = {
    "vic": "b9096e2d-485b-487e-90db-467e44eaf6cc",
    "nsw": "e5754955-29ba-4fe7-be92-065f3a6f25ba",
    "qld": "2488900b-f026-44e8-9d74-098d38ef3468",
}
CONFIRM_ENV = "RESEND_ONE_LIST_CONFIRM"
API = "https://api.resend.com"
MIN_INTERVAL = 0.2
SUMMARY_KEYS = (
    "mode",
    "phase",
    "reason",
    "expected",
    "live_writes",
    "opt_outs_sent",
    "broadcasts_called",
    "emails_called",
    "contacts",
    "skipped_unsubscribed",
    "skipped_no_segment",
    "segment_subscribed",
    "topic_opt_in_before",
    "planned_topic_opt_ins",
    "planned_segment_adds",
    "states_mismatches",
    "api_errors",
    "diffs_after",
    "report_json",
    "report_csv",
)


class Stop(Exception):
    def __init__(self, reason, summary):
        super().__init__(reason)
        self.reason = reason
        self.summary = summary


def format_summary(summary):
    lines = []
    for key in SUMMARY_KEYS:
        if key not in summary or summary[key] is None:
            continue
        lines.append("%s: %s" % (key, summary[key]))
    return "\n".join(lines) + "\n"


def counts_line(mapping):
    return " ".join("%s=%s" % (slug, mapping.get(slug, 0)) for slug in STATE_ORDER)


def redact(text, key):
    if not key or not text or key not in text:
        return text
    return text.replace(key, "[redacted]")


def parse_pairs(raw, allowed):
    found = {}
    if not raw:
        return found
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        slug, sep, value = part.partition("=")
        slug = slug.strip().lower()
        if slug in ("sa", "act"):
            raise ValueError("no_%s_topic" % slug)
        if sep != "=" or slug not in allowed:
            raise ValueError("bad_pair")
        found[slug] = value.strip()
    return found


def resolve_topics(env, raw):
    found = parse_pairs(raw, STATE_ORDER)
    for slug, key in TOPIC_ENV.items():
        found.setdefault(slug, str(env.get(key) or "").strip())
    missing = [slug for slug in STATE_ORDER if not found.get(slug)]
    return found, missing


def resolve_segments(env, raw):
    found = parse_pairs(raw, STATE_ORDER)
    for slug, key in SEGMENT_ENV.items():
        if slug not in found:
            found[slug] = str(env.get(key) or "").strip() or DEFAULT_SEGMENTS[slug]
    return found


def resolve_phase(args):
    phases = set()
    if args.apply:
        phases.add(args.apply)
    if args.apply_topics:
        phases.add("topics")
    if args.apply_segment:
        phases.add("segment")
    if args.dry_run and phases:
        return None, "dry_run_and_apply"
    if len(phases) > 1:
        return None, "one_phase_only"
    if not phases:
        return "plan", ""
    return phases.pop(), ""


class Limiter:
    def __init__(self, sleep, clock, interval=MIN_INTERVAL):
        self.sleep = sleep
        self.clock = clock
        self.interval = interval
        self.next_at = None

    def wait(self):
        now = self.clock()
        if self.next_at is not None:
            delay = self.next_at - now
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
        self.next_at = now + self.interval


class Client:
    """Read-only unless a phase asks for a topic opt-in or an all-segment add."""

    def __init__(self, api_key, transport, sleep, clock):
        self.api_key = api_key
        self.transport = transport
        self.sleep = sleep
        self.limiter = Limiter(sleep, clock)
        self.live_writes = 0
        self.opt_outs_sent = 0
        self.broadcasts_called = 0
        self.emails_called = 0
        self.writes = []

    def guard(self, method, path, body):
        bare = path.split("?", 1)[0]
        if "/broadcasts" in bare or "/emails" in bare:
            raise RuntimeError("refusing to call " + bare)
        if method not in ("GET", "POST", "PATCH"):
            raise RuntimeError("method not allowed")
        if method == "POST" and "/segments/" not in bare:
            raise RuntimeError("unexpected post")
        if method == "PATCH" and not bare.rstrip("/").endswith("/topics"):
            raise RuntimeError("unexpected patch")
        if not isinstance(body, dict):
            return
        if "unsubscribed" in body:
            raise RuntimeError("refusing to change unsubscribed")
        for topic in body.get("topics") or []:
            if topic.get("subscription") != "opt_in":
                self.opt_outs_sent += 1
                raise RuntimeError("refusing to opt out")

    def call(self, method, path, body=None, write=False):
        self.guard(method, path, body)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "User-Agent": "campconditions-one-list/1",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            self.limiter.wait()
            status, data, response_headers = self.transport(method, path, payload, headers)
            if status != 429 or attempt >= 4:
                break
            attempt += 1
            self.sleep(backoff_seconds(attempt, response_headers))
        if write and status in (200, 201, 409):
            self.live_writes += 1
            self.writes.append({"method": method, "path": path.split("?", 1)[0], "body": body})
        return status, data if isinstance(data, dict) else {}

    def list_all(self, path):
        items = []
        after = None
        seen = set()
        while True:
            query = {"limit": 100}
            if after:
                query["after"] = after
            status, data = self.call("GET", with_query(path, query))
            if status != 200:
                raise RuntimeError("list failed %s %s" % (status, path))
            batch = data.get("data") or []
            if not isinstance(batch, list):
                raise RuntimeError("list shape")
            items.extend(batch)
            if not data.get("has_more") or not batch:
                break
            new_after = str(batch[-1].get("id") or "")
            if not new_after or new_after in seen:
                break
            seen.add(new_after)
            after = new_after
        return items


def backoff_seconds(attempt, headers):
    delay = float(2 ** (attempt - 1))
    raw = ""
    if headers:
        raw = str(headers.get("retry-after") or headers.get("Retry-After") or "")
    try:
        hinted = float(raw)
    except ValueError:
        hinted = 0
    if hinted > delay:
        delay = hinted
    if delay > 30:
        delay = 30
    return delay


def with_query(path, params):
    parts = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        parts.append("%s=%s" % (key, urllib.parse.quote(str(value), safe="")))
    if not parts:
        return path
    return path + ("&" if "?" in path else "?") + "&".join(parts)


def urllib_transport(api_key):
    def transport(method, path, body, headers):
        bare = path.split("?", 1)[0]
        if "/broadcasts" in bare or "/emails" in bare:
            raise RuntimeError("refusing to call " + bare)
        request = urllib.request.Request(API + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw or "{}"), {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data = {"message": redact(raw[:300], api_key)}
            return err.code, data, {k.lower(): v for k, v in err.headers.items()}
    return transport


def property_states(properties):
    if not isinstance(properties, dict):
        return ""
    raw = properties.get("states")
    if isinstance(raw, dict):
        raw = raw.get("value")
    parts = []
    for item in str(raw or "").replace(" ", ",").split(","):
        slug = item.strip().lower()
        if slug in STATE_ORDER and slug not in parts:
            parts.append(slug)
    return ",".join(slug for slug in STATE_ORDER if slug in parts)


def topic_map(rows):
    found = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        topic_id = str(row.get("id") or "")
        if topic_id:
            found[topic_id] = str(row.get("subscription") or "")
    return found


def blank_summary(mode, phase):
    return {
        "mode": mode,
        "phase": phase,
        "live_writes": 0,
        "opt_outs_sent": 0,
        "broadcasts_called": 0,
        "emails_called": 0,
        "contacts": 0,
        "skipped_unsubscribed": 0,
        "skipped_no_segment": 0,
        "segment_subscribed": counts_line({}),
        "topic_opt_in_before": counts_line({}),
        "planned_topic_opt_ins": counts_line({}),
        "planned_segment_adds": "unset",
        "states_mismatches": 0,
        "api_errors": 0,
        "diffs_after": "n/a",
    }


def check_topics(client, topic_ids):
    checked = []
    for slug in STATE_ORDER:
        topic_id = topic_ids[slug]
        status, data = client.call("GET", "/topics/" + urllib.parse.quote(topic_id, safe=""))
        if status != 200:
            raise RuntimeError("topic_lookup_failed")
        default = str(data.get("default_subscription") or "")
        checked.append({
            "slug": slug,
            "id": topic_id,
            "name": data.get("name") or "",
            "default_subscription": default,
            "visibility": data.get("visibility") or "",
        })
        if default != "opt_out":
            raise Stop("topic_default_not_opt_out", {"topic": slug})
    return checked


def list_segment(client, segment_id):
    """Paginate one segment. A missing segment is ('missing', []), not an exception."""
    path = "/segments/%s/contacts" % urllib.parse.quote(segment_id, safe="")
    items = []
    after = None
    seen = set()
    while True:
        query = {"limit": 100}
        if after:
            query["after"] = after
        status, data = client.call("GET", with_query(path, query))
        if status == 404 and not items:
            return "missing", []
        if status != 200:
            raise RuntimeError("segment list failed")
        batch = data.get("data") or []
        items.extend(batch)
        if not data.get("has_more") or not batch:
            return "ok", items
        new_after = str(batch[-1].get("id") or "")
        if not new_after or new_after in seen:
            return "ok", items
        seen.add(new_after)
        after = new_after


def load_contacts(client, segment_ids, all_id):
    rows = {}

    def ensure(item):
        contact_id = str(item.get("id") or "")
        if not contact_id:
            return None
        row = rows.get(contact_id)
        if row is None:
            row = {
                "id": contact_id,
                "email": str(item.get("email") or ""),
                "unsubscribed": bool(item.get("unsubscribed")),
                "segments": set(),
                "in_all": False,
                "properties": item.get("properties") if isinstance(item.get("properties"), dict) else None,
            }
            rows[contact_id] = row
        else:
            row["unsubscribed"] = row["unsubscribed"] or bool(item.get("unsubscribed"))
            if row["properties"] is None and isinstance(item.get("properties"), dict):
                row["properties"] = item["properties"]
            if item.get("email"):
                row["email"] = str(item.get("email"))
        return row

    for item in client.list_all("/contacts"):
        ensure(item)
    for slug in STATE_ORDER:
        status, listed = list_segment(client, segment_ids[slug])
        if status != "ok":
            raise RuntimeError("old segment missing")
        for item in listed:
            row = ensure(item)
            if row is None:
                continue
            row["segments"].add(slug)
    all_status = "unset"
    if all_id:
        all_status, listed = list_segment(client, all_id)
        if all_status == "ok":
            for item in listed:
                row = ensure(item)
                if row is not None:
                    row["in_all"] = True
    return rows, all_status


def wanted_slugs(row):
    return [slug for slug in STATE_ORDER if slug in row["segments"]]


def plan_rows(client, rows, topic_ids, errors):
    planned = []
    mismatches = []
    for contact_id in sorted(rows):
        row = rows[contact_id]
        slugs = wanted_slugs(row)
        if row["unsubscribed"] or not slugs:
            row["current_topics"] = {}
            row["missing_topics"] = []
            continue
        if row["properties"] is None:
            status, data = client.call("GET", "/contacts/" + urllib.parse.quote(contact_id, safe=""))
            if status == 200 and isinstance(data.get("properties"), dict):
                row["properties"] = data["properties"]
            elif status != 200:
                errors.append({"op": "get_contact", "contact_id": contact_id, "status": status})
                row["properties"] = {}
        status, data = client.call("GET", with_query("/contacts/%s/topics" % urllib.parse.quote(contact_id, safe=""), {"limit": 100}))
        if status != 200:
            errors.append({"op": "get_topics", "contact_id": contact_id, "status": status})
            row["current_topics"] = {}
            row["missing_topics"] = []
            row["topic_read_failed"] = True
            continue
        current = topic_map(data.get("data"))
        if data.get("has_more"):
            extra = client.list_all("/contacts/%s/topics" % urllib.parse.quote(contact_id, safe=""))
            current = topic_map(extra)
        row["current_topics"] = current
        missing = []
        for slug in slugs:
            topic_id = topic_ids[slug]
            if current.get(topic_id) != "opt_in":
                missing.append(slug)
        row["missing_topics"] = missing
        stored = property_states(row.get("properties"))
        expected = ",".join(slugs)
        if stored != expected:
            mismatches.append({
                "email": row["email"],
                "contact_id": contact_id,
                "property": stored,
                "expected": expected,
            })
        if missing:
            planned.append(row)
    return planned, mismatches


def build_report(rows, topic_ids, mismatches, errors, checked, all_status):
    skipped_unsubscribed = []
    skipped_none = []
    for contact_id in sorted(rows):
        row = rows[contact_id]
        if row["unsubscribed"]:
            skipped_unsubscribed.append({"email": row["email"], "contact_id": contact_id, "reason": "unsubscribed"})
        elif not row["segments"]:
            skipped_none.append({"email": row["email"], "contact_id": contact_id, "reason": "no_segment"})
    states = {}
    opt_in_before = {}
    planned_counts = {}
    for slug in STATE_ORDER:
        topic_id = topic_ids[slug]
        members = [rows[contact_id] for contact_id in rows if slug in rows[contact_id]["segments"]]
        subscribed = [row for row in members if not row["unsubscribed"]]
        already = [row for row in subscribed if (row.get("current_topics") or {}).get(topic_id) == "opt_in"]
        missing = [row for row in subscribed if slug in (row.get("missing_topics") or [])]
        opt_in_before[slug] = len(already)
        planned_counts[slug] = len(missing)
        states[slug] = {
            "segment_members": len(members),
            "segment_subscribed": len(subscribed),
            "topic_opt_in": len(already),
            "planned_opt_in": len(missing),
            "diff": [row["email"] for row in sorted(missing, key=lambda item: item["email"])],
        }
    union = [
        row for row in rows.values()
        if row["segments"] and not row["unsubscribed"]
    ]
    if all_status == "ok":
        segment_adds = [row for row in union if not row["in_all"]]
        planned_adds = len(segment_adds)
    elif all_status == "missing":
        segment_adds = list(union)
        planned_adds = "missing"
    else:
        segment_adds = []
        planned_adds = "unset"
    return {
        "states": states,
        "opt_in_before": opt_in_before,
        "planned_counts": planned_counts,
        "skipped_unsubscribed": skipped_unsubscribed,
        "skipped_no_segment": skipped_none,
        "states_property_mismatches": mismatches,
        "api_errors": errors,
        "topics_checked": checked,
        "segment_status": all_status,
        "planned_segment_adds": planned_adds,
        "segment_add_emails": [row["email"] for row in sorted(segment_adds, key=lambda item: item["email"])],
        "union_subscribed": len(union),
    }


def apply_topics(client, rows, topic_ids, errors):
    for contact_id in sorted(rows):
        row = rows[contact_id]
        missing = row.get("missing_topics") or []
        if row.get("topic_read_failed") or not missing:
            continue
        body = {
            "topics": [
                {"id": topic_ids[slug], "subscription": "opt_in"}
                for slug in STATE_ORDER if slug in missing
            ]
        }
        status, _data = client.call(
            "PATCH",
            "/contacts/%s/topics" % urllib.parse.quote(contact_id, safe=""),
            body,
            write=True,
        )
        if status not in (200, 201):
            errors.append({"op": "opt_in", "contact_id": contact_id, "status": status})


def apply_segment(client, rows, all_id, errors):
    for contact_id in sorted(rows):
        row = rows[contact_id]
        if row["unsubscribed"] or not row["segments"] or row["in_all"]:
            continue
        status, _data = client.call(
            "POST",
            "/contacts/%s/segments/%s" % (
                urllib.parse.quote(contact_id, safe=""),
                urllib.parse.quote(all_id, safe=""),
            ),
            None,
            write=True,
        )
        if status in (200, 201, 409):
            row["in_all"] = True
        else:
            errors.append({"op": "add_segment", "contact_id": contact_id, "status": status})


def refresh_topics(client, rows, topic_ids, errors):
    for contact_id in sorted(rows):
        row = rows[contact_id]
        if row["unsubscribed"] or not row["segments"]:
            continue
        status, data = client.call(
            "GET",
            with_query("/contacts/%s/topics" % urllib.parse.quote(contact_id, safe=""), {"limit": 100}),
        )
        if status != 200:
            errors.append({"op": "recheck_topics", "contact_id": contact_id, "status": status})
            continue
        current = topic_map(data.get("data"))
        row["current_topics"] = current
        row["missing_topics"] = [
            slug for slug in wanted_slugs(row)
            if current.get(topic_ids[slug]) != "opt_in"
        ]


def diffs_after(rows, phase, all_status):
    if phase == "plan":
        return None
    if phase == "topics":
        counts = {}
        for slug in STATE_ORDER:
            counts[slug] = sum(
                1 for row in rows.values()
                if not row["unsubscribed"] and slug in (row.get("missing_topics") or [])
            )
        return counts_line(counts)
    missing = sum(
        1 for row in rows.values()
        if row["segments"] and not row["unsubscribed"] and not row["in_all"]
    )
    if all_status != "ok":
        return "missing"
    return "vic=0 nsw=0 qld=0" if missing == 0 else "missing=%s" % missing


def write_reports(out_dir, document, rows, topic_ids):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "one-list-report.json")
    csv_path = os.path.join(out_dir, "one-list-report.csv")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "email", "contact_id", "unsubscribed", "segments", "wanted_topics",
            "current_opt_ins", "planned_opt_ins", "states_property", "states_expected",
            "states_mismatch", "skip_reason", "in_all_segment",
        ])
        for contact_id in sorted(rows):
            row = rows[contact_id]
            slugs = wanted_slugs(row)
            current = row.get("current_topics") or {}
            opted = [slug for slug in STATE_ORDER if current.get(topic_ids[slug]) == "opt_in"]
            missing = row.get("missing_topics") or []
            stored = property_states(row.get("properties")) if row.get("properties") is not None else ""
            expected = ",".join(slugs)
            if row["unsubscribed"]:
                reason = "unsubscribed"
            elif not slugs:
                reason = "no_segment"
            else:
                reason = ""
            mismatch = "yes" if (not reason and stored != expected) else ""
            writer.writerow([
                row["email"], contact_id, "yes" if row["unsubscribed"] else "no",
                ",".join(slugs), ",".join(slugs), ",".join(opted), ",".join(missing),
                stored, expected, mismatch, reason, "yes" if row["in_all"] else "no",
            ])
    return json_path, csv_path


def run(argv, env, transport=None, sleep=None, clock=None):
    parser = argparse.ArgumentParser(description="Dry-run the one-list topic migration. Writes only with --apply and RESEND_ONE_LIST_CONFIRM.")
    parser.add_argument("--dry-run", action="store_true", help="Read and report. This is the default.")
    parser.add_argument("--apply", choices=("topics", "segment"), help="Live phase. Requires RESEND_ONE_LIST_CONFIRM=apply-topics or apply-segment.")
    parser.add_argument("--apply-topics", action="store_true", help="Same as --apply topics.")
    parser.add_argument("--apply-segment", action="store_true", help="Same as --apply segment.")
    parser.add_argument("--topics", default="", help="vic=<id>,nsw=<id>,qld=<id>. No sa= value is accepted.")
    parser.add_argument("--segments", default="", help="Override the old segment ids. Defaults to the live VIC, NSW and QLD segments.")
    parser.add_argument("--all-segment", default="", help="All-subscribers segment id. Defaults to RESEND_SEGMENT_ALL_ID.")
    parser.add_argument("--out", default="out", help="Report directory. Default: out")
    args = parser.parse_args(argv)
    phase, problem = resolve_phase(args)
    if problem:
        summary = blank_summary("refused", "plan")
        summary["reason"] = problem
        summary["live_writes"] = 0
        text = format_summary(summary)
        sys.stdout.write(text)
        return 1
    mode = "dry-run" if phase == "plan" else "apply-" + phase
    summary = blank_summary(mode, phase)
    if phase in ("topics", "segment"):
        expected = "apply-" + phase
        if str(env.get(CONFIRM_ENV) or "").strip() != expected:
            summary["mode"] = "refused"
            summary["reason"] = "confirmation_required"
            summary["expected"] = "%s=%s" % (CONFIRM_ENV, expected)
            sys.stdout.write(format_summary(summary))
            return 1
    api_key = str(env.get("RESEND_API_KEY") or "")
    if not api_key.strip():
        summary["reason"] = "missing_api_key"
        sys.stdout.write(redact(format_summary(summary), api_key))
        return 1
    try:
        topic_ids, missing_topics = resolve_topics(env, args.topics)
        segment_ids = resolve_segments(env, args.segments)
    except ValueError as exc:
        summary["reason"] = str(exc)
        sys.stdout.write(redact(format_summary(summary), api_key))
        return 1
    if missing_topics:
        summary["reason"] = "missing_topic_ids"
        sys.stdout.write(redact(format_summary(summary), api_key))
        return 1
    all_id = str(args.all_segment or env.get("RESEND_SEGMENT_ALL_ID") or "").strip()
    if phase == "segment" and not all_id:
        summary["reason"] = "missing_all_segment"
        sys.stdout.write(redact(format_summary(summary), api_key))
        return 1
    if transport is None:
        transport = urllib_transport(api_key)
    if sleep is None:
        sleep = time.sleep
    if clock is None:
        clock = time.monotonic
    client = Client(api_key, transport, sleep, clock)
    errors = []
    try:
        try:
            checked = check_topics(client, topic_ids)
        except Stop as stopped:
            slug = stopped.summary.get("topic") or ""
            summary["reason"] = stopped.reason + (":" + slug if slug else "")
            sys.stdout.write(redact(format_summary(summary), api_key))
            return 1
        rows, all_status = load_contacts(client, segment_ids, all_id)
        _planned, mismatches = plan_rows(client, rows, topic_ids, errors)
        # Snapshot the plan before any write. Later refreshes must not change these counts.
        before = build_report(rows, topic_ids, mismatches, errors, checked, all_status)
        if phase == "topics":
            apply_topics(client, rows, topic_ids, errors)
            refresh_topics(client, rows, topic_ids, errors)
        elif phase == "segment":
            apply_segment(client, rows, all_id, errors)
            again, listed = list_segment(client, all_id)
            if again != "ok":
                errors.append({"op": "reread_segment", "status": again})
            else:
                present = {str(item.get("id") or "") for item in listed}
                for row in rows.values():
                    row["in_all"] = row["id"] in present
        summary["live_writes"] = client.live_writes
        summary["opt_outs_sent"] = client.opt_outs_sent
        summary["broadcasts_called"] = client.broadcasts_called
        summary["emails_called"] = client.emails_called
        summary["contacts"] = len(rows)
        summary["skipped_unsubscribed"] = len(before["skipped_unsubscribed"])
        summary["skipped_no_segment"] = len(before["skipped_no_segment"])
        summary["segment_subscribed"] = counts_line({slug: before["states"][slug]["segment_subscribed"] for slug in STATE_ORDER})
        summary["topic_opt_in_before"] = counts_line(before["opt_in_before"])
        summary["planned_topic_opt_ins"] = counts_line(before["planned_counts"])
        adds = before["planned_segment_adds"]
        summary["planned_segment_adds"] = adds if isinstance(adds, str) else str(adds)
        summary["states_mismatches"] = len(mismatches)
        summary["api_errors"] = len(errors)
        remaining = diffs_after(rows, phase, "ok" if phase == "segment" else all_status)
        summary["diffs_after"] = "n/a" if remaining is None else remaining
        document = {
            "summary": {key: summary[key] for key in SUMMARY_KEYS if key in summary and key not in ("report_json", "report_csv")},
            "topics_checked": checked,
            "states": before["states"],
            "skipped_unsubscribed": before["skipped_unsubscribed"],
            "skipped_no_segment": before["skipped_no_segment"],
            "states_property_mismatches": mismatches,
            "api_errors": errors,
            "writes": client.writes,
            "planned_segment_add_emails": before["segment_add_emails"],
            "broadcasts_called": 0,
            "emails_called": 0,
            "opt_outs_sent": client.opt_outs_sent,
        }
        json_path, csv_path = write_reports(args.out, document, rows, topic_ids)
        summary["report_json"] = json_path
        summary["report_csv"] = csv_path
        sys.stdout.write(redact(format_summary(summary), api_key))
        if errors:
            return 1
        if phase != "plan" and summary["diffs_after"] not in ("vic=0 nsw=0 qld=0",):
            return 1
        return 0
    except Exception as exc:
        summary["reason"] = "error"
        summary["live_writes"] = client.live_writes
        summary["opt_outs_sent"] = client.opt_outs_sent
        message = redact(str(exc), api_key)
        sys.stdout.write(redact(format_summary(summary), api_key))
        sys.stderr.write(message + "\n")
        return 1


def main(argv=None):
    return run(sys.argv[1:] if argv is None else argv, os.environ)


if __name__ == "__main__":
    sys.exit(main())
