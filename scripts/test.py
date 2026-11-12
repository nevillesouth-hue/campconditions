import gzip,os,re,json,sys,html,math,subprocess,tempfile,urllib.parse,hashlib
def tip_presentation(label, html_blob, txt_blob, bad):
  """Approved digest tip presentation (HTML + plain text)."""
  if '<strong>Been somewhere lately?</strong>' not in html_blob: bad.append((label, "bold report"))
  if '<strong>The digests stay free.</strong> If they’re useful' not in html_blob or html_blob.count("<strong>The digests stay free") != 1: bad.append((label, "bold tip opener"))
  if '<br><a href="https://campconditions.au/support" style="color:#2f5d3a;">Chip in</a> $5, $10 or $20<br>No pressure either way.' not in html_blob: bad.append((label, "chip in link"))
  if html_blob.count("campconditions.au/support") != 1 or ">https://campconditions.au/support" in html_blob or "→ Chip in" in html_blob or "campconditions.au/support/" in html_blob: bad.append((label, "support url visible"))
  if txt_blob:
    if "\nChip in $5, $10 or $20\nNo pressure either way." not in txt_blob or "campconditions.au/support" in txt_blob: bad.append((label + " txt", "chip in"))
  for blob in (html_blob, txt_blob):
    if blob and not (0 <= blob.find("Been somewhere lately?") < blob.find("The digests stay free.") < blob.find("Chip in") < blob.find("No pressure either way.") < blob.find("Not an official warning service")): bad.append((label, "tip order"))
D=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"dist");bad=[];warnings=[];n=0;ldn=0;spoken_dates=0
def draft_dir(path):
  return "digest" in path.replace("\\", "/").split("/")
_asset_hash = {}
def asset_hash(rel):
  if rel not in _asset_hash:
    path = os.path.join(D, rel.lstrip("/"))
    _asset_hash[rel] = hashlib.sha256(open(path, "rb").read()).hexdigest()[:8] if os.path.isfile(path) else ""
  return _asset_hash[rel]
_ASSET_TAG = re.compile(r"<(?:script|link)\b[^>]*>", re.I)
_ASSET_URL = re.compile(r"""\b(?:src|href)\s*=\s*(["'])([^"']+)\1""", re.I)
def check_asset_urls(page_path, text):
  """Site-local .js and .css use ?v=<sha256 prefix>. Leaflet CDN links stay bare."""
  for tag in _ASSET_TAG.findall(text):
    for _quote, url in _ASSET_URL.findall(tag):
      if url.startswith(("http://", "https://", "//")):
        if "leaflet" in url and "?v=" in url.split("#", 1)[0]:
          bad.append((page_path, "cdn query", url))
        continue
      bare, _, query = url.partition("?")
      bare = bare.split("#", 1)[0]
      if not bare.startswith("/") or not bare.lower().endswith((".js", ".css")):
        continue
      digest = asset_hash(bare)
      if not digest or query != "v=" + digest:
        bad.append((page_path, "asset version", url, digest))
        return
for r,_,fs in os.walk(D):
  if draft_dir(r): continue
  for f in fs:
    if not f.endswith(".html"): continue
    p=os.path.join(r,f);t=open(p).read();n+=1
    check_asset_urls(p[len(D):] or "/", t)
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>',t,re.S): json.loads(m);ldn+=1
    for h in re.findall(r'href="(/[^"#?]*)',t):
      tgt=os.path.join(D,h.lstrip("/"));
      if not (os.path.isfile(tgt) or os.path.isfile(os.path.join(tgt,"index.html"))): bad.append((p[len(D):],h))
    if "<title>" not in t or not re.search(r"lang=[\"']en-AU", t): bad.append((p,"meta"))
    if re.search(r"Campground data dated \d{4}-\d{2}-\d{2}\b", t) or re.search(r"point dated \d{4}-\d{2}-\d{2}\b", t):
      bad.append((p[len(D):], "raw data date"))
    if re.search(r"Campground data dated \d{1,2} [A-Z][a-z]+ \d{4}", t): spoken_dates += 1
    if "paid daily digest" in t or "about $5 a month" in t: bad.append((p[len(D):], "paid digest line"))
if spoken_dates < 1: bad.append(("footer", "campground date not spoken"))
for f in ["sitemap.xml","robots.txt","llms.txt","status.json"]: assert os.path.isfile(os.path.join(D,f)),f
json.load(open(os.path.join(D,"status.json")))
sm=re.findall(r"<loc>https://campconditions.au(.*?)</loc>",open(os.path.join(D,"sitemap.xml")).read())
for u in sm:
  if not os.path.isfile(os.path.join(D,u.lstrip("/"),"index.html")): bad.append(("sitemap",u))
feed=json.load(open(os.path.join(D,"status.json")))
vic_feed=[c for c in feed["camps"] if "/vic/camp/" in c.get("url","")]
_STATUS_FROM = {"o": "open", "k": "check", "x": "closed"}
_STATE_FROM = {"v": ("vic", "Victoria"), "n": ("nsw", "New South Wales"), "q": ("qld", "Queensland"), "s": ("sa", "South Australia"), "t": ("tas", "Tasmania")}
def expand_map_point(pt):
  if isinstance(pt, dict):
    return pt
  if not isinstance(pt, list) or len(pt) < 6:
    return pt
  st = pt[5] or ""
  slug_state, state_name = _STATE_FROM.get(st, ("", ""))
  slug = pt[4] or ""
  out = {
    "name": pt[0], "lat": pt[1], "lon": pt[2],
    "status": _STATUS_FROM.get(pt[3], pt[3]),
    "slug": slug,
    "url": f"/{slug_state}/camp/{slug}/" if slug_state and slug else "",
    "cat": pt[6] if len(pt) > 6 and pt[6] else "",
    "type": pt[7] if len(pt) > 7 and pt[7] else "",
    "cost": pt[8] if len(pt) > 8 and pt[8] else "",
  }
  if state_name:
    out["stateName"] = state_name
  if len(pt) > 9 and pt[9] in (0, 1):
    out["dogs"] = pt[9]
  if len(pt) > 10 and pt[10] in (0, 1):
    out["caravans"] = pt[10]
  if len(pt) > 11 and pt[11] in (0, 1):
    out["motorhomes"] = pt[11]
  if len(pt) > 12 and pt[12]:
    out["reg"] = pt[12]
  if len(pt) > 13 and pt[13]:
    out["note"] = pt[13]
  return out
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
  data = [expand_map_point(pt) for pt in data]
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
  if 'id="camp-map"' not in html or 'src="/map.js?v=' not in html:
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
  if 'src="/map.js"' in home or 'src="/map.js?v=' in home or 'src="/map-home.js?v=' not in home or 'id="camp-map"' not in home: bad.append(("/", "national map"))
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
  region_html=open(page, encoding="utf-8").read()
  pts=expect_map(f"/vic/{name}/", region_html, True)
  if len(pts)!=len(by.get(name, [])): bad.append((f"/vic/{name}/", "region map count"))
  if 'name="states" value="vic" checked' not in region_html or 'name="states" value="nsw" checked' in region_html:
    bad.append((f"/vic/{name}/", "signup states"))
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
    if 'name="states" value="vic" checked' not in html_page or 'name="states" value="nsw" checked' in html_page:
      bad.append((slug, "signup states"))
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
        # Victoria camp rules may mention fire-danger days. NSW pages quote the RFS district rating; QLD pages quote the BoM one.
        shared_ok = national and (os.path.dirname(rel) == D and f in ("index.html", "status.json", "llms.txt", "404.html") or any(bit in rel for bit in (f"{os.sep}about{os.sep}", f"{os.sep}privacy{os.sep}", f"{os.sep}terms{os.sep}", f"{os.sep}report{os.sep}", f"{os.sep}unsubscribe{os.sep}")))
        # CFA district ratings are an official feed. The old ban was the VicEmergency warning text.
        cfa_ok = needle == "fire danger" and ("cfa.vic.gov.au" in blob or "country fire authority" in blob)
        if needle == "fire danger" and (f"{os.sep}vic{os.sep}camp{os.sep}" in rel or f"{os.sep}nsw{os.sep}" in rel or f"{os.sep}qld{os.sep}" in rel or f"{os.sep}sa{os.sep}" in rel or f"{os.sep}tas{os.sep}" in rel or f == "parksvic-flags.json" or shared_ok or cfa_ok):
          continue
        # Parks SA and theLIST credits use CC BY 3.0 AU. That credit also appears on shared pages.
        if needle == "CC BY 3.0" and "cc by 3.0 au" in blob and ("parks.sa.gov.au" in blob or "state of tasmania" in blob):
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
  _qld_priv = os.path.isdir(os.path.join(D, "qld"))
  for bit in ("Last updated 4 November 2026" if _qld_priv else "Last updated 27 October 2026", "campconditions@outlook.com", "Victoria, New South Wales and Queensland" if _qld_priv else "Victoria and New South Wales", "email address", "date and time", "tracking cookies", "Cloudflare", "IP address", "Resend", "outside Australia", "double opt-in", "unsubscribe link", "within 30 days", "OAIC", "never sell, rent or share", "Changes to this policy"):
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
  tip_html = open(os.path.join(draft, "digest.html"), encoding="utf-8").read()
  tip_txt = open(os.path.join(draft, "digest.txt"), encoding="utf-8").read()
  tip_phrase = "If they’re useful and you want to chip in, a one-off tip helps cover the running costs — coffee money is plenty."
  for label, blob in (("digest.html", tip_html), ("digest.txt", tip_txt)):
    if tip_phrase not in blob: bad.append((label, "tip block"))
    if "No pressure either way." not in blob: bad.append((label, "tip close"))
    if blob.count(tip_phrase) != 1: bad.append((label, "tip once"))
    report_at = blob.find("Been somewhere lately?")
    tip_at = blob.find(tip_phrase)
    foot_at = blob.find("Not an official warning service")
    if not (0 <= report_at < tip_at < foot_at): bad.append((label, "tip placement"))
  tip_presentation("digest", tip_html, tip_txt, bad)
confirm = subprocess.run(["node", "--input-type=module", "-e", """
import { confirmationMessage } from "./functions/api/subscribe.js";
const unsub = "https://campconditions.au/api/unsubscribe?e=reader%40example.com&t=abc";
const link = "https://campconditions.au/api/confirm?token=abc";
const m = confirmationMessage("https://campconditions.au", link, unsub, ["vic"], "reader@example.com");
const need = ["CampConditions.au", "https://campconditions.au/privacy/", "Unsubscribe"];
const ask = "Please confirm you'd like updates sent to reader@example.com.";
for (const blob of [m.html, m.text]) {
  for (const bit of need) if (!blob.includes(bit)) { console.error("missing " + bit); process.exit(1); }
  if (blob.includes("mailto:campconditions@outlook.com?subject=Unsubscribe")) process.exit(1);
  if (blob.includes("Victoria digest")) process.exit(1);
}
if (!m.text.includes(ask) || !m.html.includes(ask.replace(/'/g, "&#39;"))) process.exit(1);
if (!m.text.includes(unsub) || !m.html.includes(unsub.replace(/&/g, "&amp;"))) process.exit(1);
if (!m.html.includes("digest for Victoria") || !m.text.includes("digest for Victoria")) process.exit(1);
if (!m.html.includes("background:#2f5d3a") || !m.html.includes(">Confirm my subscription</a>")) process.exit(1);
if (m.html.split("api/confirm?token=abc").length < 4) process.exit(1);
if (!m.text.includes("Confirm my subscription:\\n" + link)) process.exit(1);
const both = confirmationMessage("https://campconditions.au", link, unsub, ["nsw", "vic"], "reader@example.com");
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
import { QLD_SEGMENT_ID } from "./functions/api/confirm.js";
import { chosenStates, statePhrase } from "./functions/_lib/token.js";
if (chosenStates(["qld", "vic", "bogus"]).join(",") !== "vic,qld" || statePhrase(["vic", "nsw", "qld"]) !== "Victoria, New South Wales and Queensland") process.exit(1);
const qldRead = await readToken(await makeToken(email, "test-secret", 60 * 60 * 48, ["qld"]), "test-secret");
if (!qldRead || qldRead.states.join(",") !== "qld") process.exit(1);
const callsQld = [];
const mockQld = async (url, init) => { callsQld.push({ url, method: init.method, body: init.body }); return new Response(JSON.stringify({ id: "c1" }), { status: 201 }); };
const qldOnly = await confirmSubscription({ ...envWithSecret, RESEND_SEGMENT_NSW_ID: "nsw-segment" }, email, mockQld, ["qld"], true);
if (!qldOnly.ok || callsQld.some((call) => String(call.url).includes(segment) || String(call.url).includes("nsw-segment"))) process.exit(2);
if (!callsQld.some((call) => String(call.url).endsWith("/segments/" + QLD_SEGMENT_ID) && call.method === "POST")) process.exit(3);
const callsQldEnv = [];
await confirmSubscription({ ...envWithSecret, RESEND_SEGMENT_QLD_ID: "qld-override" }, email, async (url, init) => { callsQldEnv.push(url); return new Response("{}", { status: 201 }); }, ["vic", "qld"], true);
if (!callsQldEnv.some((u) => u.endsWith("/segments/qld-override")) || !callsQldEnv.some((u) => u.endsWith("/segments/" + segment))) process.exit(4);
const callsMerge = [];
const mockMerge = async (url, init) => {
  callsMerge.push({ url, method: init.method, body: init.body });
  if (url.endsWith("/contacts") && init.method === "POST") return new Response(JSON.stringify({ name: "already_exists" }), { status: 409 });
  if (init.method === "GET") return new Response(JSON.stringify({ email, properties: { states: "vic,nsw" } }), { status: 200 });
  return new Response("{}", { status: 200 });
};
const merged = await confirmSubscription(envWithSecret, email, mockMerge, ["qld"], true);
if (!merged.ok || !callsMerge.some((c) => c.method === "PATCH" && c.body && c.body.includes('"states":"vic,nsw,qld"'))) process.exit(5);
if (callsMerge.some((c) => String(c.url).endsWith("/segments/" + segment))) process.exit(6);
const callsNew = [];
await confirmSubscription(envWithSecret, email, async (url, init) => { callsNew.push({ url, method: init.method, body: init.body }); return new Response(JSON.stringify({ id: "c1" }), { status: 201 }); }, ["qld"], true);
if (callsNew.some((c) => c.method === "GET") || !callsNew.some((c) => c.method === "PATCH" && c.body && c.body.includes('"states":"qld"'))) process.exit(7);
const callsLookupFail = [];
await confirmSubscription(envWithSecret, email, async (url, init) => { callsLookupFail.push({ url, method: init.method, body: init.body }); if (url.endsWith("/contacts") && init.method === "POST") return new Response("{}", { status: 409 }); if (init.method === "GET") return new Response("no", { status: 500 }); return new Response("{}", { status: 200 }); }, ["qld"], true);
if (!callsLookupFail.some((c) => c.method === "PATCH" && c.body && c.body.includes('"states":"qld"'))) process.exit(8);
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
if (calls.length !== 3 || calls[0].method !== "PATCH" || !calls[0].body.includes('"unsubscribed":true')) process.exit(1);
if (calls[1].method !== "DELETE" || !calls[1].url.endsWith("/contacts/reader%40example.com/segments/" + segment)) process.exit(1);
if (calls[2].method !== "DELETE" || !calls[2].url.endsWith("/segments/2488900b-f026-44e8-9d74-098d38ef3468")) process.exit(1);
calls.length = 0;
const posted = await onRequestPost({ request: new Request(url, { method: "POST", body: "List-Unsubscribe=One-Click" }), env });
if (posted.status !== 200 || !(await posted.text()).includes("You're unsubscribed") || calls.length !== 3) process.exit(1);
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
import facts as _stay_facts
for _raw, _want in (("3 (72 hours)", "3 nights (72 hours)"), ("1 (24 hours)", "1 night (24 hours)"), ("2", "2 nights"), ("72 hours", "72 hours")):
  if _stay_facts.stay_label(_raw) != _want: bad.append(("stay label", _raw, _stay_facts.stay_label(_raw)))
if re.search(r"Max stay: \d+ \(\d+ hours\)", open(os.path.join(D, "nsw", "camp", "lions-park-bulahdelah", "index.html"), encoding="utf-8").read()): bad.append(("lions-park-bulahdelah", "stay nights"))
# Moira Shire sits on the Murray, not in the Yarra Ranges.
for _slug in ("lions-park-numurkah", "numurkah-showgrounds", "lions-rv-park-tungamah", "katamatite-lions-memorial-park"):
  _row = next((c for c in feed["camps"] if c.get("slug") == _slug), None)
  if not _row or _row.get("region") != "murray-mallee": bad.append((_slug, "region", _row and _row.get("region")))
if states.by_slug("vic").get("credit") != CREDIT: bad.append(("states", "credit"))
if [state["slug"] for state in states.enabled()] != ["vic", "nsw", "qld", "sa", "tas"]: bad.append(("states", "enabled"))
if not all(states.by_slug(_s).get("enabled") for _s in ("vic", "nsw", "qld")): bad.append(("states", "flags"))
if states.by_slug("act").get("enabled"): bad.append(("states", "act enabled"))
os.environ["CAMPCONDITIONS_ENABLE"] = "nsw"
try:
  if [state["slug"] for state in states.enabled()] != ["vic", "nsw", "qld", "sa", "tas"]: bad.append(("states", "preview enable"))
finally:
  os.environ.pop("CAMPCONDITIONS_ENABLE", None)
if [state["slug"] for state in states.enabled()] != ["vic", "nsw", "qld", "sa", "tas"]: bad.append(("states", "enable reset"))
act_sa = subprocess.run([sys.executable, os.path.join(root, "scripts", "test_act_sa.py")], cwd=root)
if act_sa.returncode != 0: bad.append(("act-sa foundations", "test_act_sa.py failed"))
tas_check = subprocess.run([sys.executable, os.path.join(root, "scripts", "test_tas.py")], cwd=root)
if tas_check.returncode != 0: bad.append(("tas foundations", "test_tas.py failed"))
one_list = subprocess.run([sys.executable, os.path.join(root, "scripts", "test_one_list.py")], cwd=root)
if one_list.returncode != 0: bad.append(("one-list", "test_one_list.py failed"))
if "Queensland and Queensland" in open(os.path.join(D, "index.html"), encoding="utf-8").read(): bad.append(("home", "state names repeated"))
about = open(os.path.join(D, "about", "index.html"), encoding="utf-8").read()
if CREDIT not in about: bad.append(("credit", "footer or about"))
if "Department of Energy, Environment and Climate Action" not in about or "Explore Outdoors" not in about or "Recreation Assets" not in about: bad.append(("credit", "explore outdoors"))
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
_long = "Cache-Control: public, max-age=31536000, immutable"
for _dir, _sub, _files in os.walk(D):
  _sub[:] = [name for name in _sub if name != "assets"]
  for _name in _files:
    if not _name.endswith((".js", ".css")): continue
    _rel = "/" + os.path.relpath(os.path.join(_dir, _name), D).replace(os.sep, "/")
    if f"{_rel}\n  {_long}" not in headers:
      bad.append(("_headers", "long cache", _rel))
    if f"{_rel}\n  Cache-Control: no-cache" in headers:
      bad.append(("_headers", "versioned no-cache", _rel))
_rep = home.find('href="/report/">Report<span class="nav-x"> conditions</span></a>')
if _rep < 0 or home.find('<a href="/faq/">FAQ</a><a href="/about/">About</a><a href="/support/">Chip in</a></nav>') < _rep or ".nav-x{display:none}" not in home:
  bad.append(("/", "about nav"))
if '<a href="/support/">Chip in</a></nav>' not in home:
  bad.append(("/", "chip in nav"))
if '<strong>The digests stay free. If they’re useful, you can <a href="/support/">chip in</a>.</strong>' not in home:
  bad.append(("/", "chip in signup line"))
if '· <a href="/support/">Chip in</a> ·' not in home.split("<footer>", 1)[-1].split("</footer>", 1)[0]:
  bad.append(("/", "chip in footer"))
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
# Camp-page form fills the same email. /report/ still has no form and stores nothing.
for _field in ('params.get("visited")', 'params.get("full")', 'params.get("access")', 'params.get("notes")', 'params.get("by")', 'params.get("state")', 'params.get("page")'):
  if _field not in report: bad.append(("report", "visitor field", _field))
if 'class="visitor-report"' in report or 'class="visitor-report"' in home or 'id="visitor-report"' in home:
  bad.append(("report", "form on the wrong page"))
def _sample_camp(state_slug):
  for camp in feed["camps"]:
    if f"/{state_slug}/camp/" in (camp.get("url") or ""):
      return camp
  return None
for _state in ("vic", "nsw", "qld", "sa", "tas"):
  _sample = _sample_camp(_state)
  if not _sample:
    if os.path.isdir(os.path.join(D, _state)): bad.append((_state, "no camp for visitor report"))
    continue
  _rel = _sample["url"].split("campconditions.au/", 1)[-1]
  _html = open(os.path.join(D, _rel, "index.html"), encoding="utf-8").read()
  _need = (
    'id="visitor-report"', 'class="visitor-report"', 'method="get"', 'action="/report/"',
    'name="visited"', 'name="full"', 'name="access"', 'name="notes"', 'name="by"',
    'name="camp"', 'name="state"', 'name="page"', "Email this report",
    "mailto:campconditions@outlook.com", "After we check it, the report is shown on this page.", "This prepares an email",
    f'name="camp" value="{_sample["slug"]}"', f'name="state" value="{_state}"',
    'class="banner-row"', "flex:1 0 100%;flex-wrap:nowrap",
  )
  if any(bit not in _html for bit in _need) or _html.count('class="banner-row"') != 2 or _html.find("</header>") > _html.find('id="visitor-report"'):
    bad.append((_sample["slug"], "visitor report form"))
_reports = json.load(open(os.path.join(root, "data", "camper-reports.json"), encoding="utf-8"))
for _state, _camps in _reports.items():
  if str(_state).startswith("_") or not isinstance(_camps, dict): continue
  for _slug, _rows in _camps.items():
    _path = os.path.join(D, _state, "camp", _slug, "index.html")
    if not os.path.isfile(_path):
      bad.append((_slug, "camper report page missing")); continue
    _page = open(_path, encoding="utf-8").read()
    if "<h2>Camper reports</h2>" not in _page or "not checked by the land manager" not in _page:
      bad.append((_slug, "camper reports box"))
    for _row in _rows:
      if html.escape(_row.get("text") or "", quote=True) not in _page or html.escape(_row.get("by") or "a camper", quote=True) not in _page:
        bad.append((_slug, "camper report text"))
if 'alt="CampConditions.au logo"' not in home or 'src="/assets/brand/logo-160.png"' not in home or 'width="160" height="160"' not in home or ".logo{width:4.8rem;height:4.8rem" not in home or "15.9vw" not in home:
  bad.append(("/", "logo"))
if "optimum-quest" in home or "⛺" in home.split("<main>", 1)[0]: bad.append(("/", "old tent logo"))
_codes = "VIC, NSW, QLD, SA and TAS" if os.path.isdir(os.path.join(D, "tas")) else ("VIC, NSW, QLD and SA" if os.path.isdir(os.path.join(D, "sa")) else ("VIC, NSW and QLD" if os.path.isdir(os.path.join(D, "qld")) else "VIC and NSW"))
for icon in ("/assets/brand/favicon.ico", "/assets/brand/favicon-32.png", "/assets/brand/apple-touch-icon.png", "/site.webmanifest", 'content="https://campconditions.au/assets/brand/og-image-vic-nsw-qld-sa-tas.png?v=20261110"', 'content="1200"', 'content="630"', 'content="summary_large_image"',
             'property="og:image:alt" content="CampConditions.au: 5,000+ campgrounds across VIC, NSW, QLD, SA and TAS"', 'name="twitter:image:alt" content="CampConditions.au: 5,000+ campgrounds across VIC, NSW, QLD, SA and TAS"',
             f'property="og:title" content="Camp conditions and closures for {_codes} | CampConditions.au"', f'name="twitter:title" content="Camp conditions and closures for {_codes} | CampConditions.au"'):
  if icon not in home: bad.append(("/", "icon " + icon))
# Link-preview description: rounded count (row 56), never above the live total, same for Twitter.
_og_desc = re.search(r'property="og:description" content="([^"]*)"', home)
_tw_desc = re.search(r'name="twitter:description" content="([^"]*)"', home)
_og_n = re.search(r"for ([\d,]+)\+ campgrounds across " + re.escape(_codes) + r"\.$", _og_desc.group(1)) if _og_desc else None
if not _og_n or not _tw_desc or _tw_desc.group(1) != _og_desc.group(1): bad.append(("/", "og description", _og_desc and _og_desc.group(1)))
elif not (len(feed["camps"]) - 100 < int(_og_n.group(1).replace(",", "")) <= len(feed["camps"])): bad.append(("/", "og rounded count", _og_n.group(1), len(feed["camps"])))
if "VIC and NSW" in home.split("</head>", 1)[0] and os.path.isdir(os.path.join(D, "qld")): bad.append(("/", "VIC and NSW share text"))
if "Victorian camp conditions and closures" in home: bad.append(("/", "old share text"))
not_found = open(os.path.join(D, "404.html"), encoding="utf-8").read()
if "/site.webmanifest" not in not_found or "og-image-vic-nsw-qld-sa-tas.png?v=20261110" not in not_found: bad.append(("404", "icons"))
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
for icon_name in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "og-image-vic-nsw-qld-sa-tas.png"):
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
  "lake-catani-campground-mt-buffalo-np": "Lake Catani Campground is CLOSED for all camping from August 31st until October 30th 2026.",
  "notley-picnic-and-camping-area": "Notley Camping & Picnic Area - closed for upgrades",
  "kiata-campground": "There are still some areas within the park which remain closed for recovery works such as: Kiata Campground",
  "paddys-range-state-park": "Closed For Upgrades - Paddy's Ranges Campground: closed from Wednesday 09/09/2026 until Monday 30/11/2026 while works are undertaken for campground improvements",
}
# Dated overrides drop out on their reopen day; after that the camp builds as "check" like any other.
from datetime import datetime as _dt
from zoneinfo import ZoneInfo as _Zi
MEL_TODAY = _dt.now(_Zi("Australia/Melbourne")).date().isoformat()
DATED_REOPEN = {"lake-catani-campground-mt-buffalo-np": "2026-10-31", "notley-picnic-and-camping-area": "2026-10-31", "paddys-range-state-park": "2026-11-30"}
for _slug, _reopen in DATED_REOPEN.items():
  if MEL_TODAY >= _reopen: closed_notes.pop(_slug, None)
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
border_dupes = {"hinches-beach-campsite", "paradise-beach-campsite", "sandy-beach-campsite", "top-end-beach-campsite", "willis-campground-w198711455"}
if border_dupes & {c.get("slug") for c in osm}: bad.append(("osm", "border duplicate kept"))
if len(named) - len(osm) != len(border_dupes): bad.append(("osm", f"built {len(osm)} overlay {len(named)}"))
labels = {c.get("category") for c in osm}
if labels - {"Free", "Camping area", "Donation", "Showground", "Council park", "Council park (leased)", "Rest area", "Pub stay", "Paid – Parks Victoria (book ahead)"}: bad.append(("osm", labels))
# Free 1096 -> 1095: weekly OSM refresh 862df30 (10 Nov 2026) dropped one free VIC camp (data drift, not a code change).
expect_counts = {"Free": 1095, "Camping area": 5, "Council park": 76, "Showground": 40, "Paid – Parks Victoria (book ahead)": 55, "Rest area": 24, "Donation": 11, "Pub stay": 6, "Council park (leased)": 8}
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
if not isinstance(corrections, dict) or len(corrections) != 1336 or "drop" in corrections or "overrides" in corrections:
  bad.append(("corrections", "shape"))
if sum(1 for v in corrections.values() if isinstance(v, dict) and v.get("exclude")) != 221: bad.append(("corrections", "exclusions"))
if corrections.get("w1474028458", {}).get("exclude") is not True or "no-private-caravan-parks" not in str(corrections.get("w1474028458", {}).get("exclude_reason")):
  bad.append(("corrections", "browns water holes"))
if corrections.get("w204763505", {}).get("name") != "Wye River Beachfront Campground":
  bad.append(("corrections", "wye river way"))
if sum(1 for k, v in corrections.items() if str(k).startswith("new:") and isinstance(v, dict) and not v.get("exclude") and "lat" in v and "lon" in v) != 500:
  bad.append(("corrections", "new sites"))
import facts
if facts.melbourne_iso("2026-12-23T13:00:00Z") != "2026-12-24": bad.append(("facts", "ingrams reopen"))
if facts.melbourne_iso("2027-01-31T13:00:00Z") != "2027-02-01": bad.append(("facts", "pine start"))
if facts.melbourne_iso("2027-05-27T14:00:00Z") != "2027-05-28": bad.append(("facts", "pine reopen"))
if facts.melbourne_iso("2027-03-04T13:00:00Z") != "2027-03-05": bad.append(("facts", "island reopen"))
if facts.melbourne_iso("2026-12-17T13:00:00Z") != "2026-12-18": bad.append(("facts", "parkers reopen"))
if facts.melbourne_iso("2026-04-29T14:00:00Z") != "2026-04-30": bad.append(("facts", "ingrams start"))
if facts.melbourne_iso("2026-12-24") != "2026-12-24": bad.append(("facts", "date only"))
if facts.melbourne_iso("2026-10-26T00:00:00Z") != "2026-10-26": bad.append(("facts", "midnight utc"))
vic_state = states.by_slug("vic")
for lon, lat, expect in (
    (145.919769, -37.117335, "high-country"),
    (145.978398, -37.138147, "high-country"),
    (145.986529, -37.142244, "high-country"),
    (145.963204, -37.125222, "high-country"),
    (145.980006, -37.138937, "high-country"),
    (145.968092, -37.264264, "high-country"),
    (145.857745, -37.140024, "high-country"),
    (145.84056, -37.17667, "high-country"),
    (146.306821, -37.944886, "gippsland"),
    (146.4, -37.98, "gippsland"),
    (145.98, -36.55, "gippsland"),
):
    got = states.region_id(vic_state, lon, lat)
    if got != expect: bad.append(("regions", f"{lon},{lat} {got}"))
vic_js = states.js_region_function(vic_state)
if "lon >= 145.89 && lon < 146.0 && lat > -37.4 && lat < -37.05" not in vic_js: bad.append(("regions", "eildon js"))
if "lon >= 145.83 && lon < 145.89 && lat > -37.2 && lat < -37.1" not in vic_js: bad.append(("regions", "fraser js"))
if facts.override_expired("2026-10-25", "2026-10-26") is not True: bad.append(("facts", "expired until"))
if facts.override_expired("2026-10-26", "2026-10-26") or facts.override_expired("2026-10-30", "2026-10-26") or facts.override_expired("", "2026-10-26"):
  bad.append(("facts", "until still current"))
build_src = open(os.path.join(root, "scripts", "build.py"), encoding="utf-8").read()
if "statecfg.enabled" not in build_src: bad.append(("build.py", "enabled states"))
# Home-screen shortcut: the sticky freshness bar must not cover the state menu.
_fresh_z = re.search(r"html\.standalone \.freshness\{([^}]*)\}", build_src)
_menu_z = re.search(r"\.state-menu\{([^}]*)\}", build_src)
def _z_index(rule):
  found = re.search(r"z-index:\s*(\d+)", rule or "")
  return int(found.group(1)) if found else -1
_fresh_zi = _z_index(_fresh_z.group(1) if _fresh_z else "")
_menu_zi = _z_index(_menu_z.group(1) if _menu_z else "")
if _fresh_zi < 0 or _menu_zi <= _fresh_zi:
  bad.append(("build.py", "state menu under standalone freshness bar"))
nsw = states.by_slug("nsw")
if not nsw.get("enabled"): bad.append(("states", "nsw enabled"))
nsw_hooks = {
    "npws_visitor_areas": "https://mapprod2.environment.nsw.gov.au/arcgis/rest/services/Assets/AMS_Assets/FeatureServer/24",
    "npws_alerts_api": "https://api-prd.nswparks.cloud/api/v1/AlertsClosures/alerts/AD1E62CD-1182-456A-9397-EB08FF3EC793",
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
_when = __import__("datetime").datetime(2026, 10, 29, 8, 0, tzinfo=facts.MELBOURNE)
def _dated_item(title, description):
    return nswcond.parse_rss(
        '<?xml version="1.0"?><rss><channel><item><title>' + title + '</title>'
        '<link>https://www.nationalparks.nsw.gov.au/visit-a-park/parks/example/local-alerts</link>'
        '<description>' + description + '</description></item></channel></rss>'
    )[0]
_mero = _dated_item("Meroo National Park",
    "&lt;strong&gt;Closed areas: Meroo Head campground closed&lt;/strong&gt;&lt;br/&gt;"
    "Some parts of this park are closed from Monday 2 November to Friday 6 November 2026."
    "&lt;ul&gt;&lt;li&gt;Meroo Head campground&lt;/li&gt;&lt;/ul&gt;")
_mero_hit = nswcond.closure_for(_reserve("Meroo National Park", "NP"), "Meroo Head campground", _mero, _when)
if not _mero_hit or _mero_hit.get("kind") != "upcoming" or _mero_hit.get("start") != "2026-11-02" or _mero_hit.get("reopen") != "2026-11-07":
    bad.append(("alerts", "meroo upcoming " + str(_mero_hit)))
_barokee = _dated_item("Cathedral Rock National Park",
    "&lt;strong&gt;Closed areas: Barokee Campground Closed Due to Maintenance&lt;/strong&gt;&lt;br/&gt;"
    "Barokee Campground will be closed from 10am Monday 13 April to 10am Wednesday 30 June 2027 for maintenance.")
_barokee_hit = nswcond.closure_for(_reserve("Cathedral Rock National Park", "NP"), "Barokee campground", _barokee, _when)
# 13 April 2026 is a Monday, so the printed weekday puts the start in 2026: closed now.
if not _barokee_hit or _barokee_hit.get("kind") != "current" or _barokee_hit.get("start") != "2026-04-13" or _barokee_hit.get("reopen") != "2027-06-30":
    bad.append(("alerts", "barokee weekday year " + str(_barokee_hit)))
for _tok, _yr, _want in (("Monday 13 April", 2027, 2026), ("Saturday 7 November", 2026, 2026), ("Friday 1 January", 2026, 2027), ("13 April", 2027, 2027)):
    if nswcond._weekday_year(nswcond._date_tokens(_tok)[0], _yr) != _want: bad.append(("alerts", "weekday year " + _tok))
# The NPWS alerts API (the JSON the NPWS alerts pages load), in its own shape.
def _api_alert(kind, title, desc, where, locs, start="2026-10-01T00:00:00", end="2026-11-20T00:00:00", status="Active"):
    return {"Type": kind, "AlertStatus": status, "Title": title, "Description": desc, "LocationDetail": "**Where:** " + where,
            "LastModifiedDate": "2026-10-29T01:00:00", "AlertDateTimes": [{"StartDateTimeUtc": start, "EndDateTimeUtc": end}],
            "Locations": [{"Type": t, "Name": n, "EntireArea": ea, "LocationImpact": f"**Impact on {n}:** {imp}", "Url": "/visit-a-park/parks/" + n.lower().replace(" ", "-"), "ContentDataFeedItemId": cid} for t, n, ea, imp, cid in locs]}
_api = json.dumps({"AlertsMeta": {"LocationAlerts": [
    {"ContentDataFeedItemId": "c1", "Name": "Alpha campground", "Type": "Campground", "ParentName": "Alpha National Park"},
    {"ContentDataFeedItemId": "c2", "Name": "Gamma campground", "Type": "Campground", "ParentName": "Gamma National Park"},
    {"ContentDataFeedItemId": "c3", "Name": "Delta campground", "Type": "Campground"},
]}, "Alerts": [
    _api_alert("Closure", "Closure due to flooding", "The park is closed due to flooding.", "All parts of [Beta National Park](/x)",
               [("Park", "Beta National Park", True, "All parts are closed.", "p1")]),
    _api_alert("Closure", "Campground closed", "Alpha campground is closed for works. All other areas in Alpha National Park will remain open.", "Some parts of [Alpha National Park](/x)",
               [("Campground", "Alpha campground", True, "All parts are closed.", "c1")]),
    _api_alert("Closure", "Weekday closures", "Gamma campground will be open from Friday to Sunday each week.", "Some parts of Gamma National Park",
               [("Campground", "Gamma campground", True, "All parts are closed.", "c2")]),
    _api_alert("Closure", "Caves closed", "The caves are closed.", "Some parts of [Kappa National Park](/x). Only applies to: caves",
               [("Park", "Kappa National Park", True, "All parts are closed.", "p4")]),
    _api_alert("NPWS fire ban", "NPWS fire ban", "A park fire ban is in place.", "All parts of [Beta National Park](/x) and [Alpha National Park](/y)",
               [("Park", "Beta National Park", True, "All parts are affected.", "p1"), ("Park", "Alpha National Park", True, "All parts are affected.", "p5")]),
]}).encode()
_api_items, _api_newest = nswcond.parse_api(_api)
_api_by = {it["title"]: it for it in _api_items}
if not _api_newest or _api_newest.isoformat() != "2026-10-29T12:00:00+11:00": bad.append(("alerts api", "newest " + str(_api_newest)))
_api_when = __import__("datetime").datetime(2026, 10, 30, 12, tzinfo=facts.MELBOURNE)
_beta = nswcond.closure_for(_reserve("Beta National Park", "NP"), "Any campground", _api_by.get("Beta National Park") or {"sections": [], "link": ""}, _api_when)
if not _beta or _beta.get("kind") != "current": bad.append(("alerts api", "whole park " + str(_beta)))
_alpha_idx = nswcond.index_closures(_api_items, [_reserve("Alpha National Park", "NP")])
if not nswcond.lookup_closure(_alpha_idx, _reserve("Alpha National Park", "NP"), "Alpha campground", _api_when): bad.append(("alerts api", "campground all parts closed"))
if nswcond.lookup_closure(_alpha_idx, _reserve("Alpha National Park", "NP"), "Other campground", _api_when): bad.append(("alerts api", "campground closure spread to the park"))
_gamma_idx = nswcond.index_closures(_api_items, [_reserve("Gamma National Park", "NP")])
if nswcond.lookup_closure(_gamma_idx, _reserve("Gamma National Park", "NP"), "Gamma campground", _api_when): bad.append(("alerts api", "open part days read as closed"))
_kappa_idx = nswcond.index_closures(_api_items, [_reserve("Kappa National Park", "NP")])
if nswcond.lookup_closure(_kappa_idx, _reserve("Kappa National Park", "NP"), "Kappa campground", _api_when): bad.append(("alerts api", "some parts read as whole park"))
_ban = [(h, b) for h, b in (_api_by.get("Alpha National Park") or {}).get("sections", []) if h.startswith("Fire bans")]
if not _ban or not nswcond.section_applies(_ban[0][0], _ban[0][1], _reserve("Alpha National Park", "NP"), "Alpha campground") or "Closed from" in _ban[0][1]:
    bad.append(("alerts api", "fire ban note " + str(_ban)))
_water = _dated_item("Kosciuszko National Park",
    "&lt;strong&gt;Closed areas: Blue Waterholes campground closed for upgrade work&lt;/strong&gt;&lt;br/&gt;"
    "Blue Waterholes campground is closed until Friday 27th November 2026 for significant upgrades.")
_water_hit = nswcond.closure_for(_reserve("Kosciuszko National Park", "NP"), "Blue Water Holes campground", _water, _when)
if not _water_hit or _water_hit.get("kind") != "current":
    bad.append(("alerts", "blue water holes " + str(_water_hit)))
_perkins = _dated_item("Kosciuszko National Park",
    "&lt;strong&gt;Closed areas: No access to Perkins Flat campground&lt;/strong&gt;&lt;br/&gt;"
    "Long Plain Road is closed. There will be no access to Perkins Flat campground.")
if not nswcond.closure_for(_reserve("Kosciuszko National Park", "NP"), "Perkins Flat campground", _perkins, _when):
    bad.append(("alerts", "perkins access"))
_gulpa = _dated_item("Murray Valley National Park",
    "&lt;strong&gt;Closed areas: Gulpa Island National Park Campgrounds CLOSED due to flooding&lt;/strong&gt;"
    "The following campgrounds are CLOSED until 2 November:&lt;ul&gt;"
    "&lt;li&gt;Taylors Bridge campground&lt;/li&gt;&lt;li&gt;Langmans campground&lt;/li&gt;&lt;li&gt;Cod campground&lt;/li&gt;&lt;/ul&gt;")
_gulpa_reserves = [_reserve("Murray Valley National Park", "NP"), _reserve("Gulpa Island National Park", "NP")]
_gulpa_index = nswcond.index_closures([_gulpa], _gulpa_reserves)
for _camp in ("Taylors Bridge campground", "Langmans campground", "Cod campground"):
    _hit = nswcond.lookup_closure(_gulpa_index, _gulpa_reserves[0], _camp, _when)
    if not _hit or _hit.get("kind") != "current":
        bad.append(("alerts", "gulpa " + _camp))
if nswcond.lookup_closure(_gulpa_index, _gulpa_reserves[0], "Cod Hole campground", _when):
    bad.append(("alerts", "cod hole"))
_aerial = _dated_item("Nadgee Nature Reserve",
    "&lt;strong&gt;Closed areas: Parks closed for aerial shooting for feral animal control&lt;/strong&gt;"
    "The following parks will be closed from 2pm on Sunday 25th October until 10am on Saturday 31st October 2026:"
    "&lt;ul&gt;&lt;li&gt;Beowa National Park (Green Cape area), including Light to Light walk, Bittangabee campground, Mowarry campground, and Saltwater Creek campgrounds&lt;/li&gt;"
    "&lt;li&gt;Nadgee Nature Reserve (including Nadgee Wilderness Walk)&lt;/li&gt;&lt;/ul&gt;")
_nadgee = _reserve("Nadgee Nature Reserve", "NR")
_beowa = _reserve("Beowa National Park", "NP")
_air_index = nswcond.index_closures([_aerial], [_nadgee, _beowa])
if nswcond.lookup_closure(_air_index, _nadgee, "Newtons Beach camp", _when):
    bad.append(("alerts", "newtons closed"))
_bitt = nswcond.lookup_closure(_air_index, _beowa, "Bittangabee campground", _when)
if not _bitt or _bitt.get("kind") != "current":
    bad.append(("alerts", "bittangabee " + str(_bitt)))
_air_heading, _air_body = _aerial["sections"][0]
if nswcond.section_applies(_air_heading, _air_body, _nadgee, "Newtons Beach camp"):
    bad.append(("alerts", "newtons note"))
if not nswcond.section_applies(_air_heading, _air_body, _beowa, "Bittangabee campground"):
    bad.append(("alerts", "bittangabee note"))
_dt = __import__("datetime").datetime
if nswcond.lookup_closure(_air_index, _beowa, "Bittangabee campground", _dt(2026, 10, 31, 10, 30, tzinfo=facts.MELBOURNE)):
    bad.append(("alerts", "bittangabee after 10am 31 Oct"))
_wtb = _dated_item("Myall Lakes National Park",
    "&lt;strong&gt;Closed areas: White Tree Bay campground closed due to flood repairs&lt;/strong&gt;&lt;br/&gt;"
    "White Tree Bay campground in Myall Lakes National Park remains temporarily closed due to damaged amenities from flood impact.")
_myall = _reserve("Myall Lakes National Park", "NP")
_wtb_index = nswcond.index_closures([_wtb], [_myall])
_wtb_hit = nswcond.lookup_closure(_wtb_index, _myall, "White Tree Bay campground", _when)
if not _wtb_hit or _wtb_hit.get("kind") != "current":
    bad.append(("alerts", "white tree bay " + str(_wtb_hit)))
if nswcond.lookup_closure(_wtb_index, _myall, "Mungo Brush campground", _when):
    bad.append(("alerts", "white tree bay other camp"))
_wtb_head = _dated_item("Myall Lakes National Park",
    "&lt;strong&gt;Closed areas: White Tree Bay campground closed due to flood repairs&lt;/strong&gt;&lt;br/&gt;"
    "Repairs are under way after flood damage.")
if not nswcond.lookup_closure(nswcond.index_closures([_wtb_head], [_myall]), _myall, "White Tree Bay campground", _when):
    bad.append(("alerts", "closed heading"))
_4wd = _dated_item("Myall Lakes National Park",
    "&lt;strong&gt;Closed areas: Mungo Beach campground closed to 4WD vehicles&lt;/strong&gt;&lt;br/&gt;"
    "Vehicles can not drive on the beach.")
if nswcond.lookup_closure(nswcond.index_closures([_4wd], [_myall]), _myall, "Mungo Beach campground", _when):
    bad.append(("alerts", "closed to 4wd"))
if nswcond._CLOSED_SENTENCE.search("Mungo Brush campground is partially closed for works"):
    bad.append(("alerts", "partially closed"))
_berlang = _dated_item("Deua National Park",
    "&lt;strong&gt;Closed areas: Berlang campground closed for pest control&lt;/strong&gt;&lt;br/&gt;"
    "Berlang campground will be closed to the public from 2pm Sunday 1st November until 10am Saturday 7th November 2026.")
_deua = _reserve("Deua National Park", "NP")
_berlang_index = nswcond.index_closures([_berlang], [_deua])
_b1 = nswcond.lookup_closure(_berlang_index, _deua, "Berlang campground", _dt(2026, 11, 1, 13, 0, tzinfo=facts.MELBOURNE))
_b2 = nswcond.lookup_closure(_berlang_index, _deua, "Berlang campground", _dt(2026, 11, 1, 14, 30, tzinfo=facts.MELBOURNE))
if not _b1 or _b1.get("kind") != "upcoming" or not _b2 or _b2.get("kind") != "current":
    bad.append(("alerts", "berlang flip " + str(_b1) + " " + str(_b2)))
_willows = _dated_item("Yanga State Conservation Area",
    "&lt;strong&gt;Closed areas: Campground closures&lt;/strong&gt;"
    "Campgrounds will be closed as follows;&lt;ul&gt;&lt;li&gt;Willows Picnic area &amp; Campground - CLOSED 15 – 25 October for aerial shooting operations&lt;/li&gt;&lt;/ul&gt;")
if nswcond.closure_for(_reserve("Yanga State Conservation Area", "SC"), "Willows campground", _willows, _when):
    bad.append(("alerts", "willows expired"))
_thredbo = _dated_item("Kosciuszko National Park",
    "&lt;strong&gt;Closed areas: Thredbo Diggings Campground Post-Winter Closures&lt;/strong&gt;"
    "Thredbo Diggings Campground is closed for post-winter maintenance from Monday 12 October 2026 to Saturday 31 October 2026.")
_thredbo_hit = nswcond.closure_for(_reserve("Kosciuszko National Park", "NP"), "Thredbo Diggings campground", _thredbo, _when)
if not _thredbo_hit or _thredbo_hit.get("reopen") != "2026-11-01":
    bad.append(("alerts", "thredbo " + str(_thredbo_hit)))
# "to Saturday 31 October" is inclusive; "until 10am Saturday 31 October" is compared with the clock.
_kos = _reserve("Kosciuszko National Park", "NP")
for _at, _want in (((10, 31, 0, 17), "current"), ((10, 31, 23, 59), "current"), ((11, 1, 0, 0), None)):
    _h = nswcond.closure_for(_kos, "Thredbo Diggings campground", _thredbo, _dt(2026, _at[0], _at[1], _at[2], _at[3], tzinfo=facts.MELBOURNE))
    if (_h or {}).get("kind") != _want:
        bad.append(("alerts", "thredbo inclusive " + str(_at) + " " + str(_h)))
_beowa_item = _dated_item("Beowa National Park",
    "&lt;strong&gt;Closed areas: Parks closed for aerial shooting for feral animal control&lt;/strong&gt;&lt;br/&gt;"
    "The following parks, reserves and areas will be closed from 2pm on Sunday 25th October until 10am on Saturday 31st October 2026 for a pest management program:"
    "&lt;ul&gt;&lt;li&gt;Beowa National Park (Green Cape area), including Light to Light walk, Bittangabee campground, Mowarry campground, and Saltwater Creek campgrounds and&lt;/li&gt;&lt;/ul&gt;")
for _camp in ("Bittangabee campground", "Mowarry campground", "Saltwater Creek campground"):
    for _at, _want in (((31, 0, 17), "current"), ((31, 9, 59), "current"), ((31, 10, 0), None)):
        _h = nswcond.closure_for(_reserve("Beowa National Park", "NP"), _camp, _beowa_item, _dt(2026, 10, _at[0], _at[1], _at[2], tzinfo=facts.MELBOURNE))
        if (_h or {}).get("kind") != _want:
            bad.append(("alerts", "beowa 10am " + _camp + " " + str(_at) + " " + str(_h)))
_toor = _dated_item("Morton National Park",
    "&lt;strong&gt;Closed areas: Toorooroo campground closed due to damage&lt;/strong&gt;&lt;br/&gt;"
    "Toorooroo campground is closed due to fire and flood damage. Please check back for updates.")
if (nswcond.closure_for(_reserve("Morton National Park", "NP"), "Yalwal/Toorooroo campground", _toor, _when) or {}).get("kind") != "current":
    bad.append(("alerts", "toorooroo slash name"))
for _camp_name, _piece, _want in (("Bandahngan (Tooloom Falls) campground", "Tooloom Falls campground", True),
                                  ("Black Rocks - Booroora campground", "Booroora campground", True),
                                  ("Black Rocks - Booroora campground", "Black Rocks campground", False),
                                  ("Mt Warrawolong Campground - GNW", "Mt Warrawolong campground", True),
                                  ("Kira/Leaves campground", "Leaves campground", True)):
    if nswcond.keys_match(_camp_name, _piece) != _want:
        bad.append(("alerts", "compound name " + _camp_name + " / " + _piece))
_wash = _dated_item("Towarri National Park",
    "&lt;strong&gt;Closed areas: Towarri National Park partial closure&lt;/strong&gt;"
    "Areas within Towarri National Park may be intermittently closed. * Note: Washpools campground and picnic area will not be directly affected by these closures.")
if nswcond.closure_for(_reserve("Towarri National Park", "NP"), "Washpools campground", _wash, _when):
    bad.append(("alerts", "washpools exempt"))
if not nswcond.keys_match("Alexander's Hut campground", "Alexanders Hut campground"):
    bad.append(("alerts", "apostrophe"))
_near = {"title": "Edge National Park", "title_norm": "edge national park", "name_norm": "edge", "abbrev": "np", "prep": nswcond._prepare([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])}
_grid = nswcond._index([_near])
if not nswcond.reserves_at(_grid, -0.0004, 0.5) or nswcond.reserves_at(_grid, -0.002, 0.5):
    bad.append(("alerts", "boundary snap"))
_fire_only = {"name": "Test", "key": "test", "prep": nswcond._prepare([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])}
_fire_grid = nswcond._index([_fire_only])
try:
    if nswcond.reserves_at(_fire_grid, -0.0004, 0.5) or not nswcond.reserves_at(_fire_grid, 0.5, 0.5):
        bad.append(("alerts", "fire polygon snap"))
except Exception as _exc:
    bad.append(("alerts", "fire polygon " + str(_exc)))
# Fire-district fallback (row 57, Nev 6 Nov 2026): nearest SAME-state district only within
# FIRE_FALLBACK_KM (border river, shore); islands further out stay unmapped, never "No Rating".
try:
    _fa = {"name": "Alpha", "key": "alpha", "prep": nswcond._prepare([[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]])}
    _fb = {"name": "Beta", "key": "beta", "prep": nswcond._prepare([[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]])}
    _fgrid = nswcond._index([_fa, _fb])
    _rated = lambda key: key in ("alpha", "beta")
    _r, _km, _how = nswcond.district_for(_fgrid, [_fa, _fb], 0.5, 0.5, _rated)
    if _how != "inside" or _r["key"] != "alpha" or _km != 0: bad.append(("fire fallback", "inside", _how))
    _r, _km, _how = nswcond.district_for(_fgrid, [_fa, _fb], -0.0008, 0.5, _rated)  # ~89 m west of Alpha
    if _how != "fallback" or _r["key"] != "alpha" or not (0.07 < _km < 0.11): bad.append(("fire fallback", "border river", _how, _km))
    _r, _km, _how = nswcond.district_for(_fgrid, [_fa, _fb], 1.5, -0.005, _rated)  # ~550 m south of Beta
    if _how != "fallback" or _r["key"] != "beta": bad.append(("fire fallback", "shore nearest", _how))
    _r, _km, _how = nswcond.district_for(_fgrid, [_fa, _fb], -0.03, 0.5, _rated)  # ~3.3 km offshore island
    if _how != "unmapped" or _r is not None: bad.append(("fire fallback", "island 1-10 km kept unmapped", _how))
    _r, _km, _how = nswcond.district_for(_fgrid, [_fa, _fb], 0.5, 0.5, lambda key: key == "beta")
    if _how != "unrated" or _r is not None: bad.append(("fire fallback", "inside unrated never takes a neighbour", _how))
    if nswcond.FIRE_FALLBACK_KM != 1.0 or nswcond.NO_FIRE_DISTRICT != "No fire district mapped": bad.append(("fire fallback", "rule constants"))
    if "no rating" in nswcond.NO_FIRE_DISTRICT.lower() or "no rating" in nswcond.fallback_note(0.08).lower(): bad.append(("fire fallback", "No Rating wording"))
    if "80 m" not in nswcond.fallback_note(0.08) or "a few metres" not in nswcond.fallback_note(0.0): bad.append(("fire fallback", "note distance"))
    _fcamps = [{"lon": -0.0008, "lat": 0.5}, {"lon": -0.03, "lat": 0.5}, {"lon": 0.5, "lat": 0.5}]
    _frat = {k: {"district": n, "today": "High", "tomorrow": "Moderate", "ban_today": "No", "ban_tomorrow": "No"} for k, n in (("alpha", "Alpha"), ("beta", "Beta"))}
    nswcond.apply_fire_records(_fcamps, [_fa, _fb], _frat, "https://www.rfs.nsw.gov.au/feeds/fdrToban.xml")
    if (_fcamps[0].get("fire") or {}).get("today") != "High" or "fallback_km" not in (_fcamps[0].get("fire") or {}): bad.append(("fire fallback", "nsw fallback keeps official rating", _fcamps[0]))
    if _fcamps[1].get("fire") or (_fcamps[1].get("fire_unmapped") or {}).get("label") != "No fire district mapped": bad.append(("fire fallback", "nsw island unmapped", _fcamps[1]))
    if "fallback_km" in (_fcamps[2].get("fire") or {}) or _fcamps[2].get("fire_unmapped"): bad.append(("fire fallback", "nsw inside", _fcamps[2]))
    import cfa_conditions as _cfa
    _vc = [{"lon": -0.0008, "lat": 0.5}, {"lon": -0.2, "lat": 0.5}]
    _cfa.apply_fire_records(_vc, [_fa], {"alpha": {"district": "Alpha", "today": "No Rating", "ban_today": "No"}}, {}, "https://www.cfa.vic.gov.au/cfa/rssfeed/tfbfdrforecast_rss.xml", {}, "Check CFA fire danger")
    # Victoria's official "No Rating" stays as the real rating of the fallback district.
    if (_vc[0].get("fire") or {}).get("today") != "No Rating" or "fallback_km" not in _vc[0]["fire"]: bad.append(("fire fallback", "cfa fallback", _vc[0]))
    if (_vc[1].get("fire_unmapped") or {}).get("label") != "No fire district mapped" or not (_vc[1]["fire_unmapped"].get("page_url") or "").startswith("https://www.cfa.vic.gov.au/"): bad.append(("fire fallback", "cfa unmapped", _vc[1]))
except Exception as _exc:
    bad.append(("fire fallback", "error " + repr(_exc)))
for _cfg, _old in (("config/states/nsw.json", "bom.gov.au/nsw/warnings"), ("config/states/vic.json", "bom.gov.au/vic/warnings")):
    _text = open(os.path.join(root, _cfg), encoding="utf-8").read()
    if _old in _text or "weather-and-climate/warnings-and-alerts" not in _text:
        bad.append(("bom", _cfg))
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
orchard_footer = orchard.split("<footer>", 1)[-1].split("</footer>", 1)[0] if orchard else ""
if "Victoria: DataVic, Explore Outdoors and Parks Victoria" not in orchard_footer or "Vicmap Admin" not in orchard_footer or 'href="/about/#vic-sources"' not in orchard_footer: bad.append(("the-orchard", "footer attribution"))
tunnel = page_of("tunnel-bend")
must("tunnel-bend", tunnel, ["Area:</strong> Upper Goulburn State Forest (Goulburn River)", "area-wide statements on the Explore Outdoors page upper-goulburn-and-big-river-camping, not site-specific"])
burrum = page_of("lake-burrumbeet-south-1")
must("lake-burrumbeet-south-1", burrum, ["Area:</strong> Lake Burrumbeet", "lake-wide statements on the Explore Outdoors Lake Burrumbeet page"])
if "$" in orchard.split('id="newsletter"')[0]: bad.append(("the-orchard", "fee amount"))
horseshoe = page_of("horseshoe-bend-camping-area")
must("horseshoe-bend", horseshoe, ["Rubbish: take rubbish home", "Toilets: Yes"])
if 'class="badge closed"' in horseshoe: bad.append(("horseshoe-bend", "marked closed"))
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
if not avondale or avondale.get("status") == "closed" or avondale.get("source") != "datavic" or avondale.get("closure"):
  bad.append(("avondale-gardens", "still closed"))
else:
  av_html = page_of("avondale-gardens")
  must("avondale-gardens", av_html, ["<strong>Free</strong>", "Dogs: Yes", 'data-camp="avondale-gardens"'])
  line = re.search(r'class="status-line" data-camp="avondale-gardens">(.*?)</p>', av_html)
  box = av_html.split('id="camp-closure"', 1)[-1][:500] if av_html else ""
  if not line or "badge closed" in line.group(1) or "badge open" not in line.group(1) or "<strong>Closed:</strong>" in box:
    bad.append(("avondale-gardens", "closure box"))
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
murray = "https://www.parks.vic.gov.au/places-to-see/sites/centre-track-camping-area-(nurrung)"
if check_parksvic.campground_url(murray) != murray:
  bad.append(("check_parksvic", "parenthesis slug"))
if check_parksvic.campground_url("See https://www.parks.vic.gov.au/places-to-see/sites/mallee-camp).") != "https://www.parks.vic.gov.au/places-to-see/sites/mallee-camp":
  bad.append(("check_parksvic", "sentence parenthesis"))
from datetime import datetime, timedelta
_pv_now = datetime(2026, 11, 9, 12, 0, tzinfo=check_parksvic.MELBOURNE)
if not check_parksvic.cache_is_older_than_a_day(_pv_now - timedelta(hours=25), _pv_now):
  bad.append(("check_parksvic", "25h cache not stale"))
if check_parksvic.cache_is_older_than_a_day(_pv_now - timedelta(hours=2), _pv_now):
  bad.append(("check_parksvic", "2h cache counted stale"))
_pv_cache = check_parksvic.CACHE_DIR
_pv_dir = tempfile.mkdtemp(prefix="parksvic-stale-")
check_parksvic.CACHE_DIR = _pv_dir
try:
  _fresh_url = "https://www.parks.vic.gov.au/places-to-see/sites/centre-track-camping-area-(nurrung)"
  _old_url = "https://www.parks.vic.gov.au/places-to-see/sites/dry-creek-camping-area-west-(nurrung)"
  check_parksvic._cache_put(_fresh_url, {"html": "<p>open</p>", "status": 200}, _pv_now - timedelta(hours=2))
  check_parksvic._cache_put(_old_url, {"html": "<p>open</p>", "status": 200}, _pv_now - timedelta(hours=30))
  _pv_dest = os.path.join(_pv_dir, "flags.json")
  _pv_camps = [
    {"id": "new:centre-track-camping-area-murray-river", "slug": "centre-track", "name": "Centre Track Camping Area", "status": "check"},
    {"id": "new:dry-creek-camping-area-west-murray-river", "slug": "dry-creek", "name": "Dry Creek Camping Area West", "status": "check"},
  ]
  check_parksvic.write_flags(_pv_camps, _pv_dest, now=_pv_now, overall_seconds=-1, sleeper=lambda _n: None)
  _pv_doc = json.load(open(_pv_dest, encoding="utf-8"))
  if _pv_doc.get("pages_older_than_a_day") != 1:
    bad.append(("check_parksvic", "stale count", _pv_doc.get("pages_older_than_a_day")))
finally:
  check_parksvic.CACHE_DIR = _pv_cache
if check_parksvic.park_url("https://www.parks.vic.gov.au/places-to-see/parks/paddys-ranges-state-park") != "https://www.parks.vic.gov.au/places-to-see/parks/paddys-ranges-state-park":
  bad.append(("check_parksvic", "whole park url"))
paddys_html = """
<div class="explore__overview"><p>Some tracks in the park are closed for maintenance.</p></div>
<div class="change-of-conditions__item">
  <h4 class="change-of-conditions__subtitle">Paddy&#39;s Ranges Camping Area (Paddys Ranges State Park)</h4>
  <h3 class="change-of-conditions__title"><span class="change-of-conditions__title-text">Closed For Upgrades - Paddy&#39;s Ranges Campground</span></h3>
  <div class="change-of-conditions__content"><p>Paddy's Ranges Campground will be closed from Wednesday 09/09/2026 until Monday 30/11/2026.</p></div>
</div>
"""
if check_parksvic.classify_html(paddys_html, "Paddys Range State Park", True)["closed"] != ["Closed For Upgrades - Paddy's Ranges Campground"]:
  bad.append(("check_parksvic", "paddys name match"))
if check_parksvic.classify_html(paddys_html, "Greens Campground - Whroo Historical Area", True)["closed"]:
  bad.append(("check_parksvic", "park page other camp"))
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
if wrapped_found["closed"] != ["Strachans Campground Closed for Upgrades"]:
  bad.append(("check_parksvic", "wrapped " + repr(wrapped_found["closed"])))
if check_parksvic.closure_end("between 13 April and 29 October 2026") != "2026-10-29":
  bad.append(("check_parksvic", "between end"))
if check_parksvic.closure_end("from August 31st until October 30th 2026") != "2026-10-30":
  bad.append(("check_parksvic", "until end"))
if check_parksvic.wording_closes_camp("Upper Teddington Reservoir - closed for maintenance", "Teddington Camping Area"):
  bad.append(("check_parksvic", "reservoir"))
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
  signup_msg = "Choose at least one state so we know which digest to send."
  if 'name="states" value="vic"' not in home or 'name="states" value="nsw"' not in home or 'name="states" value="vic" checked' in home or 'name="states" value="nsw" checked' in home or 'name="choose_states" value="1"' not in home or signup_msg not in home or "Get the free weekly digest" not in home: bad.append(("/", "signup states"))
  for shared in ("about", "privacy", "terms", "report", "unsubscribe"):
    shared_html = open(os.path.join(D, shared, "index.html"), encoding="utf-8").read()
    if 'name="states" value="vic" checked' in shared_html or 'name="states" value="nsw" checked' in shared_html:
      bad.append((shared, "signup states"))
  if home.find('id="camp-map"') < 0 or home.find('id="newsletter"') < home.find('id="camp-map"'): bad.append(("/", "newsletter above the map"))
  if 'value="NPWS"' not in home or 'value="Parks Victoria"' not in home: bad.append(("/", "type filters"))
  if 'class="state-pick"' not in vic or 'aria-label="State: Victoria"' not in vic or ">VIC <" not in vic: bad.append(("/vic/", "state picker"))
  if 'property="og:title" content="Victorian camp conditions — ' not in vic or 'name="twitter:title" content="Victorian camp conditions — ' not in vic or "VIC and NSW" in vic.split("</head>", 1)[0].split('og:image:alt')[0]: bad.append(("/vic/", "share text"))
  _nsw_home = open(os.path.join(D, "nsw", "index.html"), encoding="utf-8").read()
  if 'property="og:title" content="New South Wales campground conditions — ' not in _nsw_home or "local council pages" not in _nsw_home.split("</head>", 1)[0]: bad.append(("/nsw/", "share text"))
  if 'href="/vic/" aria-current="page"' not in vic or 'href="/nsw/">New South Wales</a>' not in vic: bad.append(("/vic/", "state menu"))
  if 'name="states" value="vic" checked' not in vic or 'name="states" value="nsw" checked' in vic or signup_msg not in vic: bad.append(("/vic/", "signup states"))
  if 'name="states" value="nsw" checked' not in nsw_html or 'name="states" value="vic" checked' in nsw_html or signup_msg not in nsw_html: bad.append(("nsw", "signup states"))
  if 'href="/vic/">Victoria</a><a href="/nsw/">New South Wales</a>' not in home: bad.append(("/", "state menu"))
  if 'src="/map-home.js' in vic or 'src="/map.js?v=' not in vic: bad.append(("/vic/", "map script"))
  if 'class="state-pick"' not in nsw_html or 'aria-label="State: New South Wales"' not in nsw_html or ">NSW <" not in nsw_html: bad.append(("nsw", "state picker"))
  if 'href="/nsw/" aria-current="page"' not in nsw_html or 'href="/vic/">Victoria</a>' not in nsw_html: bad.append(("nsw", "state menu"))
  if 'src="/map-nsw.js?v=' not in nsw_html or 'src="/map.js"' in nsw_html or 'src="/map.js?v=' in nsw_html: bad.append(("nsw", "town script"))
  if "nsw-towns.json" in home or "map-nsw.js" in home: bad.append(("/", "nsw towns on the victoria page"))
  split = tempfile.mkdtemp(prefix="campconditions-digest-states-")
  split_env = os.environ.copy()
  split_env["CAMPCONDITIONS_ENABLE"] = "nsw,qld" if os.path.isdir(os.path.join(D, "qld")) else "nsw"
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
    qld_draft = open(os.path.join(split, "qld", "digest.html"), encoding="utf-8").read() if os.path.isdir(os.path.join(D, "qld")) else ""
    if qld_draft and ("Queensland" not in qld_draft or "Brewery Flat" in qld_draft): bad.append(("digest states", "qld copy"))
    tip_phrase = "If they’re useful and you want to chip in, a one-off tip helps cover the running costs — coffee money is plenty."
    for label, blob in (("digest states vic", vic_draft), ("digest states nsw", nsw_draft), ("digest states qld", qld_draft)):
      if not blob: continue
      if blob.count(tip_phrase) != 1: bad.append((label, "tip once"))
      sub = {"digest states vic": "", "digest states nsw": "nsw", "digest states qld": "qld"}[label]
      tip_presentation(label, blob, open(os.path.join(split, sub, "digest.txt"), encoding="utf-8").read(), bad)
      if not (0 <= blob.find("Been somewhere lately?") < blob.find(tip_phrase) < blob.find("Not an official warning service")):
        bad.append((label, "tip placement"))
    digest_total = camp_count(vic_draft) + camp_count(nsw_draft) + (camp_count(qld_draft) if qld_draft else 0)
    held_digest_camps = sum(1 for c in feed["camps"] if "/sa/" in (c.get("url") or "") or "/tas/" in (c.get("url") or ""))
    # South Australia and Tasmania have no digest while signup stays off.
    if digest_total != len(feed["camps"]) - held_digest_camps:
      bad.append(("digest states", f"{digest_total}+held {held_digest_camps}!={len(feed['camps'])}"))
  if "Spatial Services" not in nsw_html or "Creative Commons Attribution 4.0" not in nsw_html: bad.append(("nsw", "town attribution"))
  nsw_map = open(os.path.join(D, "map-nsw.js"), encoding="utf-8").read()
  if 'fetch("/nsw-towns.json")' not in nsw_map or "vic-towns.json" in nsw_map: bad.append(("map-nsw.js", "town file"))
  if 'fetch("/nsw-place-points.json")' not in nsw_map or "bestTownD <= 40" not in nsw_map: bad.append(("map-nsw.js", "place labels"))
  if 'fetch("/vic-towns.json")' not in mj or "nsw-place-points.json" in mj or "bestTownD" in mj or "chunkedLoading" in mj or "camp.stateName" in mj: bad.append(("map.js", "victoria towns"))
  home_map = open(os.path.join(D, "map-home.js"), encoding="utf-8").read()
  if 'fetch("/vic-towns.json")' not in home_map or 'fetch("/nsw-towns.json")' not in home_map: bad.append(("map-home.js", "towns"))
  if "nsw-place-points.json" in home_map or "bestTownD" in home_map: bad.append(("map-home.js", "nsw places"))
  if "chunkedLoading: true" not in home_map or "camp.stateName || regionName" not in home_map or "addLayers" not in home_map: bad.append(("map-home.js", "cluster"))
  if "zoomSnap: 0.25" not in home_map or "[[-44, 112.5], [-10, 154]]" not in home_map: bad.append(("map-home.js", "australia fit"))
  if "zoomSnap" in mj or "[[-44, 112.5], [-10, 154]]" in mj: bad.append(("map.js", "national fit"))
  for name in os.listdir(D):
    if not (name.startswith("map-") and name.endswith(".js")) or name == "map-home.js":
      continue
    state_map = open(os.path.join(D, name), encoding="utf-8").read()
    if "zoomSnap" in state_map or "[[-44, 112.5], [-10, 154]]" in state_map:
      bad.append((name, "national fit"))
  home_map_pts = map_data("/", home, vic_only=False)
  if 'id="camp-map-data" data-url="/map-points/home.json?v=' not in home or "camp-map-data\">[" in home:
    bad.append(("/", "inline map json"))
  vic_n = sum(str(p.get("url", "")).startswith("/vic/camp/") for p in home_map_pts)
  nsw_n = sum(str(p.get("url", "")).startswith("/nsw/camp/") for p in home_map_pts)
  qld_n = sum(str(p.get("url", "")).startswith("/qld/camp/") for p in home_map_pts)
  sa_n = sum(str(p.get("url", "")).startswith("/sa/camp/") for p in home_map_pts)
  tas_n = sum(str(p.get("url", "")).startswith("/tas/camp/") for p in home_map_pts)
  if vic_n != len(vic_feed) or nsw_n < 1 or vic_n + nsw_n + qld_n + sa_n + tas_n != len(home_map_pts) or (qld_n > 0) != os.path.isdir(os.path.join(D, "qld")) or (sa_n > 0) != os.path.isdir(os.path.join(D, "sa")) or (tas_n > 0) != os.path.isdir(os.path.join(D, "tas")): bad.append(("/", f"national points {vic_n}+{nsw_n}+{qld_n}+{sa_n}+{tas_n}"))
  if any(p.get("stateName") not in ("Victoria", "New South Wales", "Queensland", "South Australia", "Tasmania") for p in home_map_pts): bad.append(("/", "stateName"))
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
  for line in ("/contact /about/ 301", "/contact/ /about/ 301", "/nsw/nsw /nsw/ 301", "/nsw/nsw/ /nsw/ 301",
):
    if line not in redirects: bad.append(("_redirects", line))
  vic_redirects = json.load(open(os.path.join(os.path.dirname(D), "data", "vic-slug-redirects.json"), encoding="utf-8")).get("removed") or {}
  for old, target in vic_redirects.items():
    if os.path.isdir(os.path.join(D, "vic", "camp", old)): continue
    if f"/vic/camp/{old}/ /{target}/ 301" not in redirects or not os.path.isfile(os.path.join(D, target, "index.html")):
      bad.append(("_redirects", f"removed DataVic camp {old} must redirect to {target}"))
  if "/support" in redirects or "fZu4gs0Oafib8eX0QUfQI00" in redirects: bad.append(("_redirects", "old support redirect"))
  support = open(os.path.join(D, "support", "index.html"), encoding="utf-8").read()
  tips = {"Tip A$5": "https://donate.stripe.com/7sYbIUbsOb1V9j17fifQI01", "Tip A$10": "https://donate.stripe.com/3cIeV668uc5Z9j16befQI02", "Tip A$20": "https://donate.stripe.com/dRm5kw9kG7PJ66PdDGfQI03"}
  for label, url in tips.items():
    if not re.search(r'class="tip-btn" href="' + re.escape(url) + r'"[^>]*>' + re.escape(label) + '</a>', support): bad.append(("support", label))
  sitemap_xml = open(os.path.join(D, "sitemap.xml"), encoding="utf-8").read()
  if "<loc>https://campconditions.au/support/</loc>" not in sitemap_xml: bad.append(("sitemap", "/support/ missing"))
  for st in ("vic", "nsw", "qld", "sa", "tas"):
    sp = os.path.join(D, st, "index.html")
    if os.path.isfile(sp):
      sh = open(sp, encoding="utf-8").read()
      if not re.search(r'<p class="head-counts"><span class="badge closed" id="count-closed">\d+ closed</span> <span class="badge check" id="count-check">\d+ to check</span></p>', sh): bad.append((st, "hero closed/to-check badges"))
  if support.count('class="tip-btn"') != 3 or support.count("donate.stripe.com") != 3: bad.append(("support", "three buttons"))
  if "fZu4gs0Oafib8eX0QUfQI00" in support or "plink_" in support: bad.append(("support", "old link"))
  if "The digests stay free. If you find them useful, an optional one-off tip helps cover the running costs. Thank you." not in support: bad.append(("support", "wording"))
  if "<title>CampConditions tip" not in support or any(w in support.lower() for w in ("tax-deductible", "charity", "donation", "recurring")): bad.append(("support", "title/claims"))
  support_footer = support.split("<footer>", 1)[-1].split("</footer>", 1)[0]
  support_main = support.split("<main>", 1)[-1].split("</main>", 1)[0]
  if support_footer.count("<p>") != 1 or "Site built" not in support_footer or "without warranty" not in support_footer: bad.append(("support", "standard footer"))
  for link in ('href="/about/"', 'href="/support/"', 'href="/faq/"', 'href="/about-the-data/"', 'href="/closures-this-weekend/"', 'href="/privacy/"', 'href="/terms/"', 'href="/status.json"', 'href="/llms.txt"'):
    if link not in support_footer: bad.append(("support", "footer " + link))
  for marker in ("DataVic", "Explore Outdoors", "Parks Victoria", "DEECA", "Vicmap", "cfa.vic.gov.au", "NPWS", "QSpatial", "Rural Fire Service", 'href="/about/#vic-sources"', 'href="/about/#nsw-sources"', 'href="/about/#qld-sources"'):
    if marker in support_footer or marker in support_main: bad.append(("support", "data attribution " + marker))
  if 'class="banner-row"' not in support or 'class="tip-btn"' not in support_main: bad.append(("support", "header or tips"))
  for line in ("/nsw/camp/bulahdelah-rest-area/ /nsw/camp/lions-park-bulahdelah/ 301", "/nsw/camp/red-devil-camping/ /nsw/camp/red-devils-campsite/ 301",
               "/tas/camp/new-pelion-hut-tas-list-cs-62194 /tas/camp/new-pelion-hut/ 301",
               "/tas/camp/waterfall-valley-hut-tas-list-cs-62192/ /tas/camp/waterfall-valley-hut/ 301",
               "/tas/camp/windermere-hut-tas-list-cs-62186 /tas/camp/windermere-hut/ 301",
               "/tas/camp/wild-dog-creek-campsite-tas-list-cs-62066/ /tas/camp/wild-dog-creek-campsite/ 301"):
    if line not in redirects: bad.append(("_redirects", line))
  terms = open(os.path.join(D, "terms", "index.html"), encoding="utf-8").read()
  if "Terms of use" not in terms or "as is, without warranty" not in terms or "Victoria." not in terms or "New South Wales." not in terms or "governing law" in terms.lower(): bad.append(("terms", "wording"))
  if "NPWS" not in about or "NSW Rural Fire Service" not in about or "Spatial Services" not in about or "livetraffic.com" not in about: bad.append(("about", "nsw credits"))
  if about.count("DataVic and Explore Outdoors") != 1: bad.append(("about", "datavic credit"))
  if 'id="vic-sources"' not in about or 'id="nsw-sources"' not in about: bad.append(("about", "source anchors"))
  home_footer = home.split("<footer>", 1)[-1].split("</footer>", 1)[0]
  vic_footer = vic.split("<footer>", 1)[-1].split("</footer>", 1)[0]
  nsw_footer = nsw_html.split("<footer>", 1)[-1].split("</footer>", 1)[0]
  _footer_p = 3 + (1 if os.path.isdir(os.path.join(D, "qld")) else 0) + (1 if os.path.isdir(os.path.join(D, "sa")) else 0) + (1 if os.path.isdir(os.path.join(D, "tas")) else 0)
  if home_footer.count("<p>") != _footer_p or 'href="/about/#vic-sources"' not in home_footer or 'href="/about/#nsw-sources"' not in home_footer:
    bad.append(("/", "footer lines"))
  if vic_footer.count("<p>") != 2 or 'href="/about/#vic-sources"' not in vic_footer or "nsw-sources" in vic_footer or "Victoria: DataVic, Explore Outdoors and Parks Victoria" not in vic_footer:
    bad.append(("/vic/", "footer lines"))
  if nsw_footer.count("<p>") != 2 or 'href="/about/#nsw-sources"' not in nsw_footer or "vic-sources" in nsw_footer or "NPWS camping areas" not in nsw_footer:
    bad.append(("/nsw/", "footer lines"))
  qld_index = os.path.join(D, "qld", "index.html")
  if os.path.isfile(qld_index):
    qld_footer = open(qld_index, encoding="utf-8").read().split("<footer>", 1)[-1].split("</footer>", 1)[0]
    if qld_footer.count("<p>") != 2 or "QPWS camping grounds" not in qld_footer or 'href="/about/#qld-sources"' not in qld_footer or "vic-sources" in qld_footer:
      bad.append(("/qld/", "footer attribution"))
  privacy_footer = open(os.path.join(D, "privacy", "index.html"), encoding="utf-8").read().split("<footer>", 1)[-1].split("</footer>", 1)[0]
  if "Victoria: DataVic, Explore Outdoors and Parks Victoria" not in privacy_footer or "NPWS camping areas" not in privacy_footer:
    bad.append(("privacy", "footer attribution"))
  if "Data and attribution" in home_footer or "Data and attribution" in vic_footer or "Data and attribution" in nsw_footer:
    bad.append(("footer", "long attribution"))
  home_map_file = open(os.path.join(D, "map-points", "home.json"), "rb").read()
  # Budget per build: two states 110 kB gzip, three states 140 kB.
  _map_budget = 220000 if os.path.isdir(os.path.join(D, "tas")) else (180000 if os.path.isdir(os.path.join(D, "sa")) else (140000 if os.path.isdir(os.path.join(D, "qld")) else 110000))
  if not home_map_file.startswith(b"[[") or len(gzip.compress(home_map_file)) > _map_budget:
    bad.append(("home.json", f"raw {len(home_map_file)} gzip {len(gzip.compress(home_map_file))}"))
  _region = "Victoria, New South Wales, Queensland, South Australia and Tasmania, Australia" if os.path.isdir(os.path.join(D, "tas")) else ("Victoria, New South Wales, Queensland and South Australia, Australia" if os.path.isdir(os.path.join(D, "sa")) else ("Victoria, New South Wales and Queensland, Australia" if os.path.isdir(os.path.join(D, "qld")) else "Victoria and New South Wales, Australia"))
  if feed.get("region") != _region: bad.append(("status.json", feed.get("region")))
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
  nsw_fix = json.load(open(os.path.join(root, "data", "manual-corrections-nsw.json"), encoding="utf-8"))
  if not nsw_fix.get("n1811163531", {}).get("exclude") or "new:lions-park-bulahdelah" not in nsw_fix: bad.append(("nsw corrections", "bulahdelah"))
  nsw_names = {c.get("name") for c in nsw_camps}
  if "Bulahdelah Rest Area" in nsw_names: bad.append(("nsw corrections", "bulahdelah rest area still built"))
  lions = next((c for c in nsw_camps if c.get("name") == "Lions Park, Bulahdelah"), None)
  if not lions or lions.get("region") != "north-coast-nsw": bad.append(("nsw corrections", "lions park bulahdelah"))
  if "Lions Park, Numurkah" in nsw_names or "Gloryvale Reserve Campgrounds" in {c.get("name") for c in vic_feed}: bad.append(("corrections", "state crossover"))
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
    if 'name="states" value="nsw" checked' not in html_page or 'name="states" value="vic" checked' in html_page:
      bad.append((camp["slug"], "signup states")); break
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
  districts = ("Central", "East Gippsland", "Mallee", "North Central", "North East", "Northern Country", "South West", "West and South Gippsland", "Wimmera")
  cfa_pages = 0
  for camp in vic_feed:
    page = os.path.join(D, "vic", "camp", camp["slug"], "index.html")
    if not os.path.isfile(page):
      continue
    html_page = open(page, encoding="utf-8").read()
    main = html_page.split("<main>", 1)[-1]
    if html_page.count('class="banner-row"') != 2: bad.append((camp["slug"], "header rows")); break
    if "Check CFA fire danger" not in main:
      continue
    cfa_pages += 1
    if '<h2 class="fire-head"' not in main or ">Fire Ratings</h2>" not in main or "Total fire ban:" not in main:
      bad.append((camp["slug"], "cfa heading")); break
    if "fdrToban.xml" in main or "Check Live Traffic NSW" in main:
      bad.append((camp["slug"], "nsw fire on victoria")); break
    link = re.search(r'href="(https://www.cfa.vic.gov.au/warnings-and-restrictions/fire-bans-ratings-and-restrictions/total-fire-bans-fire-danger-ratings/[a-z-]+-fire-district)"', main)
    if not link: bad.append((camp["slug"], "cfa deep link")); break
    if not any(name + ":" in main for name in districts): bad.append((camp["slug"], "cfa district")); break
    if "https://www.cfa.vic.gov.au/cfa/rssfeed/tfbfdrforecast_rss.xml" not in html_page or "CC BY 4.0" not in html_page:
      bad.append((camp["slug"], "cfa attribution")); break
    if "Issued " not in main and "Fetched " not in main: bad.append((camp["slug"], "cfa issued")); break
  cfa_src = (feed.get("sources") or {}).get("cfa_fdr") or {}
  cfa_ok = cfa_src.get("ok")
  if not cfa_src.get("url") or "ok" not in cfa_src: bad.append(("status.json", "cfa source"))
  if not cfa_ok and not (cfa_src.get("error") or cfa_src.get("fallback")): bad.append(("status.json", "cfa failure hidden"))
  if cfa_pages < 1200 and (cfa_ok or cfa_src.get("fallback")): bad.append(("vic", f"cfa fire lines {cfa_pages}"))
  if cfa_pages < 1200 and not cfa_ok and not cfa_src.get("fallback"): warnings.append(("vic", f"cfa feed unavailable; fire lines {cfa_pages}"))
  import cfa_conditions
  sample_rss = """<?xml version="1.0"?><rss version="2.0"><channel><item><title>Day</title><link>https://www.cfa.vic.gov.au/example</link><description>&lt;p&gt;Today, example is not currently a day of Total Fire Ban.&lt;/p&gt;&lt;p&gt;Mallee: NO - RESTRICTIONS MAY APPLY&lt;/p&gt;&lt;p&gt;Fire Danger Ratings&lt;/p&gt;&lt;p&gt;Mallee: MODERATE&lt;/p&gt;</description></item><item><title>Next</title><link>https://www.cfa.vic.gov.au/example</link><description>&lt;p&gt;Tomorrow, example.&lt;/p&gt;&lt;p&gt;Mallee: YES&lt;/p&gt;&lt;p&gt;Fire Danger Ratings&lt;/p&gt;&lt;p&gt;Mallee: HIGH&lt;/p&gt;</description></item><item><title>Skip</title><link>https://www.cfa.vic.gov.au/example</link><description>&lt;p&gt;Fri, example is not currently a day of Total Fire Ban.&lt;/p&gt;&lt;p&gt;Mallee: YES&lt;/p&gt;&lt;p&gt;Fire Danger Ratings&lt;/p&gt;&lt;p&gt;Mallee: EXTREME&lt;/p&gt;</description></item></channel></rss>"""
  sample_parsed = cfa_conditions.parse_cfa(sample_rss)
  sample_today = sample_parsed["today"].get("mallee") or {}
  if sample_today.get("today") != "Moderate" or sample_today.get("ban_today") != "No - restrictions may apply":
    bad.append(("cfa parse", str(sample_today)))
  if (sample_parsed["tomorrow"].get("mallee") or {}).get("today") != "High" or "extreme" in json.dumps(sample_parsed).lower():
    bad.append(("cfa parse", "day window"))
  dated_rss = """<?xml version="1.0"?><rss version="2.0"><channel><item><title>Day</title><link>https://www.cfa.vic.gov.au/example</link><description>&lt;p&gt;Today, Wed, 28 Oct 2026 is not currently a day of Total Fire Ban.&lt;/p&gt;&lt;p&gt;Mallee: NO - RESTRICTIONS MAY APPLY&lt;/p&gt;&lt;p&gt;Fire Danger Ratings&lt;br/&gt;Bureau of Meteorology forecast issued at: Wednesday, 28 October 2026 05:30 AM&lt;/p&gt;&lt;p&gt;Mallee: MODERATE&lt;/p&gt;</description></item><item><title>Next</title><link>https://www.cfa.vic.gov.au/example</link><description>&lt;p&gt;Tomorrow, Thu, 29 Oct 2026.&lt;/p&gt;&lt;p&gt;Mallee: NO - RESTRICTIONS MAY APPLY&lt;/p&gt;&lt;p&gt;Fire Danger Ratings&lt;/p&gt;&lt;p&gt;Mallee: HIGH&lt;/p&gt;</description></item></channel></rss>"""
  dated = cfa_conditions.forecast_days(dated_rss)
  if (dated.get("2026-10-28") or {}).get("issued") != "Wednesday, 28 October 2026 05:30 AM": bad.append(("cfa parse", "issued"))
  if ((dated.get("2026-10-28") or {}).get("districts") or {}).get("mallee", {}).get("rating") != "Moderate": bad.append(("cfa parse", "dated today"))
  if ((dated.get("2026-10-29") or {}).get("districts") or {}).get("mallee", {}).get("rating") != "High": bad.append(("cfa parse", "dated tomorrow"))
  fresh_now = __import__("datetime").datetime(2026, 10, 28, 18, 0, tzinfo=facts.MELBOURNE)
  fresh = {"fetched": "2026-10-28T08:39:00+11:00", "days": dated}
  fresh_window = cfa_conditions.cache_window(fresh, fresh_now)
  if not fresh_window or not fresh_window[0] or not fresh_window[1]: bad.append(("cfa cache", "fresh window"))
  old = {"fetched": "2026-10-27T08:00:00+11:00", "days": dated}
  if cfa_conditions.cache_window(old, fresh_now) is not None: bad.append(("cfa cache", "over 24 hours"))
  other_day = {"fetched": "2026-10-28T08:39:00+11:00", "days": {"2026-10-11": dated["2026-10-28"]}}
  if cfa_conditions.cache_window(other_day, fresh_now) is not None: bad.append(("cfa cache", "other day"))
  if cfa_conditions.fetched_phrase("2026-10-28T08:39:00+11:00") != "28 October 2026, 8:39 AM AEDT": bad.append(("cfa cache", "fetched phrase"))
  if "Country Fire Authority" not in " ".join(feed.get("attribution") or []): bad.append(("status.json", "cfa credit"))
  home_visible = re.sub(r"<script[\s\S]*?</script>", "", home)
  if "Total fire ban:" in home_visible or "NPWS alerts:" in home_visible or "Official NPWS wording" in home_visible:
    bad.append(("/", "nsw conditions on victoria"))
  if npws:
    sample = os.path.join(D, "nsw", "camp", npws[0]["slug"], "index.html")
    if os.path.isfile(sample):
      sample_html = open(sample, encoding="utf-8").read()
      if "no road or track closures were found" in sample_html or "<h2>Facilities</h2>" in sample_html:
        bad.append((npws[0]["slug"], "invented detail"))
  if closed_npws:
    closed_html = open(os.path.join(D, "nsw", "camp", closed_npws[0]["slug"], "index.html"), encoding="utf-8").read()
    if "NPWS alert" not in closed_html or "badge closed" not in closed_html or "Official NPWS wording" not in closed_html or "Alert dated" not in closed_html: bad.append((closed_npws[0]["slug"], "closed page"))
by_slug = {c["slug"]: c for c in vic_feed}
for slug, region in (
    ("parkers-pines", "high-country"), ("ewarts-flat", "high-country"), ("taylors", "high-country"),
    ("the-island", "high-country"), ("wentworths", "high-country"), ("ingrams", "gippsland"),
):
    camp = by_slug.get(slug)
    if not camp or camp.get("region") != region: bad.append((slug, (camp or {}).get("region")))
for name, region in (
    ("Jerusalem Creek Campground", "high-country"),
    ("Mountaineer Creek Camping Area (Lake Eildon National Park)", "high-country"),
    ("Candlebark Campground", "high-country"),
    ("Lakeside Campground", "high-country"),
    ("Devils Cove Campground", "high-country"),
    ("Barnewall Plains Camping Area", "high-country"),
    ("O'Tooles Flat", "high-country"),
    ("Running Creek Track", "high-country"),
):
    camp = next((c for c in feed["camps"] if c.get("name") == name), None)
    if camp and camp.get("region") != region: bad.append((name, camp.get("region")))
for slug in ("kendalls", "tin-hut", "coopers-creek-camping-area-two", "strachans-campground-grampians-gariwerd-national-park", "teddington-camping-area-kara-kara-national-park"):
    row = next((c for c in feed["camps"] if c.get("slug") == slug), None)
    if not row or row.get("status") == "closed" or row.get("closure"):
        bad.append((slug, "still closed", (row or {}).get("status")))
for slug, reopen in DATED_REOPEN.items():
    if MEL_TODAY >= reopen: continue
    row = next((c for c in feed["camps"] if c.get("slug") == slug), {})
    if row.get("status") != "closed" or (row.get("closure") or {}).get("reopen") != reopen:
        bad.append((slug, row.get("status"), (row.get("closure") or {}).get("reopen")))
thredbo = next((c for c in feed["camps"] if c.get("slug") == "thredbo-diggings-campground"), {})
if MEL_TODAY < "2026-11-01" and (thredbo.get("status") != "closed" or (thredbo.get("closure") or {}).get("reopen") != "2026-11-01"):
    bad.append(("thredbo-diggings-campground", thredbo.get("status"), (thredbo.get("closure") or {}).get("reopen")))
# Peacock Creek (Richmond Range, wet conditions) and Flea Creek (weekday
# closures from 2 Nov) are now closed by NPWS, so they left this list on 30 Oct 2026.
for slug in ("washpools-campground", "cooleman-mountain-campground", "freemans-campground", "willows-campground"):
    row = next((c for c in feed["camps"] if c.get("slug") == slug), None)
    if row and (row.get("status") == "closed" or row.get("closure")):
        bad.append((slug, "false closure"))
paradise_here = [c for c in feed["camps"] if "paradise beach" in (c.get("name") or "").lower() and abs(c.get("lat") + 35.85) < 0.02 and abs(c.get("lon") - 145.28) < 0.02]
if len(paradise_here) != 1:
    bad.append(("paradise beach", [c.get("slug") for c in paradise_here]))
parkers = by_slug.get("parkers-pines") or {}
if parkers.get("status") != "closed" or (parkers.get("closure") or {}).get("reopen") != "2026-12-18":
    bad.append(("parkers-pines", parkers.get("status"), (parkers.get("closure") or {}).get("reopen")))
if parkers.get("upcoming_closure"): bad.append(("parkers-pines", "upcoming"))
ingrams = by_slug.get("ingrams") or {}
if ingrams.get("status") != "closed" or (ingrams.get("closure") or {}).get("reopen") != "2026-12-24":
    bad.append(("ingrams", ingrams.get("status"), (ingrams.get("closure") or {}).get("reopen")))
for slug, reopen in (("ewarts-flat", "2027-05-28"), ("taylors", "2027-05-28"), ("wentworths", "2027-05-28"), ("the-island", "2027-03-05")):
    camp = by_slug.get(slug) or {}
    upcoming = camp.get("upcoming_closure") or {}
    if camp.get("status") == "closed" or camp.get("closure") or upcoming.get("start") != "2027-02-01" or upcoming.get("reopen") != reopen:
        bad.append((slug, camp.get("status"), upcoming.get("start"), upcoming.get("reopen")))
for camp in feed["camps"]:
    upcoming = camp.get("upcoming_closure") or None
    closure = camp.get("closure") or {}
    if upcoming and camp.get("status") == "closed": bad.append((camp.get("slug"), "future closure still closed"))
    for record in (upcoming, closure):
        if not record: continue
        for key in ("start", "reopen"):
            value = record.get(key) or ""
            if isinstance(value, str) and "T" in value: bad.append((camp.get("slug"), key, value))
def camp_html(slug):
    path = os.path.join(D, "vic", "camp", slug, "index.html")
    return open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
ingrams_html = camp_html("ingrams")
ingrams_block = ingrams_html.split('id="camp-closure"', 1)[-1][:900] if ingrams_html else ""
ingrams_line = re.search(r'<p class="status-line" data-camp="ingrams">(.*?)</p>', ingrams_html or "")
if "Reopens 2026-12-24" not in ingrams_block or "2026-12-23" in ingrams_block or "Upcoming closure" in ingrams_block:
    bad.append(("ingrams", "page date"))
if not ingrams_line or "badge closed" not in ingrams_line.group(1) or 'href="/vic/gippsland/"' not in ingrams_html:
    bad.append(("ingrams", "page status"))
parkers_html = camp_html("parkers-pines")
parkers_block = parkers_html.split('id="camp-closure"', 1)[-1][:900] if parkers_html else ""
if "Reopens 2026-12-18" not in parkers_block or "2026-12-17" in parkers_block or 'href="/vic/high-country/"' not in parkers_html:
    bad.append(("parkers-pines", "page"))
for slug, reopen in (("ewarts-flat", "2027-05-28"), ("taylors", "2027-05-28"), ("wentworths", "2027-05-28"), ("the-island", "2027-03-05")):
    page_html = camp_html(slug)
    block = page_html.split('id="camp-closure"', 1)[-1][:1100] if page_html else ""
    line = re.search(r'<p class="status-line" data-camp="%s">(.*?)</p>' % re.escape(slug), page_html or "")
    if "Upcoming closure" not in block or "Starts 2027-02-01" not in block or "Reopens " + reopen not in block:
        bad.append((slug, "upcoming notice"))
    if not line or "badge closed" in line.group(1) or 'href="/vic/high-country/"' not in page_html:
        bad.append((slug, "still listed closed"))
    if "function melbourneDay" not in page_html or "upcoming_closure" not in page_html:
        bad.append((slug, "refresh script"))
# FAQ, About the data and Closures this weekend: built, linked from every footer,
# in the sitemap with valid lastmod dates, and listed in llms.txt for both states.
def _ld_blocks(text):
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)]
_info = {"/faq/": "FAQPage", "/about-the-data/": "Dataset", "/closures-this-weekend/": "ItemList"}
for _path, _type in _info.items():
    _fp = os.path.join(D, _path.strip("/"), "index.html")
    if not os.path.isfile(_fp):
        bad.append((_path, "missing")); continue
    _html = open(_fp, encoding="utf-8").read()
    _blocks = _ld_blocks(_html)
    _types = [b.get("@type") for b in _blocks]
    if _type not in _types or "BreadcrumbList" not in _types: bad.append((_path, "json-ld types", _types))
    for _b in _blocks:
        if _b.get("@context") != "https://schema.org": bad.append((_path, "json-ld context"))
    if f'<link rel="canonical" href="https://campconditions.au{_path}"' not in _html: bad.append((_path, "canonical"))
    if national and ("/vic/" not in _html or "/nsw/" not in _html): bad.append((_path, "both states"))
_faq_html = open(os.path.join(D, "faq", "index.html"), encoding="utf-8").read() if os.path.isfile(os.path.join(D, "faq", "index.html")) else ""
for _b in _ld_blocks(_faq_html):
    if _b.get("@type") == "FAQPage":
        _qs = _b.get("mainEntity") or []
        if len(_qs) < 5 or any(not q.get("name") or not (q.get("acceptedAnswer") or {}).get("text") for q in _qs): bad.append(("/faq/", "faq entities"))
        for _q in _qs:
            if html.escape(_q["name"], quote=False) not in _faq_html: bad.append(("/faq/", "question not on page", _q["name"]))
# Every page's JSON-LD names a schema.org context and type.
for r, _, fs in os.walk(D):
    if draft_dir(r): continue
    for f in fs:
        if not f.endswith(".html"): continue
        for _b in _ld_blocks(open(os.path.join(r, f), encoding="utf-8").read()):
            if _b.get("@context") != "https://schema.org" or not _b.get("@type"):
                bad.append((os.path.join(r, f)[len(D):], "json-ld context/type")); break
_home_html = open(os.path.join(D, "index.html"), encoding="utf-8").read()
for _path in _info:
    if f'href="{_path}"' not in _home_html: bad.append(("/", "footer link", _path))
if _home_html.split("<main", 1)[0].count('href="/faq/"') != 1: bad.append(("/", "faq link in header nav"))
_sm_text = open(os.path.join(D, "sitemap.xml"), encoding="utf-8").read()
_sm_rows = re.findall(r"<url><loc>https://campconditions.au(.*?)</loc><lastmod>(.*?)</lastmod></url>", _sm_text)
if len(_sm_rows) != len(sm) or len(set(sm)) != len(sm): bad.append(("sitemap", "duplicate or malformed rows"))
for _u, _lm in _sm_rows:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", _lm) or _lm > MEL_TODAY: bad.append(("sitemap", "lastmod", _u, _lm)); break
for _path in _info:
    if _path not in sm: bad.append(("sitemap", "missing", _path))
_llms = open(os.path.join(D, "llms.txt"), encoding="utf-8").read()
if "preview" in _llms.lower(): bad.append(("llms.txt", "preview wording"))
for _path in _info:
    if "https://campconditions.au" + _path not in _llms: bad.append(("llms.txt", "missing", _path))
if national:
    for _name in ("## Victoria", "## New South Wales", "### Victoria regions", "### New South Wales regions"):
        if _name not in _llms: bad.append(("llms.txt", "section", _name))
    _attr_states = 2 + int(os.path.isfile(os.path.join(D, "qld", "index.html"))) + int(os.path.isfile(os.path.join(D, "sa", "index.html"))) + int(os.path.isfile(os.path.join(D, "tas", "index.html")))
    if _llms.count("- Attribution: ") != _attr_states: bad.append(("llms.txt", "attribution per state"))
_headers = open(os.path.join(D, "_headers"), encoding="utf-8").read()
for _path in _info:
    if _path + "*\n  Cache-Control: no-cache" not in _headers: bad.append(("_headers", _path))
# Closures this weekend lists every camp the feed has closed into the weekend.
_wk = open(os.path.join(D, "closures-this-weekend", "index.html"), encoding="utf-8").read() if os.path.isfile(os.path.join(D, "closures-this-weekend", "index.html")) else ""
for _c in feed["camps"]:
    _rec = _c.get("closure") or {}
    if _c.get("status") == "closed" and not _rec.get("reopen"):
        _href = urllib.parse.urlparse(_c.get("url") or "").path
        if _href and f'href="{_href}"' not in _wk: bad.append(("/closures-this-weekend/", "missing closed camp", _c.get("slug")))
# NPWS clock times are kept beside the ISO dates and spoken on the camp page.
if (_b1 or {}).get("start_time") != "14:00" or (_b1 or {}).get("reopen_time") != "10:00":
    bad.append(("alerts", "berlang clock", _b1))
if (_thredbo_hit or {}).get("start_time") or (_thredbo_hit or {}).get("reopen_time"):
    bad.append(("alerts", "thredbo clock", _thredbo_hit))
# Berlang: NPWS closes it from 2pm Sunday 1 November until 10am Saturday 7 November 2026.
_berlang_row = next((c for c in feed["camps"] if (c.get("name") or "").lower().startswith("berlang") and "/nsw/" in (c.get("url") or "")), None)
if _berlang_row and MEL_TODAY <= "2026-11-06":
    _rec = _berlang_row.get("closure") or _berlang_row.get("upcoming_closure") or {}
    if _rec and (_rec.get("reopen") != "2026-11-07" or _rec.get("reopen_time") != "10:00"):
        bad.append(("berlang feed", _rec.get("reopen"), _rec.get("reopen_time")))
    _bp = os.path.join(D, urllib.parse.urlparse(_berlang_row["url"]).path.strip("/"), "index.html")
    _bhtml = open(_bp, encoding="utf-8").read() if os.path.isfile(_bp) else ""
    if _rec and "Reopens 10am Saturday 7 November 2026" not in _bhtml: bad.append(("berlang page", "spoken reopen"))
    if _rec and f'href="{urllib.parse.urlparse(_berlang_row["url"]).path}"' not in _wk: bad.append(("berlang", "not on weekend page"))
# Queensland unit tests: fixtures only, so they run whether or not Queensland is enabled.
import datetime as _qdt
import qld_conditions as qldc
_sq = lambda x, y, d=0.1: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]
_q_estates = qldc.estate_records({"estates": [
    {"name": "Testa National Park", "type": "National Park", "rings": _sq(150.0, -25.0)},
    {"name": "Paluma Range National Park", "type": "National Park", "rings": _sq(146.0, -19.0)},
    {"name": "Danbulla State Forest", "type": "State Forest", "rings": _sq(145.6, -17.2)},
]})
def _q_rss(items):
    body = "".join(f"<item><title>{t}</title><link>https://parks.qld.gov.au/park-alerts/{i}</link><pubDate>Mon, 02 Nov 2026 09:00:00 +1000</pubDate>"
                   f"<description>{html.escape(d)} Affected parks: {p}</description></item>" for i, (t, d, p) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>QPWS</title>{body}</channel></rss>'.encode()
_q_items = qldc.parse_rss(_q_rss([
    ("Testa National Park closed", "Due to flooding, Testa National Park is closed until further notice.", "Testa National Park"),
    ("Section closed", "Due to damage, the Jourama Falls section, Paluma Range National Park is closed.", "Paluma Range National Park"),
    ("Fong-On Bay camping area closure", "Fong-On Bay camping area will close on 20 November 2026 and reopen on 7 December 2026.", "Danbulla State Forest 1"),
]))
if len(_q_items) != 3 or _q_items[2]["park_loose"] != {qldc.loose_key("Danbulla State Forest")}: bad.append(("qld", "rss parse", len(_q_items)))
_q_now = _qdt.datetime(2026, 11, 2, 12, 0, tzinfo=qldc.BRISBANE)
_q_camps = [
    {"name": "Testa Creek camping area", "lat": -24.95, "lon": 150.05, "status": "check", "source": "qpws"},
    {"name": "Big Crystal Creek camping area", "lat": -18.95, "lon": 146.05, "status": "check", "source": "qpws"},
    {"name": "Fong-On Bay camping area", "lat": -17.15, "lon": 145.65, "status": "check", "source": "qpws"},
    {"name": "Lake Tinaroo camping area", "lat": -17.15, "lon": 145.62, "status": "check", "source": "qpws"},
]
_q_sum = qldc.apply_alert_items(_q_camps, _q_estates, _q_items, _q_now)
if _q_camps[0]["status"] != "closed" or not (_q_camps[0].get("closure") or {}).get("source_url", "").startswith("https://parks.qld.gov.au/"): bad.append(("qld", "whole park closure"))
if _q_camps[1]["status"] != "check" or not _q_camps[1].get("alerts"): bad.append(("qld", "section is not the whole park", _q_camps[1].get("closure")))
_q_up = _q_camps[2].get("upcoming_closure") or {}
if _q_camps[2]["status"] != "check" or _q_up.get("start") != "2026-11-20": bad.append(("qld", "upcoming named camp", _q_up))
if _q_camps[3].get("closure") or _q_camps[3].get("upcoming_closure"): bad.append(("qld", "other camp in park closed"))
if _q_sum["closed"] != 1 or _q_sum["upcoming"] != 1: bad.append(("qld", "summary", _q_sum))
# 'up to and including' is inclusive, and ordinals are read.
_q_t = qldc.timing("The camping area is closed from 1 November up to and including 29th of November 2026.", _q_now)
if _q_t.get("reopen") != "2026-11-30": bad.append(("qld", "inclusive end", _q_t))
# Permit-only council areas are excluded by default and kept only by the flag.
_q_state = {"permit_only_areas": {"include_permit_only_areas": False, "lgas": ["Testshire Aboriginal Shire"]}}
_q_lga = {"regions": [{"name": "Testshire Aboriginal Shire", "rings": _sq(142.0, -12.0)}, {"name": "Open Regional", "rings": _sq(150.0, -25.0)}]}
_q_pc = [{"name": "A", "lat": -11.95, "lon": 142.05, "source": "osm"}, {"name": "B", "lat": -24.95, "lon": 150.05, "source": "qpws"}]
_q_kept, _q_drop = qldc.exclude_permit_only([dict(c) for c in _q_pc], _q_state, _q_lga)
if [c["name"] for c in _q_kept] != ["B"] or [c["name"] for c in _q_drop] != ["A"]: bad.append(("qld", "permit-only exclusion"))
_q_state["permit_only_areas"]["include_permit_only_areas"] = True
if len(qldc.exclude_permit_only([dict(c) for c in _q_pc], _q_state, _q_lga)[0]) != 2: bad.append(("qld", "permit-only flag"))
_q_cfg = json.load(open(os.path.join(root, "config", "states", "qld.json"), encoding="utf-8"))
if (_q_cfg.get("permit_only_areas") or {}).get("include_permit_only_areas") is not False: bad.append(("qld", "permit-only default"))
# BoM fire danger: district ratings by Queensland date.
_q_fdr = qldc.parse_fdr(b'<?xml version="1.0"?><product><amoc><issue-time-utc>2026-11-02T06:00:00Z</issue-time-utc></amoc><forecast>'
    b'<area aac="QLD_FW001" description="Testa" type="fire-district"><forecast-period start-time-local="2026-11-02T00:00:00+10:00"><text type="fire_danger">High</text></forecast-period>'
    b'<forecast-period start-time-local="2026-11-03T00:00:00+10:00"><text type="fire_danger">Extreme</text></forecast-period></area></forecast></product>')
_q_fc = [{"name": "X", "lat": -24.95, "lon": 150.05}]
qldc.apply_fire(_q_fc, qldc.area_records([{"name": "Testa", "rings": _sq(150.0, -25.0)}]), _q_fdr[0], _q_fdr[1], "https://www.bom.gov.au/fwo/IDQ13016.xml",
                {"fire_bans": "https://www.fire.qld.gov.au/", "fire_bans_button": "Check local fire bans (QFD)"}, _q_now)
_q_f = _q_fc[0].get("fire") or {}
if _q_f.get("today") != "High" or _q_f.get("tomorrow") != "Extreme" or _q_f.get("ban_today") or not _q_f.get("ban_note"): bad.append(("qld", "fire danger", _q_f))
if "AEDT" not in (_q_f.get("issued") or ""): bad.append(("qld", "fire issued AEDT", _q_f.get("issued")))
# QLD fallback: a shore camp 200 m outside the coastline-clipped district takes it; an island 5 km out does not.
_q_fb = [{"name": "Shore", "lat": -24.95, "lon": 150.102}, {"name": "Island", "lat": -24.95, "lon": 150.15}]
qldc.apply_fire(_q_fb, qldc.area_records([{"name": "Testa", "rings": _sq(150.0, -25.0)}]), _q_fdr[0], _q_fdr[1], "https://www.bom.gov.au/fwo/IDQ13016.xml",
                {"fire_bans": "https://www.fire.qld.gov.au/", "fire_bans_button": "Check local fire bans (QFD)"}, _q_now)
if (_q_fb[0].get("fire") or {}).get("today") != "High" or (_q_fb[0].get("fire") or {}).get("district") != "Testa" or "fallback_km" not in _q_fb[0]["fire"]:
  bad.append(("qld", "shore fallback", _q_fb[0]))
if _q_fb[1].get("fire") or (_q_fb[1].get("fire_unmapped") or {}).get("label") != "No fire district mapped" or (_q_fb[1]["fire_unmapped"].get("page_url") or "") != "https://www.bom.gov.au/qld/forecasts/fire-danger-ratings.shtml":
  bad.append(("qld", "island unmapped", _q_fb[1]))
# QLDTraffic: skipped without the key; with a key the key never reaches the source log.
_q_log = {}
if qldc.apply_traffic(_q_fc, {"url": "https://api.qldtraffic.qld.gov.au/v2/events", "key_env": "QLDTRAFFIC_API_KEY"}, lambda *a, **k: b"", _q_log, env={}) is not None: bad.append(("qld", "traffic without key"))
if (_q_log.get("qldtraffic") or {}).get("ok") is not False: bad.append(("qld", "traffic skip logged"))
def _q_fetch(name, url, headers=None):
  _q_log[name] = {"ok": False, "url": url, "error": "HTTP 401 for " + url}
  return b""
qldc.apply_traffic(_q_fc, {"url": "https://api.qldtraffic.qld.gov.au/v2/events"}, _q_fetch, _q_log, env={"QLDTRAFFIC_API_KEY": "SECRETKEY123"})
if "SECRETKEY123" in json.dumps(_q_log): bad.append(("qld", "traffic key leaked to source log"))
_q_urls = []
qldc.apply_traffic([], {"url": "https://api.qldtraffic.qld.gov.au/v2/events", "public_key": "PUBKEY"}, lambda name, url, *a, **k: _q_urls.append(url) or b'{"features": []}', {}, env={})
if len(_q_urls) != 1 or "apikey=PUBKEY" not in _q_urls[0]: bad.append(("qld", "traffic public key fallback", _q_urls))
_q_urls = []
qldc.apply_traffic([], {"url": "https://api.qldtraffic.qld.gov.au/v2/events", "public_key": "PUBKEY"}, lambda name, url, *a, **k: _q_urls.append(url) or b'{"features": []}', {}, env={"QLDTRAFFIC_API_KEY": "OWNKEY"})
if len(_q_urls) != 1 or "apikey=OWNKEY" not in _q_urls[0]: bad.append(("qld", "traffic own key first", _q_urls))
_q_ev = qldc.traffic_events({"features": [
  {"geometry": {"type": "Point", "coordinates": [150.06, -24.95]}, "properties": {"event_type": "Flooding", "road_summary": {"road_name": "Test Rd", "locality": "Testa"}, "description": "Water over road"}},
  {"geometry": {"type": "Point", "coordinates": [150.06, -24.95]}, "properties": {"event_type": "Roadworks", "impact": {"impact_type": "Lane narrowing"}}}]})
if len(_q_ev) != 1 or qldc.apply_traffic_events(_q_fc, _q_ev, 5) != 1: bad.append(("qld", "traffic events"))
# Queensland pages, when the preview build includes them.
if os.path.isfile(os.path.join(D, "qld", "index.html")):
  _q_feed = [c for c in feed["camps"] if "/qld/camp/" in (c.get("url") or "")]
  if len(_q_feed) < 500: bad.append(("qld", "feed camps", len(_q_feed)))
  _q_closed = [c for c in _q_feed if c.get("status") == "closed"]
  for _c in _q_closed:
    if not str(((_c.get("closure") or {}).get("source_url")) or "").startswith("https://parks.qld.gov.au/"): bad.append(("qld", "closure without QPWS link", _c.get("slug")))
  for _c in _q_feed[:2000]:
    if _c.get("source") == "qpws":
      _p = os.path.join(D, "qld", "camp", _c["slug"], "index.html")
      # Visible text only: the shared closure script names NPWS for NSW estimated end dates.
      _t = re.sub(r"<script.*?</script>", "", open(_p, encoding="utf-8").read() if os.path.isfile(_p) else "", flags=re.S)
      if "NPWS" in _t.replace("QPWS", ""): bad.append(("qld", "NPWS wording on QPWS page", _c["slug"])); break
  # QLD digest sign-up: home offers QLD unticked; QLD pages carry the form with QLD ticked and both digest links stay on the page.
  if 'name="states" value="qld"' not in home or 'name="states" value="qld" checked' in home: bad.append(("/", "qld signup state"))
  _q_pages = [os.path.join(D, "qld", "index.html")]
  _q_first = next((c for c in _q_feed if c.get("source") == "qpws"), None)
  if _q_first: _q_pages.append(os.path.join(D, "qld", "camp", _q_first["slug"], "index.html"))
  for _qp in _q_pages:
    _qh = open(_qp, encoding="utf-8").read() if os.path.isfile(_qp) else ""
    if 'id="digest-form"' not in _qh or 'name="states" value="qld" checked' not in _qh or 'name="states" value="vic" checked' in _qh or 'name="states" value="nsw" checked' in _qh: bad.append((_qp[len(D):], "qld signup form"))
    if 'class="digest-cta" href="#newsletter"' not in _qh or '<a href="#newsletter">Free digest</a>' not in _qh or _qh.count('class="banner-row"') != 2: bad.append((_qp[len(D):], "qld digest links"))
  _priv = open(os.path.join(D, "privacy", "index.html"), encoding="utf-8").read()
  if "Victoria, New South Wales and Queensland" not in _priv: bad.append(("/privacy/", "qld digest"))
  _q_src = open(os.path.join(D, "status.json"), encoding="utf-8").read()
  if "apikey" in _q_src.lower(): bad.append(("qld", "api key in status.json"))
# Built pages: an unmapped camp says "No fire district mapped" (never "No Rating" for that),
# and a fallback camp shows its district's official rating plus the boundary note.
_unmapped_pages = _fallback_pages = 0
for _st in ("vic", "nsw", "qld"):
  _cdir = os.path.join(D, _st, "camp")
  if not os.path.isdir(_cdir): continue
  for _slug in os.listdir(_cdir):
    _fp = os.path.join(_cdir, _slug, "index.html")
    if not os.path.isfile(_fp): continue
    _t = open(_fp, encoding="utf-8").read()
    if "fire-unmapped" in _t:
      _unmapped_pages += 1
      _para = re.search(r'<p class="muted fire-line fire-unmapped"[^>]*>(.*?)</p>', _t, re.S)
      if not _para or "No fire district mapped" not in _para.group(1) or "no rating" in _para.group(1).lower():
        bad.append((_slug, "unmapped fire wording")); continue
      if _t.count('class="banner-row"') != 2: bad.append((_slug, "header rows"))
    if "Nearest official district:" in _t:
      _fallback_pages += 1
      _line = re.search(r'<p class="muted fire-line"[^>]*>(.*?)</p>', _t, re.S)
      if not _line or not re.search(r": [A-Z][A-Za-z ]+ (today|tomorrow)", _line.group(1)):
        bad.append((_slug, "fallback without official rating"))
print(f"fire fallback: {_fallback_pages} camp pages use the nearest district, {_unmapped_pages} show No fire district mapped")
# Town landing pages. Counts and distances come from the camp coordinates.
import town_pages as _towns
def _tcamps(*rows):
  return [{"name": n, "lat": la, "lon": lo, "slug": n, "status": "open"} for n, la, lo in rows]
def _north(lat, kilometres):
  return lat + kilometres / 111.0
_rows = [(f"a{i}", _north(0, 1 + i), 0.01) for i in range(6)]
_rows += [(f"g{i}", _north(2.0, i * 0.01), 0.0) for i in range(6)]
_rows += [("solo", 5.0, 5.0)]
_idx = _towns.CampIndex(_tcamps(*_rows))
_chosen, _skipped = _towns.choose_named(
  [{"name": "Alpha", "lat": 0, "lon": 0, "place": "town"},
   {"name": "Beta", "lat": 0, "lon": 5 / 111.0, "place": "town"},
   {"name": "Gamma", "lat": 2, "lon": 0, "place": "town"},
   {"name": "Thin", "lat": 5, "lon": 5, "place": "town"}],
  _idx, lambda lon, lat: "west",
  ["Alpha", "Beta", "Thin", "Gamma", "Missing"])
if {c["name"] for c in _chosen} != {"Alpha", "Gamma"}: bad.append(("towns", "chosen", [c["name"] for c in _chosen]))
if _chosen and any(c["count"] < _towns.MIN_CAMPS for c in _chosen): bad.append(("towns", "minimum"))
_why = {row["name"]: row["why"] for row in _skipped}
if "Beta" not in _why or "Thin" not in _why or "Missing" not in _why: bad.append(("towns", "skipped", _why))
def _at(lat, lon, kilometres):
  # Scale a northward step so the haversine distance matches kilometres.
  guess = lat + kilometres / 100.0
  dist = _towns.km(lat, lon, guess, lon) or 1
  return lat + (guess - lat) * (kilometres / dist)
_base_lat, _base_lon = -37.0, 145.0
_rim = _at(_base_lat, _base_lon, _towns.RADIUS_KM)
while _towns.km(_base_lat, _base_lon, _rim, _base_lon) > _towns.RADIUS_KM:
  _rim -= 1e-7
_edge = _towns.CampIndex([{"name": "here", "lat": _base_lat, "lon": _base_lon, "slug": "here", "status": "open"},
                          {"name": "rim", "lat": _rim, "lon": _base_lon, "slug": "rim", "status": "open"}])
if len(_edge.within(_base_lat, _base_lon, _towns.RADIUS_KM)) != 2: bad.append(("towns", "radius edge"))
_over = _towns.CampIndex([{"name": "here", "lat": _base_lat, "lon": _base_lon, "slug": "here", "status": "open"},
                          {"name": "out", "lat": _at(_base_lat, _base_lon, _towns.RADIUS_KM + 1), "lon": _base_lon, "slug": "out", "status": "open"}])
if len(_over.within(_base_lat, _base_lon, _towns.RADIUS_KM)) != 1: bad.append(("towns", "radius over"))
_town_states = ("vic", "nsw", "qld", "sa", "tas")
_town_pages = []
_town_by_state = { _st: set() for _st in _town_states }
for _st in _town_states:
  _dir = os.path.join(D, _st, "near")
  if not os.path.isdir(_dir):
    bad.append((_st, "town dir")); continue
  for _slug in sorted(os.listdir(_dir)):
    _fp = os.path.join(_dir, _slug, "index.html")
    if os.path.isfile(_fp):
      _town_pages.append((_st, _slug, _fp))
      _town_by_state[_st].add(_slug)
# Fifty pages from Victoria, New South Wales and Queensland, plus the South
# Australian and Tasmanian touring towns that clear the same threshold.
if not (70 <= len(_town_pages) <= 85): bad.append(("towns", "count", len(_town_pages)))
for _st, _need in (
  ("sa", {"port-lincoln", "normanville", "cape-jervis", "yorketown", "wilpena-chalet", "marion-bay", "penneshaw"}),
  ("tas", {"coles-bay", "swansea", "bicheno", "st-helens", "dover", "derwent-bridge", "adventure-bay"}),
):
  _missing = _need - _town_by_state[_st]
  if _missing: bad.append((_st, "town pages", sorted(_missing)))
_feed_by = {}
for _c in feed["camps"]:
  _feed_by[_c["url"].replace("https://campconditions.au", "")] = _c
# Place points for every town page, so a camp can be checked against the nearest town.
# The closest camp on a page can sit nearer another chosen town when the 30 km circles overlap.
_town_points = {}
for _st, _slug, _fp in _town_pages:
  _blocks = _ld_blocks(open(_fp, encoding="utf-8").read())
  _place = next((b for b in _blocks if b.get("@type") == "Place"), {})
  _geo = _place.get("geo") or {}
  _town_points[f"/{_st}/near/{_slug}/"] = (_geo.get("latitude"), _geo.get("longitude"), _st)
for _st, _slug, _fp in _town_pages:
  _html = open(_fp, encoding="utf-8").read()
  _path = f"/{_st}/near/{_slug}/"
  if _path not in sm: bad.append((_path, "sitemap")); break
  if f"<h1>Camping near " not in _html or "in a straight line" not in _html or "not by road" not in _html:
    bad.append((_path, "wording")); break
  if _st in ("sa", "tas"):
    # Signup stays off until that state's digest exists. The page shows the
    # coming-soon line and does not post to /api/subscribe.
    _soon = "SA weekly email coming soon" if _st == "sa" else "Tas weekly email coming soon"
    if _soon not in _html or 'action="/api/subscribe"' in _html or 'name="states"' in _html:
      bad.append((_path, "signup held")); break
  elif f'name="states" value="{_st}" checked' not in _html:
    bad.append((_path, "signup")); break
  for _other in _town_states:
    if _other != _st and f'name="states" value="{_other}" checked' in _html:
      bad.append((_path, "other state ticked")); break
  _blocks = _ld_blocks(_html)
  _types = [b.get("@type") for b in _blocks]
  if "ItemList" not in _types or "BreadcrumbList" not in _types or "Place" not in _types:
    bad.append((_path, "json-ld", _types)); break
  _place = next(b for b in _blocks if b.get("@type") == "Place")
  _geo = _place.get("geo") or {}
  _item = next(b for b in _blocks if b.get("@type") == "ItemList")
  _camp_hrefs = re.findall(r'href="(/%s/camp/[^"]+/)"' % _st, _html)
  if len(_camp_hrefs) != len(set(_camp_hrefs)) or len(_camp_hrefs) != _item.get("numberOfItems") or len(_camp_hrefs) < _towns.MIN_CAMPS:
    bad.append((_path, "camp count", len(_camp_hrefs), _item.get("numberOfItems"))); break
  if str(len(_camp_hrefs)) not in _html.split("<h1>", 1)[-1][:400]:
    bad.append((_path, "count not in intro")); break
  _far = None
  for _href in _camp_hrefs:
    _camp = _feed_by.get(_href)
    if not _camp:
      bad.append((_path, "unknown camp", _href)); _far = True; break
    if _towns.km(_geo.get("latitude"), _geo.get("longitude"), _camp["lat"], _camp["lon"]) > _towns.RADIUS_KM + 0.05:
      bad.append((_path, "outside radius", _camp.get("name"))); _far = True; break
  if _far: break
  _sample = None
  for _href in _camp_hrefs:
    _camp = _feed_by[_href]
    _best, _best_d = None, None
    for _tpath, (_tlat, _tlon, _tst) in _town_points.items():
      if _tst != _st or _tlat is None or _tlon is None:
        continue
      _d = _towns.km(_camp["lat"], _camp["lon"], _tlat, _tlon)
      if _d <= _towns.RADIUS_KM + 0.05 and (_best is None or _d < _best_d):
        _best, _best_d = _tpath, _d
    if _best == _path:
      _sample = _href
      break
  if not _sample:
    bad.append((_path, "no listed camp has this town as its nearest")); break
  _camp_html = open(os.path.join(D, _sample.strip("/"), "index.html"), encoding="utf-8").read()
  if _path not in _camp_html:
    bad.append((_sample, "camp does not link to its town")); break
  if "Nearby camps" not in _camp_html or "in a straight line" not in _camp_html:
    bad.append((_sample, "nearby camps")); break
  _region = re.search(r'href="(/%s/[a-z0-9-]+/)"' % _st, _html.split("<h1>", 1)[0])
  if _region and _path not in open(os.path.join(D, _region.group(1).strip("/"), "index.html"), encoding="utf-8").read():
    bad.append((_path, "region does not link back")); break
if os.path.isdir(os.path.join(D, "act")) or os.path.isdir(os.path.join(D, "act", "near")):
  bad.append(("towns", "act built"))
# A dated notice carries its start and end so the browser can move upcoming,
# closed and ended without waiting for the next build. The build-time label stays.
_box = os.path.join(D, "sa", "camp", "box-flat-campground", "index.html")
if os.path.isfile(_box):
  _box_html = open(_box, encoding="utf-8").read()
  if 'data-notice-start="2026-11-11T06:00:00+10:30"' not in _box_html or 'data-notice-end="2026-11-18T06:00:00+10:30"' not in _box_html:
    bad.append(("box-flat", "notice instants"))
  if "function noticePhase" not in _box_html or "campApplyNoticePhase" not in _box_html:
    bad.append(("box-flat", "view-time script"))
  _built_phase = re.search(r'data-notice-built="(upcoming|closed)"', _box_html)
  _line = re.search(r'<p class="status-line"[^>]*>(.*?)</p>', _box_html)
  _badge = re.search(r'<span class="badge [^"]+"[^>]*>([^<]+)</span>', _line.group(1) if _line else "")
  if not _built_phase or not _badge or _badge.group(1) not in ("Upcoming closure", "Closed"):
    bad.append(("box-flat", "build label", _built_phase.group(1) if _built_phase else "", _badge.group(1) if _badge else ""))
  elif (_built_phase.group(1) == "upcoming" and _badge.group(1) != "Upcoming closure") or (_built_phase.group(1) == "closed" and _badge.group(1) != "Closed"):
    bad.append(("box-flat", "label disagrees with data-notice-built", _built_phase.group(1), _badge.group(1)))
_sa_home = os.path.join(D, "sa", "index.html")
if os.path.isfile(_sa_home) and "box-flat-campground" not in open(_sa_home, encoding="utf-8").read():
  bad.append(("/sa/", "notice windows"))
_tas_page = os.path.join(D, "tas", "index.html")
if os.path.isfile(_tas_page):
  _tas_html = open(_tas_page, encoding="utf-8").read()
  if "Park alerts checked " not in _tas_html or "Park alerts updated " in _tas_html:
    bad.append(("/tas/", "checked wording"))
  if "The feed was checked at " not in _tas_html or "last reviewed more than 2 days ago" not in _tas_html:
    bad.append(("/tas/", "newest alert wording"))
  if "may be out of date: the newest" in _tas_html:
    bad.append(("/tas/", "old stale wording"))
_parks_sa = (feed.get("sources") or {}).get("parks_sa") or {}
if _parks_sa.get("fetched") != "2026-11-10T17:00:00+10:30" or _parks_sa.get("snapshot") is not True:
  bad.append(("status.json", "parks_sa snapshot", _parks_sa.get("fetched"), _parks_sa.get("snapshot")))
if _parks_sa.get("fetched") and _parks_sa.get("fetched") == feed.get("generated"):
  bad.append(("status.json", "parks_sa fetched matches the build"))
if "saved snapshot" not in (open(os.path.join(D, "about-the-data", "index.html"), encoding="utf-8").read() if os.path.isfile(os.path.join(D, "about-the-data", "index.html")) else ""):
  bad.append(("/about-the-data/", "snapshot label"))
# A problem with one camp (for example an override that clashes with the feed) is a warning:
# that camp should not hold back every other update. Site-wide problems still block, and so do
# camp problems on more than CAMP_WARN_LIMIT camps, which point to a broken source or template.
CAMP_WARN_LIMIT = 25
_camp_keys = {c.get("slug") for c in feed["camps"] if c.get("slug")} | {c.get("name") for c in feed["camps"] if c.get("name")}
_camp_bad = [b for b in bad if isinstance(b, tuple) and b and isinstance(b[0], str) and b[0] in _camp_keys]
_camps_hit = {b[0] for b in _camp_bad}
if len(feed["camps"]) < 1000:
  bad.append(("status.json", f"only {len(feed['camps'])} camps"))
elif _camp_bad and len(_camps_hit) <= CAMP_WARN_LIMIT:
  bad = [b for b in bad if b not in _camp_bad]
  warnings.extend(("camp",) + tuple(b) for b in _camp_bad)
print(f"{n} pages, {ldn} JSON-LD blocks valid, {len(sm)} sitemap URLs, {len(home_pts)} map points, {len(bad)} broken, {len(warnings)} warnings")
for item in warnings: print("WARN", item)
for item in bad[:20]: print(item)
sys.exit(1 if bad else 0)
