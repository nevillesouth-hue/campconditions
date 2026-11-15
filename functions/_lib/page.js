function esc(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export function sitePage(title, bodyHtml, status = 200, extra) {
  const head = extra && extra.head ? extra.head : "";
  const after = extra && extra.after ? extra.after : "";
  const html = `<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
${head}<style>
:root{--g:#2f5d3a;--o:#c2571a;--bg:#fbfaf6}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:var(--bg)}
header{background:var(--g);color:#fff;padding:.7rem 1rem}header a{color:#fff;text-decoration:none;font-weight:700;font-size:1.2rem;display:inline-flex;align-items:center;gap:.45rem}header img{width:44px;height:44px;display:block}
main{max-width:40rem;margin:0 auto;padding:1.25rem}h1{font-size:1.7rem;line-height:1.25}
.notice{margin:1rem 0;padding:1.15rem 1.2rem;border-radius:10px;font-size:1.35rem;font-weight:700;line-height:1.35;background:#e7f2e4;color:#1e4620;border:3px solid var(--g)}
a{color:var(--g)}
.share-step{margin:0 0 1.25rem}.share-step h2{font-size:1.15rem;line-height:1.3;margin:0 0 .35rem}
.share-text{margin:.35rem 0 .7rem;font-size:.95rem;font-weight:400;color:#222}
.share-row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:0}
.share-link,.share-step .share-btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;padding:.4rem .8rem;border-radius:6px;border:1px solid var(--g);background:#fff;color:var(--g);font:inherit;font-weight:700;font-size:.95rem;line-height:1.2;text-decoration:none;cursor:pointer;box-shadow:none;margin:0}
.share-step .share-btn{margin-left:0}
.share-link:focus-visible,.share-step .share-btn:focus-visible{outline:3px solid var(--g);outline-offset:2px}
</style></head><body>
<header><a href="/"><img src="/assets/brand/logo-160.png" width="160" height="160" alt="CampConditions.au logo">CampConditions.au</a></header>
<main><h1>${esc(title)}</h1><div class="notice">${bodyHtml}</div>
${after}<p><a href="/">Back to CampConditions.au</a> · <a href="/privacy/">Privacy</a> · <a href="/unsubscribe/">Unsubscribe</a></p></main>
</body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}
