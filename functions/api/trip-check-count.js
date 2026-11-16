// Confirmed Trip Check waitlist count. Header X-Tripcheck-Key must match TRIPCHECK_ADMIN_KEY.
// The body is {"confirmed":N}. Addresses are not included.
import { adminKeyOk, countConfirmed, kvReady } from "../_lib/trip-check.js";

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export async function onRequestGet({ request, env }) {
  try {
    if (!(await adminKeyOk(env, request))) return json({ error: "unauthorized" }, 401);
    if (!kvReady(env)) return json({ error: "unavailable" }, 503);
    const confirmed = await countConfirmed(env.TRIPCHECK_KV);
    return json({ confirmed }, 200);
  } catch {
    return json({ error: "unavailable" }, 503);
  }
}
