// HelmDeck Glance — Meta Ray-Ban Display webapp.
// Read-only glance at the HelmDeck daemon's /glance endpoint (token-gated).
// D-pad / EMG navigation, no touch. No idle intervals.
(function () {
  'use strict';

  var CFG_KEY = 'helmdeck_glance_cfg';
  var cfg = loadCfg();
  var data = { needs_you: [], yours: [], econ: {}, sows: [] };
  var screenStack = ['home'];
  var fetchedAt = 0;          // ms, local clock: when THIS build last got data

  // ---- config (daemon URL + read-only token) --------------------------------
  function loadCfg() {
    try { return JSON.parse(localStorage.getItem(CFG_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function saveCfg(c) { localStorage.setItem(CFG_KEY, JSON.stringify(c)); }

  // ---- data fetch -----------------------------------------------------------
  function glanceUrl() {
    if (!cfg.base || !cfg.token) return null;
    var base = cfg.base.replace(/\/+$/, '');
    return base + '/glance?token=' + encodeURIComponent(cfg.token);
  }
  function refresh() {
    var url = glanceUrl();
    var dot = document.getElementById('conn-dot');
    if (!url) { dot.className = 'header-meta'; showScreen('settings'); return; }
    dot.className = 'header-meta';
    fetch(url, { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        data = d; fetchedAt = Date.now();
        dot.className = 'ok'; renderHome(); renderNeeds(); renderSow();
      })
      .catch(function (e) {
        // keep showing the last data, but STOP claiming it is current: a stale
        // "all clear" is the one thing this display must never imply
        dot.className = 'err'; renderHome(); toast('Offline: ' + e.message);
      });
  }

  // Freshness without a timer. The platform guidance is "no idle intervals"
  // (battery on a head-worn display), so refresh on the events that mean the
  // owner is actually LOOKING: the app coming back to the foreground, and
  // opening the needs list. A glance that silently shows hours-old state is
  // worse than one that admits it is offline.
  function refreshIfStale(maxAgeMs) {
    if (!fetchedAt || Date.now() - fetchedAt > (maxAgeMs || 30000)) refresh();
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) refreshIfStale(10000);
  });

  function ageText() {
    if (!fetchedAt) return '';
    var s = Math.round((Date.now() - fetchedAt) / 1000);
    if (s < 45) return 'just now';
    if (s < 5400) return Math.round(s / 60) + ' min ago';
    return Math.round(s / 3600) + ' h ago';
  }

  // ---- rendering ------------------------------------------------------------
  function cur() { return (data.econ && data.econ.currency === 'USD') ? '$' : '€'; }

  function renderHome() {
    var e = data.econ || {};
    setText('needs-num', e.needs_you != null ? String(e.needs_you) : '0');
    setText('stat-wip', (e.wip != null ? e.wip : '–') + '/' + (e.wip_limit != null ? e.wip_limit : '–'));
    setText('stat-head', e.headroom != null ? String(e.headroom) : '–');
    setText('stat-margin', e.margin != null ? cur() + Math.round(e.margin) : '–');
    // unstarted work only the owner can begin - a SEPARATE line, never folded
    // into the big number, so a backlog can't drown out a red gate
    var yours = (e.yours != null) ? e.yours : (data.yours || []).length;
    var age = ageText();
    var sub = yours ? ('+' + yours + ' only you can start') : '';
    if (age) sub = sub ? (sub + ' · ' + age) : age;
    setText('needs-age', sub);
  }

  // WHY the card is blocked on you (daemon: sessions.BLOCKER_REASONS). Older
  // daemons send no `reason`, so fall back to the boolean they do send.
  var REASON = {
    question: 'asks you', delivered: 'ready for you', review: 'accept it',
    gate: 'gate red', conflict: 'cannot land', failed: 'failed'
  };
  function reasonOf(c) {
    return c.reason || (c.asking ? 'question' : 'delivered');
  }
  function reasonLabel(c) { return REASON[reasonOf(c)] || 'needs you'; }
  function isBad(c) {
    var r = reasonOf(c);
    return r === 'gate' || r === 'conflict' || r === 'failed';
  }

  function renderNeeds() {
    var list = document.getElementById('needs-list');
    var items = data.needs_you || [];
    setText('needs-count', items.length ? String(items.length) : '');
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<div class="empty">Nothing needs you.<br>All clear ✓</div>';
      return;
    }
    items.forEach(function (c) {
      var el = document.createElement('button');
      el.className = 'list-item focusable';
      el.setAttribute('data-action', 'open-detail');
      el.setAttribute('data-id', c.id);
      var sub = reasonLabel(c) + ' · ' + (c.client ? c.client : 'internal');
      el.innerHTML = '<div class="li-task">' + esc(c.task || '(untitled)') + '</div>'
        + '<div class="li-sub' + (isBad(c) ? ' neg' : '') + '">' + esc(sub) + '</div>';
      list.appendChild(el);
    });
    renderYours(list);
  }

  // Cards the machine will NEVER start (mode human/teach/cowork). Below the
  // blocked ones and visibly quieter: they are work, not alarms.
  function renderYours(list) {
    var mine = data.yours || [];
    if (!mine.length) return;
    var hd = document.createElement('div');
    hd.className = 'group-label';
    hd.textContent = 'Only you can start';
    list.appendChild(hd);
    mine.forEach(function (c) {
      var el = document.createElement('div');
      el.className = 'list-item muted';
      el.innerHTML = '<div class="li-task">' + esc(c.task || '(untitled)') + '</div>'
        + '<div class="li-sub">' + esc((c.mode || 'manual') + ' · '
          + (c.client ? c.client : 'internal')) + '</div>';
      list.appendChild(el);
    });
  }

  function renderSow() {
    var list = document.getElementById('sow-list');
    var items = data.sows || [];
    list.innerHTML = '';
    if (!items.length) { list.innerHTML = '<div class="empty">No SoWs yet.</div>'; return; }
    items.forEach(function (s) {
      var el = document.createElement('div');
      el.className = 'list-item';
      var cls = s.margin >= 0 ? 'pos' : 'neg';
      el.innerHTML = '<span class="li-margin ' + cls + '">' + cur() + Math.round(s.margin) + '</span>'
        + '<div class="li-task">' + esc(s.name || '(SoW)') + '</div>';
      list.appendChild(el);
    });
  }

  function renderDetail(id) {
    var c = (data.needs_you || []).filter(function (x) { return x.id === id; })[0];
    if (!c) { setText('detail-task', 'Card not found'); setHTML('detail-meta', ''); return; }
    setText('detail-task', c.task || '(untitled)');
    setHTML('detail-meta',
      'Blocked &nbsp;<b' + (isBad(c) ? ' class="neg"' : '') + '>' + esc(reasonLabel(c)) + '</b><br>'
      + 'Client &nbsp;<b>' + (c.client ? esc(c.client) : 'internal') + '</b>'
      + (c.detail ? '<span class="detail-why">' + esc(c.detail) + '</span>' : ''));
  }

  // ---- screen management ----------------------------------------------------
  function showScreen(id, isBack) {
    var screens = document.querySelectorAll('.screen');
    for (var i = 0; i < screens.length; i++) screens[i].classList.add('hidden');
    var el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
    if (!isBack) { if (screenStack[screenStack.length - 1] !== id) screenStack.push(id); }
    focusFirst();
  }
  function goBack() {
    if (screenStack.length > 1) { screenStack.pop(); }
    showScreen(screenStack[screenStack.length - 1], true);
  }

  // ---- D-pad focus navigation ----------------------------------------------
  function visibleFocusables() {
    var cur = document.querySelector('.screen:not(.hidden)');
    if (!cur) return [];
    return Array.prototype.slice.call(cur.querySelectorAll('.focusable'))
      .filter(function (el) { return el.offsetParent !== null; });
  }
  function focusFirst() {
    var f = visibleFocusables();
    if (f.length) f[0].focus();
  }
  document.addEventListener('keydown', function (e) {
    var f = visibleFocusables();
    if (e.key === 'Escape') { e.preventDefault(); goBack(); return; }
    if (!f.length) return;
    var idx = f.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      e.preventDefault(); f[idx < f.length - 1 ? idx + 1 : 0].focus();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      e.preventDefault(); f[idx > 0 ? idx - 1 : f.length - 1].focus();
    } else if (e.key === 'Enter') {
      if (document.activeElement && document.activeElement.getAttribute('data-action')) {
        e.preventDefault(); dispatch(document.activeElement);
      }
    }
  });

  // ---- action dispatch ------------------------------------------------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('[data-action]') : null;
    if (btn) { e.preventDefault(); dispatch(btn); }
  });
  function dispatch(btn) {
    var a = btn.getAttribute('data-action');
    switch (a) {
      case 'back': goBack(); break;
      case 'refresh': refresh(); toast('Refreshing…'); break;
      case 'open-needs': refreshIfStale(15000); showScreen('needs'); break;
      case 'open-sow': showScreen('sow'); break;
      case 'open-settings': fillSettings(); showScreen('settings'); break;
      case 'open-detail': renderDetail(btn.getAttribute('data-id')); showScreen('detail'); break;
      case 'save-settings': doSaveSettings(); break;
    }
  }

  function fillSettings() {
    document.getElementById('cfg-base').value = cfg.base || '';
    document.getElementById('cfg-token').value = cfg.token || '';
  }
  function doSaveSettings() {
    cfg.base = document.getElementById('cfg-base').value.trim();
    cfg.token = document.getElementById('cfg-token').value.trim();
    saveCfg(cfg);
    toast('Saved');
    screenStack = ['home']; showScreen('home', true);
    refresh();
  }

  // ---- helpers --------------------------------------------------------------
  function setText(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; }
  function setHTML(id, v) { var el = document.getElementById(id); if (el) el.innerHTML = v; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var toastTimer = null;
  function toast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg; t.classList.remove('hidden');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.add('hidden'); }, 1800);
  }

  // ---- boot -----------------------------------------------------------------
  if (!cfg.base || !cfg.token) { fillSettings(); showScreen('settings', true); }
  else { showScreen('home', true); refresh(); }
})();
