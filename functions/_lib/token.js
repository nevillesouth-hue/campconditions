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

export const STATE_ORDER = ["vic", "nsw"];
const STATE_LABELS = { vic: "Victoria", nsw: "New South Wales" };

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
