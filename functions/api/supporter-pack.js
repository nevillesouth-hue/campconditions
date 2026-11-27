import { checkoutKey, readDownload, retrievePaidSession, signingSecret } from "../_lib/supporter-pack.js";
import { PACK_FILENAME } from "../_lib/supporter-pack.js";

function gone() {
  return new Response("This download link has expired or is not valid.", {
    status: 403,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
  });
}

async function packBytes() {
  const res = await fetch(new URL("../_lib/supporter-pack.pdf", import.meta.url));
  if (!res.ok) throw new Error("pack missing");
  return new Uint8Array(await res.arrayBuffer());
}

export async function onRequestGet(context) {
  const url = new URL(context.request.url);
  const token = await readDownload(signingSecret(context.env), {
    sid: url.searchParams.get("sid"),
    exp: url.searchParams.get("exp"),
    sig: url.searchParams.get("sig"),
  });
  if (!token) return gone();
  if (!checkoutKey(context.env)) return gone();
  let paid = false;
  try {
    const result = await retrievePaidSession(context.env, token.sessionId, context.env.STRIPE_FETCH);
    paid = Boolean(result && result.paid);
  } catch {
    paid = false;
  }
  if (!paid) return gone();
  let bytes;
  try {
    bytes = context.env.PACK_BYTES || (await packBytes());
  } catch {
    return new Response("The pack is temporarily unavailable.", { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  return new Response(bytes, {
    status: 200,
    headers: {
      "content-type": "application/pdf",
      "content-disposition": 'attachment; filename="' + PACK_FILENAME + '"',
      "cache-control": "private, no-store",
    },
  });
}
