import { confirmSubscription, QLD_SEGMENT_ID } from "../functions/api/confirm.js";
import { listEnrolment, signupChoice } from "../functions/api/subscribe.js";
import { unsubscribeContact } from "../functions/api/unsubscribe.js";
import { broadcastBody, guardBroadcast, makeToken, oneListMode, readToken, stateOpen, topicPlan } from "../functions/_lib/token.js";
import { onRequestGet } from "../functions/api/confirm.js";
import { confirmationMessage, pickStateMessage } from "../functions/api/subscribe.js";

function assert(cond, message) {
  if (!cond) {
    console.error(message);
    process.exit(1);
  }
}

function jsonBody(call) {
  return call.body ? JSON.parse(call.body) : null;
}

function recorder(handler) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body };
    calls.push(call);
    return handler(call, calls);
  };
  return { calls, fetch };
}

const email = "reader@example.com";
const secret = "test-secret";
const vicSegment = "b9096e2d-485b-487e-90db-467e44eaf6cc";
const ALL = "seg-all";
const TOPICS = { vic: "topic-vic", nsw: "topic-nsw", qld: "topic-qld" };

function base(extra = {}) {
  return {
    RESEND_API_KEY: "test",
    CONFIRM_SECRET: secret,
    FROM_EMAIL: "CampConditions.au <digest@mail.campconditions.au>",
    SITE_URL: "https://campconditions.au",
    RESEND_SEGMENT_ID: vicSegment,
    RESEND_SEGMENT_NSW_ID: "nsw-segment",
    RESEND_SEGMENT_QLD_ID: "qld-segment",
    RESEND_SEGMENT_ACT_ID: "act-segment",
    RESEND_SEGMENT_SA_ID: "sa-segment",
    RESEND_TOPIC_VIC_ID: TOPICS.vic,
    RESEND_TOPIC_NSW_ID: TOPICS.nsw,
    RESEND_TOPIC_QLD_ID: TOPICS.qld,
    RESEND_TOPIC_SA_ID: "topic-sa",
    RESEND_SEGMENT_ALL_ID: ALL,
    ...extra,
  };
}

const okResponse = (status = 201) => new Response(JSON.stringify({ id: "c1" }), { status });

// Flag off, with no topic ids, is still create plus the Victoria segment.
assert(oneListMode(base()) === false, "flag defaults off");
assert(oneListMode(base({ ONE_LIST_MODE: "0" })) === false, "zero is off");
function withoutTopics(extra = {}) {
  return base({
    RESEND_TOPIC_VIC_ID: "",
    RESEND_TOPIC_NSW_ID: "",
    RESEND_TOPIC_QLD_ID: "",
    RESEND_TOPIC_SA_ID: "",
    RESEND_TOPIC_TAS_ID: "",
    ...extra,
  });
}
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(withoutTopics(), email, fetch);
  assert(result.ok, "flag off confirms");
  assert(calls.length === 3, "flag off is create, the victoria topic, then the victoria segment");
  assert(calls.some((call) => call.url.endsWith("/segments/" + vicSegment)), "flag off uses the victoria segment");
  const builtIn = calls.find((call) => call.url.endsWith("/topics") && call.method === "PATCH");
  assert(builtIn && JSON.stringify(jsonBody(builtIn)) === JSON.stringify([{ id: "7911f74b-59eb-4c9c-ba63-e6c8f344d6f7", subscription: "opt_in" }]), "flag off without topic env opts in to the built-in victoria topic only (bare array)");
  assert(calls.every((call) => !call.url.includes(ALL) && !call.url.includes("topic-")), "flag off does not use the all segment or env topics");
  assert(!jsonBody(calls[0]).topics && !jsonBody(calls[0]).segments, "flag off create has no topics");
}

// Legacy mode opts into a state topic when that topic id is set. It still writes the old segment.
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(base(), email, fetch);
  assert(result.ok, "legacy dual-write confirms");
  const topicCall = calls.find((call) => call.url.endsWith("/topics") && call.method === "PATCH");
  assert(topicCall && jsonBody(topicCall).length === 1, "legacy dual-write patches the victoria topic");
  assert(jsonBody(topicCall)[0].id === TOPICS.vic && jsonBody(topicCall)[0].subscription === "opt_in", "legacy dual-write is opt_in");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "legacy dual-write never opts out");
  assert(calls.some((call) => call.url.endsWith("/segments/" + vicSegment) && call.method === "POST"), "legacy dual-write still joins Victoria");
  assert(!calls.some((call) => call.url.includes(ALL) || call.url.includes("topic-sa")), "legacy Victoria does not join the all segment or SA");
}

// New contact, one-list mode, no legacy segments.
{
  const { calls, fetch } = recorder(() => okResponse());
  const env = base({ ONE_LIST_MODE: "1" });
  const result = await confirmSubscription(env, email, fetch, ["nsw", "vic"], true);
  assert(result.ok, "one-list confirm");
  const created = jsonBody(calls[0]);
  assert(created.unsubscribed === false, "new contact stays subscribed");
  assert(JSON.stringify(created.segments) === JSON.stringify([{ id: ALL }]), "new contact joins the all segment");
  const topics = created.topics.map((topic) => topic.id + ":" + topic.subscription).join(",");
  assert(topics === TOPICS.vic + ":opt_in," + TOPICS.nsw + ":opt_in", "new contact opts into the chosen topics");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "confirm never opts out");
  assert(!calls.some((call) => call.url.includes("/topics")), "create carries the topics, no follow-up patch");
  assert(!calls.some((call) => call.url.includes("/segments/nsw-segment") || call.url.includes("/segments/" + vicSegment)), "legacy segments stay off");
  assert(!calls.some((call) => call.url.includes("sa-segment") || call.url.includes("act-segment") || call.url.includes("topic-sa")), "no SA or ACT enrolment");
}

// Existing contact adding Queensland keeps Victoria and NSW.
{
  const { calls, fetch } = recorder((call) => {
    if (call.url.endsWith("/contacts") && call.method === "POST") return new Response("{}", { status: 409 });
    if (call.method === "GET") return new Response(JSON.stringify({ properties: { states: "vic,nsw" } }), { status: 200 });
    return okResponse(200);
  });
  const result = await confirmSubscription(base({ ONE_LIST_MODE: "on" }), email, fetch, ["qld"], true);
  assert(result.ok, "existing contact confirms");
  const topicPatch = calls.find((call) => call.url.endsWith("/topics") && call.method === "PATCH");
  assert(topicPatch, "existing contact gets a topic patch");
  const topics = jsonBody(topicPatch);
  assert(topics.length === 1 && topics[0].id === TOPICS.qld && topics[0].subscription === "opt_in", "only the new state is opted in");
  const statesPatch = calls.find((call) => call.method === "PATCH" && call.body && call.body.includes('"states"'));
  assert(statesPatch && jsonBody(statesPatch).properties.states === "vic,nsw,qld", "stored states keep Victoria and NSW");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "adding a state does not opt out");
  assert(calls.some((call) => call.url.endsWith("/segments/" + ALL) && call.method === "POST"), "existing contact is added to the all segment");
}

// Held states never get a topic and never call Resend.
{
  let calls = 0;
  const result = await confirmSubscription(base({ ONE_LIST_MODE: "1" }), email, async () => { calls += 1; return okResponse(); }, ["act", "sa"], true);
  assert(!result.ok && result.data.name === "signup_not_open" && calls === 0, "held states are refused");
  const planned = topicPlan(base({ ONE_LIST_MODE: "1" }), ["vic", "sa", "act"]);
  assert(planned.topics.map((topic) => topic.slug).join(",") === "vic" && planned.missing.length === 0, "held states are not topics");
}

// Legacy dual-write is explicit. Off by default inside one-list mode.
{
  const quiet = recorder(() => okResponse());
  await confirmSubscription(base({ ONE_LIST_MODE: "yes" }), email, quiet.fetch, ["qld"], true);
  assert(!quiet.calls.some((call) => call.url.includes("qld-segment") || call.url.includes(QLD_SEGMENT_ID)), "dual-write defaults off");
  const both = recorder(() => okResponse());
  await confirmSubscription(base({ ONE_LIST_MODE: "1", SIGNUP_WRITE_LEGACY_SEGMENTS: "1" }), email, both.fetch, ["vic", "qld"], true);
  assert(both.calls.some((call) => call.url.endsWith("/segments/" + vicSegment)), "dual-write keeps Victoria");
  assert(both.calls.some((call) => call.url.endsWith("/segments/qld-segment")), "dual-write keeps Queensland");
  assert(jsonBody(both.calls[0]).segments[0].id === ALL, "dual-write still joins the all segment");
}

// A 422 on the token property retries without it and keeps the topics.
{
  let posts = 0;
  const { calls, fetch } = recorder((call) => {
    if (call.url.endsWith("/contacts") && call.method === "POST") {
      posts += 1;
      if (posts === 1) return new Response(JSON.stringify({ name: "validation_error" }), { status: 422 });
    }
    return okResponse();
  });
  const result = await confirmSubscription(base({ ONE_LIST_MODE: "true" }), email, fetch, ["vic"], true);
  assert(result.ok && posts === 2, "token validation retries");
  assert(jsonBody(calls[0]).properties.unsubscribe_token, "first create stores the token");
  assert(!jsonBody(calls[1]).properties && jsonBody(calls[1]).topics[0].id === TOPICS.vic, "retry keeps the topic");
}

// One-list mode without topic ids does not create a contact.
{
  let calls = 0;
  const env = base({ ONE_LIST_MODE: "1", RESEND_TOPIC_QLD_ID: "" });
  const result = await confirmSubscription(env, email, async () => { calls += 1; return okResponse(); }, ["qld"], true);
  assert(!result.ok && result.data.name === "one_list_not_configured" && calls === 0, "missing topic fails closed");
  assert(listEnrolment(env, ["qld"]).ok === false, "signup refuses a missing topic");
  assert(listEnrolment(base(), ["qld"]).ok === true && listEnrolment(base(), ["qld"]).mode === "segments", "flag off signup does not need topics");
  assert(listEnrolment(base({ ONE_LIST_MODE: "1" }), ["vic", "nsw"]).ok === true, "signup allows configured topics");
}

assert(signupChoice(["sa"], true).reason === "not_open", "SA signup stays closed");
assert(signupChoice(["tas"], true).reason === "not_open", "TAS signup stays closed");
assert(pickStateMessage({}) === "Choose Victoria, New South Wales, Queensland, or any mix of them.", "pick-a-state text is unchanged while the flags are off");

const openSa = base({ SIGNUP_OPEN_SA: "1" });
const openBoth = base({ SIGNUP_OPEN_SA: "1", SIGNUP_OPEN_TAS: "1", RESEND_TOPIC_TAS_ID: "topic-tas" });
assert(stateOpen(openSa, "sa") === true && stateOpen(base({ SIGNUP_OPEN_SA: "1", RESEND_TOPIC_SA_ID: "" }), "sa") === false, "SA opens only with the flag and the topic");
assert(stateOpen(openBoth, "tas") === true && stateOpen(openSa, "tas") === false, "TAS stays held until its own flag and topic");
assert(signupChoice(["sa"], true, openSa).ok === true && signupChoice(["sa"], true, openSa).states.join(",") === "sa", "SA-only choice");
assert(signupChoice(["sa"], true, base({ SIGNUP_OPEN_SA: "1", RESEND_TOPIC_SA_ID: "" })).reason === "not_open", "a flag without a topic stays held");
assert(pickStateMessage(openSa) === "Choose Victoria, New South Wales, Queensland, or any mix of them.", "one open state keeps today's pick-a-state text");
assert(pickStateMessage(openBoth) === "Choose Victoria, New South Wales, Queensland, South Australia, Tasmania, or any mix of them.", "both open states use the longer sentence");
{
  const note = confirmationMessage("https://campconditions.au", "https://campconditions.au/api/confirm?token=abc", "https://campconditions.au/unsubscribe/", ["sa"], "reader@example.com", openSa);
  assert(note.html.includes("digest for South Australia") && note.text.includes("digest for South Australia"), "confirmation wording uses the state phrase");
}

// SA-only: contact, SA topic opt-in, the all segment when set, no Victoria segment and no SA segment.
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(openSa, email, fetch, ["sa"], true);
  assert(result.ok, "SA-only confirm");
  assert(calls.some((call) => call.method === "POST" && call.url.endsWith("/contacts")), "SA-only creates the contact");
  const topicCall = calls.find((call) => call.url.endsWith("/topics") && call.method === "PATCH");
  assert(topicCall && jsonBody(topicCall).length === 1 && jsonBody(topicCall)[0].id === "topic-sa" && jsonBody(topicCall)[0].subscription === "opt_in", "SA-only opts into the SA topic");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "SA-only never opts out");
  assert(calls.some((call) => call.method === "POST" && call.url.endsWith("/segments/" + ALL)), "SA-only joins the all segment when it is set");
  assert(!calls.some((call) => call.url.includes(vicSegment) || call.url.includes("sa-segment") || call.url.includes("act-segment")), "SA-only writes no state segment");
  assert(calls.some((call) => call.body && call.body.includes('"states":"sa"')), "SA-only stores sa");
}
{
  const quiet = recorder(() => { throw new Error("no resend"); });
  const result = await confirmSubscription(base({ SIGNUP_OPEN_SA: "1", RESEND_TOPIC_SA_ID: "", RESEND_SEGMENT_ALL_ID: "" }), email, quiet.fetch, ["sa"], true);
  assert(!result.ok && quiet.calls.length === 0, "SA without a topic id is not enrolled");
}
{
  const { calls, fetch } = recorder(() => okResponse());
  const env = base({ SIGNUP_OPEN_SA: "1", RESEND_SEGMENT_ALL_ID: "" });
  const result = await confirmSubscription(env, email, fetch, ["sa"], true);
  assert(result.ok, "SA-only without the all segment still confirms");
  assert(!calls.some((call) => call.url.includes("/segments/")), "no all segment means no segment call");
}

// An existing Victoria contact adding Tasmania keeps Victoria and does not opt out.
{
  const { calls, fetch } = recorder((call) => {
    if (call.url.endsWith("/contacts") && call.method === "POST") return new Response("{}", { status: 409 });
    if (call.method === "GET") return new Response(JSON.stringify({ properties: { states: "vic" } }), { status: 200 });
    return okResponse(200);
  });
  const env = base({ SIGNUP_OPEN_TAS: "1", RESEND_TOPIC_TAS_ID: "topic-tas" });
  const result = await confirmSubscription(env, email, fetch, ["tas"], true);
  assert(result.ok, "adding Tasmania confirms");
  const statesPatch = calls.find((call) => call.method === "PATCH" && call.body && call.body.includes('"states"'));
  assert(statesPatch && jsonBody(statesPatch).properties.states === "vic,tas", "stored states keep Victoria");
  const topicCall = calls.find((call) => call.url.endsWith("/topics"));
  const topics = jsonBody(topicCall);
  assert(Array.isArray(topics) && topics.length === 1 && topics[0].id === "topic-tas" && topics[0].subscription === "opt_in", "only Tasmania is opted in");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "adding Tasmania does not opt out");
  assert(!calls.some((call) => call.url.includes("sa-segment") || call.url.includes("tas-segment") || call.url.includes(vicSegment)), "adding Tasmania writes no state segment");
}

// A deleted Queensland segment is not called. A 404 on a legacy segment does not fail the confirm.
{
  const { calls, fetch } = recorder((call) => {
    if (String(call.url).includes("/segments/")) return new Response("{}", { status: 404 });
    return okResponse();
  });
  const result = await confirmSubscription(withoutTopics(), email, fetch, ["vic", "qld"], true);
  assert(result.ok, "legacy 404 still confirms");
  assert(calls.some((call) => call.url.includes("/segments/" + vicSegment)), "victoria segment was attempted");
  assert(calls.some((call) => call.url.includes("/segments/qld-segment")), "queensland segment was attempted");
}
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(withoutTopics({ RESEND_SEGMENT_QLD_ID: "none" }), email, fetch, ["qld"], true);
  assert(result.ok, "queensland none confirms");
  assert(!calls.some((call) => String(call.url).includes("/segments/")), "queensland none makes no segment call");
  assert(calls.some((call) => call.body && call.body.includes('"states":"qld"')), "queensland none still stores the state");
}
{
  const { calls, fetch } = recorder(() => new Response("{}", { status: 200 }));
  const gone = await unsubscribeContact(withoutTopics({ RESEND_SEGMENT_QLD_ID: "deleted", RESEND_SEGMENT_NSW_ID: "" }), email, fetch);
  assert(gone.ok && calls.length === 2, "unsubscribe skips a deleted Queensland segment");
  assert(calls[1].url.includes(vicSegment), "victoria segment is still removed");
  assert(!calls.some((call) => call.url.includes(QLD_SEGMENT_ID)), "deleted Queensland segment is not called");
}

// A token that names SA verifies only while SA is open.
{
  const token = await makeToken(email, secret, 3600, ["sa"], openSa);
  const open = await readToken(token, secret, openSa);
  assert(open && !open.notOpen && open.states.join(",") === "sa", "open SA token verifies");
  const closed = await readToken(token, secret, {});
  assert(closed && closed.notOpen, "closed SA token is not open");
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return okResponse(); };
  const res = await onRequestGet({
    request: new Request("https://campconditions.au/api/confirm?token=" + encodeURIComponent(token)),
    env: withoutTopics({ CONFIRM_SECRET: secret }),
  });
  const html = await res.text();
  assert(res.status === 400 && html.includes("Not open yet") && calls === 0, "confirm page says not open yet");
}

// Unsubscribe: flag off is the current three calls. Flag on also opts out of every state topic.
{
  const off = recorder(() => new Response("{}", { status: 200 }));
  const gone = await unsubscribeContact(base({ RESEND_SEGMENT_NSW_ID: "" }), email, off.fetch);
  assert(gone.ok && off.calls.length === 3, "flag off unsubscribe length");
  assert(off.calls[0].method === "PATCH" && jsonBody(off.calls[0]).unsubscribed === true, "global unsubscribe");
  assert(off.calls[1].method === "DELETE" && off.calls[1].url.includes(vicSegment), "victoria segment removed");
  assert(off.calls[2].method === "DELETE" && off.calls[2].url.includes(QLD_SEGMENT_ID) === false && off.calls[2].url.includes("qld-segment"), "queensland segment removed");
  assert(off.calls.every((call) => !call.url.includes("/topics") && !call.url.includes("sa-segment")), "flag off unsubscribe ignores topics and SA");
  const on = recorder(() => new Response("{}", { status: 200 }));
  const env = base({ ONE_LIST_MODE: "1", RESEND_SEGMENT_NSW_ID: "nsw-segment" });
  const removed = await unsubscribeContact(env, email, on.fetch);
  assert(removed.ok, "one-list unsubscribe");
  assert(on.calls[0].body.includes('"unsubscribed":true'), "one-list still unsubscribes the whole list");
  assert(on.calls.some((call) => call.method === "DELETE" && call.url.includes("nsw-segment")), "old NSW segment still removed");
  const topicCall = on.calls.find((call) => call.url.endsWith("/topics"));
  const opted = jsonBody(topicCall).map((topic) => topic.subscription + ":" + topic.id).sort();
  assert(opted.join(",") === ["opt_out:topic-sa", "opt_out:" + TOPICS.nsw, "opt_out:" + TOPICS.qld, "opt_out:" + TOPICS.vic].sort().join(","), "configured topics including SA are opted out");
  assert(!on.calls.some((call) => call.url.includes("sa-segment")), "unsubscribe does not write an SA segment");
  const withTas = recorder(() => new Response("{}", { status: 200 }));
  const tasEnv = base({ ONE_LIST_MODE: "1", RESEND_TOPIC_TAS_ID: "topic-tas" });
  const tasGone = await unsubscribeContact(tasEnv, email, withTas.fetch);
  assert(tasGone.ok, "tas topic unsubscribe");
  const tasTopics = jsonBody(withTas.calls.find((call) => call.url.endsWith("/topics"))).map((topic) => topic.id);
  assert(tasTopics.includes("topic-tas") && tasTopics.includes("topic-sa"), "SA and TAS topics are opted out");
  assert(withTas.calls.every((call) => !call.url.includes("sa-segment") && !String(call.body || "").includes("opt_in")), "unsubscribe does not opt in or write an SA segment");
}

const fields = { from: "CampConditions.au <digest@mail.campconditions.au>", subject: "Hello", html: "<p>Hi</p>" };
const offBody = broadcastBody(base(), "vic", fields);
const onVic = broadcastBody(base({ ONE_LIST_MODE: "1" }), "vic", fields);
const onNsw = broadcastBody(base({ ONE_LIST_MODE: "1" }), "nsw", fields);
const onQld = broadcastBody(base({ ONE_LIST_MODE: "1" }), "qld", fields);
assert(offBody.ok && offBody.body.segment_id === vicSegment && !("topic_id" in offBody.body), "flag off broadcast has no topic");
assert(onVic.ok && onVic.body.segment_id === ALL && onVic.body.topic_id === TOPICS.vic, "victoria topic");
assert(onNsw.body.topic_id === TOPICS.nsw && onQld.body.topic_id === TOPICS.qld, "each state has its own topic");
assert(onVic.body.topic_id !== onNsw.body.topic_id && onNsw.body.topic_id !== onQld.body.topic_id, "topics differ");
assert(!("send" in onVic.body), "broadcast body is a draft");
const refused = guardBroadcast({ segment_id: ALL, from: fields.from, subject: fields.subject, html: fields.html }, ALL);
assert(!refused.ok && refused.reason === "all_segment_requires_topic", "all segment without a topic is refused");
const saOff = broadcastBody(base(), "sa", fields);
assert(!saOff.ok && saOff.reason === "state_not_open", "SA broadcast stays closed in legacy mode");
const saOn = broadcastBody(base({ ONE_LIST_MODE: "1" }), "sa", fields);
assert(saOn.ok && saOn.body.segment_id === ALL && saOn.body.topic_id === "topic-sa", "SA broadcast uses the all segment and topic");
const saMissing = broadcastBody(base({ ONE_LIST_MODE: "1", RESEND_TOPIC_SA_ID: "" }), "sa", fields);
assert(!saMissing.ok && saMissing.reason === "state_not_open", "SA broadcast without a topic is refused");
const tasBare = broadcastBody({ ONE_LIST_MODE: "1", RESEND_TOPIC_TAS_ID: "topic-tas" }, "tas", fields);
assert(!tasBare.ok && tasBare.reason === "state_not_open", "TAS broadcast without the all segment is refused");
const tasOn = broadcastBody(base({ ONE_LIST_MODE: "1", RESEND_TOPIC_TAS_ID: "topic-tas" }), "tas", fields);
assert(tasOn.ok && tasOn.body.topic_id === "topic-tas" && tasOn.body.segment_id === ALL, "TAS broadcast uses the all segment and topic");
const qldBare = broadcastBody({ RESEND_SEGMENT_QLD_ID: "" }, "qld", fields);
assert(!qldBare.ok && qldBare.reason === "segment_unset", "queensland send never uses the deleted segment id");
const qldOff = broadcastBody(base({ RESEND_SEGMENT_QLD_ID: "none" }), "qld", fields);
assert(qldOff.ok && qldOff.body.segment_id === ALL && qldOff.body.topic_id === TOPICS.qld && qldOff.body.segment_id !== QLD_SEGMENT_ID, "queensland without its segment uses the all segment and topic");
const qldExplicit = broadcastBody({ RESEND_SEGMENT_QLD_ID: "qld-live" }, "qld", fields);
assert(qldExplicit.ok && qldExplicit.body.segment_id === "qld-live" && !("topic_id" in qldExplicit.body), "an explicit queensland segment is still honoured");
const qldNone = broadcastBody({ RESEND_SEGMENT_QLD_ID: "none" }, "qld", fields);
assert(!qldNone.ok && qldNone.reason === "segment_unset", "queensland none is not the fallback segment");

console.log("PARITY " + JSON.stringify({
  offVic: offBody.body,
  onVic: onVic.body,
  onNsw: onNsw.body,
  onQld: onQld.body,
  sa: saOn.body,
  saOff: saOff.reason,
  guard: refused.reason,
  qldOff: qldOff.body,
}));
console.log("one-list JS checks passed");
