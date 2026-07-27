/* ============================================================
   site.js — command palette (⌘K) + SCM grant-lifecycle demo
   No dependencies. View-source friendly on purpose.
   ============================================================ */
(function () {
  'use strict';
  var BASE = location.pathname.indexOf('/blog/') !== -1 ? '../' : '';

  /* ============================================================
     1. Command palette
     ============================================================ */
  var ITEMS = [
    { k: 'nav', label: 'Projects', hint: 'Home section', go: BASE + 'index.html#projects' },
    { k: 'nav', label: 'Resume', hint: 'Home section', go: BASE + 'index.html#resume' },
    { k: 'nav', label: 'Services & consulting', hint: 'Home section', go: BASE + 'index.html#services' },
    { k: 'nav', label: 'Run the architecture (interactive demo)', hint: 'Home section', go: BASE + 'index.html#system' },
    { k: 'nav', label: 'Blog', hint: 'All posts', go: BASE + 'blog.html' },
    { k: 'nav', label: 'Overwhelming Studios (games)', hint: 'UE5 titles', go: BASE + 'games.html' },
    { k: 'post', label: 'Your Agent Shouldn’t Have a Password', hint: 'SCM deep-dive', go: BASE + 'blog/scm-agent-governance.html' },
    { k: 'post', label: 'Deterministic Facts, Probabilistic Prose', hint: 'Tracewell', go: BASE + 'blog/tracewell-trust-boundaries.html' },
    { k: 'post', label: 'Deleting a Race Condition by Construction', hint: 'UoP Library', go: BASE + 'blog/uop-library-case-study.html' },
    { k: 'post', label: 'Determinism Is a Feature', hint: 'VortexeAI', go: BASE + 'blog/vortexeai-deterministic-orchestration.html' },
    { k: 'post', label: 'Shipping a 3D Configurator in a Week', hint: 'AetherisVis', go: BASE + 'blog/aetherisvis-3d-configurator.html' },
    { k: 'link', label: 'Tracewell — live deploy', hint: 'external', go: 'https://blok-agent-insight.vercel.app/', ext: true },
    { k: 'link', label: 'VortexeAI — live site', hint: 'external', go: 'https://vortexeai.com/', ext: true },
    { k: 'link', label: 'SPX configurator — live (AetherisVis)', hint: 'external', go: 'https://www.spxgymdesign.com/configurator', ext: true },
    { k: 'link', label: 'SenseUI — landing page', hint: 'external', go: 'https://sense-ui.vercel.app/', ext: true },
    { k: 'nav', label: 'Isoscapes (procedural worlds)', hint: 'Games page', go: BASE + 'games.html#isoscapes' },
    { k: 'link', label: 'GitHub — T-98', hint: 'external', go: 'https://github.com/T-98', ext: true },
    { k: 'link', label: 'LinkedIn — divyansh-khare', hint: 'external', go: 'https://www.linkedin.com/in/divyansh-khare/', ext: true },
    { k: 'act', label: 'Email me', hint: 'dkhare1998@gmail.com', go: 'mailto:dkhare1998@gmail.com' },
    { k: 'act', label: 'Copy email address', hint: 'to clipboard', act: 'copy-email' },
    { k: 'act', label: 'Download resume (PDF)', hint: 'DivyanshKhareResume.pdf', go: BASE + 'DivyanshKhareResume.pdf' },
    { k: 'egg', label: 'sudo hire divyansh', hint: 'permission granted', act: 'sudo' }
  ];

  var pal, palInput, palList, palOpen = false, sel = 0, filtered = ITEMS;

  function buildPalette() {
    pal = document.createElement('div');
    pal.className = 'pal-overlay';
    pal.innerHTML =
      '<div class="pal" role="dialog" aria-modal="true" aria-label="Command palette">' +
      '<div class="pal-head"><input class="pal-input" type="text" placeholder="Type a command or search…" ' +
      'aria-label="Search commands" autocomplete="off" spellcheck="false" />' +
      '<kbd class="pal-esc">esc</kbd></div>' +
      '<ul class="pal-list" role="listbox"></ul>' +
      '<div class="pal-foot"><span><kbd>↑↓</kbd> navigate</span><span><kbd>↵</kbd> select</span><span><kbd>esc</kbd> close</span></div>' +
      '</div>';
    document.body.appendChild(pal);
    palInput = pal.querySelector('.pal-input');
    palList = pal.querySelector('.pal-list');
    pal.addEventListener('mousedown', function (e) { if (e.target === pal) closePal(); });
    palInput.addEventListener('input', function () { filter(palInput.value); });
    palInput.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') { e.preventDefault(); run(filtered[sel]); }
      else if (e.key === 'Escape') { closePal(); }
    });
  }

  function score(item, q) {
    var l = item.label.toLowerCase(), i = l.indexOf(q);
    if (i !== -1) return 100 - i;                 // substring: earlier is better
    var qi = 0;                                   // subsequence fallback
    for (var ci = 0; ci < l.length && qi < q.length; ci++) if (l[ci] === q[qi]) qi++;
    return qi === q.length ? 10 : -1;
  }

  function filter(q) {
    q = q.trim().toLowerCase();
    filtered = !q ? ITEMS.slice() : ITEMS
      .map(function (it) { return { it: it, s: score(it, q) }; })
      .filter(function (r) { return r.s >= 0; })
      .sort(function (a, b) { return b.s - a.s; })
      .map(function (r) { return r.it; });
    sel = 0;
    render();
  }

  var KINDS = { nav: 'Go', post: 'Read', link: 'Open', act: 'Do', egg: '█' };
  function render() {
    palList.innerHTML = filtered.map(function (it, i) {
      return '<li class="pal-item' + (i === sel ? ' sel' : '') + (it.k === 'egg' ? ' egg' : '') + '" data-i="' + i + '" role="option"' + (i === sel ? ' aria-selected="true"' : '') + '>' +
        '<span class="pal-kind">' + KINDS[it.k] + '</span><span class="pal-label">' + it.label + '</span>' +
        '<span class="pal-hint">' + it.hint + '</span></li>';
    }).join('') || '<li class="pal-empty">No matches. Try “projects” — or “sudo”.</li>';
    var lis = palList.querySelectorAll('.pal-item');
    for (var i = 0; i < lis.length; i++) {
      lis[i].addEventListener('click', function () { run(filtered[+this.getAttribute('data-i')]); });
      lis[i].addEventListener('mousemove', function () { sel = +this.getAttribute('data-i'); render(); });
    }
  }

  function move(d) {
    if (!filtered.length) return;
    sel = (sel + d + filtered.length) % filtered.length;
    render();
    var el = palList.querySelector('.sel');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }

  function run(it) {
    if (!it) return;
    if (it.act === 'copy-email') {
      (navigator.clipboard ? navigator.clipboard.writeText('dkhare1998@gmail.com') : Promise.reject())
        .then(function () { toast('dkhare1998@gmail.com copied'); })
        .catch(function () { toast('dkhare1998@gmail.com'); });
      closePal(); return;
    }
    if (it.act === 'sudo') {
      closePal();
      toast('grant minted: hire_divyansh · scope: your-team · status: ACTIVE');
      setTimeout(function () {
        location.href = 'mailto:dkhare1998@gmail.com?subject=' +
          encodeURIComponent('sudo hire divyansh') + '&body=' +
          encodeURIComponent('Permission granted. Let’s talk.');
      }, 1200);
      return;
    }
    if (it.ext) { window.open(it.go, '_blank', 'noopener'); closePal(); return; }
    location.href = it.go;
  }

  function openPal() {
    if (!pal) buildPalette();
    pal.classList.add('open');
    palOpen = true;
    palInput.value = '';
    filter('');
    setTimeout(function () { palInput.focus(); }, 20);
    document.body.style.overflow = 'hidden';
  }
  function closePal() {
    if (pal) pal.classList.remove('open');
    palOpen = false;
    document.body.style.overflow = '';
  }
  window.__openPalette = openPal;

  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palOpen ? closePal() : openPal(); }
    else if (e.key === '/' && tag !== 'input' && tag !== 'textarea' && !palOpen) { e.preventDefault(); openPal(); }
  });

  var toastEl;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(function () { toastEl.classList.remove('show'); }, 2600);
  }

  /* ============================================================
     2. Grant-lifecycle demo (homepage only)
     A faithful miniature of SCM's model: authority lives in a
     row, scope is read from the row, the LLM sees opaque refs,
     and every step lands in an append-only ledger.
     ============================================================ */
  var host = document.getElementById('grant-demo');
  if (!host) return;

  var REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var TICK = REDUCED ? 0 : 640;

  host.innerHTML =
    '<div class="gd-bar"><span class="gd-dot"></span><span class="gd-dot"></span><span class="gd-dot"></span>' +
    '<span class="gd-title">scm · grant lifecycle</span><span class="gd-status" id="gd-status">idle</span></div>' +
    '<div class="gd-grant" id="gd-grant"><span class="gd-muted">no grant minted yet</span></div>' +
    '<div class="gd-log" id="gd-log"></div>' +
    '<div class="gd-actions">' +
    '<button class="btn btn-primary gd-btn" id="gd-run">Run workflow</button>' +
    '<button class="btn btn-secondary gd-btn" id="gd-replay" disabled>Replay expired grant</button>' +
    '</div>' +
    '<div class="gd-ledger"><div class="gd-ledger-head">audit ledger · append-only</div><ul id="gd-ledger"></ul></div>';

  var $ = function (id) { return document.getElementById(id); };
  var log = $('gd-log'), ledger = $('gd-ledger'), grantBox = $('gd-grant'), status = $('gd-status');
  var runBtn = $('gd-run'), replayBtn = $('gd-replay');
  var grantN = 0, lastGrant = null, ttlTimer = null, busy = false;

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function now() {
    var d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function line(html, cls) {
    var el = document.createElement('div');
    el.className = 'gd-line' + (cls ? ' ' + cls : '');
    el.innerHTML = html;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function audit(ev) {
    var li = document.createElement('li');
    li.innerHTML = '<span class="gd-time">' + now() + '</span>' + ev;
    ledger.appendChild(li);
    ledger.parentNode.scrollTop = ledger.parentNode.scrollHeight;
  }
  function newGrantId() {
    grantN++;
    var hex = '';
    for (var i = 0; i < 8; i++) hex += '0123456789abcdef'[Math.floor(Math.random() * 16)];
    return 'scm_' + hex;
  }
  function showGrant(g) {
    grantBox.innerHTML =
      '<span class="gd-gid">' + g.id + '</span>' +
      '<span class="gd-scope">scope: classroom 803 · material U4-EOU</span>' +
      '<span class="gd-chip ' + g.status.toLowerCase() + '">' + g.status + '</span>' +
      '<span class="gd-ttl" id="gd-ttl">' + (g.status === 'ACTIVE' ? 'TTL 15:00' : '') + '</span>';
  }
  function startTtl(g) {
    var s = 900;
    clearInterval(ttlTimer);
    ttlTimer = setInterval(function () {
      s--;
      var el = $('gd-ttl');
      if (!el || g.status !== 'ACTIVE' || s <= 0) { clearInterval(ttlTimer); return; }
      el.textContent = 'TTL ' + Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
    }, 1000);
  }

  function setBusy(b) {
    busy = b;
    runBtn.disabled = b;
    replayBtn.disabled = b || !lastGrant;
    status.textContent = b ? 'running' : 'idle';
    status.className = 'gd-status' + (b ? ' live' : '');
  }

  async function runWorkflow() {
    if (busy) return;
    setBusy(true);
    log.innerHTML = '';

    // Retire the previous grant the honest way: expiry, not deletion.
    if (lastGrant && lastGrant.status === 'ACTIVE') lastGrant.status = 'EXPIRED';

    var g = { id: newGrantId(), status: 'ACTIVE' };
    line('<b>POST /grants</b> { staff: you, capability: small_group_proposal }');
    await sleep(TICK);
    showGrant(g); startTtl(g);
    line('✓ grant minted · single-use · 15-minute TTL', 'ok');
    audit('<b>grant_created</b> · ' + g.id);
    await sleep(TICK);

    line('<b>POST /agent/small-group-context</b> { grantId: ' + g.id + ' }');
    await sleep(TICK);
    line('✓ scope read <i>from the grant row</i> — request params: <s>classroomId=999</s> ignored', 'ok');
    audit('<b>grant_validated</b> · scope from row');
    await sleep(TICK);

    line('fetching context … students → opaque refs: <span class="gd-refs">S1 S2 S3 S4 S5 S6</span>');
    await sleep(TICK);
    line('✓ names never enter the AI region', 'ok');
    audit('<b>context_fetched</b> · 6 refs, 0 names');
    await sleep(TICK);

    var think = line('claude · synthesize_proposal · max_attempts=1 <span class="gd-spin">⣻</span>');
    if (!REDUCED) {
      var frames = ['⣻', '⣽', '⣾', '⣷', '⣯', '⣟'], fi = 0;
      var sp = setInterval(function () {
        var el = think.querySelector('.gd-spin');
        if (el) el.textContent = frames[fi++ % frames.length];
      }, 90);
      await sleep(TICK * 2);
      clearInterval(sp);
    }
    think.innerHTML = '✓ 1 LLM call · groups proposed: [S2 S5 S6] [S1 S3 S4]';
    think.className = 'gd-line ok';
    audit('<b>llm_synthesis</b> · calls=1 · bounded');
    await sleep(TICK);

    line('✓ loose parse → rehydrate → strict validate', 'ok');
    await sleep(TICK);
    g.status = 'COMPLETED';
    showGrant(g);
    line('<b>workflow complete</b> · grant retired · authority returned', 'done');
    audit('<b>workflow_completed</b> · grant → COMPLETED');

    lastGrant = g;
    lastGrant.status = 'EXPIRED'; // for the replay button: time has "passed"
    setBusy(false);
  }

  async function replayExpired() {
    if (busy || !lastGrant) return;
    setBusy(true);
    log.innerHTML = '';
    var g = lastGrant;
    showGrant(g);
    line('<b>POST /agent/small-group-context</b> { grantId: ' + g.id + ' } <span class="gd-muted">(replayed)</span>');
    await sleep(TICK);
    line('✗ 410 Gone · grant is ' + g.status, 'err');
    await sleep(TICK);
    line('✗ ApplicationError(non_retryable=True) — retries cannot un-expire a grant', 'err');
    audit('<b>grant_reuse_denied</b> · ' + g.id);
    await sleep(TICK);
    line('workflow failed <b>terminally</b>. No data was read. That’s the point.', 'done');
    setBusy(false);
    replayBtn.disabled = true;
  }

  runBtn.addEventListener('click', runWorkflow);
  replayBtn.addEventListener('click', replayExpired);
})();
