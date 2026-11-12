#!/usr/bin/env python3
"""Build Tasmania pages into a directory outside dist.

    python3 scripts/tas_preview.py /tmp/tas-preview

CAMPCONDITIONS_PREVIEW=tas is set for that run only. The state stays off in
config, and this refuses to write into dist. It does not deploy.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tas-preview"
    dist = os.path.abspath(os.path.join(ROOT, "dist"))
    target = os.path.abspath(out if os.path.isabs(out) else os.path.join(ROOT, out))
    if target == dist or target.startswith(dist + os.sep):
        print("Refusing to write Tasmania pages into dist", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["CAMPCONDITIONS_PREVIEW"] = "tas"
    env["CAMPCONDITIONS_OUT"] = target
    env["SA_FIRE_MODE"] = "linkout"
    env.setdefault("PARKSVIC_FETCH_SECONDS", "240")
    script = os.path.join(ROOT, "scripts", "build.py")
    return subprocess.call([sys.executable, script], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
