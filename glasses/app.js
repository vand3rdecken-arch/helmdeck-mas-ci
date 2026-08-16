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
      // A card that is ASKING opens the decision directly. Routing it through
      // the detail screen first would cost an extra tap on a surface where
      // "one card fills the lens" - and the question text IS the context.
      var canDecide = !!(c.question && (c.question.questions || []).length);
      el.setAttribute('data-action', canDecide ? 'open-decide' : 'open-detail');
      el.setAttribute('data-id', c.id);
      var sub = (canDecide ? 'tap to decide' : reasonLabel(c))
        + ' · ' + (c.client ? c.client : 'internal');
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

  function cardById(id) {
    return (data.needs_you || []).filter(function (x) { return x.id === id; })[0];
  }

  function renderDetail(id) {
    var c = cardById(id);
    var nav = document.getElementById('detail-nav');
    if (!c) {
      setText('detail-task', 'Card not found'); setHTML('detail-meta', '');
      nav.classList.add('hidden'); return;
    }
    setText('detail-task', c.task || '(untitled)');
    setHTML('detail-meta',
      'Blocked &nbsp;<b' + (isBad(c) ? ' class="neg"' : '') + '>' + esc(reasonLabel(c)) + '</b><br>'
      + 'Client &nbsp;<b>' + (c.client ? esc(c.client) : 'internal') + '</b>'
      + (c.detail ? '<span class="detail-why">' + esc(c.detail) + '</span>' : ''));
    // The Decide button exists only when there is something to decide - a
    // button that opens an empty screen is worse than no button.
    if (c.question && (c.question.questions || []).length) {
      nav.classList.remove('hidden');
      nav.querySelector('[data-action="open-decide"]').setAttribute('data-id', c.id);
    } else {
      nav.classList.add('hidden');
    }
  }

  // ---- GLASS MODE: decide ---------------------------------------------------
  // The whole point of the lens: the worker asked, and you answer WITHOUT
  // reaching for the phone. Options only - the webview has no keyboard and no
  // dictation (measured on-device), so every turn must be tappable.
  var decide = null;   // {cardId, qid, questions, idx, answers}

  function openDecide(id) {
    var c = cardById(id);
    if (!c || !c.question || !(c.question.questions || []).length) {
      toast('Nothing to decide'); return;
    }
    decide = { cardId: id, qid: c.question.id, questions: c.question.questions,
               idx: 0, answers: {} };
    renderDecide();
    showScreen('decide');
  }

  function renderDecide() {
    if (!decide) return;
    var q = decide.questions[decide.idx];
    var n = decide.questions.length;
    var nopt = (q.options || []).length;
    setText('decide-head', q.header || 'Decide');
    // Say how many options there ARE. With the protocol's maximum of six the
    // last one sits below the fold on first paint - the D-pad scrolls to it
    // (measured: every option reaches fullyVisible), but a glance display must
    // never leave the owner unaware a choice exists at all.
    setText('decide-step',
      (n > 1 ? (decide.idx + 1) + '/' + n + ' · ' : '') + nopt + ' options');
    setText('decide-q', q.question || '');
    var list = document.getElementById('decide-options');
    list.innerHTML = '';
    (q.options || []).forEach(function (o) {
      var el = document.createElement('button');
      el.className = 'list-item focusable';
      el.setAttribute('data-action', 'pick');
      el.setAttribute('data-label', o.label);
      el.innerHTML = '<div class="li-task">' + esc(o.label) + '</div>'
        + (o.description ? '<div class="li-sub">' + esc(o.description) + '</div>' : '');
      list.appendChild(el);
    });
    focusFirst();
  }

  function pick(label) {
    if (!decide) return;
    var q = decide.questions[decide.idx];
    decide.answers[q.header] = label;
    if (decide.idx < decide.questions.length - 1) {
      decide.idx += 1; renderDecide(); return;   // multi-question: next one
    }
    submitDecision();
  }

  function submitDecision() {
    if (!cfg.base || !cfg.token) { toast('Not connected'); return; }
    var d = decide;
    toast('Sending…');
    fetch(cfg.base.replace(/\/+$/, '') + '/glance/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: cfg.token, id: d.cardId,
                             request_id: d.qid, answers: d.answers })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      });
    }).then(function () {
      decide = null;
      toast('Answered ✓');
      // the card is now RUNNING again, so the board this lens shows is stale by
      // definition - re-read it rather than leave the answered card sitting in
      // the needs-you list
      screenStack = ['home']; showScreen('home', true); refresh();
    }).catch(function (e) {
      toast(String(e.message || e));
    });
  }

  // ---- GLASS MODE: talk to the board agent ---------------------------------
  // The half /glance cannot be. /glance is a database read - it shows WHAT is
  // stuck. This asks the agent that can reason about it. Selection-only: the
  // agent is briefed to end every turn with options, and a turn that arrives
  // without them is shown as a dead end rather than silently swallowed.
  var talkBusy = false;

  function talkStart() { talk('Where do things stand, and what should I do next?'); }

  function talk(message) {
    if (talkBusy) return;
    if (!cfg.base || !cfg.token) { toast('Not connected'); return; }
    talkBusy = true;
    setText('talk-reply', 'Thinking…');
    setHTML('talk-options', '');
    setText('talk-meta', '');
    showScreen('talk');
    fetch(cfg.base.replace(/\/+$/, '') + '/glance/talk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: cfg.token, message: message })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      });
    }).then(function (j) {
      talkBusy = false;
      renderTalk(j);
    }).catch(function (e) {
      talkBusy = false;
      setText('talk-reply', String(e.message || e));
      setHTML('talk-options', '');
      // a failed turn must still leave a way forward, or the lens is a wall
      var list = document.getElementById('talk-options');
      var b = document.createElement('button');
      b.className = 'list-item focusable';
      b.setAttribute('data-action', 'talk-retry');
      b.innerHTML = '<div class="li-task">Try again</div>';
      list.appendChild(b);
      focusFirst();
    });
  }

  function renderTalk(j) {
    setText('talk-reply', j.reply || '(no reply)');
    // The agent is told this surface is advisory. If it tried to change the
    // board anyway, SAY so - the owner must never believe a change landed.
    var refused = (j.refused && j.refused.length) ? j.refused : null;
    setText('talk-meta', refused ? 'not run: ' + refused.join(', ') : '');
    document.getElementById('talk-meta').className =
      'header-meta' + (refused ? ' warn' : '');
    var list = document.getElementById('talk-options');
    list.innerHTML = '';
    var qs = (j.question && j.question.questions) || [];
    var opts = qs.length ? (qs[0].options || []) : [];
    if (!opts.length) {
      // the agent ignored its brief - do not strand the owner
      var b = document.createElement('button');
      b.className = 'list-item focusable';
      b.setAttribute('data-action', 'talk-retry');
      b.innerHTML = '<div class="li-task">Ask again</div>'
        + '<div class="li-sub">no options came back</div>';
      list.appendChild(b);
      focusFirst();
      return;
    }
    opts.forEach(function (o) {
      var el = document.createElement('button');
      el.className = 'list-item focusable';
      el.setAttribute('data-action', 'talk-pick');
      el.setAttribute('data-label', o.label);
      el.innerHTML = '<div class="li-task">' + esc(o.label) + '</div>'
        + (o.description ? '<div class="li-sub">' + esc(o.description) + '</div>' : '');
      list.appendChild(el);
    });
    focusFirst();
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
      case 'open-decide': openDecide(btn.getAttribute('data-id')); break;
      case 'pick': pick(btn.getAttribute('data-label')); break;
      case 'talk-start': talkStart(); break;
      case 'talk-retry': talkStart(); break;
      // the tapped option IS the next message - that is the whole conversation
      case 'talk-pick': talk(btn.getAttribute('data-label')); break;
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
