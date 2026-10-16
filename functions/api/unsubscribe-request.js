// Sends a one-click unsubscribe link to the address the visitor typed. Does not unsubscribe by itself.
import { EMAIL_RE, makeUnsubscribeToken, signupsReady, unsubscribeLink, listUnsubscribeHeaders } from "../_lib/token.js";
import { sitePage } from "../_lib/page.js";

const soon = () => sitePage("Unsubscribe unavailable", 'Unsubscribe isn\'t available just now. Email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a> and we\'ll remove you.', 503);

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
  if (!EMAIL_RE.test(email)) return sitePage("Check that address", "That doesn't look like an email address.", 400);
  const site = String(env.SITE_URL).replace(/\/$/, "");
  const token = await makeUnsubscribeToken(email, env.CONFIRM_SECRET);
  const link = unsubscribeLink(site, email, token);
  const privacy = `${site}/privacy/`;
  const html = `<p>Use this link to unsubscribe from the CampConditions.au digest. It works in one click.</p><p><a href="${link}">Unsubscribe me</a></p><p>If you didn't ask for this, you can ignore it.</p><p>CampConditions.au<br><a href="${privacy}">Privacy</a></p>`;
  const text = `Use this link to unsubscribe from the CampConditions.au digest. It works in one click.\n\n${link}\n\nIf you didn't ask for this, ignore this email.\n\nCampConditions.au\nPrivacy: ${privacy}\n`;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
      "idempotency-key": `unsubscribe-link/${email}/${new Date().toISOString().slice(0, 10)}`,
    },
    body: JSON.stringify({
      from: env.FROM_EMAIL,
      to: [email],
      subject: "Unsubscribe from the CampConditions.au digest",
      html,
      text,
      headers: listUnsubscribeHeaders(link),
    }),
  });
  if (!res.ok) return sitePage("Could not send", "We couldn't send the unsubscribe email. Please try again later.", 502);
  return sitePage("Check your email", "We've sent a one-click unsubscribe link. You stay on the list until you open it.");
}
