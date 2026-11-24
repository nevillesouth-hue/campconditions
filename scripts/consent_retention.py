#!/usr/bin/env python3
"""Delete unsubscribed Resend contacts within the 30 days the privacy page promises.

What it does, once deletion is enabled:
  1. Lists every Resend contact (GET /contacts). Subscribed contacts are never selected.
  2. For each unsubscribed contact, computes a keyed hash of the normalised email
     (HMAC-SHA-256, key in CONSENT_HMAC_KEY, which is never stored with the records).
  3. Tracks the first day the job saw that contact unsubscribed, because Resend does not
     store an unsubscribe date. A contact is due GRACE_DAYS after that first sighting.
     Contacts that were already unsubscribed when the store was first set up have no
     provable unsubscribe date, so they are due straight away.
  4. For each due contact: writes the minimal consent record first, re-reads the contact
     and checks it is still unsubscribed, then DELETE /contacts/{id}, then marks the
     record deleted. If the record cannot be written, the contact is not deleted.
  5. Deletes consent records whose purge date has passed.

Consent record (Lex, legal review 25 Nov 2026, section 5.4, reusing E-Bike Watch s11):
keyed hash, event types and times, form id, wording version, last-send date and purge
date. No email address, no IP address, no preferences (states are not kept).
Form id and wording version were not recorded before this job, so they are null.

Where records live: a private Cloudflare Workers KV namespace (CONSENT_STORE=kv),
written through the Cloudflare API. Never the public repo, never an Actions artifact
(artifacts on a public repo can be downloaded by anyone), never the Actions log.
CONSENT_STORE=file is for tests and local runs only.

Safety:
  * Default is a dry run. It reads Resend (and the store, if set) and prints counts only.
    It writes nothing anywhere.
  * Deleting needs BOTH --apply and RETENTION_DELETE=enabled, plus a configured store and
    hash key. Either one alone is still a dry run (apply without the env refuses).
  * MAX_DELETES (default 25) caps one run. More due contacts than that stops the run.
  * The only Resend calls allowed are GET /contacts... and DELETE /contacts/{id}.
  * Logs never contain an email address, a hash or a contact id. Actions logs on a
    public repo are public.

HTTP goes through curl. Keys are passed to curl on stdin (-K -), not on the command line.

Env:
  RESEND_API_KEY        Resend key that can read and delete contacts (full access).
  CONSENT_HMAC_KEY      Long random string. Rotating it orphans the old records.
  CONSENT_STORE         kv | file  (unset: dry run treats every unsubscribed contact as due)
  CONSENT_KV_ACCOUNT_ID, CONSENT_KV_NAMESPACE_ID, CONSENT_KV_TOKEN  (kv store)
  CONSENT_STORE_PATH    (file store)
  RETENTION_DELETE      must be exactly "enabled" to delete
  GRACE_DAYS            default 7 (so a missed run or two still lands well inside 30 days)
  MAX_DELETES           default 25
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.parse

RESEND_API = "https://api.resend.com"
CF_API = "https://api.cloudflare.com/client/v4"
RECORD_PREFIX = "consent:"
META_KEY = "meta:initialised"
KEY_VERSION = 1
RETAIN_YEARS = 6          # Spam Act 2003 limitation period for ACMA civil penalty action
DEFAULT_GRACE_DAYS = 7
DEFAULT_MAX_DELETES = 25
POLICY_DAYS = 30


# ---------- pure helpers (tested) ----------

def normalise_email(email):
    return str(email or "").strip().lower()


def email_hash(email, key):
    if not key:
        raise ValueError("CONSENT_HMAC_KEY is required to hash")
    return hmac.new(key.encode("utf-8"), normalise_email(email).encode("utf-8"), hashlib.sha256).hexdigest()


def parse_day(value):
    """Resend created_at looks like '2026-10-24 23:44:37.046229+00'. Returns a UTC date or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def add_years(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 Feb
        return day.replace(year=day.year + years, day=28)


def is_unsubscribed(contact):
    return contact.get("unsubscribed") is True


def plan(contacts, records, initialised, today, key, grace_days=DEFAULT_GRACE_DAYS):
    """Decide what to do with each contact. Pure: no I/O.

    contacts: Resend contact dicts (id, email, unsubscribed, created_at)
    records:  {hash: record} already in the store
    initialised: date the store was first set up, or None (never set up)
    Returns a dict of lists. Subscribed contacts are never in 'due' or 'start'.
    """
    out = {"due": [], "waiting": [], "start": [], "subscribed": 0, "resubscribed_after_delete": 0}
    for contact in contacts:
        if not is_unsubscribed(contact):
            out["subscribed"] += 1
            if key and records:
                rec = records.get(email_hash(contact.get("email"), key))
                if rec and rec.get("status") == "deleted":
                    out["resubscribed_after_delete"] += 1
            continue
        h = email_hash(contact.get("email"), key) if key else None
        rec = records.get(h) if h else None
        if rec and rec.get("status") in ("pending", "deleting") and rec.get("unsubscribe_first_seen"):
            first = dt.date.fromisoformat(rec["unsubscribe_first_seen"])
            basis = rec.get("unsubscribe_basis") or "first_seen_by_job"
            if basis == "already_unsubscribed_at_setup" or (today - first).days >= grace_days:
                out["due"].append({"contact": contact, "hash": h, "first_seen": first, "basis": basis})
            else:
                out["waiting"].append({"contact": contact, "hash": h, "first_seen": first, "basis": basis})
            continue
        if initialised is None:
            # No provable unsubscribe date: treat as already overdue.
            out["due"].append({"contact": contact, "hash": h, "first_seen": today, "basis": "already_unsubscribed_at_setup"})
        else:
            # Seen unsubscribed for the first time today (or re-unsubscribed after an earlier delete).
            out["start"].append({"contact": contact, "hash": h, "first_seen": today, "basis": "first_seen_by_job"})
    return out


def consent_record(item, today, status):
    """The only shape ever written to the store. No email, no states, no IP."""
    contact = item["contact"]
    confirmed = parse_day(contact.get("created_at"))
    first_seen = item["first_seen"]
    # We never email anyone after they unsubscribe, so the last send is on or before the
    # day the job first saw the unsubscribe. Purging 6 years after that is never early.
    last_send_bound = first_seen
    record = {
        "v": 1,
        "key_hash": item["hash"],
        "key_version": KEY_VERSION,
        "status": status,
        "events": [
            {"type": "confirmed", "at": confirmed.isoformat() if confirmed else None, "source": "resend_created_at"},
            {"type": "unsubscribed", "at": None, "observed_on": first_seen.isoformat(), "basis": item["basis"]},
        ],
        "unsubscribe_first_seen": first_seen.isoformat(),
        "unsubscribe_basis": item["basis"],
        "form_id": None,
        "wording_version": None,
        "last_send_on_or_before": last_send_bound.isoformat(),
        "purge_after": add_years(last_send_bound, RETAIN_YEARS).isoformat(),
        "updated": today.isoformat(),
    }
    if status == "deleted":
        record["events"].append({"type": "contact_deleted", "on": today.isoformat()})
        record["deleted_on"] = today.isoformat()
    return record


def assert_no_plain_email(record, email):
    blob = json.dumps(record)
    if "@" in blob or normalise_email(email) in blob.lower():
        raise RuntimeError("consent record would contain an email address")


# ---------- transports (curl) ----------

def curl(method, url, headers, body=None, timeout=60):
    """Run curl with headers on stdin so secrets never appear in argv. Returns (status, json)."""
    config = []
    for name, value in headers.items():
        config.append('header = "%s: %s"' % (name, str(value).replace('"', "")))
    args = ["curl", "-sS", "-K", "-", "-X", method, "--max-time", str(timeout), "-w", "\n%{http_code}", url]
    stdin = "\n".join(config) + "\n"
    if body is not None:
        args[1:1] = ["--data-binary", "@" + body]
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0, {"error": "curl exit %s" % proc.returncode}
    raw, _, code = proc.stdout.rpartition("\n")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {"raw": raw[:200]}
    return int(code or 0), data


class Resend:
    def __init__(self, api_key, transport=None):
        self.api_key = api_key
        self.transport = transport or self._curl
        self.deletes = 0

    def _curl(self, method, path):
        return curl(method, RESEND_API + path, {"Authorization": "Bearer " + self.api_key, "User-Agent": "campconditions-retention/1"})

    def guard(self, method, path):
        bare = path.split("?", 1)[0].rstrip("/")
        if method == "GET" and (bare == "/contacts" or bare.startswith("/contacts/")):
            return
        if method == "DELETE" and bare.startswith("/contacts/") and bare.count("/") == 2:
            return
        raise RuntimeError("refusing %s %s" % (method, bare))

    def call(self, method, path):
        self.guard(method, path)
        for attempt in range(5):
            status, data = self.transport(method, path)
            if status != 429:
                return status, data
            time.sleep(2 ** attempt)
        return status, data

    def list_contacts(self):
        items, after, seen = [], None, set()
        while True:
            q = {"limit": 100}
            if after:
                q["after"] = after
            status, data = self.call("GET", "/contacts?" + urllib.parse.urlencode(q))
            if status != 200:
                raise RuntimeError("Resend list failed with HTTP %s" % status)
            batch = data.get("data") or []
            items.extend(batch)
            if not data.get("has_more") or not batch:
                return items
            after = str(batch[-1].get("id") or "")
            if not after or after in seen:
                return items
            seen.add(after)

    def get(self, contact_id):
        return self.call("GET", "/contacts/" + urllib.parse.quote(contact_id, safe=""))

    def delete(self, contact_id):
        status, data = self.call("DELETE", "/contacts/" + urllib.parse.quote(contact_id, safe=""))
        if status in (200, 204):
            self.deletes += 1
        return status


class FileStore:
    """JSON file keyed by store key. Tests and local runs only."""

    def __init__(self, path):
        self.path = path

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, key):
        return self._load().get(key)

    def put(self, key, value):
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key):
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def keys(self, prefix):
        return [k for k in self._load() if k.startswith(prefix)]


class KVStore:
    """Cloudflare Workers KV over the REST API, through curl."""

    def __init__(self, account, namespace, token):
        self.base = "%s/accounts/%s/storage/kv/namespaces/%s" % (CF_API, account, namespace)
        self.headers = {"Authorization": "Bearer " + token}

    def get(self, key):
        status, data = curl("GET", self.base + "/values/" + urllib.parse.quote(key, safe=""), self.headers)
        if status == 404:
            return None
        if status != 200:
            raise RuntimeError("KV get failed with HTTP %s" % status)
        return data

    def put(self, key, value):
        path = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", "kv-put.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        try:
            status, data = curl("PUT", self.base + "/values/" + urllib.parse.quote(key, safe=""),
                                dict(self.headers, **{"Content-Type": "application/json"}), body=path)
        finally:
            os.remove(path)
        if status != 200 or not data.get("success", False):
            raise RuntimeError("KV put failed with HTTP %s" % status)

    def delete(self, key):
        status, _ = curl("DELETE", self.base + "/values/" + urllib.parse.quote(key, safe=""), self.headers)
        if status not in (200, 404):
            raise RuntimeError("KV delete failed with HTTP %s" % status)

    def keys(self, prefix):
        out, cursor = [], ""
        while True:
            q = {"prefix": prefix, "limit": 1000}
            if cursor:
                q["cursor"] = cursor
            status, data = curl("GET", self.base + "/keys?" + urllib.parse.urlencode(q), self.headers)
            if status != 200:
                raise RuntimeError("KV list failed with HTTP %s" % status)
            out.extend(item["name"] for item in data.get("result") or [])
            cursor = (data.get("result_info") or {}).get("cursor") or ""
            if not cursor:
                return out


def store_from_env(env):
    kind = (env.get("CONSENT_STORE") or "").strip().lower()
    if kind == "kv":
        need = ("CONSENT_KV_ACCOUNT_ID", "CONSENT_KV_NAMESPACE_ID", "CONSENT_KV_TOKEN")
        if not all(env.get(n) for n in need):
            raise RuntimeError("kv store needs CONSENT_KV_ACCOUNT_ID, CONSENT_KV_NAMESPACE_ID and CONSENT_KV_TOKEN")
        return KVStore(env["CONSENT_KV_ACCOUNT_ID"], env["CONSENT_KV_NAMESPACE_ID"], env["CONSENT_KV_TOKEN"])
    if kind == "file":
        if not env.get("CONSENT_STORE_PATH"):
            raise RuntimeError("file store needs CONSENT_STORE_PATH")
        return FileStore(env["CONSENT_STORE_PATH"])
    if kind:
        raise RuntimeError("CONSENT_STORE must be kv or file")
    return None


def load_records(store):
    records = {}
    for key in store.keys(RECORD_PREFIX):
        rec = store.get(key)
        if isinstance(rec, dict) and rec.get("key_hash"):
            records[rec["key_hash"]] = rec
    return records


# ---------- run ----------

def run(env, apply, resend=None, store=None, today=None, out=print):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    grace = int(env.get("GRACE_DAYS") or DEFAULT_GRACE_DAYS)
    cap = int(env.get("MAX_DELETES") or DEFAULT_MAX_DELETES)
    key = env.get("CONSENT_HMAC_KEY") or ""
    enabled = (env.get("RETENTION_DELETE") or "").strip() == "enabled"
    if apply and not enabled:
        out("mode: refused (--apply without RETENTION_DELETE=enabled); nothing changed")
        return 2
    if apply and not key:
        out("mode: refused (--apply needs CONSENT_HMAC_KEY); nothing changed")
        return 2
    if store is None:
        store = store_from_env(env)
    if apply and store is None:
        out("mode: refused (--apply needs CONSENT_STORE); nothing changed")
        return 2
    if resend is None:
        if not env.get("RESEND_API_KEY"):
            out("mode: skipped (RESEND_API_KEY not set); nothing changed")
            return 0
        resend = Resend(env["RESEND_API_KEY"])

    contacts = resend.list_contacts()
    records = load_records(store) if (store is not None and key) else {}
    meta = store.get(META_KEY) if store is not None else None
    initialised = dt.date.fromisoformat(meta["on"]) if isinstance(meta, dict) and meta.get("on") else None
    result = plan(contacts, records, initialised, today, key, grace)
    unsub = len(result["due"]) + len(result["waiting"]) + len(result["start"])
    purge_keys = [k for k, r in ((RECORD_PREFIX + h, r) for h, r in records.items())
                  if r.get("status") == "deleted" and r.get("purge_after") and r["purge_after"] < today.isoformat()]

    out("mode: %s" % ("apply" if apply else "dry-run"))
    out("contacts: %d" % len(contacts))
    out("subscribed: %d (never selected)" % result["subscribed"])
    out("unsubscribed: %d" % unsub)
    out("due_for_deletion: %d" % len(result["due"]))
    out("waiting_grace: %d" % len(result["waiting"]))
    out("new_unsubscribes_clock_started: %d" % len(result["start"]))
    out("grace_days: %d (policy limit %d)" % (grace, POLICY_DAYS))
    out("store: %s, initialised: %s, records: %d" % ("set" if store is not None else "unset", initialised or "no", len(records)))
    out("records_past_purge_date: %d" % len(purge_keys))
    out("subscribed_matching_deleted_hash: %d" % result["resubscribed_after_delete"])

    if not apply:
        out("deleted: 0 (dry run)")
        return 0
    if len(result["due"]) > cap:
        out("stopped: %d due is more than MAX_DELETES=%d; nothing changed" % (len(result["due"]), cap))
        return 3

    if initialised is None:
        store.put(META_KEY, {"on": today.isoformat(), "note": "contacts already unsubscribed on this day had no provable unsubscribe date and were treated as due"})
    for item in result["start"]:
        rec = consent_record(item, today, "pending")
        assert_no_plain_email(rec, item["contact"].get("email"))
        store.put(RECORD_PREFIX + item["hash"], rec)

    deleted = failed = skipped = 0
    for item in result["due"]:
        contact = item["contact"]
        rec = consent_record(item, today, "deleting")
        assert_no_plain_email(rec, contact.get("email"))
        try:
            store.put(RECORD_PREFIX + item["hash"], rec)
        except Exception:
            failed += 1
            continue
        status, fresh = resend.get(str(contact.get("id") or ""))
        if status != 200 or fresh.get("unsubscribed") is not True:
            skipped += 1   # resubscribed or vanished since listing: never delete a subscriber
            continue
        if resend.delete(str(contact["id"])) not in (200, 204):
            failed += 1
            continue
        done = consent_record(item, today, "deleted")
        assert_no_plain_email(done, contact.get("email"))
        store.put(RECORD_PREFIX + item["hash"], done)
        deleted += 1
    for key_name in purge_keys:
        store.delete(key_name)
    out("deleted: %d" % deleted)
    out("skipped_now_subscribed_or_missing: %d" % skipped)
    out("failed: %d" % failed)
    out("records_purged: %d" % len(purge_keys))
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="delete due contacts (also needs RETENTION_DELETE=enabled)")
    args = parser.parse_args(argv)
    try:
        return run(dict(os.environ), args.apply)
    except RuntimeError as err:
        print("error: %s" % err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
