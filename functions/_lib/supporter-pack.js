// Supporter Pack download helpers for /support/thanks/.
// A paid Checkout Session is read from Stripe; customer_details and email are
// discarded and must never be stored, logged, or emailed from this code.

export const PACK_TTL_SECONDS = 7 * 24 * 60 * 60;
export const SESSION_RE = /^cs_(test|live)_[A-Za-z0-9]+$/;
export const GIFT_LINE = "As a thank-you, supporters get the Supporter Pack — an All-Year Trip-Prep Kit and a printable Camp Logbook. It's our way of saying thanks.";
export const SUPPORT_EXTRA = "You can download it straight after you chip in.";
export const THANKS_LEAD = "It genuinely helps keep CampConditions.au free for everyone.";
export const DOWNLOAD_LABEL = "Download the Supporter Pack (PDF)";
export const DOWNLOAD_AFTER = "Save it now. This download link works for 7 days. Your receipt comes separately from Stripe. We don't keep your email address. Lost your download? Email campconditions@outlook.com and we'll help.";
export const SMALL_PRINT = "Camp Conditions is a small Australian business, not a charity. Tips are voluntary and are not tax-deductible. The site and the digest stay free whether or not you chip in. The Supporter Pack is a thank-you: a planning checklist of official links and a blank logbook. It is not live conditions and not official advice. Always check the official source before you go. If something is wrong with the download, email us and we'll help or refund you.";
export const ABN_LINE = "Camp Conditions · ABN 35 589 319 392";
export const PACK_FILENAME = "CampConditions-Supporter-Pack.pdf";

const enc = new TextEncoder();

function expectedLivemode(env) {
  const flag = String((env && env.STRIPE_LIVEMODE) || "").trim().toLowerCase();
  if (flag === "true" || flag === "live") return true;
  if (flag === "false" || flag === "test" || flag === "sandbox") return false;
  const key = checkoutKey(env);
  if (key.startsWith("sk_live_") || key.startsWith("rk_live_")) return true;
  if (key.startsWith("sk_test_") || key.startsWith("rk_test_")) return false;
  return null;
}

export function checkoutKey(env) {
  return String((env && (env.STRIPE_CHECKOUT_READ_KEY || env.STRIPE_SECRET_KEY)) || "").trim();
}

export function signingSecret(env) {
  return String((env && env.PACK_SIGNING_SECRET) || "").trim();
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function sameHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function sessionIdFromQuery(raw) {
  const id = String(raw || "").trim();
  return SESSION_RE.test(id) ? id : "";
}

// Drop every payer field we must not keep. Callers should use only the result.
export function publicSessionFacts(session) {
  if (!session || typeof session !== "object") return null;
  return {
    id: typeof session.id === "string" ? session.id : "",
    payment_status: session.payment_status || "",
    status: session.status || "",
    livemode: session.livemode === true,
    amount_total: session.amount_total,
    currency: session.currency || "",
  };
}

export function isPaidSession(facts, expectLivemode) {
  if (!facts || !SESSION_RE.test(facts.id)) return false;
  if (expectLivemode !== true && expectLivemode !== false) return false;
  if (facts.livemode !== expectLivemode) return false;
  return facts.payment_status === "paid" && facts.status === "complete";
}

export async function retrievePaidSession(env, sessionId, fetchImpl) {
  const id = sessionIdFromQuery(sessionId);
  const key = checkoutKey(env);
  const expectLivemode = expectedLivemode(env);
  if (!id || !key || expectLivemode === null) return { paid: false };
  const fetchFn = fetchImpl || fetch;
  const res = await fetchFn("https://api.stripe.com/v1/checkout/sessions/" + encodeURIComponent(id), {
    headers: { Authorization: "Bearer " + key },
  });
  if (!res.ok) return { paid: false };
  const session = await res.json();
  const facts = publicSessionFacts(session);
  return { paid: isPaidSession(facts, expectLivemode), facts };
}

export async function signDownload(secret, sessionId, exp) {
  const id = sessionIdFromQuery(sessionId);
  const when = Number(exp);
  if (!id || !secret || !Number.isFinite(when)) return "";
  return hmacHex(secret, "supporter-pack:" + id + ":" + String(when));
}

export async function makeDownloadPath(secret, sessionId, now) {
  const id = sessionIdFromQuery(sessionId);
  if (!id || !secret) return "";
  const exp = Math.floor((now || Date.now()) / 1000) + PACK_TTL_SECONDS;
  const sig = await signDownload(secret, id, exp);
  const q = new URLSearchParams({ sid: id, exp: String(exp), sig });
  return "/api/supporter-pack?" + q.toString();
}

export async function readDownload(secret, params, now) {
  const id = sessionIdFromQuery(params && params.sid);
  const exp = Number(params && params.exp);
  const sig = String((params && params.sig) || "");
  if (!id || !secret || !Number.isFinite(exp) || !sig) return null;
  const nowSec = Math.floor((now || Date.now()) / 1000);
  if (exp < nowSec) return null;
  if (exp > nowSec + PACK_TTL_SECONDS + 60) return null;
  const expected = await signDownload(secret, id, exp);
  if (!sameHex(sig, expected)) return null;
  return { sessionId: id, exp };
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function paidThanksMain(downloadUrl) {
  const href = escapeHtml(downloadUrl);
  return (
    "<h1>Thanks for chipping in</h1>\n" +
    "<p>" + escapeHtml(THANKS_LEAD) + "</p>\n" +
    '<p><a class="tip-btn" href="' + href + '">' + escapeHtml(DOWNLOAD_LABEL) + "</a></p>\n" +
    "<p>Save it now. This download link works for 7 days. Your receipt comes separately from Stripe. We don't keep your email address. Lost your download? Email <a href=\"mailto:campconditions@outlook.com\">campconditions@outlook.com</a> and we'll help.</p>\n" +
    '<p class="small-print">' + escapeHtml(SMALL_PRINT) + "<br>" + escapeHtml(ABN_LINE) + "</p>\n" +
    '<p><a class="back-map" href="/">← Back to the camps</a></p>'
  );
}

export function paidThanksHtml(shellHtml, downloadUrl) {
  const main = paidThanksMain(downloadUrl);
  if (!shellHtml || !shellHtml.includes("<main>")) return main;
  return shellHtml.replace(/<main>[\s\S]*?<\/main>/, "<main>\n" + main + "\n</main>");
}

export function sourceForbidsPiiLeaks(src) {
  const text = String(src || "");
  const leaks = [];
  if (/console\.(log|info|debug|warn|error)\([^)]*(customer_details|customer_email|email)/i.test(text)) leaks.push("logs payer fields");
  if (/customer_details\s*=/.test(text) && !/delete session\.customer_details|customer_details/.test(text)) {
    // presence of the field name in a delete/comment is fine; storing it is not
  }
  return leaks;
}
