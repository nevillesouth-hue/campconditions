#!/usr/bin/env python3
"""Mocked checks for one-list mode and the dry-run migration script."""
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import broadcast_plan
import resend_one_list
import sa_signup

FAILURES = []


def expect(cond, label):
    if cond:
        return
    FAILURES.append(label)
    print(" FAIL", label)


def build_corpus():
    """68 contacts in the backup shape: subscribed memberships 60/34/7, 2 unsubscribed, 1 in no segment."""
    contacts = []
    number = 1

    def add(segments, unsubscribed=False, properties=None):
        nonlocal number
        contact_id = "c%04d" % number
        email = "reader%04d@example.com" % number
        number += 1
        ordered = [slug for slug in ("vic", "nsw", "qld") if slug in segments]
        if properties is None:
            properties = {"states": {"type": "string", "value": ",".join(ordered)}}
        contacts.append({
            "id": contact_id,
            "email": email,
            "unsubscribed": unsubscribed,
            "segments": list(ordered),
            "properties": properties,
            "topics": {},
        })
        return contacts[-1]

    for _ in range(2):
        add(["vic", "nsw", "qld"])
    for _ in range(3):
        add(["vic", "qld"])
    for _ in range(2):
        add(["nsw", "qld"])
    for _ in range(27):
        add(["vic", "nsw"])
    vic_only = [add(["vic"]) for _ in range(28)]
    for _ in range(3):
        add(["nsw"])
    vic_only[0]["properties"] = {"states": {"type": "string", "value": "nsw"}}
    unsubscribed = [add(["vic"], unsubscribed=True), add(["nsw"], unsubscribed=True)]
    add([], properties={"states": {"type": "string", "value": ""}})
    expect(len(contacts) == 68, "fixture has 68 contacts")

    def subscribed(slug):
        return sum(1 for contact in contacts if slug in contact["segments"] and not contact["unsubscribed"])

    expect(subscribed("vic") == 60 and subscribed("nsw") == 34 and subscribed("qld") == 7, "fixture opt-in targets")
    expect(len(unsubscribed) == 2, "fixture unsubscribed")
    return contacts, unsubscribed


class Api:
    def __init__(self, contacts, topic_default="opt_out"):
        self.contacts = {contact["id"]: contact for contact in contacts}
        self.topics = {"vic": "topic-vic", "nsw": "topic-nsw", "qld": "topic-qld"}
        self.segments = {"vic": "seg-vic", "nsw": "seg-nsw", "qld": "seg-qld"}
        self.all_id = "seg-all"
        self.topic_default = {topic_id: topic_default for topic_id in self.topics.values()}
        self.calls = []
        self.fail_patches = 0

    def _page(self, items, params):
        limit = int((params.get("limit") or ["20"])[0])
        after = (params.get("after") or [None])[0]
        ordered = sorted(items, key=lambda item: item["id"])
        if after:
            ids = [item["id"] for item in ordered]
            ordered = ordered[ids.index(after) + 1:] if after in ids else []
        return {"object": "list", "has_more": len(ordered) > limit, "data": ordered[:limit]}

    def _row(self, contact):
        return {"id": contact["id"], "email": contact["email"], "unsubscribed": contact["unsubscribed"]}

    def transport(self, method, path, body, headers):
        self.calls.append((method, path, body, dict(headers)))
        bare, _, query = path.partition("?")
        params = urllib.parse.parse_qs(query)
        if "/broadcasts" in bare or "/emails" in bare:
            raise AssertionError("send endpoint called: " + bare)
        if method == "PATCH" and self.fail_patches:
            self.fail_patches -= 1
            return 429, {}, {"retry-after": "1"}
        payload = json.loads(body.decode("utf-8")) if body else None
        if bare == "/contacts" and method == "GET":
            return 200, self._page([self._row(contact) for contact in self.contacts.values()], params), {}
        if bare.startswith("/segments/") and bare.endswith("/contacts") and method == "GET":
            segment_id = bare.split("/")[2]
            if segment_id == self.all_id:
                chosen = [contact for contact in self.contacts.values() if "all" in contact["segments"]]
            else:
                slug = {value: key for key, value in self.segments.items()}.get(segment_id)
                if slug is None:
                    return 404, {"name": "not_found"}, {}
                chosen = [contact for contact in self.contacts.values() if slug in contact["segments"]]
            return 200, self._page([self._row(contact) for contact in chosen], params), {}
        if bare.startswith("/topics/") and method == "GET":
            topic_id = bare.split("/")[2]
            return 200, {
                "id": topic_id,
                "name": topic_id,
                "default_subscription": self.topic_default.get(topic_id, "opt_in"),
                "visibility": "private",
            }, {}
        if bare.startswith("/contacts/") and bare.endswith("/topics") and method == "GET":
            contact = self.contacts[bare.split("/")[2]]
            data = [{"id": topic_id, "subscription": subscription} for topic_id, subscription in contact["topics"].items()]
            return 200, self._page(data, params), {}
        if bare.startswith("/contacts/") and method == "GET":
            contact = self.contacts[bare.split("/")[2]]
            return 200, {
                "id": contact["id"],
                "email": contact["email"],
                "unsubscribed": contact["unsubscribed"],
                "properties": contact["properties"],
            }, {}
        if bare.startswith("/contacts/") and bare.endswith("/topics") and method == "PATCH":
            contact = self.contacts[bare.split("/")[2]]
            for topic in payload["topics"]:
                if topic["subscription"] != "opt_in":
                    raise AssertionError("opt out was sent")
                contact["topics"][topic["id"]] = topic["subscription"]
            return 200, {"object": "contact_topics"}, {}
        if bare.startswith("/contacts/") and "/segments/" in bare and method == "POST":
            contact_id, _, segment_id = bare[len("/contacts/"):].partition("/segments/")
            contact = self.contacts[contact_id]
            if segment_id == self.all_id:
                if "all" not in contact["segments"]:
                    contact["segments"].append("all")
            return 200, {}, {}
        return 500, {"message": "unexpected " + method + " " + bare}, {}


def env_for(api, key):
    return {
        "RESEND_API_KEY": key,
        "RESEND_TOPIC_VIC_ID": api.topics["vic"],
        "RESEND_TOPIC_NSW_ID": api.topics["nsw"],
        "RESEND_TOPIC_QLD_ID": api.topics["qld"],
        "RESEND_SEGMENT_ID": api.segments["vic"],
        "RESEND_SEGMENT_NSW_ID": api.segments["nsw"],
        "RESEND_SEGMENT_QLD_ID": api.segments["qld"],
        "RESEND_SEGMENT_ALL_ID": api.all_id,
    }


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def capture(argv, env, api, clock):
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        code = resend_one_list.run(argv, env, api.transport, clock.sleep, clock.clock)
    finally:
        sys.stdout, sys.stderr = previous
    return code, stdout.getvalue(), stderr.getvalue()


def methods(api):
    return [(method, path.split("?", 1)[0]) for method, path, _body, _headers in api.calls]


def test_migration():
    key = "re_test_SHOULD_NOT_APPEAR_99"
    contacts, unsubscribed = build_corpus()
    api = Api(contacts)
    env = env_for(api, key)
    out = tempfile.mkdtemp(prefix="one-list-")
    clock = Clock()
    code, text, err = capture(["--out", out], env, api, clock)
    expect(code == 0, "dry run exits 0: " + err[-200:])
    expect("mode: dry-run\n" in text, "dry run mode")
    expect("phase: plan\n" in text, "dry run phase")
    expect("live_writes: 0\n" in text, "dry run writes nothing")
    expect("opt_outs_sent: 0\n" in text, "dry run opts nobody out")
    expect("broadcasts_called: 0\n" in text and "emails_called: 0\n" in text, "dry run sends nothing")
    expect("contacts: 68\n" in text, "dry run contact count")
    expect("skipped_unsubscribed: 2\n" in text, "dry run skips unsubscribed")
    expect("skipped_no_segment: 1\n" in text, "dry run skips the contact in no segment")
    expect("segment_subscribed: vic=60 nsw=34 qld=7\n" in text, "dry run subscribed counts")
    expect("topic_opt_in_before: vic=0 nsw=0 qld=0\n" in text, "dry run topic baseline")
    expect("planned_topic_opt_ins: vic=60 nsw=34 qld=7\n" in text, "dry run plan")
    expect("planned_segment_adds: 65\n" in text, "dry run segment plan")
    expect("states_mismatches: 1\n" in text, "dry run reports the states mismatch")
    expect("api_errors: 0\n" in text, "dry run has no API errors")
    expect("diffs_after: n/a\n" in text, "dry run does not claim a diff result")
    expect(text.endswith("report_csv: %s\n" % os.path.join(out, "one-list-report.csv")), "dry run names the csv")
    expect(key not in text and key not in err, "dry run does not print the API key")
    expect(all(method == "GET" for method, _path in methods(api)), "dry run only reads")
    expect(not any("/broadcasts" in path or "/emails" in path for _method, path, _body, _headers in api.calls), "no send URL")
    expect(any("limit=100" in path for _method, path, _body, _headers in api.calls), "lists use limit 100")
    report = json.load(open(os.path.join(out, "one-list-report.json"), encoding="utf-8"))
    expect(report["states"]["vic"]["segment_members"] == 61, "victoria segment still has the unsubscribed contact")
    expect(len(report["states"]["vic"]["diff"]) == 60, "victoria diff is the subscribed contacts")
    skipped = {row["email"] for row in unsubscribed}
    expect(not skipped.intersection(report["states"]["vic"]["diff"]), "unsubscribed address is not opted in")
    expect(key not in open(os.path.join(out, "one-list-report.json"), encoding="utf-8").read(), "report hides the key")
    expect(any(row["states_mismatch"] == "yes" for row in __import__("csv").DictReader(open(os.path.join(out, "one-list-report.csv"), encoding="utf-8"))), "csv names the mismatch")
    expect(clock.slept and min(clock.slept) >= 0.19, "requests are throttled")

    # The confirmation variable on its own does not write.
    armed = dict(env)
    armed["RESEND_ONE_LIST_CONFIRM"] = "apply-topics"
    before = len(api.calls)
    code, text, _err = capture(["--out", out], armed, api, Clock())
    expect(code == 0 and "live_writes: 0\n" in text, "confirm env without --apply stays a dry run")
    expect(all(method == "GET" for method, _path in methods(api)[before:]), "confirm env does not write")

    def refuse(*_args):
        raise AssertionError("transport should not be called")

    code, text, _err = capture(["--apply", "topics", "--out", out], env, type("T", (), {"transport": staticmethod(refuse)})(), Clock())
    expect(code == 1 and "reason: confirmation_required\n" in text and "expected: RESEND_ONE_LIST_CONFIRM=apply-topics\n" in text, "apply topics needs the env var")
    code, text, _err = capture(["--apply-segment", "--out", out], env, type("T", (), {"transport": staticmethod(refuse)})(), Clock())
    expect(code == 1 and "expected: RESEND_ONE_LIST_CONFIRM=apply-segment\n" in text, "apply segment needs its own env var")
    code, text, _err = capture(["--dry-run", "--apply", "topics"], env, type("T", (), {"transport": staticmethod(refuse)})(), Clock())
    expect(code == 1 and "reason: dry_run_and_apply\n" in text, "dry-run and apply together are refused")
    code, text, _err = capture(["--topics", "sa=topic-sa,vic=a,nsw=b,qld=c"], env, type("T", (), {"transport": staticmethod(refuse)})(), Clock())
    expect(code == 1 and "no_sa_topic" in text, "an SA topic is refused")

    # Apply topics, then the same apply is a no-op.
    code, text, err = capture(["--apply-topics", "--out", out], armed, api, Clock())
    expect(code == 0, "apply topics exits 0: " + err[-300:])
    expect("mode: apply-topics\n" in text and "live_writes: 65\n" in text, "apply topics writes one patch per subscribed contact")
    expect("diffs_after: vic=0 nsw=0 qld=0\n" in text, "apply topics leaves no diff")
    expect("planned_topic_opt_ins: vic=60 nsw=34 qld=7\n" in text, "apply reports the plan it carried out")
    bodies = [json.loads(body) for method, path, body, _headers in api.calls if method == "PATCH"]
    opted = [topic for payload in bodies for topic in payload["topics"]]
    expect(len(opted) == 101 and all(topic["subscription"] == "opt_in" for topic in opted), "101 opt-ins and no opt-outs")
    expect(not any(method == "POST" for method, _path in methods(api)), "topic apply does not add segments")
    code, text, _err = capture(["--apply", "topics", "--out", out], armed, api, Clock())
    expect(code == 0 and "live_writes: 0\n" in text, "second topic apply writes nothing")
    expect("planned_topic_opt_ins: vic=0 nsw=0 qld=0\n" in text, "second topic apply is already done")
    expect("topic_opt_in_before: vic=60 nsw=34 qld=7\n" in text, "second run sees the opt-ins")

    # Segment apply, then a no-op. Unsubscribed contacts stay out.
    code, text, err = capture(["--apply-segment", "--out", out], {**armed, "RESEND_ONE_LIST_CONFIRM": "apply-segment"}, api, Clock())
    expect(code == 0 and "live_writes: 65\n" in text and "diffs_after: vic=0 nsw=0 qld=0\n" in text, "segment apply: " + (err or text)[-400:])
    added = [path for method, path, _body, _headers in api.calls if method == "POST"]
    expect(len(added) == 65 and all(path.endswith("/segments/seg-all") for path in added), "segment apply only adds the all segment")
    for contact in unsubscribed:
        expect("all" not in contact["segments"], "unsubscribed contact was not added")
    code, text, _err = capture(["--apply-segment", "--out", out], {**armed, "RESEND_ONE_LIST_CONFIRM": "apply-segment"}, api, Clock())
    expect(code == 0 and "live_writes: 0\n" in text, "second segment apply writes nothing")


def test_edges():
    key = "re_test_SHOULD_NOT_APPEAR_99"
    # Already opted into Victoria; the patch is NSW only. A second run writes nothing.
    contact = {
        "id": "c0001", "email": "partial@example.com", "unsubscribed": False,
        "segments": ["vic", "nsw"], "properties": {"states": {"type": "string", "value": "vic,nsw"}},
        "topics": {"topic-vic": "opt_in"},
    }
    api = Api([contact])
    env = env_for(api, key)
    env["RESEND_ONE_LIST_CONFIRM"] = "apply-topics"
    out = tempfile.mkdtemp(prefix="one-list-edge-")
    code, text, err = capture(["--apply-topics", "--out", out], env, api, Clock())
    expect(code == 0 and "live_writes: 1\n" in text, "partial opt-in writes once: " + err[-200:])
    patches = [json.loads(body) for method, _path, body, _headers in api.calls if method == "PATCH"]
    expect(len(patches) == 1 and patches[0]["topics"] == [{"id": "topic-nsw", "subscription": "opt_in"}], "partial patch is the missing topic only")
    code, text, _err = capture(["--apply-topics", "--out", out], env, api, Clock())
    expect(code == 0 and "live_writes: 0\n" in text, "partial second run writes nothing")

    # An opt_out topic default aborts before any contact write.
    api = Api([contact], topic_default="opt_in")
    code, text, _err = capture(["--out", out], env_for(api, key), api, Clock())
    expect(code == 1 and "reason: topic_default_not_opt_out:vic\n" in text, "opt_in default aborts")
    expect(not any(method != "GET" for method, _path in methods(api)), "abort writes nothing")
    expect(not any(path.startswith("/contacts") for _method, path, _body, _headers in api.calls), "abort stops before contacts")

    # 429 is retried. One contact, one successful patch.
    one = {
        "id": "c0001", "email": "retry@example.com", "unsubscribed": False,
        "segments": ["qld"], "properties": {"states": {"type": "string", "value": "qld"}},
        "topics": {"topic-qld": "opt_out"},
    }
    api = Api([one])
    api.fail_patches = 1
    clock = Clock()
    env = env_for(api, key)
    env["RESEND_ONE_LIST_CONFIRM"] = "apply-topics"
    code, text, err = capture(["--apply", "topics", "--out", out], env, api, clock)
    expect(code == 0 and "live_writes: 1\n" in text, "429 retries then writes: " + err[-200:])
    expect(1.0 in clock.slept, "429 backs off")
    expect(one["topics"]["topic-qld"] == "opt_in", "retry opted in")

    # Pagination follows has_more and after.
    many = []
    for index in range(1, 102):
        many.append({
            "id": "c%04d" % index,
            "email": "page%04d@example.com" % index,
            "unsubscribed": False,
            "segments": ["vic"],
            "properties": {"states": {"type": "string", "value": "vic"}},
            "topics": {},
        })
    api = Api(many)
    code, text, err = capture(["--out", out], env_for(api, key), api, Clock())
    expect(code == 0 and "contacts: 101\n" in text and "planned_topic_opt_ins: vic=101 nsw=0 qld=0\n" in text, "paged dry run: " + err[-200:])
    expect(any("after=" in path for _method, path, _body, _headers in api.calls), "pagination sends after")

    defaults = resend_one_list.resolve_segments({}, "")
    expect(defaults == resend_one_list.DEFAULT_SEGMENTS, "old segment ids default to the live segments")
    code, text, _err = capture([], {}, Api([]), Clock())
    expect(code == 1 and "mode: dry-run\n" in text and "reason: missing_api_key\n" in text, "missing key stays a dry run and does not call")


def test_broadcast_and_digest():
    node = subprocess.run(["node", os.path.join(ROOT, "scripts", "one_list_check.mjs")], cwd=ROOT, capture_output=True, text=True)
    expect(node.returncode == 0, "JS checks: " + (node.stderr or node.stdout)[-400:])
    parity = [line[7:] for line in (node.stdout or "").splitlines() if line.startswith("PARITY ")]
    expect(len(parity) == 1, "JS parity line")
    if parity:
        got = json.loads(parity[0])
        env = {
            "RESEND_SEGMENT_ID": "b9096e2d-485b-487e-90db-467e44eaf6cc",
            "RESEND_SEGMENT_NSW_ID": "nsw-segment",
            "RESEND_SEGMENT_QLD_ID": "qld-segment",
            "RESEND_SEGMENT_ALL_ID": "seg-all",
            "RESEND_TOPIC_VIC_ID": "topic-vic",
            "RESEND_TOPIC_NSW_ID": "topic-nsw",
            "RESEND_TOPIC_QLD_ID": "topic-qld",
            "RESEND_TOPIC_SA_ID": "topic-sa",
        }
        fields = dict(subject="Hello", html="<p>Hi</p>", from_email="CampConditions.au <digest@mail.campconditions.au>")
        off = broadcast_plan.broadcast_body("vic", env, **fields)
        on = dict(env)
        on["ONE_LIST_MODE"] = "1"
        expect(off == got["offVic"], "python and JS agree with the flag off")
        expect(broadcast_plan.broadcast_body("vic", on, **fields) == got["onVic"], "victoria topic matches")
        expect(broadcast_plan.broadcast_body("nsw", on, **fields) == got["onNsw"], "NSW topic matches")
        expect(broadcast_plan.broadcast_body("qld", on, **fields) == got["onQld"], "Queensland topic matches")
        try:
            broadcast_plan.broadcast_body("sa", on, **fields)
            expect(False, "SA broadcast should be refused")
        except broadcast_plan.BroadcastRefused as exc:
            expect(exc.reason == got["sa"] == "state_not_open", "SA stays closed in both languages")
        try:
            broadcast_plan.guard_broadcast({"segment_id": "seg-all", "from": "a", "subject": "s", "html": "h"}, "seg-all")
            expect(False, "guard should refuse")
        except broadcast_plan.BroadcastRefused as exc:
            expect(exc.reason == got["guard"], "guard reason matches")
        expect("topic_id" not in off, "flag off omits topic_id")
        expect(broadcast_plan.broadcast_meta("vic", env) == {}, "flag off adds no digest meta")
        meta = broadcast_plan.broadcast_meta("nsw", on)
        expect(meta["broadcast"]["topic_id"] == "topic-nsw" and meta["broadcast"]["segment_id"] == "seg-all", "digest meta carries the topic")

    plan_src = open(os.path.join(ROOT, "scripts", "broadcast_plan.py"), encoding="utf-8").read()
    expect("urllib" not in plan_src and "api.resend.com" not in plan_src, "broadcast plan does not call Resend")
    digest_src = open(os.path.join(ROOT, "scripts", "digest.py"), encoding="utf-8").read()
    expect("api.resend.com" not in digest_src and "urllib" not in digest_src, "digest script still only writes drafts")
    expect(sa_signup.COMING_SOON == "SA weekly email coming soon", "SA coming soon line is unchanged")

    status = {
        "generated": "2026-11-10T01:00:00+00:00",
        "camps": [{
            "name": "Test Camp",
            "slug": "test-camp",
            "url": "https://campconditions.au/vic/camp/test-camp/",
            "status": "closed",
            "region": "gippsland",
            "closure": {"desc": "Closed", "outdated": False},
        }],
    }
    current = os.path.join(tempfile.mkdtemp(prefix="one-list-status-"), "status.json")
    json.dump(status, open(current, "w", encoding="utf-8"))
    off_dir = tempfile.mkdtemp(prefix="digest-off-")
    on_dir = tempfile.mkdtemp(prefix="digest-on-")
    base = os.environ.copy()
    base.pop("ONE_LIST_MODE", None)
    off = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "digest.py"), "--current", current, "--out", off_dir], cwd=ROOT, capture_output=True, text=True, env=base)
    on_env = dict(base)
    on_env.update({
        "ONE_LIST_MODE": "1",
        "RESEND_SEGMENT_ALL_ID": "seg-all",
        "RESEND_TOPIC_VIC_ID": "topic-vic",
        "RESEND_TOPIC_NSW_ID": "topic-nsw",
        "RESEND_TOPIC_QLD_ID": "topic-qld",
    })
    on = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "digest.py"), "--current", current, "--out", on_dir], cwd=ROOT, capture_output=True, text=True, env=on_env)
    expect(off.returncode == 0 and on.returncode == 0, "digest drafts render")
    for name in ("digest.html", "digest.txt"):
        expect(open(os.path.join(off_dir, name), encoding="utf-8").read() == open(os.path.join(on_dir, name), encoding="utf-8").read(), "digest " + name + " is unchanged by the flag")
    off_meta = json.load(open(os.path.join(off_dir, "meta.json"), encoding="utf-8"))
    on_meta = json.load(open(os.path.join(on_dir, "meta.json"), encoding="utf-8"))
    expect("broadcast" not in off_meta and off_meta.get("state") == "vic", "flag off meta has no broadcast")
    expect(on_meta["broadcast"]["topic_id"] == "topic-vic" and on_meta["broadcast"]["segment_id"] == "seg-all", "flag on meta names the victoria topic")
    for slug, topic in (("nsw", "topic-nsw"), ("qld", "topic-qld")):
        state_meta = json.load(open(os.path.join(on_dir, slug, "meta.json"), encoding="utf-8"))
        expect(state_meta["broadcast"]["topic_id"] == topic, slug + " digest topic")
        off_state = json.load(open(os.path.join(off_dir, slug, "meta.json"), encoding="utf-8"))
        expect("broadcast" not in off_state, slug + " flag off meta")


def main():
    test_migration()
    test_edges()
    test_broadcast_and_digest()
    if FAILURES:
        print("one-list failures: %s" % len(FAILURES))
        return 1
    print("one-list checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
