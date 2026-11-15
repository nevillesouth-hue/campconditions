// One share-button handler. Static pages inline SHARE_CLICK_SOURCE (scripts/build.py
// reads this export). The confirm success page inlines the same source, so Copy link
// is not a second implementation.
// Phones call navigator.share first, with nothing awaited before it. If that API is
// missing, or it fails for a reason other than the person dismissing the sheet, the
// link is copied. AbortError (the person closed the sheet) does not copy.
export const SHARE_CLICK_SOURCE = `(function () {
  // One delegated handler: the phone-width button (#share-page-m) sits in the
  // freshness bar below this script, so it must not be bound per element.
  function flash(btn, message) {
    var label = btn.querySelector(".share-label");
    if (!label) return;
    var prev = label.textContent;
    label.textContent = message;
    btn.classList.add("share-done");
    setTimeout(function () {
      label.textContent = prev;
      btn.classList.remove("share-done");
    }, 1600);
  }
  function legacyCopy(url, done) {
    var area = document.createElement("textarea");
    area.value = url;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    document.body.removeChild(area);
    if (ok) done();
    else window.prompt("Copy this link", url);
  }
  function copyLink(url, btn) {
    var done = function () { flash(btn, "Link copied"); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(function () { legacyCopy(url, done); });
      return;
    }
    legacyCopy(url, done);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest(".share-btn") : null;
    if (!btn) return;
    var canon = document.querySelector('link[rel="canonical"]');
    var url = (canon && canon.href) ? canon.href : String(location.href || "").split("#")[0];
    var payload = { title: document.title || "CampConditions.au", url: url };
    if (navigator.share) {
      navigator.share(payload).catch(function (err) {
        if (err && err.name === "AbortError") return;
        copyLink(url, btn);
      });
      return;
    }
    copyLink(url, btn);
  });
})();`;

// Public homepage. The confirm URL carries the sign-up token, so Copy link must
// not fall through to location.href. The canonical link is what the handler copies.
export const SHARE_PAGE_URL = "https://campconditions.au/";
export const SHARE_TEXT = "I use CampConditions for free closure and fire-ban updates on Aussie camps each Thursday: https://campconditions.au/";

export function confirmShareExtras() {
  const encoded = encodeURIComponent(SHARE_TEXT);
  const facebook = "https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fcampconditions.au%2F";
  const whatsapp = "https://wa.me/?text=" + encoded;
  const sms = "sms:?&body=" + encoded;
  const after = `<section class="share-step" aria-label="Share CampConditions"><h2>Share CampConditions</h2><p class="share-text">${SHARE_TEXT}</p><p class="share-row"><a class="share-link" href="${facebook}" target="_blank" rel="noopener noreferrer">Facebook</a><a class="share-link" href="${whatsapp}" target="_blank" rel="noopener noreferrer">WhatsApp</a><a class="share-link" href="${sms.replace(/&/g, "&amp;")}">SMS</a><button type="button" class="share-btn" id="share-copy"><span class="share-label">Copy link</span></button></p></section><script>${SHARE_CLICK_SOURCE}</script>`;
  return { head: `<link rel="canonical" href="${SHARE_PAGE_URL}">`, after };
}
