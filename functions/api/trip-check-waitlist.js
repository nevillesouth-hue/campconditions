// Trip Check waitlist, step 1. Sends one confirmation email. Nobody is stored until they open the link.
// Resend is called only at POST https://api.resend.com/emails. Contact records, segments, topics and audiences are not used.
// Does not read the digest one-list flag or the digest handlers.
//
// Cloudflare, before this can store a confirmation:
//   Create a KV namespace and bind it on the campconditions Pages project as TRIPCHECK_KV (production).
//   RESEND_API_KEY and FROM_EMAIL are the existing mail secrets. The link is signed with TRIPCHECK_SECRET, or CONFIRM_SECRET when that is unset.
//   Optional TRIPCHECK_ADMIN_KEY unlocks GET /api/trip-check-count. See README and config/trip-check.wrangler.toml.example.
//   Do not add a root wrangler.toml until that namespace id is real. pages deploy would treat the file as the source of truth.
import { sitePage as page } from "../_lib/page.js";
import {
  EMAIL_RE, checkEmailText, cleanName, cleanStates, clientIp, confirmationMessage, kvReady, mailReady,
  normalEmail, rateLimited, readWaitlist, signTripCheck, siteOrigin, tripSecret,
} from "../_lib/trip-check.js";

function unavailable() {
  return page("Waitlist unavailable", 'The waitlist isn\'t available just now. Email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a> and we\'ll note your interest. Nobody has been charged.', 503);
}

export async function onRequestPost({ request, env }) {
  try {
    const signup = await readWaitlist(request);
    if (rateLimited(clientIp(request))) {
      return page("Please wait", "Please wait a few minutes and try again. Nobody has been charged.", 429);
    }
    const email = normalEmail(signup.email);
    if (String(signup.company || "").trim()) {
      const shown = EMAIL_RE.test(email) ? email : "your address";
      return page("Check your email", checkEmailText(shown));
    }
    if (!EMAIL_RE.test(email) || email.length > 254) return page("Check that address", "That doesn't look like an email address.", 400);
    if (String(signup.consent || "") !== "yes") {
      return page("Consent needed", "Tick the box to join the waitlist. Nobody has been charged.", 400);
    }
    if (!mailReady(env) || !kvReady(env)) return unavailable();
    const first_name = cleanName(signup.first_name);
    const states = cleanStates(signup.states);
    const token = await signTripCheck({ email, first_name, states }, tripSecret(env));
    if (!token) return unavailable();
    const link = `${siteOrigin(env, request)}/api/trip-check-confirm?token=${encodeURIComponent(token)}`;
    const message = confirmationMessage(link);
    const day = new Date().toISOString().slice(0, 10);
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.RESEND_API_KEY}`,
        "content-type": "application/json",
        "idempotency-key": `trip-check/${email}/${states.join(",")}/${day}`,
      },
      body: JSON.stringify({
        from: env.FROM_EMAIL,
        to: [email],
        subject: message.subject,
        html: message.html,
        text: message.text,
      }),
    });
    if (!res.ok) return page("Could not send", "We couldn't send the confirmation email. Please try again later. Nobody has been charged.", 502);
    return page("Check your email", checkEmailText(email));
  } catch {
    return unavailable();
  }
}
