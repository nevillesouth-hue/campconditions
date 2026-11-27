import { checkoutKey, makeDownloadPath, paidThanksHtml, retrievePaidSession, sessionIdFromQuery, signingSecret } from "../../_lib/supporter-pack.js";

async function staticThanks(context) {
  const url = new URL(context.request.url);
  url.search = "";
  url.pathname = "/support/thanks/";
  if (context.env && context.env.ASSETS && typeof context.env.ASSETS.fetch === "function") {
    return context.env.ASSETS.fetch(new Request(url.toString(), { method: "GET" }));
  }
  return new Response("Thanks for chipping in", { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const sessionId = sessionIdFromQuery(url.searchParams.get("session_id"));
  const asset = await staticThanks(context);
  const ready = Boolean(checkoutKey(context.env) && signingSecret(context.env));
  if (!sessionId || !ready) return asset;
  let paid = false;
  try {
    const result = await retrievePaidSession(context.env, sessionId, context.env.STRIPE_FETCH);
    paid = Boolean(result && result.paid);
  } catch {
    paid = false;
  }
  if (!paid) return asset;
  const downloadUrl = await makeDownloadPath(signingSecret(context.env), sessionId);
  const shell = await asset.text();
  const html = paidThanksHtml(shell, downloadUrl);
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "private, no-store",
    },
  });
}
