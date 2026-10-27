// Double opt-in, step 1. Sends a confirmation email only; nobody is added to the list until they click the link.
// Env (Cloudflare Pages > Settings > Variables & Secrets), all required or this returns 503:
//   RESEND_API_KEY (secret), CONFIRM_SECRET (secret, long random string),
//   FROM_EMAIL = "CampConditions.au <digest@mail.campconditions.au>", SITE_URL e.g. https://campconditions.au,
//   RESEND_SEGMENT_ID
import { makeToken, makeUnsubscribeToken, EMAIL_RE, signupsReady, unsubscribeLink, listUnsubscribeHeaders, chosenStates, statePhrase } from "../_lib/token.js";
import { sitePage as page } from "../_lib/page.js";

const soon = () => new Response("Sign-ups open soon", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

export function confirmationMessage(site, link, unsubscribeUrl, states = ["vic"]) {
  const privacy = `${String(site || "").replace(/\/$/, "")}/privacy/`;
  const unsub = unsubscribeUrl || `${String(site || "").replace(/\/$/, "")}/unsubscribe/`;
  const picked = chosenStates(states);
  const where = statePhrase(picked.length ? picked : ["vic"]);
  const html = `<p>Confirm you want the free weekly CampConditions.au digest for ${where}.</p><p><a href="${link}">Confirm my subscription</a></p><p>This link expires in 48 hours. If you didn't ask for this, you can ignore it — you won't be added until you click.</p><p>CampConditions.au<br><a href="${privacy}">Privacy</a><br><a href="${unsub}">Unsubscribe</a></p>`;
  const text = `Confirm you want the free weekly CampConditions.au digest for ${where}.\n\n${link}\n\nThis link expires in 48 hours. If you didn't ask for this, ignore this email.\n\nCampConditions.au\nPrivacy: ${privacy}\nUnsubscribe: ${unsub}\n`;
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
  const message = confirmationMessage(env.SITE_URL, link, unsub, states);
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
