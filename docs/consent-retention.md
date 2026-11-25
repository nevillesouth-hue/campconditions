# Consent retention job

`/privacy/` promises that an unsubscribed person's email address and preferences are deleted
within 30 days, keeping only a keyed-hash consent record. This job does that.
Workflow: `.github/workflows/consent-retention.yml` (daily, 3:40am AEDT, plus manual runs).
Script: `scripts/consent_retention.py`. Tests: `scripts/test_consent_retention.py` (also run by `scripts/test.py`).

## It ships disabled

Every run is a dry run that prints counts only. Deletion happens only when all of these are true:

1. Repository variable `RETENTION_DELETE` is exactly `enabled`.
2. The run is on `main`.
3. The script gets `--apply` (the workflow's second step adds it only when 1 and 2 hold).
4. The secrets below are set.

To pause deletion again, delete the variable or set it to anything else.

## Setup before enabling (Nev or Micky)

| Name | Kind | What |
|---|---|---|
| `RETENTION_RESEND_API_KEY` | secret | A Resend API key with **Full access** (a sending-only key cannot list or delete contacts). Dedicated to this job so it can be revoked on its own. |
| `CONSENT_HMAC_KEY` | secret | A long random string (for example `openssl rand -hex 32`). Kept only as an Actions secret, never with the records. Keep a copy in the vault: losing it means old records can no longer be matched. |
| `CONSENT_KV_NAMESPACE_ID` | secret | Id of a new, empty Cloudflare Workers KV namespace (suggested name `campconditions-consent`). Not bound to the Pages project, so the site cannot read it. |
| `CONSENT_KV_TOKEN` | secret | A Cloudflare API token limited to **Account > Workers KV Storage > Edit** on this account only. |
| `CLOUDFLARE_ACCOUNT_ID` | secret | Already exists (used by the deploy). |
| `RETENTION_DELETE` | variable | Set to `enabled` only after Micky approves the deletion list. |

## Unsubscribe dates

Resend does not record when a contact unsubscribed, so the job tracks it:

* The first time the job runs with deletion on, every contact that is already unsubscribed has no
  provable unsubscribe date. They are treated as overdue and deleted in that run.
* After that, the job writes a `pending` record (hash and date only) the first day it sees a new
  unsubscribe, and deletes the contact `GRACE_DAYS` (default 7) later. With a daily run that leaves
  more than three weeks of slack inside the 30-day promise.
* Before each delete the contact is re-read; if it is no longer unsubscribed it is left alone.
* `MAX_DELETES` (default 25) stops a run that would delete more than that.

## Consent record

Written to KV under `consent:<hash>` before the contact is deleted. If the write fails, the contact is not deleted.

```json
{"v": 1, "key_hash": "<HMAC-SHA-256 hex of the lower-cased, trimmed email>", "key_version": 1,
 "status": "deleted",
 "events": [{"type": "confirmed", "at": "2026-10-24", "source": "resend_created_at"},
            {"type": "unsubscribed", "at": null, "observed_on": "2026-11-26", "basis": "already_unsubscribed_at_setup"},
            {"type": "contact_deleted", "on": "2026-11-26"}],
 "unsubscribe_first_seen": "2026-11-26", "unsubscribe_basis": "already_unsubscribed_at_setup",
 "form_id": null, "wording_version": null,
 "last_send_on_or_before": "2026-11-26", "purge_after": "2032-11-26",
 "deleted_on": "2026-11-26", "updated": "2026-11-26"}
```

No email address, IP address or preferences. `form_id` and `wording_version` were never recorded
before this job, so they are null. Records are deleted automatically after `purge_after` (6 years after the
last possible send). The hash is not anonymous: anyone holding `CONSENT_HMAC_KEY` can match an address to it.

## Why Cloudflare KV

* The repo is public, and Actions artifacts and logs on a public repo can be read by anyone, so none of those can hold records.
* KV is private to the account, supports real deletion (needed for the 6-year purge, which git history would not give),
  is free at this size, and Cloudflare is already a disclosed processor on `/privacy/`.
* The Trip Check waitlist already uses KV, so there is no new vendor.
