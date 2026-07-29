// SwarmDeck Glance — Meta Ray-Ban Display webapp.
// Read-only glance at the SwarmDeck daemon's /glance endpoint (token-gated).
// D-pad / EMG navigation, no touch. No idle intervals.
(function () {
  'use strict';

  var CFG_KEY = 'swarmdeck_glance_cfg';
  var cfg = loadCfg();
  var data = { needs_you: [], econ: {}, sows: [] };
  var screenStack = ['home'];

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
        data = d; dot.className = 'ok'; renderHome(); renderNeeds(); renderSow();
      })
      .catch(function (e) {
        dot.className = 'err'; toast('Offline: ' + e.message);
      });
  }

  // ---- rendering ------------------------------------------------------------
  function cur() { return (data.econ && data.econ.currency === 'USD') ? '$' : '€'; }

  function renderHome() {
    var e = data.econ || {};
    setText('needs-num', e.needs_you != null ? String(e.needs_you) : '0');
    setText('stat-wip', (e.wip != null ? e.wip : '–') + '/' + (e.wip_limit != null ? e.wip_limit : '–'));
    setText('stat-head', e.headroom != null ? String(e.headroom) : '–');
    setText('stat-margin', e.margin != null ? cur() + Math.round(e.margin) : '–');
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
      var sub = c.client ? esc(c.client) : 'internal';
      el.innerHTML = '<div class="li-task">' + esc(c.task || '(untitled)') + '</div>'
        + '<div class="li-sub">' + sub + '</div>';
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
      'Status &nbsp;<b>needs you</b><br>'
      + 'Client &nbsp;<b>' + (c.client ? esc(c.client) : 'internal') + '</b>');
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
      case 'open-needs': showScreen('needs'); break;
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
