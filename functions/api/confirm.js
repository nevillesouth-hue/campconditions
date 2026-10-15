// Double opt-in, step 2. Adds the address to the Resend segment only after the signed link is clicked.
// Returns 503 "Sign-ups open soon" unless RESEND_API_KEY, CONFIRM_SECRET, FROM_EMAIL, SITE_URL and RESEND_SEGMENT_ID are all set.
import { readToken, signupsReady } from "../_lib/token.js";

const page = (title, msg, status = 200) =>
  new Response(
    `<!doctype html><html lang="en-AU"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><p>${msg}</p><p><a href="/">Back to CampConditions.au</a></p></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

async function resend(env, path, method, body) {
  const res = await fetch(`https://api.resend.com${path}`, {
    method,
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export async function onRequestGet({ request, env }) {
  if (!signupsReady(env)) return soon();
  const token = new URL(request.url).searchParams.get("token") || "";
  const email = await readToken(token, env.CONFIRM_SECRET);
  if (!email) return page("Link not valid", "That confirmation link is invalid or has expired. Please sign up again.", 400);
  const created = await resend(env, "/contacts", "POST", {
    email,
    unsubscribed: false,
    segments: [{ id: env.RESEND_SEGMENT_ID }],
  });
  if (!created.ok && created.status !== 409) {
    return page("Could not confirm", "We couldn't add you just now. Please try the link again later.", 502);
  }
  if (created.status === 409) {
    const existing = await resend(env, `/contacts/${encodeURIComponent(email)}`, "GET");
    const id = existing.data && existing.data.id;
    if (!existing.ok || !id) return page("Could not confirm", "We couldn't add you just now. Please try the link again later.", 502);
    const added = await resend(env, `/contacts/${encodeURIComponent(id)}/segments`, "POST", { segment_id: env.RESEND_SEGMENT_ID });
    if (!added.ok && added.status !== 409) return page("Could not confirm", "We couldn't add you just now. Please try the link again later.", 502);
  }
  return page("You're confirmed", "Thanks — you're on the free weekly Victoria digest. The first one goes out on Thursday.");
}
