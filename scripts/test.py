import os,re,json,sys,html
D=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"dist");bad=[];n=0;ldn=0
for r,_,fs in os.walk(D):
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
  for f in fs:
    if not f.endswith((".html", ".json", ".txt", ".js")): continue
    blob = open(os.path.join(r, f), encoding="utf-8").read().lower()
    for needle in banned:
      if needle.lower() in blob:
        bad.append((os.path.join(r, f)[len(D):], needle))
for key in ("nearby_emergency", "fire_danger_ratings", "emergency_data_last_received"):
  if key in feed: bad.append(("status.json", key))
if any("nearby_emergency" in c for c in feed["camps"]): bad.append(("status.json", "camp nearby_emergency"))
if "emv.vic.gov.au" in json.dumps(feed).lower() or "osom" in json.dumps(feed).lower(): bad.append(("status.json", "vicemergency data"))
ext_a = re.compile(r'<a\b[^>]*\bhref="https?://[^"]*"[^>]*>')
for r, _, fs in os.walk(D):
  for f in fs:
    if not f.endswith(".html"): continue
    p = os.path.join(r, f)
    for tag in ext_a.findall(open(p, encoding="utf-8").read()):
      if 'target="_blank"' not in tag or 'rel="noopener noreferrer"' not in tag:
        bad.append((p[len(D):], "external tab"))
        break
if 'rel="noopener noreferrer"' not in mj: bad.append(("map.js", "osm link"))
print(f"{n} pages, {ldn} JSON-LD blocks valid, {len(sm)} sitemap URLs, {len(home_pts)} map points, {len(bad)} broken"); [print(b) for b in bad[:20]]; sys.exit(1 if bad else 0)
