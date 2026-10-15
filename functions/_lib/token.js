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

export async function makeToken(email, secret, ttlSec = 60 * 60 * 48) {
  const exp = Math.floor(Date.now() / 1000) + ttlSec;
  const payload = `${email.toLowerCase()}|${exp}`;
  return `${b64url(payload)}.${await hmacHex(secret, payload)}`;
}

export async function readToken(token, secret) {
  if (!token || !token.includes(".")) return null;
  const [body, sig] = token.split(".");
  let payload;
  try { payload = b64urlDecode(body); } catch { return null; }
  if (!sameHex(await hmacHex(secret, payload), sig)) return null;
  const cut = payload.lastIndexOf("|");
  if (cut < 1) return null;
  const email = payload.slice(0, cut);
  const exp = Number(payload.slice(cut + 1));
  if (!EMAIL_RE.test(email) || !Number.isFinite(exp) || exp < Date.now() / 1000) return null;
  return email;
}
