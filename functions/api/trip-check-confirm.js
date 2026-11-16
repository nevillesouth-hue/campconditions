// Trip Check waitlist, step 2. Stores the address in TRIPCHECK_KV after the signed link is opened.
// The key is the lower-cased email, so a second confirmation updates that record and does not add another.
// Nothing is written to Resend here.
import { sitePage as page } from "../_lib/page.js";
import { kvReady, readTripCheck, saveConfirmed, thanksText, tripSecret } from "../_lib/trip-check.js";

function unavailable() {
  return page("Waitlist unavailable", 'We couldn\'t save your place just now. Please try the link again later, or email <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>. Nobody has been charged.', 503);
}

export async function onRequestGet({ request, env }) {
  try {
    if (!tripSecret(env)) return unavailable();
    const token = new URL(request.url).searchParams.get("token") || "";
    const parsed = await readTripCheck(token, tripSecret(env));
    if (!parsed) {
      return page("Link not valid", 'That confirmation link is invalid or has expired. Please <a href="/trip-check/">join the waitlist</a> again. Nobody has been charged.', 400);
    }
    if (!kvReady(env)) return unavailable();
    await saveConfirmed(env.TRIPCHECK_KV, {
      email: parsed.email,
      first_name: parsed.first_name,
      states: parsed.states,
      confirmed_at: new Date().toISOString(),
    });
    return page("You're on the waitlist", thanksText(parsed.email));
  } catch {
    return unavailable();
  }
}
