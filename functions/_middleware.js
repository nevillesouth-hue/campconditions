// Cloudflare Pages `_headers` applies to every host that serves this deployment.
// campconditions.au must stay indexable, so the duplicate-host rule lives here
// and only matches *.pages.dev (the project host and preview hosts).
// Preview URLs stay reachable. The response body is left alone, including the
// Cloudflare Web Analytics beacon.

const NOINDEX = "noindex, nofollow";

export function pagesDevHost(hostname) {
  const host = String(hostname || "").trim().toLowerCase().replace(/:\d+$/, "");
  return host.endsWith(".pages.dev");
}

export function robotsHeaderForHost(hostname) {
  return pagesDevHost(hostname) ? NOINDEX : "";
}

export async function onRequest(context) {
  const response = await context.next();
  const tag = robotsHeaderForHost(new URL(context.request.url).hostname);
  if (!tag) return response;
  try {
    response.headers.set("X-Robots-Tag", tag);
    return response;
  } catch (err) {
    const headers = new Headers(response.headers);
    headers.set("X-Robots-Tag", tag);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  }
}
