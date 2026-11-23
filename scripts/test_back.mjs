// Camp page back link. No network: names are passed in, or fetch is replaced.
import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const failures = [];
function check(cond, label) {
  if (!cond) failures.push(label);
}

function load(code) {
  const sandbox = vm.createContext({
    URL, Object, Number, String, Array, Error, Promise, JSON, console,
  });
  vm.runInContext(code, sandbox);
  if (!sandbox.campBack || typeof sandbox.campBack.mount !== "function") {
    throw new Error("campBack missing");
  }
  return sandbox.campBack;
}

const names = {
  "/": "the map",
  "/vic/": "Victoria",
  "/nsw/": "New South Wales",
  "/vic/grampians-south-west/": "Grampians & South West",
  "/vic/near/bright/": "Camps near Bright",
  "/vic/camp/other-camp/": "Other Camp",
  "/closures-this-weekend/": "Closures this weekend",
  "/trip-check/": "Trip Check",
};
const page = "https://campconditions.au/vic/camp/ingrams/";

function harness(campBack, opts) {
  const clicks = [];
  const link = {
    href: "",
    textContent: "",
    addEventListener(type, fn) { if (type === "click") clicks.push(fn); },
  };
  const el = {
    hidden: true,
    querySelector() { return opts.broken ? null : link; },
    removeAttribute(name) { if (name === "hidden") this.hidden = false; },
  };
  const hist = {
    length: opts.historyLength == null ? 1 : opts.historyLength,
    backed: 0,
    back() { this.backed += 1; },
  };
  let fetched = 0;
  const mountOpts = {
    document: {
      getElementById(id) { return id === "camp-back" ? el : null; },
      referrer: opts.referrer || "",
    },
    pageUrl: opts.pageUrl || page,
    historyLength: hist.length,
    history: hist,
    fetch: opts.fetch || (async () => { fetched += 1; throw new Error("unexpected fetch"); }),
  };
  if (Object.prototype.hasOwnProperty.call(opts, "referrer")) mountOpts.referrer = opts.referrer;
  if (Object.prototype.hasOwnProperty.call(opts, "names")) mountOpts.names = opts.names;
  if (Object.prototype.hasOwnProperty.call(opts, "namesUrl")) mountOpts.namesUrl = opts.namesUrl;
  const pending = campBack.mount(mountOpts);
  return { el, link, hist, clicks, fetched: () => fetched, pending };
}

function shown(result) {
  return result.el.hidden === false && result.link.textContent && result.link.href;
}

async function runBehavior(campBack, label) {
  const hiddenCases = [
    ["empty", "", page],
    ["external", "https://example.com/vic/grampians-south-west/", page],
    ["lookalike", "https://campconditions.au.evil.com/vic/", page],
    ["other port", "http://localhost:9090/vic/", "http://127.0.0.1:8080/vic/camp/ingrams/"],
    ["self", page, page],
    ["self slash", "https://campconditions.au/vic/camp/ingrams", page],
    ["self query", page + "?from=refresh", page],
    ["self www", "https://www.campconditions.au/vic/camp/ingrams/#top", page],
    ["self on preview", "https://campconditions.au/vic/camp/ingrams/?x=1", "http://127.0.0.1:8080/vic/camp/ingrams/"],
    ["bad protocol", "javascript:alert(1)", page],
  ];
  for (const [name, referrer, pageUrl] of hiddenCases) {
    const result = harness(campBack, { referrer, names, historyLength: 2, pageUrl });
    check(!shown(result) && result.el.hidden === true && result.clicks.length === 0, label + " hides " + name);
  }

  const local = harness(campBack, {
    referrer: "",
    names,
    pageUrl: page,
  });
  check(local.el.hidden === true && local.link.textContent === "" && local.clicks.length === 0, label + " empty referrer stays hidden");

  const external = harness(campBack, {
    referrer: "https://news.example/story",
    names,
    pageUrl: page,
    historyLength: 4,
  });
  check(external.el.hidden === true && external.link.href === "", label + " external stays hidden");

  const regionRef = "https://www.campconditions.au/vic/grampians-south-west/?hide=closed#map";
  const region = harness(campBack, { referrer: regionRef, names, historyLength: 2 });
  check(region.el.hidden === false, label + " region shows");
  check(region.link.textContent === "\u2190 Back to Grampians & South West", label + " region label");
  check(region.link.href === regionRef, label + " region keeps query and hash");

  const state = harness(campBack, { referrer: "https://campconditions.au/vic/", names, historyLength: 2 });
  check(state.link.textContent === "\u2190 Back to Victoria" && state.el.hidden === false, label + " state label");

  const home = harness(campBack, { referrer: "https://campconditions.au/?view=map#camps", names, historyLength: 2 });
  check(home.link.textContent === "\u2190 Back to the map" && home.link.href.endsWith("?view=map#camps"), label + " home label");

  const town = harness(campBack, { referrer: "http://localhost:8080/vic/near/bright/", names, pageUrl: "http://localhost:8080/vic/camp/ingrams/", historyLength: 2 });
  check(town.link.textContent === "\u2190 Back to Camps near Bright" && town.el.hidden === false, label + " town label on local origin");

  const other = harness(campBack, { referrer: "https://campconditions.au/vic/camp/other-camp/", names, historyLength: 2 });
  check(other.link.textContent === "\u2190 Back to Other Camp", label + " other camp");

  const weekend = harness(campBack, { referrer: "https://campconditions.au/closures-this-weekend/", names, historyLength: 1 });
  check(weekend.link.textContent === "\u2190 Back to Closures this weekend", label + " weekend");

  const trip = harness(campBack, { referrer: "https://campconditions.au/trip-check/?from=email", names, historyLength: 1 });
  check(trip.link.textContent === "\u2190 Back to Trip Check" && trip.link.href.includes("?from=email"), label + " trip check");

  const unknown = harness(campBack, { referrer: "https://campconditions.au/not-a-page/", names, historyLength: 2 });
  check(unknown.link.textContent === "\u2190 Back" && unknown.el.hidden === false, label + " unknown path");

  const offHost = harness(campBack, {
    referrer: "http://localhost:8080/nsw/",
    names,
    pageUrl: "http://127.0.0.1:8080/vic/camp/ingrams/",
    historyLength: 2,
  });
  check(offHost.el.hidden === true, label + " different local origin stays hidden");

  const preview = harness(campBack, {
    referrer: "https://campconditions.au/nsw/",
    names,
    pageUrl: "http://127.0.0.1:8080/vic/camp/ingrams/",
    historyLength: 2,
  });
  check(preview.link.textContent === "\u2190 Back to New South Wales" && preview.el.hidden === false, label + " production referrer on local page");

  let prevented = false;
  region.clicks[0]({ preventDefault() { prevented = true; } });
  check(prevented && region.hist.backed === 1, label + " history.back when the referrer matches");

  prevented = false;
  const direct = harness(campBack, { referrer: "https://campconditions.au/vic/", names, historyLength: 1 });
  direct.clicks[0]({ preventDefault() { prevented = true; } });
  check(!prevented && direct.hist.backed === 0, label + " short history navigates to the href");

  prevented = false;
  region.link.href = "https://campconditions.au/somewhere-else/";
  region.clicks[0]({ preventDefault() { prevented = true; } });
  check(!prevented && region.hist.backed === 1, label + " mismatched href does not call back again");

  const boom = harness(campBack, { referrer: regionRef, names, broken: true });
  check(boom.el.hidden === true, label + " missing anchor leaves the page hidden");

  let calls = 0;
  const fetched = harness(campBack, {
    referrer: regionRef,
    historyLength: 2,
    fetch: async (url) => {
      calls += 1;
      check(String(url).startsWith("/back-names.json?v=") || String(url) === "/back-names.json?v=test", label + " names url");
      return { ok: true, json: async () => names };
    },
    namesUrl: "/back-names.json?v=test",
  });
  check(fetched.el.hidden === true, label + " stays hidden until names load");
  await fetched.pending;
  check(calls === 1 && fetched.link.textContent === "\u2190 Back to Grampians & South West", label + " fetch shows the link");

  calls = 0;
  const skipped = harness(campBack, {
    referrer: "https://example.com/",
    fetch: async () => { calls += 1; return { ok: true, json: async () => names }; },
    namesUrl: "/back-names.json?v=test",
  });
  await skipped.pending;
  check(calls === 0 && skipped.el.hidden === true, label + " external does not fetch names");

  const failed = harness(campBack, {
    referrer: "https://campconditions.au/faq/",
    historyLength: 2,
    fetch: async () => { throw new Error("offline"); },
    namesUrl: "/back-names.json?v=test",
  });
  await failed.pending;
  check(failed.el.hidden === false && failed.link.textContent === "\u2190 Back", label + " failed names fall back");
}

const source = readFileSync(path.join(root, "assets", "back.js"), "utf8");
check(source.includes("try") && source.includes("catch"), "source guards failures");
check(source.includes("__BACK_NAMES_URL__"), "source keeps the names placeholder");
await runBehavior(load(source), "source");

const builtPath = path.join(root, "dist", "back.js");
const namesPath = path.join(root, "dist", "back-names.json");
if (existsSync(builtPath)) {
  const built = readFileSync(builtPath, "utf8");
  check(!built.includes("__BACK_NAMES_URL__"), "built script has no placeholder");
  const match = built.match(/\/back-names\.json\?v=([0-9a-f]{8})/);
  check(!!match, "built script points at back-names.json");
  if (match && existsSync(namesPath)) {
    const digest = createHash("sha256").update(readFileSync(namesPath)).digest("hex").slice(0, 8);
    check(match[1] === digest, "built names url matches the file hash");
  }
  await runBehavior(load(built), "built");
}

if (failures.length) {
  for (const item of failures) console.error(item);
  console.error(failures.length + " back-link checks failed");
  process.exit(1);
}
console.log("back link ok");
