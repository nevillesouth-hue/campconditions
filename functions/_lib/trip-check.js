// Trip Check waitlist. Signed confirmation links only.
// Pending sign-ups are not stored. A confirmed address is written to TRIPCHECK_KV.
// This file does not import the digest token helpers, and it does not read the one-list flag.
// Mail is sent only by functions/api/trip-check-waitlist.js, and only to the transactional send API.

export const EMAIL_RE = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;
export const TRIP_STATES = ["vic", "nsw", "qld", "sa", "tas"];
export const ADMIN_HEADER = "x-tripcheck-key";
export const TOKEN_TTL_SEC = 60 * 60 * 48;
const PURPOSE = "trip-check";

const enc = new TextEncoder();
const hits = new Map();
const WINDOW_MS = 10 * 60 * 1000;
const MAX_POSTS = 5;

export function clearRateLimits() {
  hits.clear();
}

export function tripSecret(env) {
  const dedicated = String((env && env.TRIPCHECK_SECRET) || "").trim();
  if (dedicated) return dedicated;
  return String((env && env.CONFIRM_SECRET) || "").trim();
}

export function kvReady(env) {
  const kv = env && env.TRIPCHECK_KV;
  return !!(kv && typeof kv.get === "function" && typeof kv.put === "function" && typeof kv.list === "function");
}

export function mailReady(env) {
  return !!(env && String(env.RESEND_API_KEY || "").trim() && String(env.FROM_EMAIL || "").trim() && tripSecret(env));
}

export function cleanName(raw) {
  return String(raw || "").replace(/[\u0000-\u001f\u007f]/g, "").replace(/\s+/g, " ").trim().slice(0, 80);
}

export function cleanStates(raw) {
  const list = Array.isArray(raw) ? raw : String(raw == null ? "" : raw).split(/[,\s]+/);
  const have = new Set();
  for (const item of list) {
    const slug = String(item || "").trim().toLowerCase();
    if (TRIP_STATES.includes(slug)) have.add(slug);
  }
  return TRIP_STATES.filter((slug) => have.has(slug));
}

export function normalEmail(raw) {
  return String(raw || "").trim().toLowerCase();
}

function b64urlEncode(str) {
  const bytes = enc.encode(str);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function b64urlDecode(s) {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const bin = atob(String(s || "").replace(/-/g, "+").replace(/_/g, "/") + pad);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
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

export async function signTripCheck(fields, secret, ttlSec = TOKEN_TTL_SEC) {
  const email = normalEmail(fields && fields.email);
  if (!EMAIL_RE.test(email) || email.length > 254 || !secret) return "";
  const exp = Math.floor(Date.now() / 1000) + Number(ttlSec);
  const payload = JSON.stringify({
    purpose: PURPOSE,
    email,
    first_name: cleanName(fields && fields.first_name),
    states: cleanStates(fields && fields.states),
    exp,
  });
  return `${b64urlEncode(payload)}.${await hmacHex(secret, payload)}`;
}

export async function readTripCheck(token, secret) {
  if (!token || !secret || typeof token !== "string" || !token.includes(".")) return null;
  const dot = token.indexOf(".");
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  if (!sig || sig.includes(".")) return null;
  let payload;
  try { payload = b64urlDecode(body); } catch { return null; }
  if (!sameHex(await hmacHex(secret, payload), sig)) return null;
  let data;
  try { data = JSON.parse(payload); } catch { return null; }
  if (!data || data.purpose !== PURPOSE) return null;
  const email = normalEmail(data.email);
  const exp = Number(data.exp);
  if (!EMAIL_RE.test(email) || email.length > 254 || !Number.isFinite(exp) || exp < Date.now() / 1000) return null;
  if (typeof data.first_name !== "string" || !Array.isArray(data.states)) return null;
  const states = cleanStates(data.states);
  if (states.join(",") !== data.states.join(",")) return null;
  const first_name = cleanName(data.first_name);
  if (first_name !== data.first_name) return null;
  return { email, first_name, states, exp };
}

export function clientIp(request) {
  return String((request.headers && request.headers.get("cf-connecting-ip")) || "").trim() || "unknown";
}

export function rateLimited(ip, now = Date.now()) {
  if (hits.size > 5000) hits.clear();
  const key = String(ip || "unknown");
  const recent = (hits.get(key) || []).filter((t) => now - t < WINDOW_MS);
  if (recent.length >= MAX_POSTS) {
    hits.set(key, recent);
    return true;
  }
  recent.push(now);
  hits.set(key, recent);
  return false;
}

export function siteOrigin(env, request) {
  const configured = String((env && env.SITE_URL) || "").trim().replace(/\/$/, "");
  if (configured) return configured;
  try { return new URL(request.url).origin; } catch { return "https://campconditions.au"; }
}

function esc(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export const CONFIRM_SUBJECT = "Confirm your Trip Check waitlist place";
export const CONFIRM_BODY = "Thanks for your interest in Trip Check from CampConditions.au. Click below to confirm your place on the waitlist. This is a waitlist only: nobody is charged, and confirming does not add you to the weekly digest. If you didn't ask for this, you can ignore this email.";

export function confirmationMessage(link) {
  const safe = esc(link);
  const button = `<a href="${safe}" style="display:inline-block;background:#2f5d3a;color:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;line-height:20px;text-decoration:none;padding:12px 22px;border-radius:8px;">Confirm I'm on the waitlist</a>`;
  const html = `<!DOCTYPE html><html lang="en-AU"><head><meta charset="utf-8"><title>${esc(CONFIRM_SUBJECT)}</title></head>
<body style="margin:0;background:#fbfaf6;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;padding:8px 24px 24px;">
<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;color:#222222;padding-top:16px;">${esc(CONFIRM_BODY)}</td></tr>
<tr><td style="padding-top:16px;">${button}</td></tr>
<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#666666;padding-top:12px;">If the button does not work, copy this link into your browser:<br><a href="${safe}" style="color:#2f5d3a;word-break:break-all;">${safe}</a></td></tr>
<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#666666;padding-top:24px;">CampConditions.au<br>campconditions@outlook.com</td></tr>
</table></td></tr></table></body></html>`;
  const text = `${CONFIRM_BODY}\n\nConfirm I'm on the waitlist:\n${link}\n\nCampConditions.au\ncampconditions@outlook.com\n`;
  return { html, text, subject: CONFIRM_SUBJECT };
}

export function checkEmailText(email) {
  return `We've sent a confirmation link to ${email}. You won't be added to the Trip Check waitlist until you click it. Nobody has been charged.`;
}

export function thanksText(email) {
  return `Nobody has been charged. We'll email you at ${email} if we go ahead. The weekly digest is separate, and you have not been added to it by joining this waitlist. If you already get the Thursday digest, that stays as it is.`;
}

export async function readWaitlist(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const body = await request.json().catch(() => ({}));
    const states = body.states;
    return {
      email: String(body.email || "").trim(),
      first_name: String(body.first_name || "").trim(),
      states: Array.isArray(states) ? states : (states ? String(states).split(",") : []),
      consent: String(body.consent || ""),
      company: String(body.company || ""),
    };
  }
  const form = await request.formData();
  return {
    email: String(form.get("email") || "").trim(),
    first_name: String(form.get("first_name") || "").trim(),
    states: form.getAll("states"),
    consent: String(form.get("consent") || ""),
    company: String(form.get("company") || ""),
  };
}

export async function saveConfirmed(kv, record) {
  const key = normalEmail(record.email);
  const existingRaw = await kv.get(key);
  let confirmed_at = record.confirmed_at;
  let first_name = cleanName(record.first_name);
  let states = cleanStates(record.states);
  if (existingRaw) {
    try {
      const existing = JSON.parse(existingRaw);
      if (existing && typeof existing === "object") {
        if (existing.confirmed_at) confirmed_at = existing.confirmed_at;
        if (!first_name && existing.first_name) first_name = cleanName(existing.first_name);
        if (!states.length && Array.isArray(existing.states)) states = cleanStates(existing.states);
      }
    } catch { /* a broken value is replaced by this confirmation */ }
  }
  const stored = { email: key, first_name, states, confirmed_at };
  await kv.put(key, JSON.stringify(stored));
  return stored;
}

export async function countConfirmed(kv) {
  let confirmed = 0;
  let cursor = "";
  for (let pageNo = 0; pageNo < 100; pageNo++) {
    const page = await kv.list(cursor ? { cursor } : {});
    const keys = page && Array.isArray(page.keys) ? page.keys : [];
    for (const key of keys) {
      const name = String((key && key.name) || "");
      if (EMAIL_RE.test(name)) confirmed += 1;
    }
    if (!page || page.list_complete || !page.cursor) break;
    cursor = page.cursor;
  }
  return confirmed;
}

export async function adminKeyOk(env, request) {
  const expected = String((env && env.TRIPCHECK_ADMIN_KEY) || "").trim();
  if (!expected) return false;
  const got = String(request.headers.get(ADMIN_HEADER) || "");
  if (!got || got.length > 200) return false;
  const [a, b] = await Promise.all([hmacHex("trip-check-admin", expected), hmacHex("trip-check-admin", got)]);
  return sameHex(a, b);
}
