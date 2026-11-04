// Double opt-in, step 2. Adds the address to the Resend segment only after the signed link is clicked.
// Returns 503 "Sign-ups open soon" unless RESEND_API_KEY, CONFIRM_SECRET, FROM_EMAIL, SITE_URL and RESEND_SEGMENT_ID are all set.
// Contact API (segments, not the old audiences API):
//   POST /contacts                         { email, unsubscribed: false }
//   POST /contacts/{email}/segments/{id}   no body
// A sending-only key can send the confirmation email but cannot create contacts (401 restricted_api_key).
import { readToken, signupsReady, makeUnsubscribeToken, chosenStates, statePhrase } from "../_lib/token.js";
import { sitePage as page } from "../_lib/page.js";

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

// Resend "Queensland digest" segment. A segment id is not a secret (it only works with the API key).
// RESEND_SEGMENT_QLD_ID overrides it when set on the Pages project.
export const QLD_SEGMENT_ID = "2488900b-f026-44e8-9d74-098d38ef3468";

export function qldSegmentId(env) {
  return String((env && env.RESEND_SEGMENT_QLD_ID) || QLD_SEGMENT_ID).trim();
}

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

// States already saved on an existing contact, so a reader adding QLD keeps VIC and NSW.
// Unknown shapes or a failed lookup give no states (the new choice is still saved).
export function existingStates(result) {
  if (!result || !result.ok) return [];
  const data = result.data || {};
  const props = data.properties || (data.data && data.data.properties) || {};
  let raw = props.states;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) raw = raw.value;
  return chosenStates(raw);
}

// Create the contact, then add them to the segment for each chosen state.
// 409 means that step already happened. states is stored only when the confirmation
// link named the states. A missing contact property must not undo the signup.
// NSW joins RESEND_SEGMENT_NSW_ID when that variable is set, and is not added to the Victoria segment.
// QLD joins the Queensland digest segment (qldSegmentId), and is not added to the Victoria segment.
export async function confirmSubscription(env, email, doFetch = fetch, states = ["vic"], recordStates = false) {
  const picked = chosenStates(states);
  const want = picked.length ? picked : ["vic"];
  const token = env.CONFIRM_SECRET ? await makeUnsubscribeToken(email, env.CONFIRM_SECRET) : "";
  const contact = { email, unsubscribed: false };
  if (token) contact.properties = { unsubscribe_token: token };
  let created = await resend(env, "/contacts", "POST", contact, doFetch);
  if (!created.ok && created.status === 422 && token) {
    created = await resend(env, "/contacts", "POST", { email, unsubscribed: false }, doFetch);
  }
  if (!created.ok && created.status !== 409) return created;
  if (created.status === 409 && token) {
    await resend(env, `/contacts/${encodeURIComponent(email)}`, "PATCH", { properties: { unsubscribe_token: token } }, doFetch);
  }
  if (recordStates) {
    let stored = want;
    if (created.status === 409) {
      const existing = await resend(env, `/contacts/${encodeURIComponent(email)}`, "GET", undefined, doFetch);
      stored = chosenStates([...existingStates(existing), ...want]);
    }
    await resend(env, `/contacts/${encodeURIComponent(email)}`, "PATCH", { properties: { states: stored.join(",") } }, doFetch);
  }
  const segmentIds = [];
  if (!recordStates || want.includes("vic")) segmentIds.push(env.RESEND_SEGMENT_ID);
  const nswId = String(env.RESEND_SEGMENT_NSW_ID || "").trim();
  if (recordStates && want.includes("nsw") && nswId) segmentIds.push(nswId);
  const qldId = qldSegmentId(env);
  if (recordStates && want.includes("qld") && qldId) segmentIds.push(qldId);
  if (!segmentIds.length) return { ok: true, status: 200, data: created.data || {} };
  let added = created;
  for (const id of segmentIds) {
    added = await resend(env, segmentPath(email, id), "POST", undefined, doFetch);
    if (!added.ok && added.status !== 409) return added;
  }
  return { ok: true, status: added.status, data: added.data };
}

export async function onRequestGet({ request, env }) {
  try {
    if (!signupsReady(env)) return soon();
    const token = new URL(request.url).searchParams.get("token") || "";
    const parsed = await readToken(token, env.CONFIRM_SECRET);
    if (!parsed) return page("Link not valid", "That confirmation link is invalid or has expired. Please sign up again.", 400);
    const result = await confirmSubscription(env, parsed.email, fetch, parsed.states, parsed.explicit);
    if (!result.ok) return page("Could not confirm", failureMessage(result), 503);
    return page("You're confirmed", `Thanks — you're confirmed for the free weekly CampConditions.au digest for ${statePhrase(parsed.states)}. The first one goes out on Thursday.`);
  } catch {
    return page("Could not confirm", failureMessage(null), 503);
  }
}
