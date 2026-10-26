#!/usr/bin/env python3
"""Show whether a refactored build matches a baseline dist/.

Replay mode feeds both builds the same recorded responses, then compares the
trees. Timestamps from the clock (ISO instants and the Melbourne display
stamp) are blanked before the comparison. Any other byte difference is printed.

Record mode runs a build script and stores the response bodies:

    python3 scripts/diff_dist.py record /tmp/cc-main/scripts/build.py /tmp/cc-http/bodies.pkl

Compare mode replays that file into this checkout and diffs against a baseline:

    python3 scripts/diff_dist.py compare /tmp/cc-http/bodies.pkl /tmp/cc-main/dist dist
"""
import os
import pickle
import re
import runpy
import sys
import urllib.request

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
STAMP = re.compile(r"\d{1,2} [A-Z][a-z]+ \d{4}, \d{1,2}:\d{2} [AP]M [A-Z]{2,5}")
TEXT_EXT = {".html", ".json", ".txt", ".xml", ".js", ".webmanifest", ""}


class _Headers:
    def __init__(self, encoding):
        self._encoding = encoding

    def get(self, key, default=None):
        if key == "Content-Encoding":
            return self._encoding
        return default


class _Replay:
    def __init__(self, body, encoding, status):
        self._body = body
        self.headers = _Headers(encoding)
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def record(script, dest):
    store = {}
    real = urllib.request.urlopen

    def wrapped(req, timeout=60, *args, **kwargs):
        url = getattr(req, "full_url", None) or str(req)
        response = real(req, timeout=timeout)
        body = response.read()
        store[url] = {"body": body, "encoding": response.headers.get("Content-Encoding"), "status": getattr(response, "status", 200)}
        return _Replay(body, store[url]["encoding"], store[url]["status"])

    urllib.request.urlopen = wrapped
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        urllib.request.urlopen = real
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "wb") as handle:
            pickle.dump(store, handle)
        print(f"Recorded {len(store)} responses to {dest}")


def _install_replay(path):
    with open(path, "rb") as handle:
        store = pickle.load(handle)
    real = urllib.request.urlopen

    def wrapped(req, timeout=60, *args, **kwargs):
        url = getattr(req, "full_url", None) or str(req)
        row = store.get(url)
        if row is None:
            raise RuntimeError(f"no recorded response for {url}")
        return _Replay(row["body"], row.get("encoding"), row.get("status") or 200)

    urllib.request.urlopen = wrapped
    return real, len(store)


def normalize(text):
    text = ISO.sub("TIMESTAMP", text)
    text = STAMP.sub("STAMP", text)
    return text


def compare(left, right):
    """Return paths whose normalized contents differ. left and right are dist roots."""
    def files(root):
        found = {}
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                full = os.path.join(dirpath, name)
                found[os.path.relpath(full, root)] = full
        return found

    left_files, right_files = files(left), files(right)
    diffs = []
    only_left = sorted(set(left_files) - set(right_files))
    only_right = sorted(set(right_files) - set(left_files))
    for rel in only_left:
        diffs.append((rel, "only in baseline"))
    for rel in only_right:
        diffs.append((rel, "only in refactor"))
    for rel in sorted(set(left_files) & set(right_files)):
        a = open(left_files[rel], "rb").read()
        b = open(right_files[rel], "rb").read()
        if a == b:
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext not in TEXT_EXT and not rel.endswith("_headers"):
            diffs.append((rel, f"binary {len(a)} vs {len(b)}"))
            continue
        try:
            na, nb = normalize(a.decode("utf-8")), normalize(b.decode("utf-8"))
        except UnicodeError:
            diffs.append((rel, "binary text decode"))
            continue
        if na != nb:
            diffs.append((rel, "content"))
            if len(diffs) <= 8:
                _show(rel, na, nb)
    return diffs


def _show(rel, left, right):
    import difflib
    left_lines, right_lines = left.splitlines(), right.splitlines()
    shown = 0
    for line in difflib.unified_diff(left_lines, right_lines, fromfile="baseline/" + rel, tofile="refactor/" + rel, lineterm="", n=1):
        print(line)
        shown += 1
        if shown > 40:
            print("... diff truncated ...")
            break


def main(argv):
    if len(argv) < 2 or argv[1] not in ("record", "compare"):
        print(__doc__.strip())
        return 2
    if argv[1] == "record":
        record(argv[2], argv[3])
        return 0
    replay, baseline, built = argv[2], argv[3], argv[4]
    real, count = _install_replay(replay)
    print(f"Replaying {count} responses")
    try:
        runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.py"), run_name="__main__")
    finally:
        urllib.request.urlopen = real
    diffs = compare(baseline, built)
    if not diffs:
        print("DIST MATCH after blanking build timestamps")
        return 0
    print(f"DIST DIFF {len(diffs)} files")
    for rel, kind in diffs[:30]:
        print(f"  {kind}: {rel}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
