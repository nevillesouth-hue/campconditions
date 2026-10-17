function esc(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export function sitePage(title, bodyHtml, status = 200) {
  const html = `<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>
:root{--g:#2f5d3a;--o:#c2571a;--bg:#fbfaf6}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;background:var(--bg)}
header{background:var(--g);color:#fff;padding:.7rem 1rem}header a{color:#fff;text-decoration:none;font-weight:700;font-size:1.2rem;display:inline-flex;align-items:center;gap:.45rem}header img{width:44px;height:44px;display:block}
main{max-width:40rem;margin:0 auto;padding:1.25rem}h1{font-size:1.7rem;line-height:1.25}
.notice{margin:1rem 0;padding:1.15rem 1.2rem;border-radius:10px;font-size:1.35rem;font-weight:700;line-height:1.35;background:#e7f2e4;color:#1e4620;border:3px solid var(--g)}
a{color:var(--g)}
</style></head><body>
<header><a href="/"><img src="/assets/brand/logo-160.png" width="160" height="160" alt="CampConditions.au logo">CampConditions.au</a></header>
<main><h1>${esc(title)}</h1><div class="notice">${bodyHtml}</div>
<p><a href="/">Back to CampConditions.au</a> · <a href="/privacy/">Privacy</a> · <a href="/unsubscribe/">Unsubscribe</a></p></main>
</body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}
