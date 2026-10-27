import gzip,os,re,json,sys,html,math,subprocess,tempfile,urllib.parse
D=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"dist");bad=[];warnings=[];n=0;ldn=0
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
    if "paid daily digest" in t or "about $5 a month" in t: bad.append((p[len(D):], "paid digest line"))
for f in ["sitemap.xml","robots.txt","llms.txt","status.json"]: assert os.path.isfile(os.path.join(D,f)),f
json.load(open(os.path.join(D,"status.json")))
sm=re.findall(r"<loc>https://campconditions.au(.*?)</loc>",open(os.path.join(D,"sitemap.xml")).read())
for u in sm:
  if not os.path.isfile(os.path.join(D,u.lstrip("/"),"index.html")): bad.append(("sitemap",u))
feed=json.load(open(os.path.join(D,"status.json")))
vic_feed=[c for c in feed["camps"] if "/vic/camp/" in c.get("url","")]
def map_data(where, html, vic_only=True):
  m=re.search(r'<script type="application/json" id="camp-map-data"([^>]*)>(.*?)</script>', html, re.S)
  if not m:
    bad.append((where, "missing camp-map-data")); return []
  url_m = re.search(r'data-url="([^"]+)"', m.group(1))
  try:
    if url_m:
      rel = url_m.group(1).split("?", 1)[0].lstrip("/")
      data = json.load(open(os.path.join(D, rel), encoding="utf-8"))
    else:
      data = json.loads(m.group(2))
  except Exception as ex:
    bad.append((where, f"map json {ex}")); return []
  if not isinstance(data, list):
    bad.append((where, "map data not a list")); return []
  for i, pt in enumerate(data):
    if not all(k in pt for k in ("name","lat","lon","status","url")):
      bad.append((where, f"map point {i} fields")); break
    if pt["status"] not in ("open","check","closed") or not isinstance(pt["lat"], (int, float)) or not isinstance(pt["lon"], (int, float)):
      bad.append((where, f"map point {i} values")); break
    if not os.path.isfile(os.path.join(D, pt["url"].lstrip("/"), "index.html")) or (vic_only and not str(pt["url"]).startswith("/vic/camp/")):
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
national = os.path.isfile(os.path.join(D, "nsw", "index.html"))
overview = vic if national else home
if national:
  if 'id="state-jump"' in home: bad.append(("/", "state jump cards"))
  if 'src="/map.js"' in home or 'src="/map-home.js"' not in home or 'id="camp-map"' not in home: bad.append(("/", "national map"))
  if "leaflet.markercluster" not in home: bad.append(("/", "national cluster"))
  home_pts = expect_map("/vic/", overview, True)
  vic_pts = home_pts
else:
  home_pts, vic_pts=expect_map("/", home, True), expect_map("/vic/", vic, True)
if len(home_pts)!=len(vic_feed) or len(vic_pts)!=len(vic_feed): bad.append(("overview", "map count"))
if not home_pts or not home_pts[0].get("slug"): bad.append(("overview", "map slug"))
home_urls={p["url"] for p in home_pts}
if home_urls!={c["url"].replace("https://campconditions.au","") for c in vic_feed}: bad.append(("overview","map urls"))
by_point = {p["url"]: p for p in home_pts}
for p in home_pts:
  if p.get("cost") not in ("", "free", "paid") or p.get("type") not in ("", "Showground", "Council", "Rest area", "Parks Victoria"):
    bad.append((p["url"], "filter fields")); break
  if p.get("cat") == "Pub stay" and p.get("type"): bad.append((p["url"], "pub stay filtered")); break
  if p.get("cat") in ("Council park", "Council park (leased)") and p.get("type") != "Council": bad.append((p["url"], "council merge")); break
  if p.get("cat") in ("Park campground", "Paid – Parks Victoria (book ahead)") and p.get("type") != "Parks Victoria": bad.append((p["url"], "parks merge")); break
ah = by_point.get("/vic/camp/ah-youngs/")
if not ah or ah.get("cost") != "free" or ah.get("type") != "Parks Victoria": bad.append(("ah-youngs", "datavic free cost"))
bull = by_point.get("/vic/camp/bull-creek/")
if not bull or bull.get("cost") != "paid" or bull.get("type") != "Parks Victoria": bad.append(("bull-creek", "datavic paid cost"))
if sum(1 for p in home_pts if p.get("cost") == "free" and p.get("type") == "Parks Victoria") < 100: bad.append(("filters", "datavic free missing"))
if "sha384-uIZNAcoEHVWMk8LrCSX95DJk6FQzH6zG00LQC9BykRY1UKKpkDzDhbDLYQ1Ho3mI" not in overview or "crossorigin=" not in overview: bad.append(("sri", "markercluster css"))
if "sha384-uIZNAcoEHVWMk8LrCSX95DJk6FQzH6zG00LQC9BykRY1UKKpkDzDhbDLYQ1HoRdVx8nYU4LQ5eGzI" in overview: bad.append(("sri", "old markercluster css hash"))
by={}
for c in vic_feed: by.setdefault(c["region"], []).append(c)
for name in os.listdir(os.path.join(D,"vic")):
  page=os.path.join(D,"vic",name,"index.html")
  if name=="camp" or not os.path.isfile(page): continue
  pts=expect_map(f"/vic/{name}/", open(page, encoding="utf-8").read(), True)
  if len(pts)!=len(by.get(name, [])): bad.append((f"/vic/{name}/", "region map count"))
page_titles=[]
for slug in os.listdir(os.path.join(D,"vic","camp")):
  page=os.path.join(D,"vic","camp",slug,"index.html")
  if not os.path.isfile(page): continue
  html_page=open(page, encoding="utf-8").read(); pts=expect_map(f"/vic/camp/{slug}/", html_page, False)
  if len(pts)!=1 or pts[0]["url"]!=f"/vic/camp/{slug}/": bad.append((slug, "camp map"))
  elif f"destination={pts[0]['lat']},{pts[0]['lon']}" not in html_page or "Directions in Google Maps" not in html_page or "map-sm" not in html_page:
    bad.append((slug, "directions"))
  elif "Find nearby toilets" not in html_page or 'href="https://toiletmap.gov.au/"' not in html_page or 'target="_blank"' not in html_page.split("Find nearby toilets", 1)[0][-80:]:
    bad.append((slug, "toilets"))
  else:
    lat, lon = pts[0]["lat"], pts[0]["lon"]; pad = 0.2
    bbox = f"https://emergency.vic.gov.au/respond/?bbox={lon-pad:.5f},{lat-pad:.5f},{lon+pad:.5f},{lat+pad:.5f}"
    if "Check VicEmergency for warnings near this camp" not in html_page or bbox not in html_page:
      bad.append((slug, "vicemergency link"))
    if "1800 226 226" not in html_page or ">000<" not in html_page:
      bad.append((slug, "emergency hotline"))
    if 'class="digest-cta" href="/#newsletter" aria-label="Free weekly newsletter"' not in html_page:
      bad.append((slug, "newsletter button"))
    if 'href="https://traffic.transport.vic.gov.au/"' not in html_page or "Check road closures" not in html_page or html_page.find("Find nearby toilets") > html_page.find("Check road closures"):
      bad.append((slug, "road closures"))
    if "traffic.vicroads.vic.gov.au" in html_page or "https://traffic.transport.vic.gov.au/?" in html_page:
      bad.append((slug, "invented vicroads url"))
    if "Also check" not in html_page or "Parks Victoria alerts" not in html_page or "for park camps" not in html_page or 'href="https://www.parks.vic.gov.au/coc-listing"' not in html_page:
      bad.append((slug, "parks alerts"))
  title_m = re.search(r"<title>(.*?)</title>", html_page)
  h1_m = re.search(r"<h1>(.*?)</h1>", html_page)
  if not title_m or not h1_m or h1_m.group(1) not in title_m.group(1): bad.append((slug, "title"))
  else: page_titles.append(title_m.group(1))
dup_titles = [t for t in set(page_titles) if page_titles.count(t) > 1]
if dup_titles: bad.append(("duplicate titles", dup_titles[:3]))
def named(name): return [c for c in feed["camps"] if c.get("name") == name]
if named("1 Wild Cherry Camp") or not named("Wild Cherry Camp") or named("Wild Cherry Camp")[0]["slug"] != "1-wild-cherry-camp": bad.append(("rename", "wild cherry"))
if not named("6 Mile Flat") or not any(c["name"].startswith("82 Bend Camping Area") for c in feed["camps"]): bad.append(("rename", "kept unit name"))
cherry = open(os.path.join(D, "vic", "camp", "1-wild-cherry-camp", "index.html"), encoding="utf-8").read()
if "<h1>Wild Cherry Camp</h1>" not in cherry or "<h1>1 Wild Cherry" in cherry or "<title>1 Wild Cherry" in cherry: bad.append(("1-wild-cherry-camp", "display name"))
for shore in named("Foreshore Reserve"):
  shore_html = open(os.path.join(D, "vic", "camp", shore["slug"], "index.html"), encoding="utf-8").read()
  if "<h1>Foreshore Reserve, near " not in shore_html: bad.append((shore["slug"], "near town"))
thin = open(os.path.join(D, "vic", "camp", "langfords-west-campground", "index.html"), encoding="utf-8").read()
if "Other facilities not yet confirmed. Know this spot?" not in thin or 'href="/report/?camp=langfords-west-campground&name=' not in thin or "Dogs: Unknown" in thin or "Showers: Unknown" in thin: bad.append(("langfords-west-campground", "thin facilities"))
kurra = open(os.path.join(D, "vic", "camp", "mount-lawson-state-park-the-kurrajongs", "index.html"), encoding="utf-8").read()
if ("Other facilities not yet confirmed. Know this spot?" not in kurra or 'href="/report/?camp=mount-lawson-state-park-the-kurrajongs&name=' not in kurra
    or "Dump point: Unknown" in kurra or "Motorhomes: Unknown" in kurra or "Dogs: No" not in kurra or "Tents: Yes" not in kurra):
  bad.append(("mount-lawson-state-park-the-kurrajongs", "known-only facilities"))
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
        rel = os.path.join(r, f)
        # Victoria camp rules may mention fire-danger days. NSW pages quote the RFS district rating.
        shared_ok = national and (os.path.dirname(rel) == D and f in ("index.html", "status.json", "llms.txt", "404.html") or any(bit in rel for bit in (f"{os.sep}about{os.sep}", f"{os.sep}privacy{os.sep}", f"{os.sep}terms{os.sep}", f"{os.sep}report{os.sep}", f"{os.sep}unsubscribe{os.sep}")))
        if needle == "fire danger" and (f"{os.sep}vic{os.sep}camp{os.sep}" in rel or f"{os.sep}nsw{os.sep}" in rel or f == "parksvic-flags.json" or shared_ok):
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
  for bit in ("Last updated 27 October 2026", "campconditions@outlook.com", "Victoria and New South Wales", "email address", "date and time", "tracking cookies", "Cloudflare", "IP address", "Resend", "outside Australia", "double opt-in", "unsubscribe link", "within 30 days", "OAIC", "never sell, rent or share", "Changes to this policy"):
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
  if 'src="https://campconditions.au/assets/brand/logo-160.png"' not in open(os.path.join(draft, "digest.html"), encoding="utf-8").read():
    bad.append(("digest.html", "logo"))
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
  if (blob.includes("Victoria digest")) process.exit(1);
}
if (!m.html.includes("digest for Victoria") || !m.text.includes("digest for Victoria")) process.exit(1);
const both = confirmationMessage("https://campconditions.au", "https://campconditions.au/api/confirm?token=abc", unsub, ["nsw", "vic"]);
if (!both.html.includes("digest for Victoria and New South Wales") || both.text.includes("Victoria digest")) process.exit(1);
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
import { makeToken, readToken } from "./functions/_lib/token.js";
const oldToken = await makeToken(email, "test-secret");
const oldRead = await readToken(oldToken, "test-secret");
if (!oldRead || oldRead.email !== email || oldRead.explicit || oldRead.states.join(",") !== "vic") process.exit(1);
const nswToken = await makeToken(email, "test-secret", 60 * 60 * 48, ["nsw"]);
const nswRead = await readToken(nswToken, "test-secret");
if (!nswRead || !nswRead.explicit || nswRead.states.join(",") !== "nsw") process.exit(1);
const callsNsw = [];
const mockNsw = async (url, init) => {
  callsNsw.push({ url, method: init.method, body: init.body });
  return new Response(JSON.stringify({ id: "c1" }), { status: 201 });
};
const nswOnly = await confirmSubscription({ ...envWithSecret, RESEND_SEGMENT_NSW_ID: "nsw-segment" }, email, mockNsw, ["nsw"], true);
if (!nswOnly.ok) process.exit(1);
if (callsNsw.some((call) => String(call.url).includes(segment))) process.exit(1);
if (!callsNsw.some((call) => String(call.url).endsWith("/segments/nsw-segment") && call.method === "POST" && call.body === undefined)) process.exit(1);
if (!callsNsw.some((call) => call.method === "PATCH" && call.body && call.body.includes('"states":"nsw"'))) process.exit(1);
const callsLost = [];
const mockLost = async (url, init) => {
  callsLost.push({ url, method: init.method, body: init.body });
  if (url.endsWith("/contacts") && init.method === "POST") return new Response(JSON.stringify({ id: "c1" }), { status: 201 });
  if (init.method === "PATCH") return new Response(JSON.stringify({ name: "validation_error" }), { status: 422 });
  if (url.endsWith("/segments/" + segment)) return new Response(JSON.stringify({ id: segment }), { status: 200 });
  return new Response("no", { status: 500 });
};
const kept = await confirmSubscription(envWithSecret, email, mockLost, ["vic"], true);
if (!kept.ok || !callsLost.some((call) => String(call.url).endsWith("/segments/" + segment))) process.exit(1);
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

CREDIT = "Campground and town data © OpenStreetMap contributors (ODbL); Campground details from DataVic and Explore Outdoors © State of Victoria (DEECA), CC BY 4.0, and Parks Victoria."
sys.path.insert(0, os.path.join(root, "scripts"))
import states
if states.by_slug("vic").get("credit") != CREDIT: bad.append(("states", "credit"))
if [state["slug"] for state in states.enabled()] != ["vic", "nsw"]: bad.append(("states", "enabled"))
if not states.by_slug("nsw").get("enabled") or not states.by_slug("vic").get("enabled"): bad.append(("states", "flags"))
os.environ["CAMPCONDITIONS_ENABLE"] = "nsw"
try:
  if [state["slug"] for state in states.enabled()] != ["vic", "nsw"]: bad.append(("states", "preview enable"))
finally:
  os.environ.pop("CAMPCONDITIONS_ENABLE", None)
if [state["slug"] for state in states.enabled()] != ["vic", "nsw"]: bad.append(("states", "enable reset"))
about = open(os.path.join(D, "about", "index.html"), encoding="utf-8").read()
if CREDIT not in home or CREDIT not in about: bad.append(("credit", "footer or about"))
if "Department of Energy, Environment and Climate Action" not in about or "Explore Outdoors" not in about or "Recreation Assets" not in home: bad.append(("credit", "explore outdoors"))
if "font-size:1.7rem" not in home or "font-weight:700" not in home or 'class="brand"' not in home or 'class="logo"' not in home or "font-size:2.4rem" not in home:
  bad.append(("/", "banner"))
if national:
  if 'class="soon"' in home or 'class="soon"' in overview or "Covering Victoria now" in home or "Covering Victoria now" in overview or "Other states coming soon" in home:
    bad.append(("/", "soon bar"))
elif "Covering Victoria now" not in overview or "Other states coming soon" not in overview or 'class="soon"' not in overview:
  bad.append(("/", "banner"))
if 'class="digest-cta" href="#newsletter" aria-label="Free weekly newsletter"' not in home or "Free weekly newsletter" not in home or "Free newsletter" not in home or 'class="digest-icon"' not in home or 'aria-hidden="true"' not in home:
  bad.append(("/", "newsletter button"))
if ".digest-cta:focus-visible" not in home or ".digest-cta-short{display:none}" not in home or ".digest-cta-short{display:inline}" not in home:
  bad.append(("/", "newsletter button style"))
if 'querySelectorAll("a.digest-cta")' not in home or "email.focus({ preventScroll: true })" not in home or 'getAttribute("href") !== "#newsletter"' not in home:
  bad.append(("/", "newsletter button focus"))
if 'class="digest-cta" href="/#newsletter" aria-label="Free weekly newsletter"' not in about:
  bad.append(("about", "newsletter button"))
if 'id="a2hs"' not in home or "campconditions-a2hs" not in home or "localStorage.getItem" not in home or "Add to Home Screen." not in home or "Add to Home screen or Install app." not in home or "iPad|iPhone|iPod" not in home or "/Android/i" not in home or "display-mode: standalone" not in home:
  bad.append(("/", "home screen tip"))
if "in Safari, tap Share, then Add to Home Screen." not in home or "in Chrome, tap the menu" not in home:
  bad.append(("/", "home screen steps"))
if 'id="share-page"' not in home or "navigator.share" not in home or "clipboard.writeText" not in home or "Copy this link" not in home:
  bad.append(("/", "share"))
if 'id="updated-line"' not in home or 'id="refresh-data"' not in home or "Updated " not in home or 'id="count-closed"' not in overview:
  bad.append(("/", "updated line"))
if 'cache: "no-store"' not in home or "/status.json?v=" not in home or "visibilitychange" not in home or "pageshow" not in home or 'name="campconditions-built"' not in home:
  bad.append(("/", "fresh status"))
if "campApplyStatus" not in mj or "applyLiveStatus" not in mj:
  bad.append(("map.js", "live status"))
if 'name="apple-mobile-web-app-capable"' not in home or 'name="apple-mobile-web-app-title"' not in home or 'name="mobile-web-app-capable"' not in home or 'name="apple-mobile-web-app-status-bar-style"' not in home:
  bad.append(("/", "apple web app"))
headers = open(os.path.join(D, "_headers"), encoding="utf-8").read()
if "/status.json" not in headers or "/vic/*" not in headers or headers.count("Cache-Control: no-cache") < 8 or "/assets/" in headers:
  bad.append(("_headers", "no-cache"))
if home.find('href="/report/">Report conditions') < 0 or home.find('href="/about/">About') < home.find('href="/report/">Report conditions'):
  bad.append(("/", "about nav"))
if "flex:1 0 100%;flex-wrap:nowrap" not in home:
  bad.append(("/", "nav collapse"))
if 'class="filter-status"' not in overview or 'class="filter-status-rule"' not in overview or overview.find('class="hide-closed"') > overview.find('id="filter-count"'):
  bad.append(("/", "filter separation"))
if ".filter-status{display:flex;flex-direction:column" not in home:
  bad.append(("/", "phone filter count"))
if "Add to Home Screen." not in about or "Add to Home screen or Install app." not in about:
  bad.append(("about", "home screen"))
contact = 'Feedback, corrections or questions? Email us at <a href="mailto:campconditions@outlook.com">campconditions@outlook.com</a>'
if about.find(contact) < 0 or about.find(contact) < about.find("Optimum Quest for Big Things") or about.find("Not an official warning service") < about.find(contact):
  bad.append(("about", "contact line"))
if "Find nearby toilets" not in about or "https://toiletmap.gov.au/" not in about or "Australian Government" not in about or "National Public Toilet Map" not in about:
  bad.append(("about", "toilet map"))
if "Check road closures" not in about or 'href="https://traffic.transport.vic.gov.au/"' not in about or "VicTraffic" not in about or "Victorian Government" not in about or "official live map of road closures and incidents" not in about or "Check it before you head out." not in about:
  bad.append(("about", "victraffic"))
report = open(os.path.join(D, "report", "index.html"), encoding="utf-8").read()
if 'class="back-map" href="/">← Back to map' not in report or 'id="report-mail"' not in report or "mailto:campconditions@outlook.com" not in report or "nothing was sent" in report or "<form" in report:
  bad.append(("report", "mailto"))
if 'alt="CampConditions.au logo"' not in home or 'src="/assets/brand/logo-160.png"' not in home or 'width="160" height="160"' not in home or ".logo{width:4.8rem;height:4.8rem" not in home or "15.9vw" not in home:
  bad.append(("/", "logo"))
if "optimum-quest" in home or "⛺" in home.split("<main>", 1)[0]: bad.append(("/", "old tent logo"))
for icon in ("/assets/brand/favicon.ico", "/assets/brand/favicon-32.png", "/assets/brand/apple-touch-icon.png", "/site.webmanifest", 'content="https://campconditions.au/assets/brand/og-image.png"', 'content="1200"', 'content="630"', 'content="summary_large_image"'):
  if icon not in home: bad.append(("/", "icon " + icon))
not_found = open(os.path.join(D, "404.html"), encoding="utf-8").read()
if "/site.webmanifest" not in not_found or "og-image.png" not in not_found: bad.append(("404", "icons"))
if 'class="digest-cta" href="/#newsletter"' not in not_found: bad.append(("404", "newsletter button"))
logo = os.path.join(D, "assets", "brand", "logo-160.png")
if not os.path.isfile(logo) or os.path.getsize(logo) < 1000: bad.append(("logo-160.png", os.path.getsize(logo) if os.path.isfile(logo) else "missing"))
manifest = json.load(open(os.path.join(D, "site.webmanifest"), encoding="utf-8"))
if manifest.get("name") != "CampConditions.au" or manifest.get("theme_color") != "#113521" or manifest.get("background_color") != "#F5ECD6" or manifest.get("display") != "standalone":
  bad.append(("site.webmanifest", "brand"))
icons = manifest.get("icons") or []
if not any("icon-192.png" in (i.get("src") or "") for i in icons) or not any("icon-512.png" in (i.get("src") or "") for i in icons):
  bad.append(("site.webmanifest", "icons"))
if 'rel="apple-touch-icon" href="/assets/brand/apple-touch-icon.png"' not in home:
  bad.append(("/", "apple touch icon"))
for icon_name in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "og-image.png"):
  if not os.path.isfile(os.path.join(D, "assets", "brand", icon_name)): bad.append((icon_name, "missing"))
if os.path.exists(os.path.join(D, "optimum-quest-logo.webp")) or os.path.exists(os.path.join(root, "assets", "optimum-quest-logo.webp")):
  bad.append(("optimum-quest-logo.webp", "still present"))
if ((not national) and overview.find("<nav>") > overview.find('class="soon"')) or home.find("<nav>") < 0 or "justify-content:flex-start" not in home or "justify-content:flex-end" in home or ".digest-cta{order:2;margin-left:auto" not in home:
  bad.append(("/", "nav alignment"))
if "download" in about.lower() and "osm-camps" in about.lower(): bad.append(("about", "combined download"))
page_js = open(os.path.join(root, "functions", "_lib", "page.js"), encoding="utf-8").read()
if "⛺" in page_js or 'src="/assets/brand/logo-160.png"' not in page_js: bad.append(("page.js", "logo"))
for fn in ("functions/api/confirm.js", "functions/api/subscribe.js"):
  src = open(os.path.join(root, fn), encoding="utf-8").read()
  if "sitePage" not in src: bad.append((fn, "confirmation page logo"))
for bit in ("Search by town or camp name", 'id="town-search"', 'role="combobox"', 'aria-haspopup="listbox"', 'aria-live="polite"', 'id="camp-filters"', "Known to be free/donation", 'name="cost" value="free"', "Known to be paid", 'name="cost" value="paid"', "Showground", 'value="Council"', 'value="Rest area"', 'value="Parks Victoria"', "Dogs OK", "Known to suit caravans", "Known to suit motorhomes", "These filters only show sites where the detail is confirmed.", "Hide closed", 'data-flag="hide-closed"', 'id="filter-count"', "Showing ", " of ", " camps", "No camps match these filters", 'id="filter-clear"', "Clear filters", 'class="page-head"', 'class="head-counts"', 'id="filters-all"', 'id="filter-btn-cost"', 'id="filter-panel-facilities"', 'aria-expanded="false"', "font-size:16px", 'id="filter-done"', 'id="filter-sheet-close"', 'id="filter-backdrop"', "Show "):
  if bit not in overview: bad.append(("/", "missing " + bit))
if "Right now" in overview: bad.append(("/", "counts still in the intro"))
fac = overview.find('id="filter-panel-facilities"')
note = overview.find("These filters only show sites where the detail is confirmed.")
count_at = overview.find('id="filter-count"')
if not (0 <= fac < note < count_at): bad.append(("/", "facility note not in the popover"))
if overview.find('class="head-counts"') > overview.find("campgrounds across Victoria"): bad.append(("/", "counts below the intro"))
for bit in ('value="Free"', 'value="Donation"', 'value="Camping area"', 'value="Pub stay"', 'value="Council park"', 'value="Council park (leased)"', 'value="Park campground"', 'value="Paid – Parks Victoria (book ahead)"', 'data-flag="self"', 'data-flag="dump"', 'data-flag="tents"', 'data-flag="showers"', "Self-contained only", "Dump point", "Suits tents", "Suits caravans", "Suits motorhomes", "> Showers<", "> Free/Donation<", "> Paid<"):
  if bit in overview: bad.append(("/", "old filter " + bit))
if 'placeholder="Search by town"' in overview: bad.append(("/", "old town placeholder"))
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
for bit in ("slice(0, 12)", "ArrowDown", "aria-activedescendant", "hit-tag", 'kind === "camp"', 'replace(/[^a-z0-9]+/g, " ")', "regionName", 'window.location.assign(hit.camp.url)', 'document.createElement("a")', '[role="option"]'):
  if bit not in mj: bad.append(("map.js", "camp search " + bit))
if "openPopup" in mj or "zoomToShowLayer" in mj: bad.append(("map.js", "camp search still opens a popup"))
for flag in ("dogs", "caravans", "motorhomes", "hide-closed"):
  if f'data-flag="{flag}"' not in overview: bad.append(("/", "toggle " + flag))
if 'input[name="cat"]' in mj or 'andFlags = ["self"' in mj: bad.append(("map.js", "old filters"))
for bit in ('selected("type")', 'selected("cost")', 'data-flag="hide-closed"', 'obj.status === "closed"', '["dogs", "caravans", "motorhomes"]', "updateFilterStatus", "formatCount", "filter-count", "filter-empty", "filter-clear", "No camps match these filters", "refreshFilterButtons", "filters-open", "max-width: 640px", "aria-expanded", "invalidateSize", "filter-backdrop", "touchend"):
  if bit not in mj: bad.append(("map.js", "filter " + bit))
osm = [c for c in vic_feed if c.get("source") == "osm"]
dv = [c for c in vic_feed if c.get("source") == "datavic"]
if not osm or not dv: bad.append(("status.json", "both sources"))
pmr = next((c for c in feed["camps"] if c.get("slug") == "princess-margaret-rose-caves-lower-glenelg-np"), None)
if not pmr or pmr.get("status") != "closed" or pmr.get("source") != "osm":
  bad.append(("princess-margaret-rose-caves-lower-glenelg-np", "closed override"))
else:
  pmr_html = open(os.path.join(D, "vic", "camp", "princess-margaret-rose-caves-lower-glenelg-np", "index.html"), encoding="utf-8").read()
  note = "Please note: Princess Margaret Rose Cave Campground remains closed for assessments and upgrade works."
  src = "https://www.parks.vic.gov.au/places-to-see/parks/lower-glenelg-national-park/where-to-stay/princess-margaret-rose-cave-campground"
  if note not in pmr_html or src not in pmr_html or 'id="camp-closure"' not in pmr_html or 'class="badge closed"' not in pmr_html:
    bad.append(("princess-margaret-rose-caves-lower-glenelg-np", "closure box"))
  if (pmr.get("closure") or {}).get("desc") != note or (pmr.get("closure") or {}).get("source_url") != src:
    bad.append(("princess-margaret-rose-caves-lower-glenelg-np", "closure feed"))
closed_notes = {
  "princess-margaret-rose-caves-lower-glenelg-np": "Please note: Princess Margaret Rose Cave Campground remains closed for assessments and upgrade works.",
  "strachans-campground-grampians-gariwerd-national-park": "Strachans Campground will be closed to visitors between 13 April and 29 October 2026 while major upgrade works are completed.",
  "lake-catani-campground-mt-buffalo-np": "Lake Catani Campground is CLOSED for all camping from August 31st until October 30th 2026.",
  "notley-picnic-and-camping-area": "Notley Camping & Picnic Area - closed for upgrades",
  "teddington-camping-area-kara-kara-national-park": "Upper Teddington Reservoir - closed for maintenance",
  "kiata-campground": "There are still some areas within the park which remain closed for recovery works such as: Kiata Campground",
}
if any(c.get("nearby_closures") for c in osm):
  bad.append(("status.json", "osm nearby closures"))
for camp in osm:
  note = closed_notes.get(camp.get("slug"))
  if note:
    if camp.get("status") != "closed" or (camp.get("closure") or {}).get("desc") != note or not (camp.get("closure") or {}).get("source_url"):
      bad.append((camp.get("slug"), "closed override"))
    else:
      page = open(os.path.join(D, "vic", "camp", camp["slug"], "index.html"), encoding="utf-8").read()
      if note not in page or 'id="camp-closure"' not in page:
        bad.append((camp.get("slug"), "closure box"))
  elif camp.get("status") != "check" or camp.get("closure"):
    bad.append((camp.get("slug"), "osm closure"))
if set(closed_notes) - {c.get("slug") for c in osm}:
  bad.append(("status.json", "missing closed override"))
if str(len(feed["camps"]) if national else len(vic_feed)) not in home: bad.append(("/", "home count"))
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
    if "Book ahead with Parks Victoria" not in html_page or f"Type: {PV}" not in html_page or ("13 1963" not in html_page and 'href="tel:' not in html_page):
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
  if re.search(r"(?:Dogs|Dump point|Showers|Tents|Caravans|Motorhomes|Self-contained only): Unknown", html_page):
    bad.append((camp["slug"], "unknown facility row"))
  if "Other facilities not yet confirmed. Know this spot?" in html_page: shown["unknown"] = True
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
corrections_doc = build_osm.load_corrections(corr_path)
corrected_ids = set(corrections_doc) if isinstance(corrections_doc, dict) else set()
# The Monday refresh writes the extract after corrections, so hand-checked
# park camps and pub stays are already in the file. Guard the uncorrected rows.
fresh = [s for s in curated_sites if s.get("osm_id") not in corrected_ids]
if set(s.get("category") for s in fresh) - allowed: bad.append(("osm data", "category outside the six"))
merged = build_osm.apply_corrections(curated_sites, corrections_doc)
named = [s for s in merged if re.search(r"[A-Za-z0-9]", (s.get("name") or ""))]
if len(named) != len(osm): bad.append(("osm", f"built {len(osm)} overlay {len(named)}"))
labels = {c.get("category") for c in osm}
if labels - {"Free", "Camping area", "Donation", "Showground", "Council park", "Council park (leased)", "Rest area", "Pub stay", "Paid – Parks Victoria (book ahead)"}: bad.append(("osm", labels))
expect_counts = {"Free": 1101, "Camping area": 5, "Council park": 75, "Showground": 40, "Paid – Parks Victoria (book ahead)": 56, "Rest area": 24, "Donation": 11, "Pub stay": 6, "Council park (leased)": 8}
got_counts = {}
for camp in osm: got_counts[camp.get("category")] = got_counts.get(camp.get("category"), 0) + 1
if got_counts != expect_counts: bad.append(("osm", got_counts))
if sum(1 for c in osm if c.get("needs_review")) != sum(1 for c in osm if c.get("needs_review") is True): bad.append(("osm", "review flag"))
if not any(c.get("needs_review") is False for c in osm): bad.append(("osm", "no confirmed sites"))
if any(classify.CHAIN.search(s.get("name") or "") for s in fresh): bad.append(("osm data", "chain name kept"))
def _still_excluded(name):
  checked = name or ""
  if re.search(r"(?i)camp", checked): checked = re.sub(r"(?i)picnic", "", checked)
  return classify.EXCL.search(checked)
if any(_still_excluded(s.get("name") or "") for s in fresh): bad.append(("osm data", "hiker or group name kept"))
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
picnic_camp = classify.decide({"tourism": "camp_site", "fee": "no", "name": "Kurth Kiln Camping and Picnic"})
if not picnic_camp or picnic_camp["category"] != "free": bad.append(("classify", "picnic camp"))
if classify.decide({"tourism": "camp_site", "fee": "no", "name": "Riverside Picnic Area"}): bad.append(("classify", "picnic only"))
if classify.decide({"tourism": "camp_site", "name": "Scout Picnic Camp"}): bad.append(("classify", "scout picnic"))
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
if not isinstance(corrections, dict) or len(corrections) != 1333 or "drop" in corrections or "overrides" in corrections:
  bad.append(("corrections", "shape"))
if sum(1 for v in corrections.values() if isinstance(v, dict) and v.get("exclude")) != 220: bad.append(("corrections", "exclusions"))
if corrections.get("w1474028458", {}).get("exclude") is not True or "no-private-caravan-parks" not in str(corrections.get("w1474028458", {}).get("exclude_reason")):
  bad.append(("corrections", "browns water holes"))
if corrections.get("w204763505", {}).get("name") != "Wye River Beachfront Campground":
  bad.append(("corrections", "wye river way"))
if sum(1 for k, v in corrections.items() if str(k).startswith("new:") and isinstance(v, dict) and not v.get("exclude") and "lat" in v and "lon" in v) != 500:
  bad.append(("corrections", "new sites"))
import facts
if facts.override_expired("2026-10-25", "2026-10-26") is not True: bad.append(("facts", "expired until"))
if facts.override_expired("2026-10-26", "2026-10-26") or facts.override_expired("2026-10-30", "2026-10-26") or facts.override_expired("", "2026-10-26"):
  bad.append(("facts", "until still current"))
build_src = open(os.path.join(root, "scripts", "build.py"), encoding="utf-8").read()
if "statecfg.enabled" not in build_src: bad.append(("build.py", "enabled states"))
nsw = states.by_slug("nsw")
if not nsw.get("enabled"): bad.append(("states", "nsw enabled"))
nsw_hooks = {
    "npws_visitor_areas": "https://mapprod2.environment.nsw.gov.au/arcgis/rest/services/Assets/AMS_Assets/FeatureServer/24",
    "npws_alerts_rss": "https://www.nationalparks.nsw.gov.au/api/rssfeed/get",
    "rfs_fdr": "https://www.rfs.nsw.gov.au/feeds/fdrToban.xml",
}
for hook, url in nsw_hooks.items():
    if ((nsw.get("sources") or {}).get(hook) or {}).get("url") != url: bad.append(("states", hook))
    if url in build_src: bad.append(("build.py", "fetches " + hook))
if "nsw_conditions" not in build_src or "fetch_text" not in build_src: bad.append(("build.py", "nsw conditions"))
import nsw_conditions as nswcond
_square = {"title": "Test National Park", "title_norm": "test national park", "name_norm": "test", "abbrev": "np", "prep": nswcond._prepare([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])}
if not nswcond._contains(_square["prep"], 0.5, 0.5) or nswcond._contains(_square["prep"], 2, 2): bad.append(("nsw", "point in polygon"))
_rss = """<?xml version="1.0"?><rss><channel>
<item><title>Test National Park</title><link>https://www.nationalparks.nsw.gov.au/visit-a-park/parks/test/local-alerts</link>
<category>Closed parks</category><description>&lt;strong&gt;Closed parks: Test National Park closed&lt;/strong&gt;&lt;br/&gt;Test National Park is closed to the public.</description></item>
<item><title>Kinchega National Park</title><link>https://www.nationalparks.nsw.gov.au/visit-a-park/parks/kinchega/local-alerts</link>
<category>Closed parks</category><description>&lt;strong&gt;Closed parks: No Solid Fuel Fires in Kinchega National Park&lt;/strong&gt;&lt;br/&gt;A park fire ban is in place. Solid fuel fires are prohibited.</description></item>
<item><title>Bournda National Park</title><link>https://www.nationalparks.nsw.gov.au/visit-a-park/parks/bournda/local-alerts</link>
<category>Closed areas</category><description>&lt;strong&gt;Closed areas: Hobart Beach Campground Closure&lt;/strong&gt;&lt;br/&gt;Hobart Beach Campground is closed from Sunday.</description></item>
<item><title>Murray Valley National Park</title><link>https://www.nationalparks.nsw.gov.au/visit-a-park/parks/murray/local-alerts</link>
<category>Closed areas</category><description>&lt;strong&gt;Closed areas: Millewa Campgrounds CLOSED due to flooding&lt;/strong&gt;Millewa National Park campgrounds are CLOSED:&lt;ul&gt;&lt;li&gt;Wire Fence Landing campground&lt;/li&gt;&lt;/ul&gt;Millewa National Park campgrounds are OPEN:&lt;ul&gt;&lt;li&gt;McLaurens campground&lt;/li&gt;&lt;/ul&gt;</description></item>
</channel></rss>"""
_items = nswcond.parse_rss(_rss)
def _reserve(title, code):
    label = nswcond.TYPE_LABEL[code]
    name = title[: -len(label)].strip()
    return {"title": title, "title_norm": nswcond.norm(title), "name_norm": nswcond.norm(name), "abbrev": nswcond.BULLET_ABBREV.get(code, "")}
_by = {item["title"]: item for item in _items}
if not nswcond.closure_for(_reserve("Test National Park", "NP"), "Any Camp", _by["Test National Park"]): bad.append(("alerts", "whole park"))
if nswcond.closure_for(_reserve("Kinchega National Park", "NP"), "Any Camp", _by["Kinchega National Park"]): bad.append(("alerts", "fire ban closed"))
if not nswcond.closure_for(_reserve("Bournda National Park", "NP"), "Hobart Beach Campground", _by["Bournda National Park"]): bad.append(("alerts", "named camp"))
if nswcond.closure_for(_reserve("Bournda National Park", "NP"), "Other Campground", _by["Bournda National Park"]): bad.append(("alerts", "other camp"))
_millewa = _reserve("Millewa National Park", "NP")
_index = nswcond.index_closures([_by["Murray Valley National Park"]], [_millewa, _reserve("Murray Valley National Park", "NP")])
if not nswcond.lookup_closure(_index, _millewa, "Wire Fence Landing Campground"): bad.append(("alerts", "named in another park"))
if nswcond.lookup_closure(_index, _millewa, "McLaurens Campground"): bad.append(("alerts", "open list"))
_fdr = nswcond.parse_fdr(b"<FireDangerMap><District><Name>Illawarra/Shoalhaven</Name><DangerLevelToday>HIGH</DangerLevelToday><DangerLevelTomorrow>EXTREME</DangerLevelTomorrow><FireBanToday>No</FireBanToday><FireBanTomorrow>Yes</FireBanTomorrow></District></FireDangerMap>")
_row = _fdr.get("illawarrashoalhaven") or {}
if _row.get("today") != "High" or _row.get("tomorrow") != "Extreme" or _row.get("ban_today") != "No": bad.append(("fdr", "parse"))
if nswcond.parse_rss(b"") or nswcond.parse_fdr(b"not xml"): bad.append(("feeds", "empty"))
if "facts.override_expired" not in build_src or "Closure override expired:" not in build_src:
  bad.append(("build.py", "expired override"))
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
if facts.fee_label("paid") != "Paid – contact for details" or facts.fee_label("paid", "book_ahead") != "Paid – book ahead" or facts.fee_label("paid", "pay_on_site") != "Fee payable on site" or facts.fee_label("paid", "permit") != "Permit required" or facts.fee_label("free") != "Free" or facts.fee_label("free", "permit") != "Free" or facts.fee_label("$25") != "": bad.append(("fee", "label"))
if "$" in facts.without_prices("A permit site. Cars $7 per night. Dogs are not allowed.") or "Dogs are not allowed" not in facts.without_prices("A permit site. Cars $7 per night. Dogs are not allowed."): bad.append(("fee", "sentence"))
if "$" in facts.scrub_money("yes ($5 public)") or facts.yn_flag("yes ($5 public)") is not True: bad.append(("fee", "amount"))
if facts.booking_label("not required") != "No" or facts.booking_label("required (Parks Victoria)") != "Yes": bad.append(("booking", "label"))
dv_path = os.path.join(root, "data", "datavic-enrichment.json")
dv_before = os.path.getmtime(dv_path)
dv_doc = json.load(open(dv_path, encoding="utf-8"))
dv_camps = dv_doc.get("camps") or {}
if len(dv_camps) != 353 or dv_doc.get("_meta", {}).get("count") != 353: bad.append(("datavic enrichment", "count"))
cache_path = os.path.join(root, "data", "recweb-camping-cache.json.gz")
try:
  with gzip.open(cache_path, "rt", encoding="utf-8") as handle:
    cached_feed = json.load(handle)
  cached_features = cached_feed.get("features") or []
except Exception as exc:
  cached_features = []
  bad.append(("datavic cache", str(exc)[:120]))
if len(cached_features) < 342 or any((f.get("properties") or {}).get("camping") != "Y" for f in cached_features):
  bad.append(("datavic cache", len(cached_features)))
build_src = open(os.path.join(root, "scripts", "build.py"), encoding="utf-8").read()
if os.path.basename((states.by_slug("vic").get("files") or {}).get("enrichment") or "") != "datavic-enrichment.json": bad.append(("states", "enrichment path"))
if re.search(r"open\(\s*.*datavic-enrichment[^)]*[\"']w", build_src): bad.append(("build.py", "enrichment write"))
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
must("king-hut-alpine-np", king, ["Drinking water: No", "Dogs: No", "<strong>Free</strong>", "bring your own drinking water", "Checked against official source, 18 October 2026", ">official source</a>", "parks.vic.gov.au", 'data-camp="king-hut-alpine-np"', 'id="checked-line"', 'id="refresh-data"'])
if 'id="camp-closure"' in king: bad.append(("king-hut-alpine-np", "osm closure block"))
if "Unverified, help us confirm" in king: bad.append(("king-hut-alpine-np", "still unverified"))
if "$" in king.split('id="newsletter"')[0]: bad.append(("king-hut-alpine-np", "fee amount"))
dargo = page_of("dargo-river-inn")
must("dargo-river-inn", dargo, ["Pub stay", "<strong>Paid – contact for details</strong>", "Toilets: Yes", "Showers: Yes", "Tents: Yes", "Caravans: Yes", "Motorhomes: Yes", 'href="tel:0351401330"', "info@dargoriverinn.com.au", "Checked against official source, 18 October 2026"])
if "$" in dargo.split('id="newsletter"')[0]: bad.append(("dargo-river-inn", "fee amount"))
goulburn = page_of("angling-club-bend-camping-area-lower-goulburn-national-park-goulburn-river-heritage-river")
must("angling-club-bend", goulburn, ["Lower Goulburn National Park", "Dogs: No", 'href="tel:131963"', "parks.vic.gov.au", "Checked against official source"])
murray = page_of("abbotsford-bend-camping-area-murray-river")
must("abbotsford-bend", murray, ["<strong>Free</strong>", "Booking required:</strong> No", "Dogs: on lead", "Murray", "Checked against official source, 18 October 2026"])
orchard = page_of("the-orchard")
must("the-orchard", orchard, ["Toilets: Yes (sealed pump-out)", "Drinking water: No", "Water source: reliable access to water (not stated as drinkable)", "Booking required:</strong> No", "<strong>Free</strong>", "Caravans: Yes", "Access: 2WD access", "Area:</strong> Delatite Arm Reserve, Lake Eildon", "reserve-wide", "toilet from the DataVic Recreation Assets layer", "exploreoutdoors.vic.gov.au", "Checked against official source, 18 October 2026"])
if "Tents: Yes" in orchard or "Matched via the Delatite" in orchard or "Operator: MANSFIELD" in orchard or "Resolved 18 Oct" in orchard: bad.append(("the-orchard", "suits, flag or raw maintainer"))
tunnel = page_of("tunnel-bend")
must("tunnel-bend", tunnel, ["Area:</strong> Upper Goulburn State Forest (Goulburn River)", "area-wide statements on the Explore Outdoors page upper-goulburn-and-big-river-camping, not site-specific"])
burrum = page_of("lake-burrumbeet-south-1")
must("lake-burrumbeet-south-1", burrum, ["Area:</strong> Lake Burrumbeet", "lake-wide statements on the Explore Outdoors Lake Burrumbeet page"])
if "$" in orchard.split('id="newsletter"')[0]: bad.append(("the-orchard", "fee amount"))
horseshoe = page_of("horseshoe-bend-camping-area")
must("horseshoe-bend", horseshoe, ["Rubbish: take rubbish home", "Toilets: Yes", 'class="badge check"'])
lands = page_of("landsborough-caravan-park")
must("landsborough-caravan-park", lands, ["Type: Council park", "<strong>Paid – contact for details</strong>"])
if "<strong>Free</strong>" in lands: bad.append(("landsborough-caravan-park", "still free"))
donald = page_of("donald-lakeside-caravan-park")
must("donald-lakeside-caravan-park", donald, ["Type: Council park (leased)", "<strong>Paid – contact for details</strong>"])
if "<strong>Free</strong>" in donald: bad.append(("donald-lakeside-caravan-park", "still free"))
forrest = page_of("forrest-holiday-park")
must("forrest-holiday-park", forrest, ["Type: Council park (leased)", "<strong>Paid – contact for details</strong>", "Forrest Holiday Park"])
if "<strong>Free</strong>" in forrest: bad.append(("forrest-holiday-park", "still free"))
corinella = page_of("corinella-foreshore-caravan-park")
must("corinella-foreshore-caravan-park", corinella, ["Type: Council park", "<strong>Paid – book ahead</strong>"])
if "<strong>Free</strong>" in corinella or "Council park (leased)" in corinella: bad.append(("corinella-foreshore-caravan-park", "category"))
tolmie = page_of("tolmie-recreational-reserve")
must("tolmie-recreational-reserve", tolmie, ["Type: Camping area", "<strong>Fee payable on site</strong>", "Booking required:</strong> No", "Max stay: 28 nights", "honesty box"])
if "Type: Free" in tolmie: bad.append(("tolmie-recreational-reserve", "paid site still typed Free"))
if "$" in tolmie.split('id="newsletter"')[0]: bad.append(("tolmie-recreational-reserve", "fee amount"))
permit = page_of("blackwood")
must("blackwood", permit, ["<strong>Permit required</strong>", "Toilets: Yes (sealed pump-out, septic)", "Water source: tap (not stated as drinkable)", "Vehicles: Camper trailers mentioned as suitable", "Accessibility: Partial wheelchair access (DataVic)"])
if "$" in permit.split('id="newsletter"')[0]: bad.append(("blackwood", "fee amount"))
beer = page_of("beeripmo-campground")
must("beeripmo-campground", beer, ["<strong>Free</strong>", "Toilets: Yes", "Drinking water: No (untreated rainwater tank, not reliable for drinking)", "Water source: untreated rainwater tank", "dogs on lead in daytime only"])
if "Booking conflict" in beer or "Resolved 18 Oct" in beer: bad.append(("beeripmo-campground", "internal note"))
if "$" in beer.split('id="newsletter"')[0]: bad.append(("beeripmo-campground", "fee amount"))
avondale = next((c for c in feed["camps"] if c.get("slug") == "avondale-gardens"), None)
if not avondale or avondale.get("status") != "closed" or avondale.get("source") != "datavic" or avondale.get("closure") in (None, {}, []):
  bad.append(("avondale-gardens", "closure changed"))
else:
  av_html = page_of("avondale-gardens")
  must("avondale-gardens", av_html, ['class="badge closed"', "<strong>Closed:</strong>", "<strong>Free</strong>", "Dogs: Yes", 'id="camp-closure"', 'data-camp="avondale-gardens"'])
for slug, vans, homes in (("dargo-river-inn", 1, 1), ("coleraine-caravan-park", 1, 1)):
  point = next((p for p in home_pts if p.get("url", "").rstrip("/").endswith("/" + slug)), None)
  if not point or point.get("caravans") != vans or point.get("motorhomes") != homes or "tents" in point or "self" in point:
    bad.append((slug, "map suit flags"))
# Last known-good DataVic Recreation Sites count (22 Oct 2026, before Dindi Mill
# left the feed). A site can disappear upstream without the build being broken.
DATAVIC_BASELINE = 360
DATAVIC_DROP = 0.05
dv_count = len(dv)
if dv_count == 0 or dv_count < DATAVIC_BASELINE * (1 - DATAVIC_DROP):
  bad.append(("datavic count", dv_count))
elif dv_count < DATAVIC_BASELINE:
  warnings.append(("datavic count", f"{dv_count} of {DATAVIC_BASELINE}"))
applied = 0
missing_enrichment = []
for row in dv_camps.values():
  slug = str(row.get("slug") or "")
  path = os.path.join(D, "vic", "camp", slug, "index.html")
  html_page = open(path, encoding="utf-8").read() if slug and os.path.isfile(path) else ""
  if "Checked against official source" not in html_page:
    missing_enrichment.append(slug or str(row.get("name") or "?"))
  else:
    applied += 1
# Named camps above stay hard failures. Overlay rows can leave the feed: a gap
# within 5% warns, an empty match or a larger gap still fails the deploy.
if applied == 0 or len(missing_enrichment) > len(dv_camps) * DATAVIC_DROP:
  bad.append(("datavic enrichment", applied, missing_enrichment[:12]))
elif missing_enrichment:
  shown = ", ".join(missing_enrichment[:12])
  extra = "" if len(missing_enrichment) <= 12 else f" (+{len(missing_enrichment) - 12} more)"
  warnings.append(("datavic enrichment", f"{applied} of {len(dv_camps)}; not on a page: {shown}{extra}"))
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
if "manual-corrections" in add or "osm-camps-vic.json" not in add or "vic-towns.json" not in add or "pending-osm.json" not in add: bad.append(("refresh-osm.yml", "git add"))
if "left the vetted files unchanged" not in osm_src or "outside Victoria" not in osm_src or "missing id, needs remap" not in osm_src: bad.append(("build_osm.py", "soft fail or pending"))
if not build_osm.in_state(-37.8136, 144.9631) or build_osm.in_state(-36.09, 144.75) or build_osm.in_state(-37.993592, 140.965965): bad.append(("boundary", "Victoria"))
def _sample(osm_id, name, lat, lon):
  return {"osm_id": osm_id, "name": name, "lat": lat, "lon": lon, "category": "free", "tags": {"tourism": "camp_site", "name": name}}
published, pending = build_osm.vet_camps(
  [_sample("n1", "Old Camp", -37.1, 144.2), _sample("n2", "Red Bank Camp", -37.2, 144.3)],
  [_sample("n3", "Moama Camp", -36.09, 144.75)],
  {"n1": {"needs_review": False, "name": "Old Camp", "checked_date": "2026-10-20"}},
  [{"osm_id": "n1", "name": "Old Camp", "lat": -37.1, "lon": 144.2, "category": "free"}],
)
if [c.get("osm_id") for c in published] != ["n1"] or any(c.get("osm_id") == "n2" for c in published): bad.append(("vet", "new id published"))
new_row = next((row for row in pending if row.get("id") == "n2"), None)
out_row = next((row for row in pending if row.get("id") == "n3"), None)
if not new_row or new_row.get("tags", {}).get("name") != "Red Bank Camp" or "lat" not in new_row: bad.append(("vet", "pending new id"))
if not out_row or out_row.get("note") != "outside Victoria": bad.append(("vet", "outside Victoria"))
published, pending = build_osm.vet_camps(
  [_sample("n1", "Red Bank Camp", -37.2, 144.3), _sample("n4", "Red Bank Campsite", -37.2004, 144.3004)],
  [],
  {"n1": {"name": "Red Bank Camp"}},
  [{"osm_id": "n1", "name": "Red Bank Camp", "lat": -37.2, "lon": 144.3, "category": "free"}],
)
flagged = next((row for row in pending if row.get("id") == "n4"), None)
if not flagged or "likely duplicate of n1" not in flagged.get("duplicate", ""): bad.append(("vet", "duplicate"))
far, far_pending = build_osm.vet_camps(
  [_sample("n1", "Red Bank Camp", -37.2, 144.3), _sample("n5", "Red Bank Camp", -38.2, 146.3)],
  [],
  {"n1": {"name": "Red Bank Camp"}},
  [{"osm_id": "n1", "name": "Red Bank Camp", "lat": -37.2, "lon": 144.3, "category": "free"}],
)
far_row = next((row for row in far_pending if row.get("id") == "n5"), {})
if far_row.get("duplicate"): bad.append(("vet", "distant duplicate"))
kept, missing = build_osm.vet_camps(
  [],
  [],
  {"n9": {"name": "Gone Camp", "category": "free"}, "n8": {"exclude": "closed"}},
  [{"osm_id": "n9", "name": "Gone Camp", "lat": -37.5, "lon": 145.1, "category": "free"}],
)
if not any(c.get("osm_id") == "n9" for c in kept) or any(c.get("osm_id") == "n8" for c in kept): bad.append(("vet", "missing kept"))
if not any(row.get("id") == "n9" and row.get("note") == "missing id, needs remap" for row in missing): bad.append(("vet", "missing note"))
if any(row.get("id") == "n8" for row in missing): bad.append(("vet", "exclusion logged missing"))
import check_parksvic
sample_html = """
<p>Please note: Princess Margaret Rose Cave Campground remains closed for assessments and upgrade works.</p>
<p>The gates closed at night.</p>
<p>The campground is closed over the winter shoulder season.</p>
<div class="quick-reference"><a href="#change-of-conditions">This area is closed</a></div>
<p>These tracks will remain closed until further notice.</p>
<p>The lookout is closed to visitors.</p>
"""
sample_found = check_parksvic.classify_html(sample_html)
if sample_found["closed"] != ["Please note: Princess Margaret Rose Cave Campground remains closed for assessments and upgrade works."]:
  bad.append(("check_parksvic", "closed sentence " + repr(sample_found["closed"])))
if sample_found["seasonal"] != ["The campground is closed over the winter shoulder season."]:
  bad.append(("check_parksvic", "seasonal sentence " + repr(sample_found["seasonal"])))
named_html = """
<div class="explore__overview"><p>Stapylton Campground is open all year.</p></div>
<div class="change-of-conditions__item">
  <h4 class="change-of-conditions__subtitle">Strachans Campground</h4>
  <div class="change-of-conditions__content"><p>Strachans Campground is closed for upgrades.</p></div>
</div>
<div class="change-of-conditions__item">
  <h4 class="change-of-conditions__subtitle">Stapylton Campground</h4>
  <div class="change-of-conditions__content"><p>Stapylton Campground remains closed for upgrade works.</p></div>
</div>
"""
named_found = check_parksvic.classify_html(named_html, "Stapylton Campground (Grampians (Gariwerd) National Park)")
if named_found["closed"] != ["Stapylton Campground remains closed for upgrade works."]:
  bad.append(("check_parksvic", "named alert " + repr(named_found["closed"])))
area_html = """
<div class="change-of-conditions__item">
  <h3 class="change-of-conditions__title-text">No Vehicle access to Farley Bend</h3>
  <div class="change-of-conditions__content"><p>This section of the River Murray reserve is closed to vehicles due to the poor and unsafe condition of the roads.</p><p>In the interest of visitor safety, this area is closed until further notice.</p></div>
</div>
<div class="change-of-conditions__item">
  <h3 class="change-of-conditions__title-text">Strachans Campground</h3>
  <div class="change-of-conditions__content"><p>Strachans Campground is closed for upgrades.</p></div>
</div>
"""
abbotsford_found = check_parksvic.classify_html(area_html, "Abbotsford Bend Camping Area (Murray River)")
if abbotsford_found["closed"]:
  bad.append(("check_parksvic", "shared murray notice " + repr(abbotsford_found["closed"])))
farley_found = check_parksvic.classify_html(area_html, "Farley Bend Camping Area Site 2")
if farley_found["closed"] != ["In the interest of visitor safety, this area is closed until further notice."]:
  bad.append(("check_parksvic", "farley " + repr(farley_found["closed"])))
if check_parksvic.site_phrase("Farley Bend Camping Area Site 2") != "farley bend":
  bad.append(("check_parksvic", "farley phrase"))
if not check_parksvic.campground_url("https://www.parks.vic.gov.au/places-to-see/sites/desert-discovery-walk---kiata-to-mallee-camp"):
  bad.append(("check_parksvic", "camp url"))
if check_parksvic.campground_url("https://www.parks.vic.gov.au/places-to-see/parks/little-desert-national-park"):
  bad.append(("check_parksvic", "park url"))
facility_html = """
<div class="change-of-conditions__item">
  <h3 class="change-of-conditions__title-text">The Gums campground Communal BBQ closed</h3>
  <div class="change-of-conditions__content"><p>The Gums campground communal BBQ is closed. Nearest alternative BBQ is Jehosaphat Gully.</p><p>The toilets are closed.</p><p>The picnic shelter is closed.</p><p>The shower is closed.</p><p>The dump point is closed.</p></div>
</div>
"""
facility_found = check_parksvic.classify_html(facility_html, "The Gums Campground (Kinglake National Park)")
if facility_found["closed"]:
  bad.append(("check_parksvic", "facility " + repr(facility_found["closed"])))
kiata_html = """
<div class="change-of-conditions__item">
  <h3 class="change-of-conditions__title-text">Park Areas Closed - Little Desert NP</h3>
  <div class="change-of-conditions__content">
    <p>The Eastern Block of the Little Desert NP remains closed following the fire.</p>
    <p>Areas within the park that were not impacted by the fire and remain open are:</p>
    <ul><li>Kiata Sanctuary Picnic Ground</li></ul>
    <p>There are still some areas within the park which remain closed for recovery works such as:</p>
    <ul>
      <li>Eastern Block including Stringybark walk</li>
      <li>Kiata Campground</li>
      <li>Desert Discovery Walk</li>
    </ul>
    <p>Broughton's Waterhole and Stan's Camp have reopened.</p>
  </div>
</div>
"""
kiata_found = check_parksvic.classify_html(kiata_html, "Kiata Campground")
kiata_sentence = "There are still some areas within the park which remain closed for recovery works such as: Kiata Campground"
if kiata_found["closed"] != [kiata_sentence]:
  bad.append(("check_parksvic", "kiata list " + repr(kiata_found["closed"])))
for other_name in ("Yellow Gum Walkers Camp", "Broughton's Waterhole Camping Area (Little Desert National Park)", "Stan's Camp (Little Desert National Park)"):
  other_found = check_parksvic.classify_html(kiata_html, other_name)
  if other_found["closed"]:
    bad.append(("check_parksvic", "open list " + other_name + " " + repr(other_found["closed"])))
wrapped_html = """
<div class="change-of-conditions__item">
  <h3 class="change-of-conditions__title-text">Strachans Campground Closed for Upgrades</h3>
  <div class="change-of-conditions__content"><p>Strachans Campground will
be closed to visitors between 13 April and 29 October 2026 while major upgrade
works are completed.</p><p>Alternative campgrounds such as Buandik or Boreang Campgrounds can be booked.</p></div>
</div>
"""
wrapped_found = check_parksvic.classify_html(wrapped_html, "Strachans Campground (Grampians (Gariwerd) National Park)")
if wrapped_found["closed"] != ["Strachans Campground Closed for Upgrades", "Strachans Campground will be closed to visitors between 13 April and 29 October 2026 while major upgrade works are completed."]:
  bad.append(("check_parksvic", "wrapped " + repr(wrapped_found["closed"])))
buandik_found = check_parksvic.classify_html(wrapped_html, "Buandik Campground")
if buandik_found["closed"]:
  bad.append(("check_parksvic", "alternative camp " + repr(buandik_found["closed"])))
sample_camp = {"slug": "example-camp", "name": "Example Camp", "osm_id": "n316599357", "id": "n316599357", "status": "check"}
sample_page = {"error": "", "html": sample_html, "cached": True}
sample_dest = os.path.join(tempfile.mkdtemp(), "parksvic-flags.json")
sample_count = check_parksvic.write_flags([sample_camp], sample_dest, fetcher=lambda url: sample_page, sleeper=lambda _n: None, overall_seconds=5)
if sample_camp["status"] != "check" or sample_count != 1:
  bad.append(("check_parksvic", "status changed or flag count"))
else:
  sample_doc = json.load(open(sample_dest, encoding="utf-8"))
  sample_flag = sample_doc["flags"][0]
  if sample_flag.get("slug") != "example-camp" or "remains closed" not in sample_flag.get("sentence", "") or not sample_doc["seasonal"]:
    bad.append(("check_parksvic", "flags file"))
  if any(row.get("error") for row in sample_doc["errors"]):
    bad.append(("check_parksvic", "unexpected error"))
closed_camp = dict(sample_camp, status="closed")
closed_count = check_parksvic.write_flags([closed_camp], sample_dest, fetcher=lambda url: sample_page, sleeper=lambda _n: None, overall_seconds=5)
if closed_camp["status"] != "closed" or closed_count != 0:
  bad.append(("check_parksvic", "closed camp flagged"))
error_count = check_parksvic.write_flags([sample_camp], sample_dest, fetcher=lambda url: {"error": "403", "html": "", "cached": True}, sleeper=lambda _n: None, overall_seconds=5)
error_doc = json.load(open(sample_dest, encoding="utf-8"))
if error_count != 0 or not error_doc["errors"] or error_doc["errors"][0].get("error") != "403":
  bad.append(("check_parksvic", "403"))
if "20 18 * * 1" not in refresh: bad.append(("refresh-osm.yml", "weekly schedule"))
preview = open(os.path.join(root, ".github", "workflows", "preview-more-sites.yml"), encoding="utf-8").read()
if "feature/more-sites" not in preview or "--branch=main" in preview or 'branches: [main]' in preview: bad.append(("preview-more-sites.yml", "branch"))
if 'if [ "$branch" = "main" ]' not in preview: bad.append(("preview-more-sites.yml", "refuse main"))
if "feature/more-sites" in wf or "17 */3 * * *" not in wf: bad.append(("build-deploy.yml", "production schedule"))
if "CAMPCONDITIONS_ENABLE" in wf: bad.append(("build-deploy.yml", "preview enable"))
nsw_index = os.path.join(D, "nsw", "index.html")
if os.path.isfile(nsw_index):
  nsw_html = open(nsw_index, encoding="utf-8").read()
  if "NPWS Visitor Area" not in nsw_html or "CC BY" not in nsw_html: bad.append(("nsw", "attribution"))
  if home.count('class="banner-row"') != 2 or nsw_html.count('class="banner-row"') != 2 or vic.count('class="banner-row"') != 2: bad.append(("nav", "header rows"))
  if 'id="state-jump"' in home or "<strong>VIC</strong>" in home or "<strong>NSW</strong>" in home: bad.append(("/", "state jump"))
  if 'class="state-pick"' not in home or 'aria-label="All states"' not in home or ">All <" not in home: bad.append(("/", "national header"))
  if '<p class="soon">' in home or '<p class="soon">' in vic or '<p class="soon">' in nsw_html: bad.append(("/", "soon bar"))
  if "html.filters-locked .leaflet-control-container" not in home or "html.filters-locked .leaflet-control-container" not in vic or "html.filters-locked .leaflet-control-container" not in nsw_html: bad.append(("filters", "cover"))
  if 'name="states" value="vic" checked' not in home or 'name="choose_states" value="1"' not in home or 'name="states" value="nsw" checked' in home or "Get the free weekly digest" not in home: bad.append(("/", "signup states"))
  if home.find('id="camp-map"') < 0 or home.find('id="newsletter"') < home.find('id="camp-map"'): bad.append(("/", "newsletter above the map"))
  if 'value="NPWS"' not in home or 'value="Parks Victoria"' not in home: bad.append(("/", "type filters"))
  if 'class="state-pick"' not in vic or 'aria-label="State: Victoria"' not in vic or ">VIC <" not in vic: bad.append(("/vic/", "state picker"))
  if 'href="/vic/" aria-current="page"' not in vic or 'href="/nsw/">New South Wales</a>' not in vic: bad.append(("/vic/", "state menu"))
  if 'name="states" value="vic" checked' not in vic or 'name="states" value="nsw" checked' in vic: bad.append(("/vic/", "signup states"))
  if 'name="states" value="nsw" checked' not in nsw_html or 'name="states" value="vic" checked' in nsw_html: bad.append(("nsw", "signup states"))
  if 'href="/vic/">Victoria</a><a href="/nsw/">New South Wales</a>' not in home: bad.append(("/", "state menu"))
  if 'src="/map-home.js"' in vic or 'src="/map.js"' not in vic: bad.append(("/vic/", "map script"))
  if 'class="state-pick"' not in nsw_html or 'aria-label="State: New South Wales"' not in nsw_html or ">NSW <" not in nsw_html: bad.append(("nsw", "state picker"))
  if 'href="/nsw/" aria-current="page"' not in nsw_html or 'href="/vic/">Victoria</a>' not in nsw_html: bad.append(("nsw", "state menu"))
  if 'src="/map-nsw.js"' not in nsw_html or 'src="/map.js"' in nsw_html: bad.append(("nsw", "town script"))
  if "nsw-towns.json" in home or "map-nsw.js" in home: bad.append(("/", "nsw towns on the victoria page"))
  split = tempfile.mkdtemp(prefix="campconditions-digest-states-")
  split_env = os.environ.copy()
  split_env["CAMPCONDITIONS_ENABLE"] = "nsw"
  split_run = subprocess.run([sys.executable, os.path.join(root, "scripts", "digest.py"), "--current", os.path.join(D, "status.json"), "--out", split], cwd=root, capture_output=True, text=True, env=split_env)
  if split_run.returncode != 0:
    bad.append(("digest states", (split_run.stderr or split_run.stdout)[-240:]))
  else:
    vic_draft = open(os.path.join(split, "digest.html"), encoding="utf-8").read()
    nsw_draft = open(os.path.join(split, "nsw", "digest.html"), encoding="utf-8").read()
    vic_meta = json.load(open(os.path.join(split, "meta.json"), encoding="utf-8"))
    nsw_meta = json.load(open(os.path.join(split, "nsw", "meta.json"), encoding="utf-8"))
    if vic_meta.get("state") != "vic" or nsw_meta.get("state") != "nsw": bad.append(("digest states", "meta state"))
    if "Brewery Flat" in vic_draft: bad.append(("digest states", "nsw camp in victoria"))
    if "Victoria" not in vic_draft or "New South Wales" not in nsw_draft: bad.append(("digest states", "copy"))
    def camp_count(blob):
      found = re.search(r"of (\d+) campgrounds are closed", blob)
      return int(found.group(1)) if found else -1
    if camp_count(vic_draft) + camp_count(nsw_draft) != len(feed["camps"]):
      bad.append(("digest states", f"{camp_count(vic_draft)}+{camp_count(nsw_draft)}!={len(feed['camps'])}"))
  if "Spatial Services" not in nsw_html or "Creative Commons Attribution 4.0" not in nsw_html: bad.append(("nsw", "town attribution"))
  nsw_map = open(os.path.join(D, "map-nsw.js"), encoding="utf-8").read()
  if 'fetch("/nsw-towns.json")' not in nsw_map or "vic-towns.json" in nsw_map: bad.append(("map-nsw.js", "town file"))
  if 'fetch("/nsw-place-points.json")' not in nsw_map or "bestTownD <= 40" not in nsw_map: bad.append(("map-nsw.js", "place labels"))
  if 'fetch("/vic-towns.json")' not in mj or "nsw-place-points.json" in mj or "bestTownD" in mj or "chunkedLoading" in mj or "stateName" in mj: bad.append(("map.js", "victoria towns"))
  home_map = open(os.path.join(D, "map-home.js"), encoding="utf-8").read()
  if 'fetch("/vic-towns.json")' not in home_map or 'fetch("/nsw-towns.json")' not in home_map: bad.append(("map-home.js", "towns"))
  if "nsw-place-points.json" in home_map or "bestTownD" in home_map: bad.append(("map-home.js", "nsw places"))
  if "chunkedLoading: true" not in home_map or "camp.stateName || regionName" not in home_map or "addLayers" not in home_map: bad.append(("map-home.js", "cluster"))
  home_map_pts = map_data("/", home, vic_only=False)
  if 'id="camp-map-data" data-url="/map-points/home.json?v=' not in home or "camp-map-data\">[" in home:
    bad.append(("/", "inline map json"))
  vic_n = sum(str(p.get("url", "")).startswith("/vic/camp/") for p in home_map_pts)
  nsw_n = sum(str(p.get("url", "")).startswith("/nsw/camp/") for p in home_map_pts)
  if vic_n != len(vic_feed) or nsw_n < 1 or vic_n + nsw_n != len(home_map_pts): bad.append(("/", f"national points {vic_n}+{nsw_n}"))
  if any(p.get("stateName") not in ("Victoria", "New South Wales") for p in home_map_pts): bad.append(("/", "stateName"))
  if any(p.get("stateName") != "Victoria" for p in vic_pts): bad.append(("/vic/", "stateName on combined build"))
  nsw_towns = json.load(open(os.path.join(D, "nsw-towns.json"), encoding="utf-8"))
  town_names = {row.get("name", "").casefold() for row in nsw_towns}
  for required in ("Narrandera", "Dubbo", "Tumut", "Goulburn", "Gillenbah"):
    if required.casefold() not in town_names: bad.append(("nsw-towns.json", required))
  if any(row.get("lat") is None or row.get("lon") is None or not row.get("name") for row in nsw_towns): bad.append(("nsw-towns.json", "blank coordinate"))
  if any(row["name"] == "Canberra" for row in nsw_towns): bad.append(("nsw-towns.json", "Canberra"))
  places = json.load(open(os.path.join(D, "nsw-place-points.json"), encoding="utf-8"))
  place_by = {row["name"]: row for row in places}
  for required, kind in (("Goulburn", "city"), ("Wagga Wagga", "city"), ("Albury", "city"), ("Orange", "city"), ("Bathurst", "city"), ("Tamworth", "city"), ("Armidale", "city"), ("Broken Hill", "city"), ("Port Macquarie", "town"), ("Coffs Harbour", "city"), ("Narrandera", "town"), ("Gillenbah", "locality")):
    row = place_by.get(required)
    if not row or row.get("place") != kind: bad.append(("nsw-place-points.json", required))
    search = next((item for item in nsw_towns if item["name"] == required), None)
    if required != "Gillenbah" and (not search or search.get("place") != kind): bad.append(("nsw-towns.json", required + " class"))
  def town_km(lat1, lon1, lat2, lon2):
    radius = math.pi / 180
    dlat, dlon = (lat2 - lat1) * radius, (lon2 - lon1) * radius
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1 * radius) * math.cos(lat2 * radius) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(hav)))
  def nearest_town(lat, lon):
    return min(nsw_towns, key=lambda row: town_km(lat, lon, row["lat"], row["lon"]))
  nsw_camps = [c for c in feed["camps"] if "/nsw/camp/" in c.get("url", "")]
  def nearest_camps(place, limit=15):
    ranked = sorted(nsw_camps, key=lambda camp: town_km(place["lat"], place["lon"], camp["lat"], camp["lon"]))
    return ranked[:limit]
  narrandera = next(row for row in nsw_towns if row["name"] == "Narrandera")
  if not any(camp["name"].startswith("Brewery Flat") for camp in nearest_camps(narrandera)): bad.append(("Narrandera", "Brewery Flat"))
  brewery = next(camp for camp in nsw_camps if camp["name"].startswith("Brewery Flat"))
  import towns as town_mod
  brewery_label, brewery_km = town_mod.nearest_label(brewery["lat"], brewery["lon"], places)
  if brewery_label != "Narrandera": bad.append(("Brewery Flat", brewery_label))
  brewery_page = open(os.path.join(D, "nsw", "camp", brewery["slug"], "index.html"), encoding="utf-8").read()
  if "Near Narrandera" not in brewery_page or "Near Gillenbah" in brewery_page: bad.append(("Brewery Flat", "page label"))
  if 'href="https://www.livetraffic.com/"' not in brewery_page or "Check Live Traffic NSW" not in brewery_page or "traffic.transport.vic.gov.au" in brewery_page: bad.append(("Brewery Flat", "roads"))
  if "/nsw/nsw/" in brewery_page or ">New South Wales</a> › <a href=\"/nsw/nsw/\">" in brewery_page: bad.append(("Brewery Flat", "one region"))
  if "Riverina" not in brewery_page: bad.append(("Brewery Flat", "region"))
  redirects = open(os.path.join(D, "_redirects"), encoding="utf-8").read()
  for line in ("/contact /about/ 301", "/contact/ /about/ 301", "/nsw/nsw /nsw/ 301", "/nsw/nsw/ /nsw/ 301"):
    if line not in redirects: bad.append(("_redirects", line))
  terms = open(os.path.join(D, "terms", "index.html"), encoding="utf-8").read()
  if "Terms of use" not in terms or "as is, without warranty" not in terms or "Victoria." not in terms or "New South Wales." not in terms or "governing law" in terms.lower(): bad.append(("terms", "wording"))
  if "NPWS" not in about or "NSW Rural Fire Service" not in about or "Spatial Services" not in about or "livetraffic.com" not in about: bad.append(("about", "nsw credits"))
  if about.count("DataVic and Explore Outdoors") != 2: bad.append(("about", "duplicated datavic credit"))
  if feed.get("region") != "Victoria and New South Wales, Australia": bad.append(("status.json", feed.get("region")))
  joined = " ".join(feed.get("attribution") or [])
  if "Victoria:" not in feed.get("disclaimer", "") or "New South Wales:" not in feed.get("disclaimer", ""): bad.append(("status.json", "disclaimer"))
  for credit in ("NPWS Visitor Area", "NSW Rural Fire Service", "Spatial Services", "livetraffic.com"):
    if credit not in joined and credit not in feed.get("disclaimer", ""): bad.append(("status.json", credit))
  if states.region_id(states.by_slug("nsw"), 151.2153, -33.8568) != "sydney": bad.append(("regions", "sydney"))
  if states.region_id(states.by_slug("nsw"), 146.550606, -34.753557) != "riverina": bad.append(("regions", "riverina"))
  if os.path.isdir(os.path.join(D, "nsw", "nsw")): bad.append(("/nsw/nsw/", "still built"))
  for place_name in ("Goulburn", "Wagga Wagga", "Albury", "Orange", "Bathurst", "Tamworth", "Armidale", "Broken Hill", "Port Macquarie", "Coffs Harbour"):
    place = next(row for row in nsw_towns if row["name"] == place_name)
    closest = nearest_camps(place, 1)[0]
    gap = town_km(place["lat"], place["lon"], closest["lat"], closest["lon"])
    if gap > 15: bad.append((place_name, closest["name"] + " " + str(round(gap, 1))))
  for place_name in ("Dubbo", "Tumut"):
    place = next(row for row in nsw_towns if row["name"] == place_name)
    closest = nearest_camps(place, 1)[0]
    if town_km(place["lat"], place["lon"], closest["lat"], closest["lon"]) > 40: bad.append((place_name, closest["name"]))
  for camp in nsw_camps:
    page = os.path.join(D, camp["url"].lstrip("/"), "index.html")
    if not os.path.isfile(page):
      continue
    heading = re.search(r"<h1>([^<]*)</h1>", open(page, encoding="utf-8").read())
    if not heading or ", near " not in heading.group(1):
      continue
    place = heading.group(1).split(", near ", 1)[1].split(",")[0].strip()
    place = re.sub(r" \((?:south|north|\d+)\)$", "", place)
    if place.casefold() not in town_names: bad.append((camp["slug"], "near " + place)); break
  npws = [c for c in nsw_camps if c.get("source") == "npws"]
  if len(npws) < 700: bad.append(("nsw", "npws count " + str(len(npws))))
  ratings = ("None", "No Rating", "Moderate", "High", "Extreme", "Catastrophic")
  closed_npws = []
  for camp in npws:
    closure = camp.get("closure") or {}
    if camp.get("status") == "closed":
      if not str(closure.get("desc") or "").strip() or not str(closure.get("source_url") or "").startswith("https://www.nationalparks.nsw.gov.au/"):
        bad.append((camp.get("slug"), "closed without alert")); break
      closed_npws.append(camp)
    elif camp.get("status") != "check" or closure:
      bad.append((camp.get("slug"), "npws status")); break
  if len(closed_npws) < 1: bad.append(("nsw", "no alert closure"))
  fire_pages = 0
  for camp in nsw_camps:
    page = os.path.join(D, "nsw", "camp", camp["slug"], "index.html")
    if not os.path.isfile(page):
      continue
    html_page = open(page, encoding="utf-8").read()
    main = html_page.split("<main>", 1)[-1]
    if html_page.count('class="banner-row"') != 2: bad.append((camp["slug"], "header rows")); break
    if "Total fire ban:" in html_page.split("<main>", 1)[0]: bad.append((camp["slug"], "fire in header")); break
    if "Total fire ban:" not in main:
      continue
    fire_pages += 1
    if '<h2 class="fire-head"' not in main or ">Fire Ratings</h2>" not in main: bad.append((camp["slug"], "fire heading")); break
    if ">NSW RFS</a>" in main: bad.append((camp["slug"], "inline rfs link")); break
    if "https://www.rfs.nsw.gov.au/feeds/fdrToban.xml" not in html_page: bad.append((camp["slug"], "fire source")); break
    if "© State of New South Wales (NSW Rural Fire Service)." not in html_page: bad.append((camp["slug"], "rfs attribution")); break
    loc = re.search(r"Location: (-?\d+(?:\.\d+)?), (-?\d+(?:\.\d+)?)", main)
    link = re.search(r'href="(https://www.rfs.nsw.gov.au/fire-information/fdr-and-tobans\?[^"]+)"', main)
    href = html.unescape(link.group(1)) if link else ""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
    same = loc and query.get("lat") and query.get("lng") and abs(float(query["lat"][0]) - float(loc.group(1))) < 1e-6 and abs(float(query["lng"][0]) - float(loc.group(2))) < 1e-6
    if not same or "fullAddress" not in query or not query.get("placeId"):
      bad.append((camp["slug"], "rfs deep link")); break
    if not any(token in main for token in ratings): bad.append((camp["slug"], "fire rating")); break
    if main.count('class="banner-row"'): bad.append((camp["slug"], "banner in page")); break
  if fire_pages < 1: bad.append(("nsw", "no fire danger line"))
  if "Total fire ban:" in home or "NPWS alerts:" in home or "Official NPWS wording" in home: bad.append(("/", "nsw conditions on victoria"))
  if npws:
    sample = os.path.join(D, "nsw", "camp", npws[0]["slug"], "index.html")
    if os.path.isfile(sample):
      sample_html = open(sample, encoding="utf-8").read()
      if "no road or track closures were found" in sample_html or "<h2>Facilities</h2>" in sample_html:
        bad.append((npws[0]["slug"], "invented detail"))
  if closed_npws:
    closed_html = open(os.path.join(D, "nsw", "camp", closed_npws[0]["slug"], "index.html"), encoding="utf-8").read()
    if "NPWS alert" not in closed_html or "badge closed" not in closed_html or "Official NPWS wording" not in closed_html or "Alert dated" not in closed_html: bad.append((closed_npws[0]["slug"], "closed page"))
print(f"{n} pages, {ldn} JSON-LD blocks valid, {len(sm)} sitemap URLs, {len(home_pts)} map points, {len(bad)} broken, {len(warnings)} warnings")
for item in warnings: print("WARN", item)
for item in bad[:20]: print(item)
sys.exit(1 if bad else 0)
