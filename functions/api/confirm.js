// Double opt-in, step 2. Creates the Resend contact only after the signed link is clicked.
// Returns 503 "Sign-ups open soon" unless RESEND_API_KEY, CONFIRM_SECRET, FROM_EMAIL, SITE_URL and RESEND_SEGMENT_ID are all set.
// Contact API (segments, not the old audiences API):
//   POST  /contacts                          { email, unsubscribed: false, properties, topics? }
//   PATCH /contacts/{email}/topics           bare array [{ id, subscription: "opt_in" }] for the chosen states only
//   POST  /contacts/{email}/segments/{id}    no body (ALL segment, plus legacy state segments while SIGNUP_WRITE_LEGACY_SEGMENTS=1)
// A sending-only key can send the confirmation email but cannot create contacts (401 restricted_api_key).
import { readToken, signupsReady, makeUnsubscribeToken, chosenStates, heldSignupStates, statePhrase, oneListMode, legacySegmentWrite, topicPlan, topicId, allSegmentId, legacySegmentId } from "../_lib/token.js";
import { sitePage as page } from "../_lib/page.js";
import { confirmShareExtras } from "../_lib/share-click.js";

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

// Resend "Queensland digest" segment. A segment id is not a secret (it only works with the API key).
// RESEND_SEGMENT_QLD_ID overrides it when set on the Pages project.
export const QLD_SEGMENT_ID = "2488900b-f026-44e8-9d74-098d38ef3468";

export function qldSegmentId(env) {
  return legacySegmentId(env, "qld");
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
export function existingStates(result, env) {
  if (!result || !result.ok) return [];
  const data = result.data || {};
  const props = data.properties || (data.data && data.data.properties) || {};
  let raw = props.states;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) raw = raw.value;
  return chosenStates(raw, env);
}

// Segment ids this confirmation would touch. South Australia and Tasmania are topic-only.
// A request that names only closed states does not fall back to the Victoria segment.
export function segmentPlan(env, states, recordStates) {
  const picked = chosenStates(states, env);
  const held = heldSignupStates(states, env);
  const sa = { send: false, reason: "not_used", segmentId: "", calledResend: false };
  if (!picked.length && held.length) return { enrol: [], refuse: "not_open", segmentIds: [], sa };
  const want = picked.length ? picked : ["vic"];
  const segmentIds = [];
  if (!recordStates || want.includes("vic")) segmentIds.push(env.RESEND_SEGMENT_ID);
  const nswId = String((env && env.RESEND_SEGMENT_NSW_ID) || "").trim();
  if (recordStates && want.includes("nsw") && nswId) segmentIds.push(nswId);
  const qldId = qldSegmentId(env);
  if (recordStates && want.includes("qld") && qldId) segmentIds.push(qldId);
  return { enrol: want, refuse: "", segmentIds, sa };
}

function notOpen() {
  return { ok: false, status: 400, data: { name: "signup_not_open", message: "Those digests are not open. No address was added." } };
}

// Resend state topics (private, opt_out). The digests send with topic_id, so a contact
// that is in a segment but not opted in to its state topic gets no digest.
// Topic ids are not secrets. RESEND_TOPIC_<STATE>_ID overrides each one when set.
// SA and TAS have no built-in id: they stay topic-env-only and held until opened.
export const LIVE_TOPIC_IDS = {
  vic: "7911f74b-59eb-4c9c-ba63-e6c8f344d6f7",
  nsw: "166c5fbd-9691-4dbc-9b62-b6c600b0e076",
  qld: "268e2f38-88e7-4d84-8e35-b6a05823100c",
};

// Topics this confirmation opts into. Never opt_out. Only the chosen open states.
export function chosenTopicOptIns(env, slugs) {
  const topics = [];
  for (const slug of slugs) {
    const id = topicId(env, slug) || LIVE_TOPIC_IDS[slug] || "";
    if (!id) continue;
    topics.push({ id, subscription: "opt_in" });
  }
  return topics;
}

async function patchTopics(env, email, doFetch, topics) {
  if (!topics.length) return { ok: true, status: 200, data: {} };
  // The body is a bare array of { id, subscription } (Resend REST and SDK). A { topics } wrapper is rejected.
  const opted = await resend(env, `/contacts/${encodeURIComponent(email)}/topics`, "PATCH", topics, doFetch);
  if (!opted.ok && opted.status !== 409) return opted;
  return { ...opted, ok: true };
}

async function addAllSegment(env, email, doFetch) {
  const allId = allSegmentId(env);
  if (!allId) return { ok: true, status: 200, data: {}, skipped: true };
  const added = await resend(env, segmentPath(email, allId), "POST", undefined, doFetch);
  if (!added.ok && added.status !== 409) return added;
  return { ...added, ok: true };
}

// Legacy segment writes. 404 means that segment is already gone, so the confirm continues.
async function addLegacySegments(env, email, doFetch, segmentIds, created) {
  const ids = (segmentIds || []).filter(Boolean);
  if (!ids.length) return { ok: true, status: 200, data: created.data || {} };
  let added = created;
  for (const id of ids) {
    added = await resend(env, segmentPath(email, id), "POST", undefined, doFetch);
    if (!added.ok && added.status !== 409 && added.status !== 404) return added;
  }
  return { ok: true, status: added.status, data: added.data || created.data || {} };
}

async function syncStates(env, email, doFetch, want, created) {
  let stored = want;
  if (created.status === 409) {
    const existing = await resend(env, `/contacts/${encodeURIComponent(email)}`, "GET", undefined, doFetch);
    stored = chosenStates([...existingStates(existing, env), ...want], env);
  }
  await resend(env, `/contacts/${encodeURIComponent(email)}`, "PATCH", { properties: { states: stored.join(",") } }, doFetch);
  return stored;
}

// Create the contact, then add them to the segment for each chosen open state.
// 409 means that step already happened. states is stored only when the confirmation
// link named the states. A missing contact property must not undo the signup.
// NSW joins RESEND_SEGMENT_NSW_ID when that variable is set, and is not added to the Victoria segment.
// QLD joins the Queensland digest segment (qldSegmentId), and is not added to the Victoria segment.
// A Queensland id of none or deleted skips that write. A 404 on a legacy segment does not fail the confirm.
// South Australia and Tasmania are topic-only: no segment is created for them.
// When a VIC, NSW or QLD topic id is set, the contact is also opted into that topic.
async function confirmLegacy(env, email, doFetch, states, recordStates) {
  const plan = segmentPlan(env, states, recordStates);
  if (plan.refuse === "not_open") return notOpen();
  const want = plan.enrol;
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
  if (recordStates) await syncStates(env, email, doFetch, want, created);
  const topics = chosenTopicOptIns(env, want);
  const opted = await patchTopics(env, email, doFetch, topics);
  if (!opted.ok) return opted;
  if (want.some((slug) => slug === "sa" || slug === "tas")) {
    const added = await addAllSegment(env, email, doFetch);
    if (!added.ok) return added;
  }
  return addLegacySegments(env, email, doFetch, plan.segmentIds, created);
}

function optInTopics(topics) {
  return topics.map((topic) => ({ id: topic.id, subscription: "opt_in" }));
}

// ONE_LIST_MODE on: the contact joins the all-subscribers segment and opts in to
// the chosen state topics. A 409 updates those topics with opt_in only.
// SIGNUP_WRITE_LEGACY_SEGMENTS=1 also writes the old per-state segments.
async function confirmOneList(env, email, doFetch, states, recordStates) {
  const plan = segmentPlan(env, states, recordStates);
  if (plan.refuse === "not_open") return notOpen();
  const want = plan.enrol;
  const planned = topicPlan(env, want);
  const allId = allSegmentId(env);
  const topicOnly = want.length > 0 && want.every((slug) => slug === "sa" || slug === "tas");
  if (planned.missing.length || !planned.topics.length || (!allId && !topicOnly)) {
    return { ok: false, status: 503, data: { name: "one_list_not_configured", message: "State topics are not configured." } };
  }
  const topicPayload = optInTopics(planned.topics);
  const token = env.CONFIRM_SECRET ? await makeUnsubscribeToken(email, env.CONFIRM_SECRET) : "";
  const contact = { email, unsubscribed: false, topics: topicPayload };
  if (allId) contact.segments = [{ id: allId }];
  if (token) contact.properties = { unsubscribe_token: token };
  let created = await resend(env, "/contacts", "POST", contact, doFetch);
  if (!created.ok && created.status === 422 && token) {
    const retry = { email, unsubscribed: false, topics: topicPayload };
    if (allId) retry.segments = [{ id: allId }];
    created = await resend(env, "/contacts", "POST", retry, doFetch);
  }
  if (!created.ok && created.status !== 409) return created;
  if (created.status === 409 && token) {
    await resend(env, `/contacts/${encodeURIComponent(email)}`, "PATCH", { properties: { unsubscribe_token: token } }, doFetch);
  }
  if (recordStates) await syncStates(env, email, doFetch, want, created);
  if (created.status === 409) {
    const opted = await patchTopics(env, email, doFetch, topicPayload);
    if (!opted.ok) return opted;
    if (allId) {
      const added = await resend(env, segmentPath(email, allId), "POST", undefined, doFetch);
      if (!added.ok && added.status !== 409) return added;
    }
  } else if (want.some((slug) => slug === "sa" || slug === "tas")) {
    const opted = await patchTopics(env, email, doFetch, topicPayload);
    if (!opted.ok) return opted;
  }
  if (legacySegmentWrite(env)) {
    const legacy = await addLegacySegments(env, email, doFetch, plan.segmentIds, created);
    if (!legacy.ok) return legacy;
  }
  return { ok: true, status: created.status === 409 ? 200 : created.status, data: created.data || {} };
}

export async function confirmSubscription(env, email, doFetch = fetch, states = ["vic"], recordStates = false) {
  if (oneListMode(env)) return confirmOneList(env, email, doFetch, states, recordStates);
  return confirmLegacy(env, email, doFetch, states, recordStates);
}

export async function onRequestGet({ request, env }) {
  try {
    if (!signupsReady(env)) return soon();
    const token = new URL(request.url).searchParams.get("token") || "";
    const parsed = await readToken(token, env.CONFIRM_SECRET, env);
    if (!parsed) return page("Link not valid", "That confirmation link is invalid or has expired. Please sign up again.", 400);
    if (parsed.notOpen) return page("Not open yet", "Those digests are not open. No address was added.", 400);
    const result = await confirmSubscription(env, parsed.email, fetch, parsed.states, parsed.explicit);
    if (!result.ok && result.data && result.data.name === "signup_not_open") {
      return page("Not open yet", "Those digests are not open. No address was added.", 400);
    }
    if (!result.ok) return page("Could not confirm", failureMessage(result), 503);
    const extras = confirmShareExtras();
    extras.after = `<p><a href="/summer/">Your free Summer Camp Check Kit: one page of official links for VIC, NSW, QLD, SA and TAS, with the rest of Australia coming soon.</a></p>${extras.after}`;
    return page("You're confirmed", `Thanks — you're confirmed for the free weekly CampConditions.au digest for ${statePhrase(parsed.states)}. The first one goes out on Thursday.`, 200, extras);
  } catch {
    return page("Could not confirm", failureMessage(null), 503);
  }
}
