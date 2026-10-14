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
print(f"{n} pages, {ldn} JSON-LD blocks valid, {len(sm)} sitemap URLs, {len(bad)} broken"); [print(b) for b in bad[:20]]; sys.exit(1 if bad else 0)
