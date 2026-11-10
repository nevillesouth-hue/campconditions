// Signed, expiring confirmation tokens. Web Crypto only (Cloudflare Workers).
export const EMAIL_RE = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;
export const REQUIRED_ENV = ["RESEND_API_KEY", "CONFIRM_SECRET", "FROM_EMAIL", "SITE_URL", "RESEND_SEGMENT_ID"];

export function signupsReady(env) {
  return REQUIRED_ENV.every((key) => env && String(env[key] || "").trim());
}

const enc = new TextEncoder();

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function b64url(s) {
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function b64urlDecode(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  return atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
}

function sameHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export const STATE_ORDER = ["vic", "nsw", "qld"];
const STATE_LABELS = { vic: "Victoria", nsw: "New South Wales", qld: "Queensland" };

// Held until inventory, licence, fire, digest and regression gates pass.
// chosenStates ignores these, so a crafted body cannot enrol them.
// Creating RESEND_SEGMENT_ACT_ID or RESEND_SEGMENT_SA_ID must not change that.
// Activation has to remove the slug here in the same change that opens the gate.
export const HELD_SIGNUP_STATES = ["act", "sa"];
// Region flags for signup and the digest send. SA stays false until the launch gate passes.
export const REGION_ENABLED = { act: false, sa: false };

export function saDigestSend(env, regionEnabled = REGION_ENABLED.sa) {
  const segmentId = String((env && env.RESEND_SEGMENT_SA_ID) || "").trim();
  if (!regionEnabled) return { send: false, reason: "region_disabled", segmentId: "", calledResend: false };
  if (!segmentId) return { send: false, reason: "segment_unset", segmentId: "", calledResend: false };
  return { send: true, reason: "", segmentId, calledResend: false };
}
export const HELD_SEGMENT_ENV = {
  act: "RESEND_SEGMENT_ACT_ID",
  sa: "RESEND_SEGMENT_SA_ID",
};

// Preview only. Names the env var a future activation would need and does not read it.
export function heldSignupPreview(slug) {
  const key = HELD_SEGMENT_ENV[slug];
  if (!key) return null;
  return { slug, enrol: false, send: false, readsSegmentEnv: false, requiredEnv: key };
}

export function heldSignupStates(raw) {
  const list = Array.isArray(raw) ? raw : String(raw == null ? "" : raw).split(/[,\s]+/);
  const have = new Set();
  for (const item of list) {
    const slug = String(item || "").trim().toLowerCase();
    if (HELD_SIGNUP_STATES.includes(slug)) have.add(slug);
  }
  return HELD_SIGNUP_STATES.filter((slug) => have.has(slug));
}

export function chosenStates(raw) {
  const list = Array.isArray(raw) ? raw : String(raw == null ? "" : raw).split(/[,\s]+/);
  const have = new Set();
  for (const item of list) {
    const slug = String(item || "").trim().toLowerCase();
    if (STATE_ORDER.includes(slug)) have.add(slug);
  }
  return STATE_ORDER.filter((slug) => have.has(slug));
}

export function statePhrase(states) {
  const labels = (states && states.length ? states : ["vic"]).map((slug) => STATE_LABELS[slug] || slug);
  if (labels.length <= 1) return labels[0] || "Victoria";
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

// ONE_LIST_MODE is off unless it is exactly one of these. Anything else, including
// an empty value, keeps today's per-state segments.
export function flagOn(value) {
  const raw = String(value == null ? "" : value).trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "on" || raw === "yes";
}

export function oneListMode(env) {
  return flagOn(env && env.ONE_LIST_MODE);
}

// While the all-subscribers segment is being proved, confirm also writes the old
// per-state segments. Off unless set. Ignored while ONE_LIST_MODE is off.
export function legacySegmentWrite(env) {
  return flagOn(env && env.SIGNUP_WRITE_LEGACY_SEGMENTS);
}

// Live state topics only. There is no SA topic: SA sign-up stays closed until Nev says otherwise.
export const TOPIC_ENV = {
  vic: "RESEND_TOPIC_VIC_ID",
  nsw: "RESEND_TOPIC_NSW_ID",
  qld: "RESEND_TOPIC_QLD_ID",
};

// Same id confirm.js uses when RESEND_SEGMENT_QLD_ID is unset. A segment id is not a secret.
const QLD_SEGMENT_FALLBACK = "2488900b-f026-44e8-9d74-098d38ef3468";
const LEGACY_SEGMENT_ENV = {
  vic: "RESEND_SEGMENT_ID",
  nsw: "RESEND_SEGMENT_NSW_ID",
  qld: "RESEND_SEGMENT_QLD_ID",
};

export function topicId(env, slug) {
  const key = TOPIC_ENV[slug];
  return key ? String((env && env[key]) || "").trim() : "";
}

export function allSegmentId(env) {
  return String((env && env.RESEND_SEGMENT_ALL_ID) || "").trim();
}

// Opt-in topics for the states this confirmation is allowed to enrol.
// Held states are already dropped by chosenStates, so they never get a topic.
export function topicPlan(env, states) {
  const topics = [];
  const missing = [];
  for (const slug of chosenStates(states)) {
    const id = topicId(env, slug);
    if (!id) missing.push(slug);
    else topics.push({ id, subscription: "opt_in", slug });
  }
  return { topics, missing };
}

export function broadcastTarget(env, slug) {
  const state = String(slug || "").trim().toLowerCase();
  if (!STATE_ORDER.includes(state)) {
    return { ok: false, reason: "state_not_open", segmentId: "", topicId: "" };
  }
  if (!oneListMode(env)) {
    let segmentId = String((env && env[LEGACY_SEGMENT_ENV[state]]) || "").trim();
    if (state === "qld" && !segmentId) segmentId = QLD_SEGMENT_FALLBACK;
    if (!segmentId) return { ok: false, reason: "segment_unset", segmentId: "", topicId: "" };
    return { ok: true, reason: "", segmentId, topicId: "", oneList: false };
  }
  const segmentId = allSegmentId(env);
  const id = topicId(env, state);
  if (!segmentId || !id) return { ok: false, reason: "missing_one_list_ids", segmentId, topicId: id };
  return { ok: true, reason: "", segmentId, topicId: id, oneList: true };
}

// A broadcast to the all-subscribers segment with no topic would mail every state.
export function guardBroadcast(body, allId) {
  const segment = String((body && (body.segment_id || body.segmentId)) || "");
  const topic = String((body && (body.topic_id || body.topicId)) || "").trim();
  const allSegment = String(allId || "").trim();
  if (allSegment && segment === allSegment && !topic) {
    return { ok: false, reason: "all_segment_requires_topic" };
  }
  return { ok: true, reason: "" };
}

// Draft broadcast fields. This does not call Resend. topic_id is set only in one-list mode.
export function broadcastBody(env, slug, fields) {
  const found = broadcastTarget(env, slug);
  if (!found.ok) return { ok: false, reason: found.reason, body: null };
  const body = {
    from: fields.from,
    subject: fields.subject,
    segment_id: found.segmentId,
    html: fields.html,
  };
  if (fields.text != null) body.text = fields.text;
  if (found.topicId) body.topic_id = found.topicId;
  const guard = guardBroadcast(body, allSegmentId(env));
  if (!guard.ok) return { ok: false, reason: guard.reason, body: null };
  return { ok: true, reason: "", body };
}

export async function makeToken(email, secret, ttlSec = 60 * 60 * 48, states) {
  const exp = Math.floor(Date.now() / 1000) + ttlSec;
  const normal = email.toLowerCase();
  let payload = `${normal}|${exp}`;
  if (arguments.length >= 4) {
    const picked = chosenStates(states);
    if (!picked.length) return "";
    payload = `${normal}|${exp}|${picked.join(",")}`;
  }
  return `${b64url(payload)}.${await hmacHex(secret, payload)}`;
}

export async function makeUnsubscribeToken(email, secret) {
  return hmacHex(secret, `unsubscribe\n${String(email || "").trim().toLowerCase()}`);
}

export function unsubscribeLink(site, email, token) {
  const base = String(site || "").replace(/\/$/, "");
  return `${base}/api/unsubscribe?e=${encodeURIComponent(String(email || "").trim().toLowerCase())}&t=${token}`;
}

export async function unsubscribeTokenMatches(email, token, secret) {
  const normal = String(email || "").trim().toLowerCase();
  if (!EMAIL_RE.test(normal) || typeof token !== "string" || !token || !secret) return false;
  return sameHex(await makeUnsubscribeToken(normal, secret), token.trim());
}

export function listUnsubscribeHeaders(url) {
  return {
    "List-Unsubscribe": `<${url}>`,
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
  };
}

export async function readToken(token, secret) {
  if (!token || !token.includes(".")) return null;
  const dot = token.indexOf(".");
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  if (!sig || sig.includes(".")) return null;
  let payload;
  try { payload = b64urlDecode(body); } catch { return null; }
  if (!sameHex(await hmacHex(secret, payload), sig)) return null;
  const parts = payload.split("|");
  if (parts.length !== 2 && parts.length !== 3) return null;
  const email = parts[0];
  const exp = Number(parts[1]);
  if (!EMAIL_RE.test(email) || !Number.isFinite(exp) || exp < Date.now() / 1000) return null;
  if (parts.length === 2) return { email, states: ["vic"], explicit: false };
  const states = chosenStates(parts[2]);
  if (!states.length || states.join(",") !== parts[2]) return null;
  return { email, states, explicit: true };
}
