/* ELNOC ops-console interactions. Vanilla JS only (offline-safe, NFR-04). */
(function () {
  // WAT clock in topbar
  function tick() {
    var el = document.getElementById('wat-clock');
    if (!el) return;
    try {
      var fmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Africa/Lagos', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
      el.textContent = fmt.format(new Date()) + ' WAT';
    } catch (e) { el.textContent = new Date().toUTCString(); }
  }
  setInterval(tick, 1000); tick();

  // mark active nav
  var path = location.pathname;
  document.querySelectorAll('.nav-item').forEach(function (a) {
    if (a.getAttribute('href') === path) a.classList.add('active');
  });

  // toast helper
  window.elnocToast = function (msg) {
    var box = document.getElementById('toast');
    if (!box) return;
    var d = document.createElement('div');
    d.className = 'toast'; d.textContent = msg;
    box.appendChild(d);
    setTimeout(function () { d.remove(); }, 4200);
  };

  // copy helper for phoenix / whatsapp outputs
  window.elnocCopy = function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    var txt = el.innerText || el.value || '';
    if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () { window.elnocToast('Copied — paste it over.'); });
    else { var ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch (e) {} ta.remove(); }
  };

  // ---- global keyboard shortcuts (work on every app page) ----
  //   Ctrl+Shift+L → Quick Log   (mirrors the OS-level desktop pane client)
  //   Alt+Shift+L  → Quick Log   (fallback: some drivers swallow Ctrl+Shift)
  //   Ctrl+K or /  → focus Quick Log search
  // None of these fire while typing except the combos (safe: they type no text).
  function inField(el) {
    return el && /INPUT|TEXTAREA|SELECT/.test(el.tagName);
  }
  document.addEventListener('keydown', function (e) {
    var k = (e.key || '').toLowerCase();
    // Ctrl+Shift+L — check e.code too ('KeyL'), some layouts report odd e.key
    if ((e.ctrlKey && e.shiftKey && (k === 'l' || e.code === 'KeyL')) ||
        (e.altKey && e.shiftKey && (k === 'l' || e.code === 'KeyL'))) {
      e.preventDefault();
      if (location.pathname !== '/quicklog') location.href = '/quicklog';
      else { var q0 = document.getElementById('q'); if (q0) q0.focus(); }
      return;
    }
    // Ctrl+Shift+M — MyShift pane (P3-5 desktop pane tab)
    if (e.ctrlKey && e.shiftKey && (k === 'm' || e.code === 'KeyM')) {
      e.preventDefault();
      if (location.pathname !== '/myshift') location.href = '/myshift';
      else { /* already on myshift — could focus the note input */ var n = document.getElementById('shiftNotes'); if (n) n.focus(); }
      return;
    }
    // Ctrl+K → palette search (also a fallback when Ctrl+Shift is captured)
    if ((e.ctrlKey && !e.altKey && k === 'k') || (k === '/' && !inField(document.activeElement))) {
      var q = document.getElementById('q');
      if (q) { e.preventDefault(); q.focus(); }
    }
  });

  // ---- command-deck liveliness: count-up + 45s stat refresh ----
  // Numbers are server-rendered first (readable with JS off); JS then
  // animates them and keeps them fresh without a reload. Quiet on failure.
  function countUp(el, to) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = to; return;
    }
    var from = 0, t0 = null, dur = 700;
    function step(t) {
      if (!t0) t0 = t;
      var p = Math.min(1, (t - t0) / dur);
      el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var to = parseInt(el.getAttribute('data-count'), 10) || 0;
    el.textContent = '0';
    countUp(el, to);
  });
  var deck = document.getElementById('deck-stats');
  if (deck && deck.getAttribute('data-poll')) {
    var url = deck.getAttribute('data-poll');
    setInterval(function () {
      fetch(url, { credentials: 'same-origin' }).then(function (r) {
        if (!r.ok) throw 0;
        return r.json();
      }).then(function (j) {
        document.querySelectorAll('[data-stat]').forEach(function (el) {
          var k = el.getAttribute('data-stat');
          if (!(k in j)) return;
          if (String(el.textContent) !== String(j[k])) {
            el.textContent = j[k];
            el.classList.remove('flash');
            void el.offsetWidth; /* restart the animation */
            el.classList.add('flash');
          }
        });
        var note = document.querySelector('[data-stat-note]');
        if (note) note.textContent = 'live · refreshed just now';
      }).catch(function () { /* stay quiet; next poll retries */ });
    }, 45000);
  }
})();
