// HelmDeck Glance — Meta Ray-Ban Display webapp.
// Read-only glance at the HelmDeck daemon's /glance endpoint (token-gated).
// D-pad / EMG navigation, no touch. Polling is bounded and foreground-only
// (see startPoll/stopPoll) - "start timers on demand, stop them when not
// visible" (performance-guidelines.md) and never a FAST poll (glass-crud-
// harness's own factory rule, default 60s) - the lens still has no
// background execution (measured, ops/docs/glasses-reference.md §3.2), so this
// can only ever notice something new while the owner is actually looking.
(function () {
  'use strict';

  var CFG_KEY = 'helmdeck_glance_cfg';
  var cfg = loadCfg();
  var data = { needs_you: [], yours: [], econ: {}, sows: [] };
  var screenStack = ['home'];
  var fetchedAt = 0;          // ms, local clock: when THIS build last got data
  // diff detection for proactive notification. null = not yet baselined (no
  // notification on the very first load - every card would look "new").
  var knownIds = null;
  var unseenNew = 0;          // new needs_you cards since the owner last opened the list

  // ---- config (daemon URL + read-only token) --------------------------------
  function loadCfg() {
    try { return JSON.parse(localStorage.getItem(CFG_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function saveCfg(c) { localStorage.setItem(CFG_KEY, JSON.stringify(c)); }

  // SAME-ORIGIN is now the normal case. When this app is served BY the Glance
  // Worker (surfaces/glasses/worker), the API lives on the very origin the page came
  // from, so there is nothing to configure but the token. An explicit cfg.base
  // still means "talk to that daemon directly" - the LAN / desktop smoke test
  // path - and keeps working exactly as before.
  function apiBase() { return (cfg.base || '').replace(/\/+$/, ''); }
  function sameOrigin() {
    return !cfg.base && /^https?:$/.test(location.protocol);
  }
  function connected() {
    return Boolean(cfg.token) && (Boolean(cfg.base) || sameOrigin());
  }

  // The token travels in a HEADER when we are same-origin, and in the query
  // string only when talking to a daemon directly (the daemon reads ?token=
  // and nothing else - daemon/server.py:415-418). The distinction is not
  // pedantry: a URL with the token in it is written to Cloudflare's request
  // logs, a header is not. The Worker converts one to the other upstream.
  function glanceHeaders(extra) {
    var h = extra || {};
    if (sameOrigin() && cfg.token) h['X-Glance-Token'] = cfg.token;
    return h;
  }

  // ONE registered URL, carrying its own login - the trick from
  // glass-crud-harness/ops/tools/qr.py, where the QR encodes
  // ".../#glass&t=<password>" so nothing is ever typed on the glasses. The
  // fragment is never sent to a server, so the token does not reach the edge
  // on the way in; we lift it into localStorage and scrub it from the URL so
  // it does not linger in the address bar or a history entry.
  function adoptUrlToken() {
    var m = /[#&?]t=([^&]+)/.exec(location.hash || '') ||
            /[?&]t=([^&]+)/.exec(location.search || '');
    if (!m) return;
    try {
      cfg.token = decodeURIComponent(m[1]);
      saveCfg(cfg);
      history.replaceState(null, '', location.pathname);
    } catch (e) { /* a hostile hash is not worth breaking boot over */ }
  }

  // ---- data fetch -----------------------------------------------------------
  function glanceUrl() {
    if (!connected()) return null;
    if (sameOrigin()) return '/glance';        // token rides in the header
    return apiBase() + '/glance?token=' + encodeURIComponent(cfg.token);
  }
  function refresh() {
    var url = glanceUrl();
    var dot = document.getElementById('conn-dot');
    if (!url) { dot.className = 'header-meta'; showScreen('settings'); return; }
    dot.className = 'header-meta';
    fetch(url, { cache: 'no-store', headers: glanceHeaders() })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        // diff BEFORE overwriting `data` - new = present now, absent from the
        // ids this build already knew about. Only ids, never task text: a
        // proactive surface must stay glance-safe even before the owner has
        // looked (§4.4/§11.3 - a bystander glancing at the lens learns nothing).
        var prevIds = knownIds;
        var ids = {};
        (d.needs_you || []).forEach(function (c) { ids[c.id] = true; });
        var fresh = prevIds
          ? (d.needs_you || []).filter(function (c) { return !prevIds[c.id]; })
          : [];
        knownIds = ids;
        data = d; fetchedAt = Date.now();
        dot.className = 'ok'; renderHome(); renderNeeds(); renderSow();
        if (fresh.length) {
          unseenNew += fresh.length;
          updateBadge();
          // never mid-decision: a decide screen is an active input flow, and a
          // banner there would be pure distraction, not help.
          if (screenStack[screenStack.length - 1] !== 'decide') {
            notifyBanner(unseenNew);
            speakBanner(unseenNew);       // same count, spoken (mute-aware)
          }
        }
      })
      .catch(function (e) {
        // keep showing the last data, but STOP claiming it is current: a stale
        // "all clear" is the one thing this display must never imply
        dot.className = 'err'; renderHome(); toast('Offline: ' + e.message);
      });
  }

  // Freshness on the events that mean the owner is actually LOOKING: the app
  // coming back to the foreground, and opening the needs list. A glance that
  // silently shows hours-old state is worse than one that admits it is offline.
  function refreshIfStale(maxAgeMs) {
    if (!fetchedAt || Date.now() - fetchedAt > (maxAgeMs || 30000)) refresh();
  }

  // Proactive poll, ONLY while the lens is actually visible: a card newly
  // blocking while the owner sits on another screen would otherwise stay
  // invisible until his next navigation. Bounded (60s, matching the cited
  // factory default) and stopped the instant the page hides - the lens has no
  // background execution to fall back on, so an unbounded timer here would
  // just drain the battery for a screen nobody is looking at.
  var POLL_MS = 60000;
  var pollTimer = null;
  function startPoll() {
    if (pollTimer) return;
    pollTimer = setInterval(function () {
      if (!document.hidden && connected()) refresh();
    }, POLL_MS);
  }
  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { refreshIfStale(10000); startPoll(); }
    else stopPoll();
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
    if (!connected()) { toast('Not connected'); return; }
    var d = decide;
    toast('Sending…');
    fetch(apiBase() + '/glance/answer', {
      method: 'POST',
      headers: glanceHeaders({ 'Content-Type': 'application/json' }),
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

  // VOICE OUT. The lens has no speechSynthesis (measured on-device) but it DOES
  // play audio, so the daemon renders the answer and we play the clip.
  //
  // THE TRAP, already paid for in glass-crud-harness (app/index.html:809-812):
  // browsers refuse programmatic audio until a user gesture has played
  // something. The agent's reply arrives ~2s LATER, outside any gesture, so it
  // would be silently blocked. Fix: a muted play inside the opening tap unlocks
  // the element for every later programmatic call.
  var replyAudio = null;
  function audioUnlock() {
    try {
      if (!replyAudio) { replyAudio = new Audio(); replyAudio.preload = 'auto'; }
      replyAudio.muted = true;
      var pr = replyAudio.play();
      if (pr && pr.catch) pr.catch(function () {});
      replyAudio.pause();
      replyAudio.muted = false;
    } catch (e) { /* speech is an enhancement - never break the screen for it */ }
  }
  function speak(url) {
    if (!url) return;                    // offline / no edge-tts: text only
    try {
      if (!replyAudio) { replyAudio = new Audio(); replyAudio.preload = 'auto'; }
      replyAudio.muted = false;
      // The one place the token unavoidably rides in a URL: an <audio> element
      // cannot set a header. Same constraint glass-crud-harness hit with its
      // TTS proxy - and the reason that proxy had to be same-origin too.
      replyAudio.src = apiBase() + url;
      var pr = replyAudio.play();
      if (pr && pr.catch) pr.catch(function () { toast('Tap to hear'); });
    } catch (e) { /* silent */ }
  }
  function replay() { if (replyAudio && replyAudio.src) { replyAudio.currentTime = 0; speakAgain(); } }
  function speakAgain() {
    try { var pr = replyAudio.play(); if (pr && pr.catch) pr.catch(function () {}); }
    catch (e) { /* silent */ }
  }

  // ---- VOICE-OUT for blockers: mute + repeat --------------------------------
  // "Blocker werden vorgelesen" - the fresh-blocker banner (notifyBanner,
  // below) gets a spoken counterpart, reusing the exact mechanism already
  // shipped for talk replies (speak()/replyAudio above): the lens cannot
  // synthesise speech, so the daemon renders a clip and hands back a URL
  // (GET /glance/banner - routes_glance.py). GLANCE-SAFE by construction: the
  // daemon only ever speaks a COUNT, never a task name (SS4.4/SS11.3).
  //
  // Two controls, both required because a proactive (non-gesture) play can
  // be silently blocked by the browser's autoplay policy (undocumented for
  // this webview - ops/docs/glasses-reference.md SS6.4) and because a bystander
  // conversation can talk over a first attempt anyway:
  //   - MUTE: persisted in cfg, so a public/meeting setting stays quiet.
  //   - REPEAT: manual playback of the last-announced count - also the
  //     fallback when autoplay was blocked and nothing was heard at all.
  var voiceMuted = !!cfg.voiceMuted;
  var lastBlockerVoiceUrl = null;

  function bannerVoiceEndpoint(n) {
    if (!connected()) return null;
    if (sameOrigin()) return '/glance/banner?n=' + n;
    return apiBase() + '/glance/banner?n=' + n + '&token=' + encodeURIComponent(cfg.token);
  }
  function speakBanner(n) {
    if (voiceMuted) return;
    var url = bannerVoiceEndpoint(n);
    if (!url) return;
    fetch(url, { cache: 'no-store', headers: glanceHeaders() })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.voice) { lastBlockerVoiceUrl = j.voice; speak(j.voice); }
      })
      .catch(function () { /* speech is an enhancement - never break the banner for it */ });
  }
  function toggleVoiceMuted() {
    voiceMuted = !voiceMuted;
    cfg.voiceMuted = voiceMuted;
    saveCfg(cfg);
    updateVoiceToggleLabel();
    toast(voiceMuted ? 'Voice off' : 'Voice on');
  }
  function updateVoiceToggleLabel() {
    setText('voice-toggle-btn', voiceMuted ? 'Voice off' : 'Voice on');
  }
  function repeatBlockerVoice() {
    if (!lastBlockerVoiceUrl) { toast('Nothing to repeat'); return; }
    audioUnlock();                       // this tap IS a gesture - unlocks too
    // same clip already loaded (nothing spoken since) - just restart it;
    // otherwise (re)load it fresh, same as a first play
    if (replyAudio && replyAudio.src && replyAudio.src.indexOf(lastBlockerVoiceUrl) !== -1) {
      replay();
    } else {
      speak(lastBlockerVoiceUrl);
    }
  }

  function talkStart() {
    audioUnlock();                       // MUST be inside the gesture
    talk('Where do things stand, and what should I do next?');
  }

  function talk(message) {
    if (talkBusy) return;
    if (!connected()) { toast('Not connected'); return; }
    talkBusy = true;
    setText('talk-reply', 'Thinking…');
    setHTML('talk-options', '');
    setText('talk-meta', '');
    showScreen('talk');
    fetch(apiBase() + '/glance/talk', {
      method: 'POST',
      headers: glanceHeaders({ 'Content-Type': 'application/json' }),
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
    speak(j.voice);                      // the answer, out loud
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
      case 'open-needs':
        refreshIfStale(15000);
        unseenNew = 0; updateBadge();     // the owner looked - the badge's job is done
        showScreen('needs');
        break;
      case 'open-sow': showScreen('sow'); break;
      case 'open-settings': fillSettings(); showScreen('settings'); break;
      case 'open-detail': renderDetail(btn.getAttribute('data-id')); showScreen('detail'); break;
      case 'open-decide': openDecide(btn.getAttribute('data-id')); break;
      case 'pick': pick(btn.getAttribute('data-label')); break;
      case 'talk-start': talkStart(); break;
      case 'talk-retry': talkStart(); break;
      case 'talk-replay': replay(); break;
      // the tapped option IS the next message - that is the whole conversation
      case 'talk-pick': audioUnlock(); talk(btn.getAttribute('data-label')); break;
      case 'voice-toggle': toggleVoiceMuted(); break;
      case 'voice-repeat': repeatBlockerVoice(); break;
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

  // the small dot on "Needs you": persists (unlike the banner) until the
  // owner actually opens the list, so a missed banner is never the only shot.
  function updateBadge() {
    var b = document.getElementById('needs-badge');
    if (!b) return;
    b.classList.toggle('hidden', unseenNew <= 0);
  }

  // The proactive notification itself. Deliberately NOT the toast() function:
  // "toasts are for feedback only" (display-guidelines.md), and this is an
  // unprompted alert, not a response to something the owner did. Count only,
  // never a task name - a bystander glancing at the lens must read nothing
  // sensitive (§4.4/§11.3 glance-safe rule, applied to the display as well as
  // voice).
  var bannerTimer = null;
  function notifyBanner(n) {
    var el = document.getElementById('notify-banner');
    if (!el) return;
    var msg = n + ' new · needs you';
    el.textContent = msg;
    el.classList.remove('hidden');
    if (bannerTimer) clearTimeout(bannerTimer);
    // display-guidelines.md toast timing: 3.5s + 300ms/word, capped at 8s.
    var words = msg.split(/\s+/).length;
    var dur = Math.min(8000, 3500 + words * 300);
    bannerTimer = setTimeout(function () { el.classList.add('hidden'); }, dur);
  }

  // ---- boot -----------------------------------------------------------------
  // The registered URL may carry the token, in which case the glasses go
  // straight to the board and the Connect screen is never seen.
  adoptUrlToken();
  updateVoiceToggleLabel();
  if (!connected()) { fillSettings(); showScreen('settings', true); }
  else { showScreen('home', true); refresh(); if (!document.hidden) startPoll(); }
})();
