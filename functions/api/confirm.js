// Double opt-in, step 2. Adds the address to the Resend segment only after the signed link is clicked.
// Returns 503 "Sign-ups open soon" unless RESEND_API_KEY, CONFIRM_SECRET, FROM_EMAIL, SITE_URL and RESEND_SEGMENT_ID are all set.
// Contact API (segments, not the old audiences API):
//   POST /contacts                         { email, unsubscribed: false }
//   POST /contacts/{email}/segments/{id}   no body
// A sending-only key can send the confirmation email but cannot create contacts (401 restricted_api_key).
import { readToken, signupsReady } from "../_lib/token.js";

const page = (title, msg, status = 200) =>
  new Response(
    `<!doctype html><html lang="en-AU"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><p>${msg}</p><p><a href="/">Back to CampConditions.au</a></p></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

export function segmentPath(email, segmentId) {
  return `/contacts/${encodeURIComponent(email)}/segments/${encodeURIComponent(segmentId)}`;
}

export function failureMessage(result) {
  const name = String(result?.data?.name || "");
  const message = String(result?.data?.message || "");
  if (name === "restricted_api_key" || /only send emails/i.test(message)) {
    return "We couldn't confirm you because the email key on this site can send mail but cannot save contacts. Email <a href=\"mailto:campconditions@outlook.com\">campconditions@outlook.com</a> and we'll add you.";
  }
  return "We couldn't add you just now. Please try the link again later, or email <a href=\"mailto:campconditions@outlook.com\">campconditions@outlook.com</a>.";
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

// Create the contact, then add them to the segment. 409 means that step already happened.
export async function confirmSubscription(env, email, doFetch = fetch) {
  const created = await resend(env, "/contacts", "POST", { email, unsubscribed: false }, doFetch);
  if (!created.ok && created.status !== 409) return created;
  const added = await resend(env, segmentPath(email, env.RESEND_SEGMENT_ID), "POST", undefined, doFetch);
  if (!added.ok && added.status !== 409) return added;
  return { ok: true, status: added.status, data: added.data };
}

export async function onRequestGet({ request, env }) {
  try {
    if (!signupsReady(env)) return soon();
    const token = new URL(request.url).searchParams.get("token") || "";
    const email = await readToken(token, env.CONFIRM_SECRET);
    if (!email) return page("Link not valid", "That confirmation link is invalid or has expired. Please sign up again.", 400);
    const result = await confirmSubscription(env, email);
    if (!result.ok) return page("Could not confirm", failureMessage(result), 503);
    return page("You're confirmed", "Thanks — you're on the free weekly Victoria digest. The first one goes out on Thursday.");
  } catch {
    return page("Could not confirm", failureMessage(null), 503);
  }
}
