#!/usr/bin/env python3
"""Tests for scripts/consent_retention.py. No network: Resend and the store are fakes."""
import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consent_retention as cr  # noqa: E402

KEY = "test-hmac-key-not-a-real-secret"
TODAY = dt.date(2026, 11, 25)
failures = []


def check(cond, name):
    if not cond:
        failures.append(name)


class FakeResend:
    def __init__(self, contacts):
        self.contacts = {c["id"]: dict(c) for c in contacts}
        self.calls = []
        self.deleted = []

    def list_contacts(self):
        self.calls.append(("GET", "/contacts"))
        return [dict(c) for c in self.contacts.values()]

    def get(self, cid):
        self.calls.append(("GET", "/contacts/" + cid))
        c = self.contacts.get(cid)
        return (200, dict(c)) if c else (404, {})

    def delete(self, cid):
        self.calls.append(("DELETE", "/contacts/" + cid))
        self.deleted.append(cid)
        self.contacts.pop(cid, None)
        return 200


def contacts():
    return [
        {"id": "s1", "email": "Sub.One@Example.com", "unsubscribed": False, "created_at": "2026-10-20 01:00:00+00"},
        {"id": "s2", "email": "sub2@example.com", "unsubscribed": False, "created_at": "2026-11-20 01:00:00+00"},
        {"id": "u1", "email": "old.unsub@example.com", "unsubscribed": True, "created_at": "2026-10-24 23:44:37+00"},
        {"id": "u2", "email": "Other.Unsub@Example.org", "unsubscribed": True, "created_at": "2026-10-30 05:14:26+00"},
    ]


def env(tmp, **extra):
    base = {"RESEND_API_KEY": "x", "CONSENT_HMAC_KEY": KEY, "CONSENT_STORE": "file", "CONSENT_STORE_PATH": os.path.join(tmp, "store.json")}
    base.update(extra)
    return base


def store_blob(tmp):
    path = os.path.join(tmp, "store.json")
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


lines = []
# 1. Dry run deletes nothing and writes nothing, even with deletion enabled in env.
with tempfile.TemporaryDirectory() as tmp:
    fake = FakeResend(contacts())
    rc = cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=False, resend=fake, today=TODAY, out=lines.append)
    check(rc == 0, "dry run exit 0")
    check(fake.deleted == [], "dry run deletes nothing")
    check(not any(m == "DELETE" for m, _ in fake.calls), "dry run makes no DELETE call")
    check(not os.path.exists(os.path.join(tmp, "store.json")), "dry run writes no store file")
    check("due_for_deletion: 2" in lines and "deleted: 0 (dry run)" in lines, "dry run counts")
    check(not any("@" in l for l in lines), "dry run log has no email address")

# 2. --apply without RETENTION_DELETE=enabled refuses and changes nothing.
with tempfile.TemporaryDirectory() as tmp:
    fake = FakeResend(contacts())
    out = []
    rc = cr.run(env(tmp), apply=True, resend=fake, today=TODAY, out=out.append)
    check(rc == 2 and fake.deleted == [] and not os.path.exists(os.path.join(tmp, "store.json")), "apply without enable refuses")
    rc = cr.run(env(tmp, RETENTION_DELETE="yes"), apply=True, resend=fake, today=TODAY, out=out.append)
    check(rc == 2 and fake.deleted == [], "only the exact word enabled works")

# 3. Due selection: subscribed never selected; first run treats existing unsubscribes as due.
p = cr.plan(contacts(), {}, None, TODAY, KEY)
due_ids = sorted(i["contact"]["id"] for i in p["due"])
check(due_ids == ["u1", "u2"], "existing unsubscribes due on first run")
check(p["subscribed"] == 2, "two subscribed counted")
for bucket in ("due", "waiting", "start"):
    check(all(i["contact"]["unsubscribed"] is True for i in p[bucket]), "only unsubscribed in " + bucket)
# A contact with unsubscribed missing or a string is treated as subscribed (never deleted).
odd = [{"id": "o1", "email": "odd@example.com", "created_at": "2026-10-01"}, {"id": "o2", "email": "o2@example.com", "unsubscribed": "true"}]
p = cr.plan(odd, {}, None, TODAY, KEY)
check(p["due"] == [] and p["subscribed"] == 2, "ambiguous unsubscribed flag is never selected")

# 4. Grace clock after setup: new unsubscribe waits GRACE_DAYS, then becomes due.
h = cr.email_hash("new@example.com", KEY)
new = [{"id": "n1", "email": "new@example.com", "unsubscribed": True, "created_at": "2026-11-01"}]
p = cr.plan(new, {}, dt.date(2026, 11, 1), TODAY, KEY, grace_days=7)
check(len(p["start"]) == 1 and not p["due"], "new unsubscribe starts the clock")
rec = {"key_hash": h, "status": "pending", "unsubscribe_first_seen": "2026-11-20", "unsubscribe_basis": "first_seen_by_job"}
p = cr.plan(new, {h: rec}, dt.date(2026, 11, 1), TODAY, KEY, grace_days=7)
check(len(p["waiting"]) == 1 and not p["due"], "5 days in: still waiting")
p = cr.plan(new, {h: rec}, dt.date(2026, 11, 1), dt.date(2026, 11, 27), KEY, grace_days=7)
check(len(p["due"]) == 1, "7 days in: due")
check(cr.DEFAULT_GRACE_DAYS < cr.POLICY_DAYS, "grace inside the 30-day promise")

# 5. Apply: deletes only due unsubscribed contacts; records hold no plain email; second run is a no-op.
with tempfile.TemporaryDirectory() as tmp:
    fake = FakeResend(contacts())
    out = []
    rc = cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=True, resend=fake, today=TODAY, out=out.append)
    check(rc == 0, "apply exit 0")
    check(sorted(fake.deleted) == ["u1", "u2"], "apply deletes exactly the unsubscribed contacts")
    check("s1" in fake.contacts and "s2" in fake.contacts, "subscribed contacts kept")
    blob = store_blob(tmp)
    check("@" not in blob, "store has no @")
    for c in contacts():
        check(cr.normalise_email(c["email"]) not in blob.lower(), "store has no plain email " + c["id"])
        check(c["email"].split("@")[0].lower() not in blob.lower(), "store has no local part " + c["id"])
    data = json.loads(blob)
    recs = [v for k, v in data.items() if k.startswith(cr.RECORD_PREFIX)]
    check(len(recs) == 2 and all(r["status"] == "deleted" for r in recs), "two deleted records")
    check(all(len(r["key_hash"]) == 64 for r in recs), "sha-256 hex hash")
    check(all("states" not in json.dumps(r) for r in recs), "no preferences kept")
    check(all(r["purge_after"] == "2032-11-25" for r in recs), "purge 6 years after last-send bound")
    check(cr.email_hash("OLD.UNSUB@example.com ", KEY) in {r["key_hash"] for r in recs}, "hash uses normalised email")
    check(cr.email_hash("old.unsub@example.com", "other-key") not in {r["key_hash"] for r in recs}, "hash is keyed")
    check(cr.META_KEY in data, "store marked initialised")
    fake2 = FakeResend(list(fake.contacts.values()))
    rc = cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=True, resend=fake2, today=TODAY, out=out.append)
    check(rc == 0 and fake2.deleted == [], "second run deletes nothing")
    check(not any("@" in l for l in out), "apply log has no email address")

# 6. Race: contact resubscribed between listing and delete is not deleted.
class RaceResend(FakeResend):
    def get(self, cid):
        status, c = super().get(cid)
        c["unsubscribed"] = False
        return status, c
with tempfile.TemporaryDirectory() as tmp:
    fake = RaceResend(contacts())
    cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=True, resend=fake, today=TODAY, out=lambda _l: None)
    check(fake.deleted == [], "resubscribed-since-listing is never deleted")

# 7. Record write failure means no delete.
class BrokenStore(cr.FileStore):
    def put(self, key, value):
        if key.startswith(cr.RECORD_PREFIX):
            raise RuntimeError("store down")
        super().put(key, value)
with tempfile.TemporaryDirectory() as tmp:
    fake = FakeResend(contacts())
    rc = cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=True, resend=fake, store=BrokenStore(os.path.join(tmp, "s.json")), today=TODAY, out=lambda _l: None)
    check(fake.deleted == [] and rc == 1, "no record, no delete")

# 8. Cap: more due than MAX_DELETES stops before any change.
with tempfile.TemporaryDirectory() as tmp:
    fake = FakeResend(contacts())
    rc = cr.run(env(tmp, RETENTION_DELETE="enabled", MAX_DELETES="1"), apply=True, resend=fake, today=TODAY, out=lambda _l: None)
    check(rc == 3 and fake.deleted == [] and not os.path.exists(os.path.join(tmp, "store.json")), "cap stops the run")

# 9. Purge: deleted records past purge date are removed.
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "store.json")
    old = {"key_hash": "a" * 64, "status": "deleted", "purge_after": "2026-01-01"}
    keep = {"key_hash": "b" * 64, "status": "deleted", "purge_after": "2032-01-01"}
    json.dump({cr.META_KEY: {"on": "2020-01-01"}, cr.RECORD_PREFIX + "a" * 64: old, cr.RECORD_PREFIX + "b" * 64: keep}, open(path, "w"))
    cr.run(env(tmp, RETENTION_DELETE="enabled"), apply=True, resend=FakeResend([]), today=TODAY, out=lambda _l: None)
    left = json.load(open(path))
    check(cr.RECORD_PREFIX + "a" * 64 not in left and cr.RECORD_PREFIX + "b" * 64 in left, "purge removes only expired records")

# 10. Guard: the real client refuses anything but GET contacts and DELETE one contact.
client = cr.Resend("x", transport=lambda m, p: (200, {}))
for method, path in (("POST", "/emails"), ("PATCH", "/contacts/abc"), ("DELETE", "/contacts"), ("GET", "/broadcasts"), ("DELETE", "/segments/x/contacts/y")):
    try:
        client.call(method, path)
        failures.append("guard allowed %s %s" % (method, path))
    except RuntimeError:
        pass
check(client.call("GET", "/contacts?limit=100")[0] == 200 and client.call("DELETE", "/contacts/abc")[0] == 200, "guard allows the two needed calls")

# 11. assert_no_plain_email catches a leak.
try:
    cr.assert_no_plain_email({"x": "a@b.com"}, "a@b.com")
    failures.append("leak not caught")
except RuntimeError:
    pass

if failures:
    print("consent retention tests FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("consent retention tests passed")
