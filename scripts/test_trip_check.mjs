// Trip Check waitlist. No network: fetch is replaced before any handler runs.
import { readFileSync } from "node:fs";
import { makeToken, readToken } from "../functions/_lib/token.js";
import {
  CONFIRM_BODY, adminKeyOk, checkEmailText, clearRateLimits, confirmationMessage, countConfirmed,
  readTripCheck, signTripCheck, thanksText, tripSecret,
} from "../functions/_lib/trip-check.js";
import { onRequestPost } from "../functions/api/trip-check-waitlist.js";
import { onRequestGet as confirmGet } from "../functions/api/trip-check-confirm.js";
import { onRequestGet as countGet } from "../functions/api/trip-check-count.js";

const failures = [];
function check(cond, label) {
  if (!cond) failures.push(label);
}

globalThis.fetch = async () => {
  throw new Error("blocked network");
};

function memoryKv() {
  const store = new Map();
  return {
    store,
    async get(key) { return store.has(key) ? store.get(key) : null; },
    async put(key, value) { store.set(String(key), String(value)); },
    async list() {
      return { keys: [...store.keys()].map((name) => ({ name })), list_complete: true, cursor: "" };
    },
  };
}

const secret = "test-secret";
const email = "ada@example.com";

const token = await signTripCheck({ email: "Ada@Example.com", first_name: "José", states: ["tas", "qld", "vic", "wa", "act"] }, secret);
const parsed = await readTripCheck(token, secret);
check(!!parsed && parsed.email === email && parsed.first_name === "José" && parsed.states.join(",") === "vic,qld,tas", "sign and verify");
check(await readTripCheck(token, "other-secret") === null, "wrong secret");
check(await readTripCheck(token.slice(0, -1) + (token.endsWith("a") ? "b" : "a"), secret) === null, "bad token");
check(await readTripCheck(await signTripCheck({ email, first_name: "Ada", states: ["vic"] }, secret, -30), secret) === null, "expired token");
check(tripSecret({ CONFIRM_SECRET: secret }) === secret, "secret falls back");
check(tripSecret({ TRIPCHECK_SECRET: "dedicated", CONFIRM_SECRET: secret }) === "dedicated", "dedicated secret");
check(await readTripCheck(await signTripCheck({ email, first_name: "", states: [] }, secret), "dedicated") === null, "fallback secret does not verify a dedicated token");
check(!!(await readTripCheck(await signTripCheck({ email, first_name: "Ada", states: ["sa"] }, "dedicated"), "dedicated")), "dedicated secret verifies");

const digestToken = await makeToken(email, secret);
check(await readTripCheck(digestToken, secret) === null, "digest token rejected");
check(await readToken(token, secret) === null, "trip-check token is not a digest token");

const message = confirmationMessage("https://campconditions.au/api/trip-check-confirm?token=abc");
check(message.subject === "Confirm your Trip Check waitlist place", "subject");
check(message.text.includes(CONFIRM_BODY), "email body");
check(message.text.includes("Confirm I'm on the waitlist"), "email button");
check(message.text.includes("CampConditions.au\ncampconditions@outlook.com\n"), "email footer");
check(message.html.includes("Confirm I'm on the waitlist") && message.html.includes("campconditions@outlook.com"), "email html");

const src = [
  "functions/_lib/trip-check.js",
  "functions/api/trip-check-waitlist.js",
  "functions/api/trip-check-confirm.js",
  "functions/api/trip-check-count.js",
].map((file) => readFileSync(file, "utf8")).join("\n");
for (const bit of ["/contacts", "/segments", "/audiences", "/topics", "ONE_LIST_MODE", "RESEND_SEGMENT", "confirmSubscription"]) {
  if (src.includes(bit)) failures.push("source mentions " + bit);
}
check(src.includes("https://api.resend.com/emails"), "emails api");
check(!src.includes("functions/api/subscribe.js") && !src.includes("functions/api/confirm.js"), "does not import digest handlers");

const calls = [];
function installFetch() {
  calls.length = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init && init.method, body: init && init.body });
    if (String(url) !== "https://api.resend.com/emails" || !init || init.method !== "POST") {
      return new Response("no", { status: 500 });
    }
    return new Response(JSON.stringify({ id: "email_1" }), { status: 200, headers: { "content-type": "application/json" } });
  };
}

function baseEnv(kv) {
  return {
    RESEND_API_KEY: "test-not-a-real-key",
    FROM_EMAIL: "CampConditions.au <digest@mail.campconditions.au>",
    CONFIRM_SECRET: secret,
    SITE_URL: "https://campconditions.au",
    TRIPCHECK_KV: kv,
    TRIPCHECK_ADMIN_KEY: "admin-test-key",
    ONE_LIST_MODE: "1",
    RESEND_SEGMENT_ID: "should-not-be-used",
    RESEND_SEGMENT_ALL_ID: "should-not-be-used",
  };
}

async function postForm(env, fields, ip) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (Array.isArray(value)) value.forEach((item) => form.append(key, item));
    else form.set(key, String(value));
  }
  return onRequestPost({
    request: new Request("https://campconditions.au/api/trip-check-waitlist", {
      method: "POST",
      body: form,
      headers: { "cf-connecting-ip": ip },
    }),
    env,
  });
}

installFetch();
const kv = memoryKv();
const env = baseEnv(kv);

clearRateLimits();
const honey = await postForm(env, { email: "bot@example.com", consent: "yes", company: "Acme", states: ["vic"] }, "198.51.100.8");
const honeyHtml = await honey.text();
check(honey.status === 200 && honeyHtml.includes("Check your email") && honeyHtml.includes(checkEmailText("bot@example.com")), "honeypot copy");
check(calls.length === 0, "honeypot sent no email");

clearRateLimits();
calls.length = 0;
const missingKv = await postForm(baseEnv(undefined), { email, first_name: "Ada", consent: "yes", company: "" }, "198.51.100.9");
const missingHtml = await missingKv.text();
check(missingKv.status === 503 && missingHtml.includes("isn't available") && missingHtml.includes("Nobody has been charged."), "missing kv");
check(calls.length === 0, "missing kv sent no email");

clearRateLimits();
calls.length = 0;
const noConsent = await postForm(env, { email, consent: "", company: "", first_name: "Ada" }, "198.51.100.10");
check((await noConsent.text()).includes("Tick the box") && noConsent.status === 400, "consent");
check(calls.length === 0, "consent sent no email");

clearRateLimits();
const joined = await postForm(env, {
  email: "Ada@Example.com",
  first_name: "José",
  consent: "yes",
  company: "",
  states: ["tas", "qld", "nope"],
}, "198.51.100.11");
const joinedHtml = await joined.text();
check(joined.status === 200 && joinedHtml.includes("<h1>Check your email</h1>") && joinedHtml.includes(checkEmailText(email)), "check your email");
check(calls.length === 1 && calls[0].url === "https://api.resend.com/emails" && calls[0].method === "POST", "only the emails api");
const sent = JSON.parse(calls[0].body);
check(Object.keys(sent).sort().join(",") === "from,html,subject,text,to", "email payload fields");
check(sent.subject === "Confirm your Trip Check waitlist place" && sent.to[0] === email && sent.text.includes(CONFIRM_BODY), "sent copy");
check(!JSON.stringify(sent).includes("/contacts") && !JSON.stringify(sent).includes("segment"), "sent body has no list fields");
const link = (sent.text.match(/https:\/\/campconditions\.au\/api\/trip-check-confirm\?token=\S+/) || [])[0];
check(!!link, "confirm link");

calls.length = 0;
globalThis.fetch = async () => {
  calls.push("confirm");
  throw new Error("confirm must not call resend");
};
const bad = await confirmGet({ request: new Request("https://campconditions.au/api/trip-check-confirm?token=nope"), env });
const badHtml = await bad.text();
check(bad.status === 400 && badHtml.includes("Link not valid") && calls.length === 0, "bad token rejected");
check(kv.store.size === 0, "bad token stored nothing");

const unsaved = await confirmGet({ request: new Request(link), env: { ...env, TRIPCHECK_KV: undefined } });
const unsavedHtml = await unsaved.text();
check(unsaved.status === 503 && unsavedHtml.includes("couldn't save") && !unsavedHtml.includes("You&#39;re on the waitlist"), "confirm without kv");

const ok = await confirmGet({ request: new Request(link), env });
const okHtml = await ok.text();
check(ok.status === 200 && okHtml.includes("You&#39;re on the waitlist") && okHtml.includes(thanksText(email)), "thank you");
check(kv.store.size === 1 && kv.store.has(email), "stored once by lower-case email");
const first = JSON.parse(kv.store.get(email));
check(first.first_name === "José" && first.states.join(",") === "qld,tas" && first.email === email, "stored fields");
first.confirmed_at = "2020-01-01T00:00:00.000Z";
kv.store.set(email, JSON.stringify(first));
const againToken = await signTripCheck({ email, first_name: "Ada", states: ["nsw", "vic"] }, secret);
const again = await confirmGet({
  request: new Request("https://campconditions.au/api/trip-check-confirm?token=" + encodeURIComponent(againToken)),
  env,
});
check(again.status === 200, "second confirm");
check(kv.store.size === 1, "duplicate confirm counted once");
const second = JSON.parse(kv.store.get(email));
check(second.confirmed_at === "2020-01-01T00:00:00.000Z" && second.first_name === "Ada" && second.states.join(",") === "vic,nsw", "re-join updates the same record");

const otherToken = await signTripCheck({ email: "Bob@Example.com", first_name: "", states: ["sa"] }, secret);
const other = await confirmGet({
  request: new Request("https://campconditions.au/api/trip-check-confirm?token=" + encodeURIComponent(otherToken)),
  env,
});
check(other.status === 200 && kv.store.size === 2, "second address");

const counted = await countGet({
  request: new Request("https://campconditions.au/api/trip-check-count", { headers: { "x-tripcheck-key": "admin-test-key" } }),
  env,
});
const countedBody = await counted.text();
check(counted.status === 200 && countedBody === '{"confirmed":2}', "count " + countedBody);
check(!countedBody.includes("@") && !countedBody.includes("Ada") && !countedBody.includes("José"), "count has no addresses");

const denied = await countGet({
  request: new Request("https://campconditions.au/api/trip-check-count", { headers: { "x-tripcheck-key": "nope" } }),
  env,
});
const deniedBody = await denied.text();
check(denied.status === 401 && deniedBody === '{"error":"unauthorized"}' && !deniedBody.includes("@"), "bad admin key");
const closed = await countGet({
  request: new Request("https://campconditions.au/api/trip-check-count", { headers: { "x-tripcheck-key": "admin-test-key" } }),
  env: { ...env, TRIPCHECK_ADMIN_KEY: "" },
});
check(closed.status === 401, "admin key unset");
const noStore = await countGet({
  request: new Request("https://campconditions.au/api/trip-check-count", { headers: { "x-tripcheck-key": "admin-test-key" } }),
  env: { ...env, TRIPCHECK_KV: undefined },
});
const noStoreBody = await noStore.text();
check(noStore.status === 503 && noStoreBody === '{"error":"unavailable"}' && !noStoreBody.includes("@"), "count without kv");
check(await adminKeyOk(env, new Request("https://campconditions.au/api/trip-check-count")) === false, "missing header");

const paging = {
  async list(opts = {}) {
    if (!opts.cursor) return { keys: [{ name: email }], list_complete: false, cursor: "next" };
    return { keys: [{ name: "bob@example.com" }, { name: "rate-limit" }], list_complete: true, cursor: "" };
  },
};
check(await countConfirmed(paging) === 2, "paged count");

clearRateLimits();
installFetch();
let limited = null;
for (let i = 0; i < 6; i++) {
  limited = await postForm(env, { email: "limit@example.com", consent: "yes", company: "" }, "203.0.113.4");
}
const limitedHtml = await limited.text();
check(limited.status === 429 && limitedHtml.includes("Please wait a few minutes") && calls.length === 5, "rate limit");

if (failures.length) {
  for (const label of failures) console.error("FAIL", label);
  process.exit(1);
}
console.log("trip-check ok");
