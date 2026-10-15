// Double opt-in, step 1. Sends a confirmation email only; nobody is added to the list until they click the link.
// Env (Cloudflare Pages > Settings > Variables & Secrets), all required or this returns 503:
//   RESEND_API_KEY (secret), CONFIRM_SECRET (secret, long random string),
//   FROM_EMAIL = "CampConditions.au <digest@mail.campconditions.au>", SITE_URL e.g. https://campconditions.au,
//   RESEND_SEGMENT_ID
import { makeToken, EMAIL_RE, signupsReady } from "../_lib/token.js";

const page = (title, msg, status = 200) =>
  new Response(
    `<!doctype html><html lang="en-AU"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><p>${msg}</p><p><a href="/">Back to CampConditions.au</a></p></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

const UNSUBSCRIBE = "mailto:campconditions@outlook.com?subject=Unsubscribe%20from%20CampConditions.au";

export function confirmationMessage(site, link) {
  const privacy = `${String(site || "").replace(/\/$/, "")}/privacy/`;
  const html = `<p>Confirm you want the free weekly Victoria digest from CampConditions.au.</p><p><a href="${link}">Confirm my subscription</a></p><p>This link expires in 48 hours. If you didn't ask for this, you can ignore it — you won't be added until you click.</p><p>CampConditions.au<br><a href="${privacy}">Privacy</a><br><a href="${UNSUBSCRIBE}">Unsubscribe</a></p>`;
  const text = `Confirm you want the free weekly Victoria digest from CampConditions.au.\n\n${link}\n\nThis link expires in 48 hours. If you didn't ask for this, ignore this email.\n\nCampConditions.au\nPrivacy: ${privacy}\nUnsubscribe: ${UNSUBSCRIBE}\n`;
  return { html, text };
}

async function readEmail(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const body = await request.json().catch(() => ({}));
    return String(body.email || "").trim();
  }
  const form = await request.formData();
  return String(form.get("email") || "").trim();
}

export async function onRequestPost({ request, env }) {
  if (!signupsReady(env)) return soon();
  const email = (await readEmail(request)).toLowerCase();
  if (!EMAIL_RE.test(email)) return page("Check that address", "That doesn't look like an email address.", 400);
  const token = await makeToken(email, env.CONFIRM_SECRET);
  const link = `${String(env.SITE_URL).replace(/\/$/, "")}/api/confirm?token=${encodeURIComponent(token)}`;
  const message = confirmationMessage(env.SITE_URL, link);
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
      "idempotency-key": `confirm/${email}/${new Date().toISOString().slice(0, 10)}`,
    },
    body: JSON.stringify({
      from: env.FROM_EMAIL,
      to: [email],
      subject: "Confirm your CampConditions.au digest",
      html: message.html,
      text: message.text,
    }),
  });
  if (!res.ok) return page("Could not send", "We couldn't send the confirmation email. Please try again later.", 502);
  return page("Check your email", "We've sent a confirmation link. You won't be added to the list until you click it.");
}
