// One-click unsubscribe. GET and POST /api/unsubscribe?e=<email>&t=<HMAC>.
// The token is HMAC-SHA256 of "unsubscribe\n" + the lowercase email, keyed with CONFIRM_SECRET.
// POST is the RFC 8058 one-click action (List-Unsubscribe-Post: List-Unsubscribe=One-Click).
// A valid token marks the Resend contact unsubscribed and removes it from RESEND_SEGMENT_ID.
import { signupsReady, unsubscribeTokenMatches } from "../_lib/token.js";
import { sitePage } from "../_lib/page.js";
import { segmentPath } from "./confirm.js";

function failureMessage(result) {
  const name = String(result?.data?.name || "");
  const message = String(result?.data?.message || "");
  if (name === "restricted_api_key" || /only send emails/i.test(message)) {
    return 'We couldn\'t unsubscribe you because the email key on this site can send mail but cannot update contacts. Email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a> and we\'ll remove you.';
  }
  return 'We couldn\'t unsubscribe you just now. Please try again later, or email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>.';
}

async function resend(env, path, method, body, doFetch) {
  const headers = { authorization: `Bearer ${env.RESEND_API_KEY}` };
  const init = { method, headers };
  if (body !== undefined) {
    headers["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await doFetch(`https://api.resend.com${path}`, init);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// Mark the contact unsubscribed and remove them from the digest segment.
// 404 on either call means that step is already done.
// RESEND_SEGMENT_NSW_ID is optional. When it is set, that segment is removed too.
export async function unsubscribeContact(env, email, doFetch = fetch) {
  const patched = await resend(env, `/contacts/${encodeURIComponent(email)}`, "PATCH", { unsubscribed: true }, doFetch);
  const removed = await resend(env, segmentPath(email, env.RESEND_SEGMENT_ID), "DELETE", undefined, doFetch);
  const nswId = String(env.RESEND_SEGMENT_NSW_ID || "").trim();
  const removedNsw = nswId ? await resend(env, segmentPath(email, nswId), "DELETE", undefined, doFetch) : null;
  if (removedNsw && !removedNsw.ok && removedNsw.status !== 404) return removedNsw;
  if (patched.ok || removed.ok || (patched.status === 404 && removed.status === 404)) return { ok: true, status: 200, data: {} };
  return patched.ok ? removed : patched;
}

async function handle(request, env) {
  if (!signupsReady(env)) {
    return sitePage("Unsubscribe unavailable", 'Unsubscribe isn\'t available just now. Email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a> and we\'ll remove you.', 503);
  }
  const url = new URL(request.url);
  const email = url.searchParams.get("e") || "";
  const token = url.searchParams.get("t") || "";
  if (!(await unsubscribeTokenMatches(email, token, env.CONFIRM_SECRET))) {
    return sitePage("Link not valid", 'That unsubscribe link is not valid. <a href="/unsubscribe/">Request a new one</a>.', 400);
  }
  try {
    const result = await unsubscribeContact(env, email.trim().toLowerCase());
    if (!result.ok) return sitePage("Could not unsubscribe", failureMessage(result), 503);
  } catch {
    return sitePage("Could not unsubscribe", failureMessage(null), 503);
  }
  return sitePage("You're unsubscribed", "You're unsubscribed from the CampConditions.au digest. You won't receive any more weekly emails.");
}

export function onRequestGet(ctx) { return handle(ctx.request, ctx.env); }
export function onRequestPost(ctx) { return handle(ctx.request, ctx.env); }
