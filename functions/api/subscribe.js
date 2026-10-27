// Double opt-in, step 1. Sends a confirmation email only; nobody is added to the list until they click the link.
// Env (Cloudflare Pages > Settings > Variables & Secrets), all required or this returns 503:
//   RESEND_API_KEY (secret), CONFIRM_SECRET (secret, long random string),
//   FROM_EMAIL = "CampConditions.au <digest@mail.campconditions.au>", SITE_URL e.g. https://campconditions.au,
//   RESEND_SEGMENT_ID
import { makeToken, makeUnsubscribeToken, EMAIL_RE, signupsReady, unsubscribeLink, listUnsubscribeHeaders, chosenStates, statePhrase } from "../_lib/token.js";
import { sitePage as page } from "../_lib/page.js";

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

function esc(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export function confirmationMessage(site, link, unsubscribeUrl, states = ["vic"], email = "") {
  const privacy = `${String(site || "").replace(/\/$/, "")}/privacy/`;
  const unsub = unsubscribeUrl || `${String(site || "").replace(/\/$/, "")}/unsubscribe/`;
  const picked = chosenStates(states);
  const where = statePhrase(picked.length ? picked : ["vic"]);
  const address = String(email || "").trim();
  const ask = address
    ? `Please confirm you'd like updates sent to ${address}.`
    : "Please confirm you'd like these updates.";
  const safeLink = esc(link);
  const style = "font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:22px;color:#222222;";
  const button = `<a href="${safeLink}" style="display:inline-block;background:#2f5d3a;color:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;line-height:20px;text-decoration:none;padding:12px 22px;border-radius:8px;">Confirm my subscription</a>`;
  const html = `<!DOCTYPE html><html lang="en-AU"><head><meta charset="utf-8"><title>Confirm your CampConditions.au digest</title></head>
<body style="margin:0;background:#fbfaf6;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;padding:8px 24px 24px;">
<tr><td style="padding-top:16px;"><img src="https://campconditions.au/assets/brand/logo-160.png" width="77" height="77" alt="CampConditions.au" style="display:block;border:0;"></td></tr>
<tr><td style="${style}font-size:22px;line-height:28px;font-weight:bold;color:#2f5d3a;padding-top:8px;">CampConditions.au</td></tr>
<tr><td style="${style}padding-top:16px;">${esc(ask)}</td></tr>
<tr><td style="${style}padding-top:8px;">Confirm you want the free weekly CampConditions.au digest for ${esc(where)}.</td></tr>
<tr><td style="padding-top:16px;">${button}</td></tr>
<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#666666;padding-top:12px;">If the button does not work, copy this link into your browser:<br><a href="${safeLink}" style="color:#2f5d3a;word-break:break-all;">${safeLink}</a></td></tr>
<tr><td style="${style}padding-top:8px;">This link expires in 48 hours. If you didn't ask for this, you can ignore it — you won't be added until you click.</td></tr>
<tr><td style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#666666;padding-top:24px;">CampConditions.au<br><a href="${esc(privacy)}" style="color:#666666;">Privacy</a><br><a href="${esc(unsub)}" style="color:#666666;">Unsubscribe</a></td></tr>
</table></td></tr></table></body></html>`;
  const text = `${ask}\n\nConfirm you want the free weekly CampConditions.au digest for ${where}.\n\nConfirm my subscription:\n${link}\n\nThis link expires in 48 hours. If you didn't ask for this, ignore this email.\n\nCampConditions.au\nPrivacy: ${privacy}\nUnsubscribe: ${unsub}\n`;
  return { html, text, headers: listUnsubscribeHeaders(unsub) };
}

async function readSignup(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const body = await request.json().catch(() => ({}));
    const states = body.states;
    return {
      email: String(body.email || "").trim(),
      states: Array.isArray(states) ? states : (states ? String(states).split(",") : []),
      choosing: body.choose_states,
    };
  }
  const form = await request.formData();
  return { email: String(form.get("email") || "").trim(), states: form.getAll("states"), choosing: form.get("choose_states") };
}

export async function onRequestPost({ request, env }) {
  if (!signupsReady(env)) return soon();
  const signup = await readSignup(request);
  const email = signup.email.toLowerCase();
  if (!EMAIL_RE.test(email)) return page("Check that address", "That doesn't look like an email address.", 400);
  const choosing = String(signup.choosing || "") === "1";
  let states = ["vic"];
  let explicit = false;
  if (choosing) {
    states = chosenStates(signup.states);
    if (!states.length) return page("Pick a state", "Choose Victoria, New South Wales, or both.", 400);
    explicit = true;
  }
  const token = explicit ? await makeToken(email, env.CONFIRM_SECRET, 60 * 60 * 48, states) : await makeToken(email, env.CONFIRM_SECRET);
  const site = String(env.SITE_URL).replace(/\/$/, "");
  const link = `${site}/api/confirm?token=${encodeURIComponent(token)}`;
  const unsub = unsubscribeLink(site, email, await makeUnsubscribeToken(email, env.CONFIRM_SECRET));
  const message = confirmationMessage(env.SITE_URL, link, unsub, states, email);
  const day = new Date().toISOString().slice(0, 10);
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
      "idempotency-key": explicit ? `confirm/${email}/${states.join(",")}/${day}` : `confirm/${email}/${day}`,
    },
    body: JSON.stringify({
      from: env.FROM_EMAIL,
      to: [email],
      subject: "Confirm your CampConditions.au digest",
      html: message.html,
      text: message.text,
      headers: message.headers,
    }),
  });
  if (!res.ok) return page("Could not send", "We couldn't send the confirmation email. Please try again later.", 502);
  return page("Check your email", "We've sent a confirmation link. You won't be added to the list until you click it.");
}
