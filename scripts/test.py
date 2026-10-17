import os,re,json,sys,html,subprocess,tempfile
D=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"dist");bad=[];n=0;ldn=0
def draft_dir(path):
  return "digest" in path.replace("\\", "/").split("/")
for r,_,fs in os.walk(D):
  if draft_dir(r): continue
  for f in fs:
    if not f.endswith(".html"): continue
    p=os.path.join(r,f);t=open(p).read();n+=1
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>',t,re.S): json.loads(m);ldn+=1
    for h in re.findall(r'href="(/[^"#?]*)',t):
      tgt=os.path.join(D,h.lstrip("/"));
      if not (os.path.isfile(tgt) or os.path.isfile(os.path.join(tgt,"index.html"))): bad.append((p[len(D):],h))
    if "<title>" not in t or not re.search(r"lang=[\"']en-AU", t): bad.append((p,"meta"))
for f in ["sitemap.xml","robots.txt","llms.txt","status.json"]: assert os.path.isfile(os.path.join(D,f)),f
json.load(open(os.path.join(D,"status.json")))
sm=re.findall(r"<loc>https://campconditions.au(.*?)</loc>",open(os.path.join(D,"sitemap.xml")).read())
for u in sm:
  if not os.path.isfile(os.path.join(D,u.lstrip("/"),"index.html")): bad.append(("sitemap",u))
feed=json.load(open(os.path.join(D,"status.json")))
def map_data(where, html):
  m=re.search(r'<script type="application/json" id="camp-map-data">(.*?)</script>', html, re.S)
  if not m:
    bad.append((where, "missing camp-map-data")); return []
  try: data=json.loads(m.group(1))
  except Exception as ex:
    bad.append((where, f"map json {ex}")); return []
  if not isinstance(data, list):
    bad.append((where, "map data not a list")); return []
  for i, pt in enumerate(data):
    if not all(k in pt for k in ("name","lat","lon","status","url")):
      bad.append((where, f"map point {i} fields")); break
    if pt["status"] not in ("open","check","closed") or not isinstance(pt["lat"], (int, float)) or not isinstance(pt["lon"], (int, float)):
      bad.append((where, f"map point {i} values")); break
    if not str(pt["url"]).startswith("/vic/camp/") or not os.path.isfile(os.path.join(D, pt["url"].lstrip("/"), "index.html")):
      bad.append((where, pt.get("url"))); break
    if pt.get("note") and (pt["status"] != "closed" or "outdated" not in pt["note"].lower()):
      bad.append((where, "outdated marker note")); break
  return data
def expect_map(where, html, cluster):
  if 'id="camp-map"' not in html or 'src="/map.js"' not in html:
    bad.append((where, "missing map"))
  if "leaflet/1.9.4/leaflet.min.js" not in html or "integrity=" not in html or "crossorigin=" not in html:
    bad.append((where, "leaflet sri"))
  clustered="leaflet.markercluster" in html
  if clustered != cluster: bad.append((where, "cluster" if cluster else "unexpected cluster"))
  return map_data(where, html)
mj=open(os.path.join(D,"map.js"), encoding="utf-8").read()
if "tile.openstreetmap.org" not in mj or "openstreetmap.org/copyright" not in mj: bad.append(("map.js","osm"))
for colour in ("#2e7d32","#e08a00","#b71c1c"):
  if colour not in mj: bad.append(("map.js", colour))
home=open(os.path.join(D,"index.html"), encoding="utf-8").read()
if 'action="/api/subscribe"' not in home or "nothing was sent" in home or 'id="newsletter"' not in home:
  bad.append(("/", "newsletter form"))
vic=open(os.path.join(D,"vic","index.html"), encoding="utf-8").read()
home_pts, vic_pts=expect_map("/", home, True), expect_map("/vic/", vic, True)
if len(home_pts)!=len(feed["camps"]) or len(vic_pts)!=len(feed["camps"]): bad.append(("overview", "map count"))
home_urls={p["url"] for p in home_pts}
if home_urls!={c["url"].replace("https://campconditions.au","") for c in feed["camps"]}: bad.append(("overview","map urls"))
by={}
for c in feed["camps"]: by.setdefault(c["region"], []).append(c)
for name in os.listdir(os.path.join(D,"vic")):
  page=os.path.join(D,"vic",name,"index.html")
  if name=="camp" or not os.path.isfile(page): continue
  pts=expect_map(f"/vic/{name}/", open(page, encoding="utf-8").read(), True)
  if len(pts)!=len(by.get(name, [])): bad.append((f"/vic/{name}/", "region map count"))
for slug in os.listdir(os.path.join(D,"vic","camp")):
  page=os.path.join(D,"vic","camp",slug,"index.html")
  if not os.path.isfile(page): continue
  html_page=open(page, encoding="utf-8").read(); pts=expect_map(f"/vic/camp/{slug}/", html_page, False)
  if len(pts)!=1 or pts[0]["url"]!=f"/vic/camp/{slug}/": bad.append((slug, "camp map"))
  elif f"destination={pts[0]['lat']},{pts[0]['lon']}" not in html_page or "Directions in Google Maps" not in html_page or "map-sm" not in html_page:
    bad.append((slug, "directions"))
  else:
    lat, lon = pts[0]["lat"], pts[0]["lon"]; pad = 0.2
    bbox = f"https://emergency.vic.gov.au/respond/?bbox={lon-pad:.5f},{lat-pad:.5f},{lon+pad:.5f},{lat+pad:.5f}"
    if "Check VicEmergency for warnings near this camp" not in html_page or bbox not in html_page:
      bad.append((slug, "vicemergency link"))
    if "1800 226 226" not in html_page or ">000<" not in html_page:
      bad.append((slug, "emergency hotline"))
banned = ("emergency.vic.gov.au/public", "osom", "emv.vic.gov.au", "nearby_emergency", "fire_danger", "fire danger", "CC BY 3.0", "Emergency data last received", "Current VicEmergency warnings", "within 25 km")
for r, _, fs in os.walk(D):
  if draft_dir(r): continue
  for f in fs:
    if not f.endswith((".html", ".json", ".txt", ".js")): continue
    blob = open(os.path.join(r, f), encoding="utf-8").read().lower()
    for needle in banned:
      # "osom" is the VicEmergency feed name. A word match keeps camp names such as Possum.
      if needle == "osom":
        if re.search(r"\bosom\b", blob): bad.append((os.path.join(r, f)[len(D):], needle))
      elif needle.lower() in blob:
        # One official camping rule mentions fire-danger days. That is not a VicEmergency feed.
        if needle == "fire danger" and f"{os.sep}vic{os.sep}camp{os.sep}" in os.path.join(r, f):
          continue
        bad.append((os.path.join(r, f)[len(D):], needle))
for key in ("nearby_emergency", "fire_danger_ratings", "emergency_data_last_received"):
  if key in feed: bad.append(("status.json", key))
if any("nearby_emergency" in c for c in feed["camps"]): bad.append(("status.json", "camp nearby_emergency"))
if "emv.vic.gov.au" in json.dumps(feed).lower() or "osom" in json.dumps(feed).lower(): bad.append(("status.json", "vicemergency data"))
ext_a = re.compile(r'<a\b[^>]*\bhref="https?://[^"]*"[^>]*>')
for r, _, fs in os.walk(D):
  if draft_dir(r): continue
  for f in fs:
    if not f.endswith(".html"): continue
    p = os.path.join(r, f)
    for tag in ext_a.findall(open(p, encoding="utf-8").read()):
      if 'target="_blank"' not in tag or 'rel="noopener noreferrer"' not in tag:
        bad.append((p[len(D):], "external tab"))
        break
if 'rel="noopener noreferrer"' not in mj: bad.append(("map.js", "osm link"))
notice = "We'll only use your email to send the CampConditions digest. We never sell or share it."
if notice not in home or '<a href="/unsubscribe/">Unsubscribe any time</a>' not in home:
  bad.append(("/", "privacy notice"))
for bit in ('for="digest-email"', "Your email", 'id="digest-note"', 'class="notice"', "scrollIntoView", "note.focus()", "el.disabled = true", "min-height:48px", "notice.ok", "notice.err"):
  if bit not in home: bad.append(("/", "signup " + bit))
if '<a href="/privacy/">Unsubscribe any time</a>' in home: bad.append(("/", "unsubscribe still points at privacy"))
if "/privacy/" not in sm or "/unsubscribe/" not in sm: bad.append(("sitemap", "privacy or unsubscribe"))
unsub_path = os.path.join(D, "unsubscribe", "index.html")
if not os.path.isfile(unsub_path):
  bad.append(("/unsubscribe/", "missing"))
else:
  unsub = open(unsub_path, encoding="utf-8").read()
  for bit in ("one-click unsubscribe link", 'for="unsub-email"', "Your email", 'action="/api/unsubscribe-request"', "Email me an unsubscribe link", "scrollIntoView", "min-height:48px", 'href="/privacy/"'):
    if bit not in unsub: bad.append(("/unsubscribe/", bit))
  if "color:#0000ee" in unsub.lower() or "color:blue" in unsub.lower(): bad.append(("/unsubscribe/", "default blue"))
priv_path = os.path.join(D, "privacy", "index.html")
if not os.path.isfile(priv_path):
  bad.append(("/privacy/", "missing"))
else:
  priv = open(priv_path, encoding="utf-8").read()
  for bit in ("Last updated 16 October 2026", "campconditions@outlook.com", "email address", "date and time", "tracking cookies", "Cloudflare", "IP address", "Resend", "outside Australia", "double opt-in", "unsubscribe link", "within 30 days", "OAIC", "never sell, rent or share", "Changes to this policy"):
    if bit not in priv: bad.append(("/privacy/", bit))
for r, _, fs in os.walk(D):
  if draft_dir(r): continue
  for f in fs:
    if not f.endswith(".html"): continue
    p = os.path.join(r, f)
    blob = open(p, encoding="utf-8").read()
    if 'href="/privacy/"' not in blob and "href='/privacy/'" not in blob:
      bad.append((p[len(D):] or "/", "privacy link"))
root = os.path.dirname(D)
dsrc = open(os.path.join(root, "scripts", "digest.py"), encoding="utf-8").read()
for bit in ("api.resend.com", "smtplib", "sendmail", "urllib", "requests"):
  if bit in dsrc: bad.append(("digest.py", "must only write drafts, found " + bit))
wf = open(os.path.join(root, ".github", "workflows", "build-deploy.yml"), encoding="utf-8").read()
for bit in ("api.resend.com", "digest.py", "scripts/digest"):
  if bit in wf: bad.append(("build-deploy.yml", "scheduled deploy must not send the digest: " + bit))
draft = tempfile.mkdtemp(prefix="campconditions-digest-")
digest = subprocess.run([sys.executable, os.path.join(root, "scripts", "digest.py"), "--out", draft], cwd=root, capture_output=True, text=True)
if digest.returncode != 0:
  bad.append(("digest", (digest.stderr or digest.stdout)[-240:]))
else:
  for name in ("digest.html", "digest.txt"):
    blob = open(os.path.join(draft, name), encoding="utf-8").read()
    for bit in ("CampConditions.au", "https://campconditions.au/privacy/", "https://campconditions.au/api/unsubscribe?e={{{EMAIL}}}&t={{{unsubscribe_token}}}", "Unsubscribe"):
      if bit not in blob: bad.append((name, bit))
    if "mailto:campconditions@outlook.com?subject=Unsubscribe" in blob or "{{{RESEND_UNSUBSCRIBE_URL}}}" in blob:
      bad.append((name, "old unsubscribe link"))
  meta = json.load(open(os.path.join(draft, "meta.json"), encoding="utf-8"))
  headers = meta.get("headers") or {}
  if headers.get("List-Unsubscribe") != "<https://campconditions.au/api/unsubscribe?e={{{EMAIL}}}&t={{{unsubscribe_token}}}>":
    bad.append(("digest meta", "List-Unsubscribe"))
  if headers.get("List-Unsubscribe-Post") != "List-Unsubscribe=One-Click":
    bad.append(("digest meta", "List-Unsubscribe-Post"))
confirm = subprocess.run(["node", "--input-type=module", "-e", """
import { confirmationMessage } from "./functions/api/subscribe.js";
const unsub = "https://campconditions.au/api/unsubscribe?e=reader%40example.com&t=abc";
const m = confirmationMessage("https://campconditions.au", "https://campconditions.au/api/confirm?token=abc", unsub);
const need = ["CampConditions.au", "https://campconditions.au/privacy/", "Unsubscribe", unsub];
for (const blob of [m.html, m.text]) {
  for (const bit of need) if (!blob.includes(bit)) { console.error("missing " + bit); process.exit(1); }
  if (blob.includes("mailto:campconditions@outlook.com?subject=Unsubscribe")) process.exit(1);
}
if (m.html.includes("api.resend.com")) process.exit(1);
if (m.headers["List-Unsubscribe"] !== "<" + unsub + ">") process.exit(1);
if (m.headers["List-Unsubscribe-Post"] !== "List-Unsubscribe=One-Click") process.exit(1);
"""], cwd=root, capture_output=True, text=True)
if confirm.returncode != 0:
  bad.append(("confirm email", (confirm.stderr or confirm.stdout)[-240:]))
confirm_api = subprocess.run(["node", "--input-type=module", "-e", """
import { readFileSync } from "node:fs";
import { confirmSubscription, failureMessage, segmentPath } from "./functions/api/confirm.js";
const segment = "b9096e2d-485b-487e-90db-467e44eaf6cc";
const email = "reader@example.com";
const env = { RESEND_API_KEY: "test", RESEND_SEGMENT_ID: segment };
if (segmentPath(email, segment) !== "/contacts/reader%40example.com/segments/" + segment) {
  console.error("segment path"); process.exit(1);
}
const calls = [];
const mock = async (url, init) => {
  calls.push({ url, method: init.method, body: init.body });
  if (url.endsWith("/contacts")) return new Response(JSON.stringify({ id: "c1" }), { status: 201 });
  if (url.endsWith("/segments/" + segment)) return new Response(JSON.stringify({ id: segment }), { status: 200 });
  return new Response("no", { status: 500 });
};
const ok = await confirmSubscription(env, email, mock);
if (!ok.ok || calls.length !== 2 || calls[0].method !== "POST" || !calls[0].body.includes('"unsubscribed":false')) process.exit(1);
if (calls[1].method !== "POST" || calls[1].body !== undefined) process.exit(1);
if (!calls[1].url.endsWith(segmentPath(email, segment))) process.exit(1);
calls.length = 0;
const again = async (url) => {
  calls.push(url);
  return new Response(JSON.stringify({ name: "already_exists" }), { status: 409 });
};
const dup = await confirmSubscription(env, email, again);
if (!dup.ok || calls.length !== 2) process.exit(1);
const restricted = { ok: false, status: 401, data: { name: "restricted_api_key", message: "This API key is restricted to only send emails." } };
const msg = failureMessage(restricted);
if (!msg.includes("can send mail but cannot save contacts") || msg.includes("502")) process.exit(1);
const src = readFileSync("./functions/api/confirm.js", "utf8");
if (src.includes(", 502)") || src.includes("status: 502")) { console.error("still returns 502"); process.exit(1); }
const envWithSecret = { ...env, CONFIRM_SECRET: "test-secret", FROM_EMAIL: "CampConditions.au <digest@mail.campconditions.au>", SITE_URL: "https://campconditions.au" };
const calls2 = [];
let contactPosts = 0;
const mock2 = async (url, init) => {
  calls2.push({ url, method: init.method, body: init.body });
  if (url.endsWith("/contacts") && init.method === "POST") {
    contactPosts += 1;
    if (contactPosts === 1) return new Response(JSON.stringify({ name: "validation_error" }), { status: 422 });
    return new Response(JSON.stringify({ id: "c1" }), { status: 201 });
  }
  if (url.endsWith("/segments/" + segment)) return new Response(JSON.stringify({ id: segment }), { status: 200 });
  return new Response("no", { status: 500 });
};
const retried = await confirmSubscription(envWithSecret, email, mock2);
if (!retried.ok || calls2.length !== 3 || !calls2[0].body.includes("unsubscribe_token") || calls2[1].body.includes("unsubscribe_token")) process.exit(1);
"""], cwd=root, capture_output=True, text=True)
if confirm_api.returncode != 0:
  bad.append(("confirm api", (confirm_api.stderr or confirm_api.stdout)[-400:]))
unsub_api = subprocess.run(["node", "--input-type=module", "-e", """
import { makeUnsubscribeToken, unsubscribeTokenMatches, listUnsubscribeHeaders } from "./functions/_lib/token.js";
import { onRequestGet, onRequestPost, unsubscribeContact } from "./functions/api/unsubscribe.js";
const segment = "b9096e2d-485b-487e-90db-467e44eaf6cc";
const secret = "test-secret";
const email = "reader@example.com";
const token = await makeUnsubscribeToken(email, secret);
if (token.length !== 64 || !(await unsubscribeTokenMatches(email, token, secret))) process.exit(1);
if (await unsubscribeTokenMatches("other@example.com", token, secret)) process.exit(1);
if (await unsubscribeTokenMatches(email, "0".repeat(64), secret)) process.exit(1);
const env = {
  RESEND_API_KEY: "test", CONFIRM_SECRET: secret, FROM_EMAIL: "CampConditions.au <digest@mail.campconditions.au>",
  SITE_URL: "https://campconditions.au", RESEND_SEGMENT_ID: segment,
};
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url, method: init.method, body: init.body });
  return new Response("{}", { status: 200 });
};
const url = "https://campconditions.au/api/unsubscribe?e=" + encodeURIComponent(email) + "&t=" + token;
const got = await onRequestGet({ request: new Request(url), env });
const html = await got.text();
if (got.status !== 200 || !html.includes("You're unsubscribed") || !html.includes("/privacy/")) process.exit(1);
if (calls.length !== 2 || calls[0].method !== "PATCH" || !calls[0].body.includes('"unsubscribed":true')) process.exit(1);
if (calls[1].method !== "DELETE" || !calls[1].url.endsWith("/contacts/reader%40example.com/segments/" + segment)) process.exit(1);
calls.length = 0;
const posted = await onRequestPost({ request: new Request(url, { method: "POST", body: "List-Unsubscribe=One-Click" }), env });
if (posted.status !== 200 || !(await posted.text()).includes("You're unsubscribed") || calls.length !== 2) process.exit(1);
calls.length = 0;
const badToken = await onRequestGet({ request: new Request(url + "nope"), env });
if (badToken.status !== 400 || calls.length !== 0) process.exit(1);
const headers = listUnsubscribeHeaders(url);
if (!headers["List-Unsubscribe"].startsWith("<https://") || headers["List-Unsubscribe-Post"] !== "List-Unsubscribe=One-Click") process.exit(1);
const gone = await unsubscribeContact(env, email, async () => new Response("{}", { status: 404 }));
if (!gone.ok) process.exit(1);
"""], cwd=root, capture_output=True, text=True)
if unsub_api.returncode != 0:
  bad.append(("unsubscribe api", (unsub_api.stderr or unsub_api.stdout)[-400:]))

CREDIT = "Campground and town data © OpenStreetMap contributors (ODbL); Recreation Sites © State of Victoria (DataVic, CC BY 4.0); Explore Outdoors © State of Victoria (Department of Energy, Environment and Climate Action), CC BY 4.0"
about = open(os.path.join(D, "about", "index.html"), encoding="utf-8").read()
if CREDIT not in home or CREDIT not in about: bad.append(("credit", "footer or about"))
if "© State of Victoria (Department of Energy, Environment and Climate Action), CC BY 4.0" not in home or "Explore Outdoors" not in about: bad.append(("credit", "explore outdoors"))
if "Covering Victoria now" not in home or "Other states coming soon" not in home or 'class="soon"' not in home or "font-size:1.7rem" not in home or "font-weight:700" not in home or 'class="brand"' not in home or 'class="logo"' not in home or "font-size:2.4rem" not in home:
  bad.append(("/", "banner"))
if home.find("<nav>") > home.find('class="soon"') or home.find("<nav>") < 0 or 'justify-content:flex-end' not in home:
  bad.append(("/", "nav alignment"))
if "download" in about.lower() and "osm-camps" in about.lower(): bad.append(("about", "combined download"))
for bit in ("Search by town or camp name", 'id="town-search"', 'role="combobox"', 'aria-haspopup="listbox"', 'aria-live="polite"', 'id="camp-filters"', "Self-contained only", "Dogs OK", "Dump point", "Showers", "Suits tents", "Suits caravans", "Suits motorhomes", "Free", "Donation", "Showground", "Council park (leased)", 'value="Rest area"', 'value="Pub stay"', 'value="Paid – Parks Victoria (book ahead)"'):
  if bit not in home: bad.append(("/", "missing " + bit))
if 'placeholder="Search by town"' in home: bad.append(("/", "old town placeholder"))
if "vic-towns.json" in home: bad.append(("/", "towns JSON should be lazy-loaded, not inlined"))
towns_path = os.path.join(D, "vic-towns.json")
if not os.path.isfile(towns_path): bad.append(("vic-towns.json", "missing"))
else:
  towns = json.load(open(towns_path, encoding="utf-8"))
  if not towns or any(k not in towns[0] for k in ("name", "lat", "lon", "place", "rank")): bad.append(("vic-towns.json", "shape"))
  if not any(t.get("rank") == 0 for t in towns) or not any(t.get("rank") == 1 for t in towns): bad.append(("vic-towns.json", "ranks"))
  sample = json.dumps(towns[:2], ensure_ascii=False)
  if sample and sample in home: bad.append(("/", "towns inlined"))
if 'fetch("/vic-towns.json")' not in mj or "setView" not in mj or ", 10)" not in mj: bad.append(("map.js", "town search"))
if "slice(0, 15)" not in mj: bad.append(("map.js", "nearest camps"))
for bit in ("slice(0, 12)", "openPopup", "zoomToShowLayer", "ArrowDown", "aria-activedescendant", "hit-tag", 'kind === "camp"', 'replace(/[^a-z0-9]+/g, " ")', "regionName"):
  if bit not in mj: bad.append(("map.js", "camp search " + bit))
for flag in ("self", "dogs", "dump", "showers", "tents", "caravans", "motorhomes"):
  if f'data-flag="{flag}"' not in home: bad.append(("/", "toggle " + flag))
osm = [c for c in feed["camps"] if c.get("source") == "osm"]
dv = [c for c in feed["camps"] if c.get("source") == "datavic"]
if not osm or not dv: bad.append(("status.json", "both sources"))
if any(c.get("nearby_closures") for c in osm) or any(c.get("status") != "check" for c in osm) or any(c.get("closure") for c in osm):
  bad.append(("status.json", "osm must not get parks vic closures"))
if str(len(feed["camps"])) not in home: bad.append(("/", "home count"))
shown = {"call": False, "operator": False, "review": False, "confirmed": False, "max": False, "unknown": False, "tel": False, "https": False, "pub": False, "park": False, "water": False, "checked": False, "source": False, "access": False, "follow": False, "dogs": False}
PV = "Paid – Parks Victoria (book ahead)"
for camp in osm:
  page = os.path.join(D, "vic", "camp", camp["slug"], "index.html")
  if not os.path.isfile(page):
    bad.append((camp["slug"], "missing osm page")); continue
  html_page = open(page, encoding="utf-8").read()
  if "no road or track closures were found" in html_page: bad.append((camp["slug"], "false road claim"))
  if camp.get("category") == "Showground":
    if "Call first" not in html_page: bad.append((camp["slug"], "call first"))
    else: shown["call"] = True
  elif camp.get("category") == PV:
    if "Book ahead with Parks Victoria" not in html_page or "13 1963" not in html_page or f"Type: {PV}" not in html_page:
      bad.append((camp["slug"], "parks victoria label"))
    else: shown["park"] = True
  elif "Conditions: check with operator" not in html_page:
    bad.append((camp["slug"], "operator conditions"))
  else:
    shown["operator"] = True
  if camp.get("category") == "Pub stay":
    if "Pub stay" not in html_page: bad.append((camp["slug"], "pub stay"))
    else: shown["pub"] = True
  if camp.get("needs_review"):
    if "Unverified, help us confirm" not in html_page or f'/report/?camp={camp["slug"]}' not in html_page:
      bad.append((camp["slug"], "unverified"))
    else:
      shown["review"] = True
  elif "Unverified, help us confirm" in html_page:
    bad.append((camp["slug"], "confirmed still unverified"))
  else:
    shown["confirmed"] = True
  if "Max stay:" not in html_page: bad.append((camp["slug"], "max stay"))
  else: shown["max"] = True
  if "Dogs: Unknown" in html_page or "Dump point: Unknown" in html_page or "Showers: Unknown" in html_page: shown["unknown"] = True
  if 'href="tel:' in html_page: shown["tel"] = True
  if ">Website</a>" in html_page: shown["https"] = True
  if "Water tap:" in html_page: shown["water"] = True
  if "Checked against official source," in html_page: shown["checked"] = True
  if ">official source</a>" in html_page: shown["source"] = True
  if "4WD (dry weather)" in html_page: shown["access"] = True
  if "Follow signs on site" in html_page: shown["follow"] = True
  if "Dogs: on lead" in html_page or "Dogs: yes (on lead)" in html_page: shown["dogs"] = True
for key in shown:
  if not shown[key]: bad.append(("osm pages", "missing example of " + key))
for r, _, fs in os.walk(D):
  for f in fs:
    if "osm-camps" in f: bad.append((f, "combined dataset published"))
if "osm-camps-vic" in home or "osm-camps-vic" in about: bad.append(("download", "combined dataset linked"))
import classify, towns as townmod, build_osm
allowed = {"free", "donation", "showground", "council_park", "council_park_leased", "rest_area"}
curated = json.load(open(os.path.join(root, "data", "osm-camps-vic.json"), encoding="utf-8"))
curated_sites = curated["sites"] if isinstance(curated, dict) else curated
corr_path = os.path.join(root, "data", "manual-corrections.json")
if set(s.get("category") for s in curated_sites) - allowed: bad.append(("osm data", "category outside the six"))
merged = build_osm.apply_corrections(curated_sites, build_osm.load_corrections(corr_path))
if len(merged) != len(osm): bad.append(("osm", f"built {len(osm)} overlay {len(merged)}"))
labels = {c.get("category") for c in osm}
if labels - {"Free", "Donation", "Showground", "Council park", "Council park (leased)", "Rest area", "Pub stay", "Paid – Parks Victoria (book ahead)"}: bad.append(("osm", labels))
expect_counts = {"Free": 1075, "Council park": 68, "Showground": 40, "Paid – Parks Victoria (book ahead)": 52, "Rest area": 24, "Donation": 11, "Pub stay": 6, "Council park (leased)": 3}
got_counts = {}
for camp in osm: got_counts[camp.get("category")] = got_counts.get(camp.get("category"), 0) + 1
if got_counts != expect_counts: bad.append(("osm", got_counts))
if sum(1 for c in osm if c.get("needs_review")) != sum(1 for c in osm if c.get("needs_review") is True): bad.append(("osm", "review flag"))
if not any(c.get("needs_review") is False for c in osm): bad.append(("osm", "no confirmed sites"))
if any(classify.CHAIN.search(s.get("name") or "") for s in curated_sites): bad.append(("osm data", "chain name kept"))
if any(classify.EXCL.search(s.get("name") or "") for s in curated_sites): bad.append(("osm data", "hiker or group name kept"))
show = classify.decide({"name": "Echuca Showgrounds"})
if not show or show["category"] != "showground" or show["label"] != "call first" or not show["needs_review"]: bad.append(("classify", "showground"))
if (classify.decide({"tourism": "camp_site", "fee": "no", "name": "Apex"}) or {}).get("category") != "free": bad.append(("classify", "free"))
if (classify.decide({"tourism": "camp_site", "fee": "donation", "name": "Mill"}) or {}).get("category") != "donation": bad.append(("classify", "donation"))
council = classify.decide({"tourism": "caravan_site", "operator": "Campaspe Shire Council", "fee": "no", "name": "Park"})
if not council or council["category"] != "council_park": bad.append(("classify", "council"))
leased = classify.decide({"tourism": "caravan_site", "name": "Marlo Caravan Park"})
if not leased or leased["category"] != "council_park_leased" or not leased["needs_review"]: bad.append(("classify", "leased"))
rest = classify.decide({"highway": "rest_area", "camping": "yes", "name": "Night Rest Area"})
if not rest or rest["category"] != "rest_area": bad.append(("classify", "rest"))
if classify.decide({"highway": "rest_area", "name": "Day use"}): bad.append(("classify", "day rest area"))
if classify.decide({"tourism": "camp_site", "name": ""}): bad.append(("classify", "unnamed"))
if classify.decide({"tourism": "camp_site", "name": "."}): bad.append(("classify", "dot name"))
if classify.decide({"tourism": "camp_site", "name": "Quiet", "access": "private"}): bad.append(("classify", "private"))
if classify.decide({"tourism": "camp_site", "name": "Old", "disused": "yes"}): bad.append(("classify", "disused"))
if classify.decide({"tourism": "camp_site", "name": "Mount Thackeray Hiker Camp"}): bad.append(("classify", "hiker"))
if classify.decide({"tourism": "camp_site", "name": "Stoney Creek Group Camping Area"}): bad.append(("classify", "group"))
if classify.decide({"tourism": "camp_site", "name": "1st Camberwell Scout Camp"}): bad.append(("classify", "scout"))
if classify.decide({"tourism": "caravan_site", "name": "Discovery Parks Melbourne", "brand": "Discovery"}): bad.append(("classify", "chain"))
if classify.decide({"tourism": "caravan_site", "name": "BIG4 Bendigo Park Lane"}): bad.append(("classify", "big4"))
if classify.decide({"tourism": "caravan_site", "name": "Hamilton Caravan Park"}): bad.append(("classify", "commercial"))
unknown = classify.decide({"tourism": "camp_site", "name": "Border RA"})
if not unknown or unknown["category"] != "free" or not unknown["needs_review"] or unknown["dogs"] != "unknown": bad.append(("classify", "unconfirmed free"))
if classify.decide({"tourism": "camp_site", "name": "Paid Camp", "fee": "yes"}): bad.append(("classify", "paid other"))
if townmod.place_rank({"place": "town", "name": "Bendigo"}) != 0 or townmod.place_rank({"place": "locality", "name": "X"}) != 1: bad.append(("towns", "rank"))
if townmod.place_rank({"place": "isolated_dwelling", "name": "X"}) is not None: bad.append(("towns", "skip"))
before = os.path.getmtime(corr_path)
corrections = json.load(open(corr_path, encoding="utf-8"))
if not isinstance(corrections, dict) or len(corrections) != 1041 or "drop" in corrections or "overrides" in corrections:
  bad.append(("corrections", "shape"))
if sum(1 for v in corrections.values() if isinstance(v, dict) and v.get("exclude")) != 107: bad.append(("corrections", "exclusions"))
if sum(1 for k, v in corrections.items() if str(k).startswith("new:") and isinstance(v, dict) and not v.get("exclude") and "lat" in v and "lon" in v) != 439:
  bad.append(("corrections", "new sites"))
import facts
suit_cases = [
  ("tent|caravan|motorhome", (True, True, True)),
  ("tents, caravans", (True, True, None)),
  ("Tents, Caravans, Motorhomes", (True, True, True)),
  ("tents, caravans, campervans; limited powered sites", (True, True, True)),
  ("caravan", (None, True, None)),
  ("4WD only, river crossings", (None, None, None)),
  ("unknown", (None, None, None)),
  ("tents only (walk-in about 300 m, single site; no vehicle camping)", (True, None, None)),
]
for raw, expect in suit_cases:
  if facts.suit_flags(raw) != expect: bad.append(("suits", raw))
if facts.fee_label("paid") != "Paid – book ahead" or facts.fee_label("free") != "Free" or facts.fee_label("$25") != "": bad.append(("fee", "label"))
if "$" in facts.scrub_money("yes ($5 public)") or facts.yn_flag("yes ($5 public)") is not True: bad.append(("fee", "amount"))
if facts.booking_label("not required") != "No" or facts.booking_label("required (Parks Victoria)") != "Yes": bad.append(("booking", "label"))
dv_path = os.path.join(root, "data", "datavic-enrichment.json")
dv_before = os.path.getmtime(dv_path)
dv_doc = json.load(open(dv_path, encoding="utf-8"))
dv_camps = dv_doc.get("camps") or {}
if len(dv_camps) != 116 or dv_doc.get("_meta", {}).get("count") != 116: bad.append(("datavic enrichment", "count"))
build_src = open(os.path.join(root, "scripts", "build.py"), encoding="utf-8").read()
if "datavic-enrichment.json" not in build_src or re.search(r"open\(\s*.*datavic-enrichment[^)]*[\"']w", build_src): bad.append(("build.py", "enrichment write"))
if "apply_row_facts" not in build_src or "_FACT_PROTECTED" not in build_src: bad.append(("build.py", "status guard"))
def page_of(slug):
  path = os.path.join(D, "vic", "camp", slug, "index.html")
  if not os.path.isfile(path):
    bad.append((slug, "missing sample")); return ""
  return open(path, encoding="utf-8").read()
def must(slug, html_page, bits):
  for bit in bits:
    if bit not in html_page: bad.append((slug, "missing " + bit))
king = page_of("king-hut-alpine-np")
must("king-hut-alpine-np", king, ["Drinking water: No", "Dogs: No", "<strong>Free</strong>", "bring your own drinking water", "Checked against official source, 18 October 2026", ">official source</a>", "parks.vic.gov.au"])
if "Unverified, help us confirm" in king: bad.append(("king-hut-alpine-np", "still unverified"))
if "$" in king.split('id="newsletter"')[0]: bad.append(("king-hut-alpine-np", "fee amount"))
dargo = page_of("dargo-river-inn")
must("dargo-river-inn", dargo, ["Pub stay", "<strong>Paid – book ahead</strong>", "Toilets: Yes", "Showers: Yes", "Tents: Yes", "Caravans: Yes", "Motorhomes: Yes", 'href="tel:0351401330"', "info@dargoriverinn.com.au", "Checked against official source, 18 October 2026"])
if "$" in dargo.split('id="newsletter"')[0]: bad.append(("dargo-river-inn", "fee amount"))
goulburn = page_of("angling-club-bend-camping-area-lower-goulburn-national-park-goulburn-river-heritage-river")
must("angling-club-bend", goulburn, ["Lower Goulburn National Park", "Dogs: No", 'href="tel:131963"', "parks.vic.gov.au", "Checked against official source"])
murray = page_of("abbotsford-bend-camping-area-murray-river")
must("abbotsford-bend", murray, ["<strong>Free</strong>", "Booking required:</strong> No", "Dogs: on lead", "Murray", "Checked against official source, 18 October 2026"])
orchard = page_of("the-orchard")
must("the-orchard", orchard, ["Toilets: Yes", "Drinking water: No", "Water source: reliable access to water (not stated as drinkable)", "Booking required:</strong> No", "<strong>Free</strong>", "Caravans: Yes", "Access: 2WD access", "exploreoutdoors.vic.gov.au", "Checked against official source, 18 October 2026"])
if "Tents: Yes" in orchard or "Matched via the Delatite" in orchard or "Operator: MANSFIELD" in orchard: bad.append(("the-orchard", "suits, flag or raw maintainer"))
if "$" in orchard.split('id="newsletter"')[0]: bad.append(("the-orchard", "fee amount"))
horseshoe = page_of("horseshoe-bend-camping-area")
must("horseshoe-bend", horseshoe, ["Rubbish: take rubbish home", "Toilets: Yes", 'class="badge check"'])
avondale = next((c for c in feed["camps"] if c.get("slug") == "avondale-gardens"), None)
if not avondale or avondale.get("status") != "closed" or avondale.get("source") != "datavic" or avondale.get("closure") in (None, {}, []):
  bad.append(("avondale-gardens", "closure changed"))
else:
  av_html = page_of("avondale-gardens")
  must("avondale-gardens", av_html, ['class="badge closed"', "<strong>Closed:</strong>", "<strong>Free</strong>", "Dogs: Yes"])
for slug, tents, vans, homes, self_flag in (("dargo-river-inn", 1, 1, 1, None), ("coleraine-caravan-park", 1, 1, 1, 0)):
  point = next((p for p in home_pts if p.get("url", "").rstrip("/").endswith("/" + slug)), None)
  if not point or point.get("tents") != tents or point.get("caravans") != vans or point.get("motorhomes") != homes:
    bad.append((slug, "map suit flags"))
  elif self_flag is not None and point.get("self") != self_flag:
    bad.append((slug, "map self flag"))
applied = 0
for row in dv_camps.values():
  html_page = page_of(row["slug"])
  if "Checked against official source" not in html_page: bad.append((row["slug"], "enrichment missing"))
  else: applied += 1
if applied != 116: bad.append(("datavic enrichment", applied))
if os.path.getmtime(dv_path) != dv_before: bad.append(("datavic enrichment", "file overwritten"))
kept = build_osm.apply_corrections([{"osm_id": "node/1", "name": "A"}, {"osm_id": "node/2", "name": "B"}], {"drop": ["node/1"], "overrides": {"node/2": {"category": "Free"}}})
if [c["osm_id"] for c in kept] != ["node/2"] or kept[0]["category"] != "Free": bad.append(("corrections", "legacy apply"))
overlay = build_osm.apply_corrections(
  [{"osm_id": "n1", "name": "Stop", "category": "free", "needs_review": True}, {"osm_id": "n2", "name": "Old", "category": "free", "needs_review": True}],
  {"n1": {"exclude": "bus stop", "checked_date": "2026-10-16"}, "n2": {"category": "pub_stay", "needs_review": False, "phone": "13 1963"},
   "new:pub": {"name": "Pub Camp", "lat": -37.1, "lon": 144.2, "category": "pub_stay", "new": True, "needs_review": False}})
if [c["osm_id"] for c in overlay] != ["n2", "new:pub"] or overlay[0]["category"] != "pub_stay" or overlay[0]["needs_review"] is not False or overlay[1]["lat"] != -37.1:
  bad.append(("corrections", "overlay apply"))
again = build_osm.apply_corrections(overlay, {"n1": {"exclude": "bus stop"}, "n2": {"category": "pub_stay", "needs_review": False}, "new:pub": {"name": "Pub Camp", "lat": -37.1, "lon": 144.2, "category": "pub_stay", "new": True}})
if [c["osm_id"] for c in again] != ["n2", "new:pub"]: bad.append(("corrections", "overlay twice"))
if os.path.getmtime(corr_path) != before: bad.append(("corrections", "file overwritten"))
osm_src = open(os.path.join(root, "scripts", "build_osm.py"), encoding="utf-8").read()
if "manual-corrections.json" not in osm_src or re.search(r"open\(\s*CORRECTIONS\s*,\s*[\"']w", osm_src): bad.append(("build_osm.py", "corrections write"))
refresh = open(os.path.join(root, ".github", "workflows", "refresh-osm.yml"), encoding="utf-8").read()
if "wrangler" in refresh or "pages deploy" in refresh or "--branch=main" in refresh: bad.append(("refresh-osm.yml", "must not deploy"))
add = refresh.split("git add", 1)[1].split("git commit", 1)[0]
if "manual-corrections" in add or "osm-camps-vic.json" not in add or "vic-towns.json" not in add: bad.append(("refresh-osm.yml", "git add"))
if "20 18 * * 1" not in refresh: bad.append(("refresh-osm.yml", "weekly schedule"))
preview = open(os.path.join(root, ".github", "workflows", "preview-more-sites.yml"), encoding="utf-8").read()
if "feature/more-sites" not in preview or "--branch=main" in preview or 'branches: [main]' in preview: bad.append(("preview-more-sites.yml", "branch"))
if 'if [ "$branch" = "main" ]' not in preview: bad.append(("preview-more-sites.yml", "refuse main"))
if "feature/more-sites" in wf or "17 */3 * * *" not in wf: bad.append(("build-deploy.yml", "production schedule"))
print(f"{n} pages, {ldn} JSON-LD blocks valid, {len(sm)} sitemap URLs, {len(home_pts)} map points, {len(bad)} broken"); [print(b) for b in bad[:20]]; sys.exit(1 if bad else 0)
