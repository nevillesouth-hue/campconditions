import { confirmSubscription, QLD_SEGMENT_ID } from "../functions/api/confirm.js";
import { listEnrolment, signupChoice } from "../functions/api/subscribe.js";
import { unsubscribeContact } from "../functions/api/unsubscribe.js";
import { broadcastBody, guardBroadcast, oneListMode, topicPlan } from "../functions/_lib/token.js";

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

// Flag off ignores topic ids and the all-subscribers segment.
assert(oneListMode(base()) === false, "flag defaults off");
assert(oneListMode(base({ ONE_LIST_MODE: "0" })) === false, "zero is off");
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(base(), email, fetch);
  assert(result.ok, "flag off confirms");
  assert(calls.length === 3, "flag off is create, the victoria segment, then the victoria topic");
  assert(calls[1].url.endsWith("/segments/" + vicSegment), "flag off uses the victoria segment");
  assert(calls[2].method === "PATCH" && calls[2].url.endsWith("/contacts/reader%40example.com/topics"), "flag off opts in to the topic");
  assert(JSON.stringify(jsonBody(calls[2])) === JSON.stringify([{ id: TOPICS.vic, subscription: "opt_in" }]), "flag off opts in to the victoria topic only");
  assert(calls.every((call) => !call.url.includes(ALL)), "flag off does not use the all segment");
  assert(!jsonBody(calls[0]).topics && !jsonBody(calls[0]).segments, "flag off create has no topics");
}

// Flag off: a confirmed sign-up opts in to its chosen state's topic only (19 Nov fix).
{
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(base(), email, fetch, ["nsw"], true);
  assert(result.ok, "flag off nsw confirms");
  const patches = calls.filter((call) => call.url.endsWith("/topics"));
  assert(patches.length === 1 && JSON.stringify(jsonBody(patches[0])) === JSON.stringify([{ id: TOPICS.nsw, subscription: "opt_in" }]), "flag off nsw opts in to nsw only");
  assert(calls.every((call) => !String(call.body || "").includes("opt_out")), "flag off never opts out");
}
{
  // No topic env vars: the built-in live topic ids are used, and held states get none.
  const env = base();
  for (const key of ["RESEND_TOPIC_VIC_ID", "RESEND_TOPIC_NSW_ID", "RESEND_TOPIC_QLD_ID", "RESEND_TOPIC_SA_ID"]) delete env[key];
  const { calls, fetch } = recorder(() => okResponse());
  const result = await confirmSubscription(env, email, fetch, ["vic", "qld", "sa", "act"], true);
  assert(result.ok, "flag off without topic env confirms");
  const patch = calls.find((call) => call.url.endsWith("/topics"));
  assert(patch && JSON.stringify(jsonBody(patch)) === JSON.stringify([{ id: "7911f74b-59eb-4c9c-ba63-e6c8f344d6f7", subscription: "opt_in" }, { id: "268e2f38-88e7-4d84-8e35-b6a05823100c", subscription: "opt_in" }]), "built-in topic ids for vic and qld only");
}
{
  // Existing contact (409) adding QLD: opts in to QLD only and never touches VIC or NSW.
  const { calls, fetch } = recorder((call) => {
    if (call.url.endsWith("/contacts") && call.method === "POST") return new Response("{}", { status: 409 });
    if (call.method === "GET") return new Response(JSON.stringify({ properties: { states: "vic,nsw" } }), { status: 200 });
    return okResponse(200);
  });
  const result = await confirmSubscription(base(), email, fetch, ["qld"], true);
  assert(result.ok, "flag off 409 confirms");
  const patch = calls.find((call) => call.url.endsWith("/topics"));
  assert(patch && JSON.stringify(jsonBody(patch)) === JSON.stringify([{ id: TOPICS.qld, subscription: "opt_in" }]), "409 opts in to the new state only");
}
{
  // A failed topic write is reported, so the reader can retry the link.
  const { fetch } = recorder((call) => (call.url.endsWith("/topics") ? new Response("{}", { status: 500 }) : okResponse()));
  const result = await confirmSubscription(base(), email, fetch, ["nsw"], true);
  assert(!result.ok && result.status === 500, "topic failure is not reported as confirmed");
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
  const opted = jsonBody(topicCall).topics.map((topic) => topic.subscription + ":" + topic.id).sort();
  assert(opted.join(",") === ["opt_out:" + TOPICS.nsw, "opt_out:" + TOPICS.qld, "opt_out:" + TOPICS.vic].sort().join(","), "all state topics opted out");
  assert(!on.calls.some((call) => call.url.includes("sa-segment") || call.url.includes("topic-sa")), "unsubscribe does not touch SA");
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
const sa = broadcastBody(base({ ONE_LIST_MODE: "1" }), "sa", fields);
assert(!sa.ok && sa.reason === "state_not_open", "no SA broadcast");
const qldOff = broadcastBody({ RESEND_SEGMENT_QLD_ID: "" }, "qld", fields);
assert(qldOff.ok && qldOff.body.segment_id === QLD_SEGMENT_ID && !("topic_id" in qldOff.body), "queensland fallback segment");

console.log("PARITY " + JSON.stringify({
  offVic: offBody.body,
  onVic: onVic.body,
  onNsw: onNsw.body,
  onQld: onQld.body,
  sa: sa.reason,
  guard: refused.reason,
  qldOff: qldOff.body,
}));
console.log("one-list JS checks passed");
