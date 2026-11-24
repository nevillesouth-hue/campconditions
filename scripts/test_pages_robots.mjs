// *.pages.dev is noindex. campconditions.au is not. The body, including the
// Cloudflare Web Analytics beacon, is not rewritten.
import { onRequest, pagesDevHost, robotsHeaderForHost } from "../functions/_middleware.js";

const failures = [];
function check(cond, label) {
  if (!cond) failures.push(label);
}

const BEACON = '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{"token": "ac659ae5"}\'></script>';

check(pagesDevHost("campconditions.pages.dev") === true, "project host");
check(pagesDevHost("abc123.campconditions.pages.dev") === true, "preview host");
check(pagesDevHost("CAMPCONDITIONS.PAGES.DEV") === true, "host case");
check(pagesDevHost("campconditions.pages.dev:443") === true, "host port");
check(pagesDevHost("campconditions.au") === false, "apex");
check(pagesDevHost("www.campconditions.au") === false, "www");
check(pagesDevHost("notpages.dev") === false, "lookalike");
check(pagesDevHost("pages.dev") === false, "bare pages.dev");
check(pagesDevHost("") === false, "empty host");
check(robotsHeaderForHost("campconditions.pages.dev") === "noindex, nofollow", "header value");
check(robotsHeaderForHost("campconditions.au") === "", "apex header");

function context(url, body) {
  return {
    request: new Request(url),
    async next() {
      return new Response(body, {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    },
  };
}

const prod = await onRequest(context("https://campconditions.au/vic/", "<html>" + BEACON + "</html>"));
const prodBody = await prod.text();
check(prod.headers.get("x-robots-tag") === null, "au sends no X-Robots-Tag");
check(prodBody.includes("ac659ae5"), "au beacon kept");
check(!prodBody.includes("noindex"), "au body has no noindex");

const www = await onRequest(context("https://www.campconditions.au/", "<html>" + BEACON));
check(www.headers.get("x-robots-tag") === null, "www sends no X-Robots-Tag");

const project = await onRequest(context("https://campconditions.pages.dev/", "<html>" + BEACON + "</html>"));
check(project.headers.get("x-robots-tag") === "noindex, nofollow", "pages.dev noindex");
const projectBody = await project.text();
check(projectBody.includes("ac659ae5"), "pages.dev beacon kept");
check(projectBody.includes("<html>"), "pages.dev html kept");

const preview = await onRequest(context("https://46f3.campconditions.pages.dev/tas/camp/edgar-dam-camping-ground/", "<html>" + BEACON));
check(preview.headers.get("X-Robots-Tag") === "noindex, nofollow", "preview noindex");
check((await preview.text()).includes("beacon.min.js"), "preview beacon kept");

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("pages robots ok");
