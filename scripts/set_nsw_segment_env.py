#!/usr/bin/env python3
"""Set RESEND_SEGMENT_NSW_ID on the Cloudflare Pages project.

Uses the same API token as the Pages deploy. Adds one plain-text variable to
the preview and production configs. Other variables are left in place. The
script prints variable names only, never values.
"""
import json
import os
import urllib.error
import urllib.request

KEY = "RESEND_SEGMENT_NSW_ID"
VALUE = os.environ["NSW_SEGMENT_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
ACCOUNT = os.environ["CLOUDFLARE_ACCOUNT_ID"]
PROJECT = "campconditions"
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/pages/projects/{PROJECT}"


def call(method, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        API,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"Cloudflare {method} failed: HTTP {err.code} {detail}")
    if not payload.get("success"):
        raise SystemExit(f"Cloudflare {method} failed")
    return payload["result"]


def env_vars(project, name):
    configs = project.get("deployment_configs") or {}
    return (configs.get(name) or {}).get("env_vars") or {}


def names(project, name):
    return set(env_vars(project, name))


before = call("GET")
for environment in ("preview", "production"):
    print(f"before {environment}: {', '.join(sorted(names(before, environment))) or '(none)'}")
    block = {"env_vars": {KEY: {"type": "plain_text", "value": VALUE}}}
    config_hash = ((before.get("deployment_configs") or {}).get(environment) or {}).get("wrangler_config_hash")
    if isinstance(config_hash, str) and config_hash:
        block["wrangler_config_hash"] = config_hash
    call("PATCH", {"deployment_configs": {environment: block}})
    after = call("GET")
    saved = env_vars(after, environment).get(KEY) or {}
    missing = names(before, environment) - names(after, environment)
    if missing:
        raise SystemExit(f"{environment} lost variables: {', '.join(sorted(missing))}")
    if saved.get("type") != "plain_text" or saved.get("value") != VALUE:
        raise SystemExit(f"{environment} did not save {KEY}")
    print(f"after {environment}: {', '.join(sorted(names(after, environment)))}")
    before = after
