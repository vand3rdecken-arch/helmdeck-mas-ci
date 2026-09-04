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
    if (!document.hidden) { refreshIfStale(10000); startPoll(); startChatStream(); }
    else { stopPoll(); stopChatStream(); }
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

  // ---- THE CONVERSATION STREAM ---------------------------------------------
  // The lens's half of the glasses voice loop, and the reason this file changed.
  //
  // WHAT WAS BROKEN. The voice loop already worked and already went to Henry:
  // the phone's GlassVoiceService opens the glasses mic, hands the recognised
  // words to POST /glance/talk (the same copilot session the phone and the watch
  // use) and plays the answer back. But the LENS was not on that path at any
  // point. Nothing on the display said a microphone was open - the only status
  // surface was the service's Android notification, which is in the owner's
  // pocket - and the words about to be sent in his name were never shown, so he
  // could not catch a misheard sentence before it became a message.
  //
  // WHAT THIS IS NOT. Not a second channel. The daemon publishes the state of
  // the ONE conversation (routes_glance.glance_chat + spine/ops/glassturn.py)
  // and this reads it. Nothing here holds a lens-local transcript, so the
  // glasses cannot drift from what the phone and the watch see.
  //
  // A HANGING GET, NOT A POLL. /glance/chat blocks until the transcript or the
  // turn state actually moves (~20s otherwise). That is the same shape the watch
  // was moved to on 2026-08-30, and it is what lets a listening indicator feel
  // live without violating the factory rule this file's own header cites: never
  // ship a fast poll. An idle lens holds ONE request and transmits nothing.
  var chatMsgs = [];
  var turn = { state: 'idle', text: '', mic: '', seq: 0, age: null };
  // null = "I have nothing yet", which is NOT the same as 0 and is sent as an
  // OMITTED parameter. On a freshly started daemon both server counters are
  // genuinely zero, so claiming c=0 would mean "I am up to date" and the request
  // would correctly block for its full 20s - leaving a first-time lens on an
  // empty conversation with no explanation. Omitting them says the true thing
  // and is answered at once.
  var chatCursor = null, glassCursor = null;
  var chatOn = false, chatCtl = null, chatBackoff = 3000;
  var lastTurnSeq = -1;
  var lastOptions = [];      // the tappable half of Henry's most recent reply

  function chatStreamUrl() {
    if (!connected()) return null;
    var q = (chatCursor === null || glassCursor === null)
      ? '' : ('c=' + chatCursor + '&g=' + glassCursor);
    if (sameOrigin()) {                             // token rides in the header
      return q ? ('/glance/chat?' + q) : '/glance/chat';
    }
    return apiBase() + '/glance/chat?' + (q ? q + '&' : '')
      + 'token=' + encodeURIComponent(cfg.token);
  }

  function startChatStream() {
    if (chatOn) return;
    chatOn = true; chatBackoff = 3000;
    chatLoop();
  }
  function stopChatStream() {
    chatOn = false;
    // Abort where we can, so the held request dies with the screen rather than
    // lingering for the rest of its 20s window. AbortController is not something
    // this webview's support was ever measured for (the reference doc is blunt
    // that undocumented means unknown here, not available), so its absence is a
    // caught non-event: chatOn=false already stops the loop re-arming, and the
    // late reply is discarded by the guard in chatLoop.
    try { if (chatCtl) chatCtl.abort(); } catch (e) { /* not supported - fine */ }
    chatCtl = null;
  }

  function chatLoop() {
    if (!chatOn) return;
    var url = chatStreamUrl();
    if (!url) { chatOn = false; return; }
    var ctl = null;
    try { ctl = new AbortController(); } catch (e) { ctl = null; }
    chatCtl = ctl;
    var opts = { cache: 'no-store', headers: glanceHeaders() };
    if (ctl) opts.signal = ctl.signal;
    fetch(url, opts)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (j) {
        if (!chatOn) return;             // hidden while in flight - drop it
        chatBackoff = 3000;
        applyChat(j);
        chatLoop();                      // re-arm immediately
      })
      .catch(function () {
        if (!chatOn) return;
        // Capped exponential backoff, and the CURSORS ARE NOT RESET: whatever
        // moved while we were away is reported on the next success, so the
        // reconnect IS the catch-up path and no timer is needed to find it.
        setTimeout(chatLoop, chatBackoff);
        chatBackoff = Math.min(chatBackoff * 2, 30000);
      });
  }

  function applyChat(j) {
    chatCursor = typeof j.c === 'number' ? j.c : chatCursor;
    glassCursor = typeof j.g === 'number' ? j.g : glassCursor;
    if (j.messages) chatMsgs = j.messages;
    if (j.turn) {
      turn = j.turn;
      // THE OPTIONS COME FROM THE TURN, so a turn the LENS did not start still
      // gets them. On a spoken turn the POST to /glance/talk is made by
      // GlassVoiceService on the phone and this app never sees that response -
      // deriving options from it alone left every voice turn with nothing to
      // tap, on the one surface that has no keyboard. Found by driving the real
      // thing, not by reading it.
      //
      // renderTalk still sets these on the local D-pad path so a tap feels
      // instant even if the stream is mid-backoff. The two cannot disagree:
      // both are the same _glance_question(q) object computed once per turn on
      // the daemon.
      // The options belong to the answer that produced them, so any other state
      // clears them: leaving the previous turn's choices tappable while a new
      // sentence is being spoken is how the owner answers a question that is no
      // longer on the table. (A stale snapshot arriving mid-turn cannot show
      // through - renderOptions draws nothing while talkBusy.)
      var qs = (turn.question && turn.question.questions) || [];
      lastOptions = qs.length ? (qs[0].options || []) : [];
    }
    renderTurnbar();
    if (screenStack[screenStack.length - 1] === 'talk') renderChat();
    maybeOpenTalk();
  }

  // BRING THE SCREEN TO THE CONVERSATION. The owner speaks without touching the
  // lens, so if the display stayed on the home screen the listening indicator
  // would be on a screen nobody navigated to - which is the defect this card was
  // written about, merely moved one level down.
  //
  // Only on a state the owner is part of (a mic opened, his words landed, Henry
  // is working) and only when the seq actually moved, so a re-render never
  // steals the screen. `decide` and `settings` are never interrupted: both are
  // active input flows the owner started deliberately, and the existing banner
  // code already refuses to talk over `decide` for the same reason.
  // `draft` belongs here above all the others: it is the one state that is
  // WAITING ON HIM. Words he just spoke are held, unsent, until he accepts or
  // rejects them - so a draft that failed to pull the screen would be a question
  // asked into a void, and the mic owner would sit on a long-poll until it timed
  // out and dropped the sentence.
  var TALK_STATES = { listening: 1, draft: 1, heard: 1, thinking: 1 };
  function maybeOpenTalk() {
    if (turn.seq === lastTurnSeq) return;
    lastTurnSeq = turn.seq;
    if (!TALK_STATES[turn.state]) return;
    var here = screenStack[screenStack.length - 1];
    if (here === 'talk' || here === 'decide' || here === 'settings') return;
    showScreen('talk');                  // renders the conversation on arrival
  }

  var TURN_LABEL = {
    idle: 'Ready',
    listening: 'Listening',
    // Phrased as the QUESTION it is, not as a status ("Draft"). The bar is the
    // only thing above the sentence, so it has to say what the two buttons under
    // it are for.
    draft: 'Send this?',
    heard: 'Heard you',
    thinking: 'Henry is thinking',
    answered: 'Answered',
    failed: 'No answer - ask again'
  };
  // A transient state this old is not credible any more - the mic owner is a
  // separate process on a separate device and can die without ever reporting
  // that it stopped. We do NOT invent the transition it failed to send (that
  // would be exactly the assumed state the repo forbids); we show the age and
  // let the owner see for himself that nothing has moved in a while.
  var TURN_STALE_S = 90;

  function renderTurnbar() {
    var bar = document.getElementById('turnbar');
    if (!bar) return;
    var st = turn.state || 'idle';
    bar.className = 'turnbar ' + st;
    var label = TURN_LABEL[st] || st;
    if (TALK_STATES[st] && typeof turn.age === 'number' && turn.age > TURN_STALE_S) {
      label += ' (' + Math.round(turn.age / 60) + ' min)';
    }
    setText('turn-label', label);
    // WHICH microphone. Only while one is actually open: naming a mic next to
    // "Answered" would suggest something is still listening when nothing is.
    var mic = document.getElementById('turn-mic');
    if (!mic) {
      mic = document.createElement('span');
      mic.id = 'turn-mic'; mic.className = 'turn-mic';
      bar.appendChild(mic);
    }
    mic.textContent = (st === 'listening' && turn.mic) ? (turn.mic + ' mic') : '';
  }

  // The pending line: what he said, before the transcript carries it.
  //
  // copilot only writes the log at TURN END, so between `heard` and `answered`
  // the owner's own sentence exists nowhere but in the turn state - and that gap
  // is precisely the moment he needs to read it, while it is still being acted
  // on in his name. The dedupe matters for a real race: the hanging GET can wake
  // on the CHAT cursor the instant the log is written, while the turn state has
  // not yet moved off `thinking`, and without this the same sentence would be on
  // screen twice.
  function pendingText() {
    if (!turn.text) return '';
    if (turn.state !== 'listening' && turn.state !== 'draft' &&
        turn.state !== 'heard' && turn.state !== 'thinking') return '';
    for (var i = chatMsgs.length - 1; i >= 0; i--) {
      if (chatMsgs[i].mine) return chatMsgs[i].text === turn.text ? '' : turn.text;
    }
    return turn.text;
  }

  function renderChat() {
    var box = document.getElementById('talk-chat');
    if (!box) return;
    var html = '';
    chatMsgs.forEach(function (m) {
      html += '<div class="msg' + (m.mine ? ' mine' : '') + '">'
        + (m.label ? '<div class="msg-label">' + esc(m.label) + '</div>'
                   : '<div class="msg-who">' + (m.mine ? 'You' : 'Henry') + '</div>')
        + '<div class="msg-body">' + esc(m.text) + '</div></div>';
    });
    var pend = pendingText();
    if (pend) {
      // A DRAFT IS MARKED, and that is not decoration. Every other pending line
      // is already on its way to Henry; this one is not sent and will be thrown
      // away if he ignores it. Rendering the two identically would be the lens
      // telling him the same thing about two opposite situations.
      var draft = turn.state === 'draft';
      html += '<div class="msg mine pending' + (draft ? ' draft' : '') + '">'
        + '<div class="msg-who">' + (draft ? 'You said' : 'You') + '</div>'
        + '<div class="msg-body">' + esc(pend) + '</div></div>';
    }
    if (!html) {
      html = '<div class="empty">Say something, or tap Ask.</div>';
    }
    box.innerHTML = html;
    renderOptions();
    // follow the conversation - the newest line is the one he is reading
    var sc = document.getElementById('talk-scroll');
    if (sc) sc.scrollTop = sc.scrollHeight;
  }

  function renderOptions() {
    var list = document.getElementById('talk-options');
    if (!list) return;
    list.innerHTML = '';
    // A DRAFT REPLACES THE OPTION LIST ENTIRELY. The old options belong to the
    // previous answer, and showing them beside an unsent sentence would let one
    // tap answer a question while another question is still on screen. Two
    // choices, nothing else - this is the confirm step and it is the only thing
    // the owner can do here.
    if (turn.state === 'draft') {
      [['talk-send', 'Send', 'ask Henry this'],
       ['talk-redo', 'Speak again', 'discard and re-record']
      ].forEach(function (o) {
        var el = document.createElement('button');
        el.className = 'list-item focusable' + (o[0] === 'talk-send' ? ' primary' : '');
        el.setAttribute('data-action', o[0]);
        el.innerHTML = '<div class="li-task">' + o[1] + '</div>'
          + '<div class="li-sub">' + o[2] + '</div>';
        list.appendChild(el);
      });
      return;
    }
    // Nothing to offer while a turn is in flight: the options belong to the
    // PREVIOUS answer, and leaving them tappable invites a second question on
    // top of the one being answered.
    if (turn.state === 'thinking' || turn.state === 'heard' || talkBusy) return;
    if (!lastOptions.length) return;
    lastOptions.forEach(function (o) {
      var el = document.createElement('button');
      el.className = 'list-item focusable';
      el.setAttribute('data-action', 'talk-pick');
      el.setAttribute('data-label', o.label);
      el.innerHTML = '<div class="li-task">' + esc(o.label) + '</div>'
        + (o.description ? '<div class="li-sub">' + esc(o.description) + '</div>' : '');
      list.appendChild(el);
    });
  }

  function talkStart() {
    audioUnlock();                       // MUST be inside the gesture
    talk('Where do things stand, and what should I do next?');
  }

  /**
   * The owner's verdict on a draft (owner, 2026-09-04: "user kann bestaetigen
   * oder loeschen und neu sprechen").
   *
   * DELIBERATELY NOT talk(). The lens does not send the sentence - it releases
   * the PHONE to send it, and the phone is already blocked on /glance/decision
   * waiting to hear which way. Posting to /glance/talk from here as well would
   * ask Henry the same question twice, once from each device.
   *
   * So there is no optimistic turn state either: the mic owner drives what
   * happens next and the stream reports it a beat later. Faking `heard` here
   * would be this surface claiming an observation it did not make - and if the
   * phone had meanwhile timed out and dropped the words, the claim would be
   * false. `talkBusy` alone stops a double tap.
   */
  function decideDraft(decision) {
    if (talkBusy) return;
    if (!connected()) { toast('Not connected'); return; }
    audioUnlock();                       // the answer plays after Send
    talkBusy = true;
    renderOptions();                     // buttons away - the tap registered
    fetch(apiBase() + '/glance/decide', {
      method: 'POST',
      headers: glanceHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ token: cfg.token, decision: decision, seq: turn.seq })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
        return j;
      });
    }).then(function () {
      talkBusy = false;
      // Nothing to render: the next real state (heard/listening) arrives on the
      // stream from the party that actually did it.
    }).catch(function (e) {
      talkBusy = false;
      // 409 is the stale-draft case and it has a specific, non-alarming
      // meaning: the phone gave up on this one, or a newer draft replaced it.
      // Say that rather than "error", or the owner re-taps a dead button.
      setText('talk-meta', /409|no live draft/.test(String(e.message || e))
        ? 'that draft expired - speak again'
        : String(e.message || e));
      document.getElementById('talk-meta').className = 'header-meta warn';
      renderOptions();
      focusFirst();
    });
  }

  function talk(message) {
    if (talkBusy) return;
    if (!connected()) { toast('Not connected'); return; }
    talkBusy = true;
    setText('talk-meta', '');
    // OPTIMISTIC, and immediately corrected. The daemon sets `heard` the moment
    // this request lands, so the stream confirms it within a beat - but a D-pad
    // tap must feel answered NOW, and on a 600x600 lens the alternative is a
    // screen that looks frozen for the length of a round trip.
    turn = { state: 'heard', text: message, mic: turn.mic, seq: turn.seq, age: 0 };
    lastOptions = [];
    lastTurnSeq = turn.seq;              // this one is ours - do not re-open on it
    if (screenStack[screenStack.length - 1] !== 'talk') showScreen('talk');
    else { renderTurnbar(); renderChat(); }
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
      turn = { state: 'failed', text: '', mic: turn.mic, seq: turn.seq, age: 0 };
      renderTurnbar();
      setText('talk-meta', String(e.message || e));
      document.getElementById('talk-meta').className = 'header-meta warn';
      // a failed turn must still leave a way forward, or the lens is a wall
      lastOptions = [];
      renderChat();
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
    speak(j.voice);                      // the answer, out loud
    // The agent is told this surface is advisory. If it tried to change the
    // board anyway, SAY so - the owner must never believe a change landed.
    var refused = (j.refused && j.refused.length) ? j.refused : null;
    setText('talk-meta', refused ? 'not run: ' + refused.join(', ') : '');
    document.getElementById('talk-meta').className =
      'header-meta' + (refused ? ' warn' : '');
    var qs = (j.question && j.question.questions) || [];
    lastOptions = qs.length ? (qs[0].options || []) : [];
    // The REPLY itself is not painted from here. It arrives through the stream
    // as part of the one transcript, which is what keeps this surface from
    // holding its own private copy of the conversation - the drift the shared
    // copilot.history() read exists to prevent. The turn state moves to
    // `answered` on the same event.
    turn = { state: 'answered', text: '', mic: turn.mic, seq: turn.seq, age: 0,
             question: j.question || null };
    lastTurnSeq = turn.seq;
    renderTurnbar();
    renderChat();
    if (!lastOptions.length) {
      // the agent ignored its brief - do not strand the owner
      var list = document.getElementById('talk-options');
      var b = document.createElement('button');
      b.className = 'list-item focusable';
      b.setAttribute('data-action', 'talk-retry');
      b.innerHTML = '<div class="li-task">Ask again</div>'
        + '<div class="li-sub">no options came back</div>';
      list.appendChild(b);
    }
    focusFirst();
  }

  // ---- screen management ----------------------------------------------------
  function showScreen(id, isBack) {
    var screens = document.querySelectorAll('.screen');
    for (var i = 0; i < screens.length; i++) screens[i].classList.add('hidden');
    var el = document.getElementById(id);
    if (el) el.classList.remove('hidden');
    if (!isBack) { if (screenStack[screenStack.length - 1] !== id) screenStack.push(id); }
    // The conversation is LIVE, so arriving at it - forwards or by going back -
    // must paint what is true now, not whatever was last drawn. Doing it here
    // rather than at each call site is what stops one navigation path (Escape
    // out of a card, say) from landing on a stale screen while the others are
    // fine, which is the kind of gap that only shows up on the device.
    if (id === 'talk') { renderTurnbar(); renderChat(); }
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
      // the confirm step: release the phone to send, or send it back to the mic
      case 'talk-send': decideDraft('send'); break;
      case 'talk-redo': decideDraft('redo'); break;
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
    // First run reaches the board through THIS path, never through boot - so
    // without starting it here the conversation stream would stay dead until the
    // lens was hidden and shown again, and the listening indicator with it.
    if (!document.hidden) startChatStream();
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
  else {
    showScreen('home', true); refresh();
    // The conversation stream runs from ANY screen, not just the talk one: the
    // owner speaks without touching the lens, so the display has to be able to
    // notice a mic opening while he is looking at the board. It is one hanging
    // request that transmits nothing until something moves - strictly less
    // traffic than the 60s board poll beside it.
    if (!document.hidden) { startPoll(); startChatStream(); }
  }
})();
