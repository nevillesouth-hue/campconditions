#!/usr/bin/env python3
"""Upcoming, closed or ended from a notice's start and end.

The build still writes the label. That label is what a browser without
JavaScript shows. Pages also carry the start and end instants, and a short
script recomputes the label from the clock when the page is opened, so a
closure does not wait for the next build to flip.
"""
import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

ZONES = {
    "sa": "Australia/Adelaide",
    "tas": "Australia/Hobart",
    "qld": "Australia/Brisbane",
    "nsw": "Australia/Melbourne",
    "vic": "Australia/Melbourne",
}
LABELS = {
    "upcoming": "Upcoming closure",
    "closed": "Closed",
    "ended": "Closure ended",
}

# Kept in step with phase_at(). The page script is this function plus the DOM updates.
PHASE_JS = r"""
function noticePhase(start, end, now) {
  var s = start ? Date.parse(start) : NaN;
  var z = end ? Date.parse(end) : NaN;
  if (isNaN(s) && isNaN(z)) return "";
  if (!isNaN(z) && now >= z) return "ended";
  if (isNaN(s)) return "";
  if (now < s) return "upcoming";
  return "closed";
}
""".strip()

NOTICE_JS = r"""<script>
""" + PHASE_JS + r"""
(function () {
  var LABELS = {upcoming: "Upcoming closure", closed: "Closed", ended: "Closure ended"};
  var CLASS = {upcoming: "check", closed: "closed", ended: "check"};
  function bucket(phase) { return phase === "closed" ? "closed" : "check"; }
  function paint(node, next) {
    if (!node || !LABELS[next]) return;
    var badge = node.classList && node.classList.contains("badge") ? node : (node.querySelector ? node.querySelector(".badge") : null);
    if (badge) {
      badge.className = "badge " + CLASS[next];
      badge.textContent = LABELS[next];
    }
    var strong = node.querySelector ? node.querySelector("strong") : null;
    if (strong) {
      var text = strong.textContent || "";
      var match = /^(Upcoming closure|Closed|Closure ended)([.:])(.*)$/.exec(text);
      if (match) strong.textContent = LABELS[next] + match[2] + match[3];
    }
    if (node.id === "camp-closure" && next === "closed" && node.classList.contains("box")) {
      node.classList.remove("box");
      node.classList.add("warn");
    }
    var row = node.closest ? node.closest("tr[data-slug]") : null;
    if (row) {
      row.setAttribute("data-status", next === "closed" ? "closed" : "check");
      var note = row.querySelector(".camp-note");
      if (note && /^(Upcoming closure|Closed|Closure ended)$/.test(note.textContent || "")) note.textContent = LABELS[next];
    }
    if (node.closest && node.closest(".status-line")) {
      var title = document.title;
      Object.keys(LABELS).forEach(function (key) {
        title = title.split("\u2014 " + LABELS[key]).join("\u2014 " + LABELS[next]);
      });
      document.title = title;
    }
  }
  function baseNumber(el, attr) {
    if (!el.hasAttribute(attr)) {
      var n = parseInt(el.textContent, 10);
      if (isNaN(n)) return null;
      el.setAttribute(attr, String(n));
    }
    return parseInt(el.getAttribute(attr), 10);
  }
  function apply() {
    var now = Date.now();
    var changed = {};
    document.querySelectorAll("[data-notice-built]").forEach(function (node) {
      var built = node.getAttribute("data-notice-built") || "";
      var next = noticePhase(node.getAttribute("data-notice-start"), node.getAttribute("data-notice-end"), now);
      if (!next || next === built) return;
      paint(node, next);
      var slug = "";
      var camp = node.closest ? node.closest("[data-camp]") : null;
      if (camp) slug = camp.getAttribute("data-camp") || "";
      if (!slug) {
        var row = node.closest ? node.closest("tr[data-slug]") : null;
        slug = row ? (row.getAttribute("data-slug") || "") : "";
      }
      if (slug) changed[slug] = {status: next === "closed" ? "closed" : "check"};
    });
    var raw = document.getElementById("notice-windows");
    var rows = [];
    if (raw) { try { rows = JSON.parse(raw.textContent) || []; } catch (err) { rows = []; } }
    var closedDelta = 0, checkDelta = 0, regions = {};
    rows.forEach(function (row) {
      var next = noticePhase(row.start, row.end, now);
      if (!next || !row.built || next === row.built) return;
      if (bucket(next) !== bucket(row.built)) {
        var dir = next === "closed" ? 1 : -1;
        closedDelta += dir;
        checkDelta -= dir;
        var reg = regions[row.region] || (regions[row.region] = {closed: 0, check: 0});
        reg.closed += dir;
        reg.check -= dir;
      }
      if (row.slug) changed[row.slug] = {status: next === "closed" ? "closed" : "check"};
    });
    var closedEl = document.getElementById("count-closed");
    var checkEl = document.getElementById("count-check");
    if (rows.length && closedEl) {
      var baseClosed = baseNumber(closedEl, "data-base");
      if (baseClosed !== null) closedEl.textContent = (baseClosed + closedDelta) + " closed";
    }
    if (rows.length && checkEl) {
      var baseCheck = baseNumber(checkEl, "data-base");
      if (baseCheck !== null) checkEl.textContent = (baseCheck + checkDelta) + " to check";
    }
    if (rows.length) {
      document.querySelectorAll("[data-region]").forEach(function (card) {
        var el = card.querySelector(".region-counts");
        if (!el) return;
        if (!el.hasAttribute("data-base-closed")) {
          var match = /^(\d+) campgrounds · (\d+) closed · (\d+) to check$/.exec(el.textContent || "");
          if (!match) return;
          el.setAttribute("data-base-n", match[1]);
          el.setAttribute("data-base-closed", match[2]);
          el.setAttribute("data-base-check", match[3]);
        }
        var delta = regions[card.getAttribute("data-region")] || {closed: 0, check: 0};
        el.textContent = el.getAttribute("data-base-n") + " campgrounds · " +
          (parseInt(el.getAttribute("data-base-closed"), 10) + delta.closed) + " closed · " +
          (parseInt(el.getAttribute("data-base-check"), 10) + delta.check) + " to check";
      });
    }
    var weekClosed = document.getElementById("weekend-closed");
    var weekUp = document.getElementById("weekend-upcoming");
    if (weekClosed && weekUp) {
      var seenHref = {};
      var upToClosed = 0, closedLeft = 0, upLeft = 0;
      document.querySelectorAll(".weekend-list [data-notice-built]").forEach(function (node) {
        var item = node.closest ? node.closest("li") : null;
        var link = item ? item.querySelector("a") : null;
        var href = link ? link.getAttribute("href") || "" : "";
        if (!href || seenHref[href]) return;
        seenHref[href] = 1;
        var built = node.getAttribute("data-notice-built") || "";
        var next = noticePhase(node.getAttribute("data-notice-start"), node.getAttribute("data-notice-end"), now);
        if (!next || next === built) return;
        if (built === "upcoming" && next === "closed") upToClosed += 1;
        if (built === "closed" && next !== "closed") closedLeft += 1;
        if (built === "upcoming" && next !== "upcoming") upLeft += 1;
      });
      var baseW = baseNumber(weekClosed, "data-base");
      var baseU = baseNumber(weekUp, "data-base");
      if (baseW !== null) weekClosed.textContent = String(baseW + upToClosed - closedLeft);
      if (baseU !== null) weekUp.textContent = String(baseU - upLeft);
    }
    var pending = window.__campStatusPending || {};
    Object.keys(changed).forEach(function (slug) {
      pending[slug] = Object.assign({}, pending[slug] || {}, changed[slug]);
    });
    window.__campStatusPending = pending;
    if (window.campApplyStatus) window.campApplyStatus(changed);
  }
  window.campApplyNoticePhase = apply;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();
</script>
"""


def phase_at(start, end, now):
    """upcoming before the start, ended at the end, otherwise closed.

    An end with no start can still finish. A start with no end stays closed
    once it has begun. A missing window returns None.
    """
    if now is None or (start is None and end is None):
        return None
    if end is not None and now >= end:
        return "ended"
    if start is None:
        return None
    if now < start:
        return "upcoming"
    return "closed"


def _zone(camp):
    return ZoneInfo(ZONES.get(camp.get("state_slug") or "", "Australia/Melbourne"))


def _parse_instant(value, zone):
    if not value:
        return None
    try:
        when = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    return when


def _clock_instant(day, clock, zone, date_only_next_midnight=False):
    try:
        when = dt.date.fromisoformat(str(day or "")[:10])
    except ValueError:
        return None
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(clock or ""))
    if match:
        return dt.datetime.combine(when, dt.time(int(match.group(1)), int(match.group(2))), tzinfo=zone)
    if date_only_next_midnight:
        when = when + dt.timedelta(days=1)
    return dt.datetime.combine(when, dt.time(0, 0), tzinfo=zone)


def _record_bounds(camp, record):
    """Start and end instants. A Tasmania date-only end covers that calendar day."""
    zone = _zone(camp)
    start = _parse_instant(record.get("start_instant"), zone)
    if start is None and record.get("start"):
        start = _clock_instant(record.get("start"), record.get("start_time"), zone, False)
    end = _parse_instant(record.get("reopen_instant") or record.get("end_instant"), zone)
    if end is None:
        day = record.get("reopen") or record.get("end")
        clock = record.get("reopen_time") if record.get("reopen") else (record.get("end_time") or record.get("reopen_time"))
        tas = (camp.get("state_slug") == "tas" or camp.get("source") == "tas") and day and not clock
        if day:
            end = _clock_instant(day, clock, zone, tas)
    return start, end


def notice_window(camp):
    """(start, end, built) for a single dated notice, or None.

    Weekly patterns and outdated records are left to the build. Their label
    is not a single start and end.
    """
    closure = camp.get("closure") or {}
    upcoming = camp.get("upcoming_closure") or {}
    if closure.get("closed_days") or upcoming.get("closed_days") or closure.get("outdated"):
        return None
    if camp.get("status") == "closed" and closure:
        record, built = closure, "closed"
    elif upcoming.get("start") or upcoming.get("start_instant"):
        record, built = upcoming, "upcoming"
    else:
        return None
    start, end = _record_bounds(camp, record)
    if start is None and end is None:
        return None
    return start, end, built


def notice_attr(camp):
    """Attribute string, with a leading space, or empty."""
    window = notice_window(camp)
    if not window:
        return ""
    start, end, built = window
    bits = [f'data-notice-built="{built}"']
    if start is not None:
        bits.append(f'data-notice-start="{start.isoformat()}"')
    if end is not None:
        bits.append(f'data-notice-end="{end.isoformat()}"')
    return " " + " ".join(bits)


def windows_tag(camps):
    """JSON of dated notices so a state page can correct counts for camps it does not list."""
    rows = []
    for camp in camps or []:
        window = notice_window(camp)
        if not window:
            continue
        start, end, built = window
        rows.append({
            "slug": camp.get("slug") or "",
            "region": camp.get("region") or "",
            "built": built,
            "start": start.isoformat() if start is not None else "",
            "end": end.isoformat() if end is not None else "",
        })
    if not rows:
        return ""
    payload = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="notice-windows">{payload}</script>'
