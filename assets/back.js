/* Camp page back link. Hidden unless the visitor came from another CampConditions page. */
(function (root) {
  "use strict";
  var NAMES_URL = "__BACK_NAMES_URL__";

  function prodHost(hostname) {
    var host = String(hostname || "").replace(/\.$/, "").toLowerCase();
    return host === "campconditions.au" || host === "www.campconditions.au";
  }

  function canonPath(pathname) {
    var path = pathname || "/";
    if (path.length > 1 && path.charAt(path.length - 1) === "/") path = path.slice(0, -1);
    return path || "/";
  }

  function isSameSite(ref, page) {
    if (prodHost(ref.hostname)) return true;
    return ref.origin === page.origin;
  }

  function lookupName(names, pathname) {
    if (!names || typeof names !== "object") return "";
    var path = pathname || "/";
    if (Object.prototype.hasOwnProperty.call(names, path) && typeof names[path] === "string") return names[path];
    if (path.length > 1 && path.charAt(path.length - 1) === "/") {
      var cut = path.slice(0, -1);
      if (Object.prototype.hasOwnProperty.call(names, cut) && typeof names[cut] === "string") return names[cut];
    } else {
      var slash = path + "/";
      if (Object.prototype.hasOwnProperty.call(names, slash) && typeof names[slash] === "string") return names[slash];
    }
    return "";
  }

  function labelFor(pathname, names) {
    if (canonPath(pathname) === "/") return "\u2190 Back to the map";
    var name = lookupName(names, pathname);
    if (!name) return "\u2190 Back";
    return "\u2190 Back to " + name;
  }

  function urlKey(value) {
    var u = new URL(value);
    return u.origin.toLowerCase() + canonPath(u.pathname) + u.search;
  }

  function resolveBack(opts) {
    opts = opts || {};
    var referrer = String(opts.referrer || "");
    var pageUrl = String(opts.pageUrl || "");
    if (!referrer || !pageUrl) return null;
    var ref, page;
    try {
      ref = new URL(referrer);
      page = new URL(pageUrl);
    } catch (err) {
      return null;
    }
    if (ref.protocol !== "http:" && ref.protocol !== "https:") return null;
    if (!isSameSite(ref, page)) return null;
    if (canonPath(ref.pathname) === canonPath(page.pathname)) return null;
    var length = Number(opts.historyLength);
    return {
      href: referrer,
      label: labelFor(ref.pathname, opts.names || {}),
      useHistory: length > 1,
      path: ref.pathname || "/"
    };
  }

  function mount(env) {
    try {
      env = env || {};
      var doc = env.document || (typeof document !== "undefined" ? document : null);
      if (!doc || !doc.getElementById) return;
      var el = doc.getElementById("camp-back");
      if (!el) return;
      var link = el.querySelector ? el.querySelector("a") : null;
      if (!link) return;
      var referrer = Object.prototype.hasOwnProperty.call(env, "referrer") ? env.referrer : (doc.referrer || "");
      var pageUrl = env.pageUrl || (typeof location !== "undefined" ? location.href : "");
      var historyLength = Object.prototype.hasOwnProperty.call(env, "historyLength")
        ? env.historyLength
        : (typeof history !== "undefined" ? history.length : 0);
      function liveHistory() {
        if (env.history) return env.history;
        return typeof history !== "undefined" ? history : null;
      }
      function liveReferrer() {
        if (Object.prototype.hasOwnProperty.call(env, "referrer")) return env.referrer || "";
        return (doc.referrer || "");
      }
      var preview = resolveBack({
        referrer: referrer,
        pageUrl: pageUrl,
        historyLength: historyLength,
        names: {}
      });
      if (!preview) return;
      function show(names) {
        try {
          var decision = resolveBack({
            referrer: referrer,
            pageUrl: pageUrl,
            historyLength: historyLength,
            names: names || {}
          });
          if (!decision) return;
          link.href = decision.href;
          link.textContent = decision.label;
          link.addEventListener("click", function (ev) {
            try {
              var hist = liveHistory();
              var refNow = liveReferrer();
              var hrefNow = link.href || decision.href;
              if (hist && hist.length > 1 && refNow && urlKey(refNow) === urlKey(hrefNow)) {
                if (ev && ev.preventDefault) ev.preventDefault();
                hist.back();
              }
            } catch (err) {}
          });
          el.hidden = false;
          if (el.removeAttribute) el.removeAttribute("hidden");
        } catch (err) {}
      }
      if (Object.prototype.hasOwnProperty.call(env, "names")) {
        show(env.names || {});
        return;
      }
      var url = env.namesUrl || NAMES_URL;
      var fetchFn = env.fetch || (typeof fetch === "function" ? fetch : null);
      if (!url || url.indexOf("BACK_NAMES_URL") !== -1 || typeof fetchFn !== "function") {
        show({});
        return;
      }
      return fetchFn(url, { credentials: "same-origin" }).then(function (res) {
        if (!res || !res.ok) throw new Error("names");
        return res.json();
      }).then(function (data) {
        show(data && typeof data === "object" && !Array.isArray(data) ? data : {});
      }).catch(function () { show({}); });
    } catch (err) {}
  }

  root.campBack = {
    resolveBack: resolveBack,
    labelFor: labelFor,
    canonPath: canonPath,
    isSameSite: isSameSite,
    urlKey: urlKey,
    mount: mount
  };

  try {
    if (typeof document !== "undefined" && document.getElementById && document.getElementById("camp-back")) mount();
  } catch (err) {}
})(typeof globalThis !== "undefined" ? globalThis : this);
