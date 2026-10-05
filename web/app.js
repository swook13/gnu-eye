/* GNU-Eye v2 화면 로직. 모든 값은 FastAPI에서 받는다. 화면에 고정된 검사 수치는 없다. */
(function () {
  'use strict';
  var PAGE = document.body.getAttribute('data-page');
  var app = document.getElementById('app');
  var SID_KEY = 'gnueye_sid';
  var NAME_KEY = 'gnueye_inspector';
  var MODE_KEY = 'gnueye_mode';
  var state = null;

  // 검사 모드: 정비 점검(maintenance) 또는 제조 검사(manufacturing). 주소의 ?mode=mfg|maint 가 우선이고 브라우저에 기억한다.
  // 같은 화면과 같은 API를 쓰고, 용어와 기준 묶음만 다르다.
  (function () {
    var m = location.search.match(/[?&]mode=(mfg|maint)/);
    if (m) { try { localStorage.setItem(MODE_KEY, m[1] === 'mfg' ? 'manufacturing' : 'maintenance'); } catch (e) {} }
  })();
  function mode() { try { return localStorage.getItem(MODE_KEY) === 'manufacturing' ? 'manufacturing' : 'maintenance'; } catch (e) { return 'maintenance'; } }
  function setMode(v) { try { localStorage.setItem(MODE_KEY, v); } catch (e) {} }
  function mfg() { return mode() === 'manufacturing'; }
  var WORDS = {
    maintenance: { name: '정비 점검', subject: '기체', unit: '카드', unitObj: '카드를', unitTopic: '카드는', unitLong: '작업카드', criteria: '기준', history: '이전 점검 기록 (가상)', report: '기체 단위 NDT 점검 보고서' },
    manufacturing: { name: '제조 검사', subject: '생산 로트', unit: '부품', unitObj: '부품을', unitTopic: '부품은', unitLong: '검사 부품', criteria: '고객사양', history: '과거 NCR 이력', report: '로트 검사 보고서와 NCR' }
  };
  function W(k) { return WORDS[mode()][k]; }
  function sidKey() { return mfg() ? SID_KEY + '_mfg' : SID_KEY; }  // 모드마다 진행 중인 세션을 따로 기억한다

  // ---------------------------------------------------------------- 공통 도구
  function esc(x) {
    return String(x === null || x === undefined ? '' : x).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function sid() { try { return localStorage.getItem(sidKey()); } catch (e) { return null; } }
  // 주소에 ?sid=...가 있으면 그 세션을 연다 (다른 창이나 다른 PC에서 같은 검사를 볼 때)
  (function () { var m = location.search.match(/[?&]sid=([\w\-]+)/); if (m) { try { localStorage.setItem(sidKey(), m[1]); } catch (e) {} } })();
  function setSid(v) { try { v ? localStorage.setItem(sidKey(), v) : localStorage.removeItem(sidKey()); } catch (e) {} }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { throw new Error(j.error || j.detail || ('요청 실패 (' + r.status + ')')); }
        return j;
      });
    });
  }
  function postJson(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  // 한 턴 실행: POST 후 SSE 형식 응답을 읽어 이벤트마다 onEvent(kind, data)를 부른다.
  function runTurn(body, onEvent) {
    return fetch('/api/sessions/' + sid() + '/turn', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) { return r.json().then(function (j) { throw new Error(j.error || '요청 실패'); }); }
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = '';
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) { return; }
          buf += dec.decode(res.value, { stream: true });
          var parts = buf.split('\n\n');
          buf = parts.pop();
          parts.forEach(function (blk) {
            var m = blk.match(/^event: (\w+)\ndata: ([\s\S]*)$/);
            if (!m) { return; }
            var data; try { data = JSON.parse(m[2]); } catch (e) { return; }
            if (m[1] === 'state') { state = data; }
            onEvent(m[1], data);
          });
          return pump();
        });
      }
      return pump();
    });
  }

  var DISP = {
    ALLOW: { cls: 'bg-verdict-pass-bg text-verdict-pass-text', icon: 'check_circle', bar: '#1E7F4F' },
    REPAIR: { cls: 'bg-verdict-conditional-bg text-verdict-conditional-text', icon: 'build', bar: '#C77700' },
    EXCEED: { cls: 'bg-verdict-fail-bg text-verdict-fail-text', icon: 'cancel', bar: '#C0392B' },
    NOT_EVALUATED: { cls: 'bg-chip-bg text-chip-text', icon: 'help', bar: '#74777f' }
  };
  var DISP_KO = {
    maintenance: { ALLOW: '허용(기록)', REPAIR: '수리 가능', EXCEED: '한도 초과(제작사 문의)', NOT_EVALUATED: '미평가' },
    manufacturing: { ALLOW: '적합(기록)', REPAIR: '보류(재검사 권고)', EXCEED: '부적합(NCR 대상)', NOT_EVALUATED: '미평가' }
  };
  function dispKo(d) { return DISP_KO[mode()][DISP[d] ? d : 'NOT_EVALUATED']; }
  function tag(d) {
    var x = DISP[d] || DISP.NOT_EVALUATED;
    return '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg font-label-md text-[12px] whitespace-nowrap ' + x.cls + '">' +
      '<span class="material-symbols-outlined text-[15px]">' + (d === 'REPAIR' && mfg() ? 'pending' : x.icon) + '</span>' + dispKo(d) + '</span>';
  }
  function chip(t) { return '<span class="px-2 py-0.5 rounded bg-chip-bg border border-border text-chip-text font-code-mono text-[12px]">' + esc(t) + '</span>'; }
  function box(inner, extra) { return '<section class="panel bg-surface rounded-xl p-space-lg shadow-[0_0_0_1px_#E1E4EA] ' + (extra || '') + '">' + inner + '</section>'; }
  // AI가 일하는 동안 보이는 점구(thinking-orbs, MIT). 캔버스를 그려 두고 mountOrbs가 움직이게 한다.
  function orb(state, size, dark, id) {
    return '<canvas ' + (id ? 'id="' + id + '" ' : '') + 'class="orb" data-orb="' + state + '" data-size="' + size + '"' + (dark ? ' data-dark="1"' : '') + ' role="img" aria-label="AI 에이전트 작업 중"></canvas>';
  }
  function mountOrbs(root) {
    if (!window.ThinkingOrbs) { return; }
    $all('canvas[data-orb]:not([data-on])', root).forEach(function (c) {
      c.setAttribute('data-on', '1');
      window.ThinkingOrbs.mount(c, { state: c.dataset.orb, size: +c.dataset.size, dark: !!c.dataset.dark });
    });
  }
  function h1(t, sub) {
    return '<div><h1 class="font-headline-lg text-headline-lg font-bold text-chip-text tracking-tight">' + esc(t) + '</h1>' +
      (sub ? '<p class="font-body-lg text-body-lg text-on-surface-variant mt-1">' + esc(sub) + '</p>' : '') + '</div>';
  }
  function h2(t) { return '<h2 class="font-headline-md text-headline-md font-bold text-primary mb-space-sm">' + esc(t) + '</h2>'; }
  function btn(label, id, kind, extra) {
    var c = kind === 'ghost' ? 'bg-chip-bg text-chip-text border border-border hover:bg-surface-variant'
      : kind === 'danger' ? 'bg-verdict-fail-graphic text-white hover:opacity-90'
        : 'bg-primary-container text-on-primary hover:bg-primary';
    return '<button type="button" id="' + id + '" class="whitespace-nowrap px-4 py-2.5 rounded-lg font-label-md text-label-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed ' + c + '" ' + (extra || '') + '>' + label + '</button>';
  }
  function linkBtn(label, href) {
    return '<a href="' + href + '" class="inline-flex items-center gap-1 px-4 py-2.5 rounded-lg font-label-md text-label-md bg-primary-container text-on-primary hover:bg-primary transition-colors">' + label + '<span class="material-symbols-outlined text-[18px]">arrow_forward</span></a>';
  }
  function note(t, kind) {
    var c = kind === 'warn' ? 'bg-notice-band-bg text-notice-band-text' : kind === 'err' ? 'bg-verdict-fail-bg text-verdict-fail-text' : 'bg-info-box-bg text-info-box-text';
    return '<div class="px-space-md py-space-sm rounded-lg font-body-sm text-body-sm ' + c + '">' + t + '</div>';
  }
  var INPUT = 'w-full h-11 px-3 rounded-lg bg-background border border-border text-on-surface font-body-sm text-body-sm focus:outline-none focus:border-secondary';

  function noSession() {
    app.innerHTML = h1(W('name') + ' 모드에 진행 중인 검사가 없습니다', '검사 요청 화면에서 ' + (mfg() ? '생산 로트 패키지' : '작업 패키지') + '를 올리면 여기에 결과가 표시됩니다.') +
      '<div>' + linkBtn('검사 요청으로', 'request.html') + '</div>';
  }
  function loadState() {
    if (!sid()) { return Promise.resolve(null); }
    return api('/api/sessions/' + sid()).then(function (s) {
      // 다른 모드에서 만든 세션은 이 모드 화면에 보여 주지 않는다 (세션은 지우지 않으므로 모드를 되돌리면 다시 보인다)
      state = s.domain === mode() ? s : null; return state;
    }).catch(function () { setSid(null); state = null; return null; });
  }

  // ---------------------------------------------------------------- 상단 상태, 챗봇
  function initHeader() {
    api('/api/health').then(function (h) {
      var ok = h.llm.ok;
      $('#llm-dot').style.background = ok ? '#3BE38A' : '#FF5A4F'; $('#llm-dot').style.boxShadow = '0 0 10px ' + (ok ? '#3BE38A' : '#FF5A4F');
      $('#llm-status').textContent = ok ? 'LLM ' + h.llm.model + ' 연결됨' : 'LLM 연결 안 됨 · 고정 순서 모드로 동작';
      $('#llm-status').title = h.llm.host + (h.llm.error ? ' · ' + h.llm.error : '');
      window.__llm = h.llm;
    }).catch(function () { $('#llm-status').textContent = '서버 연결 안 됨'; });
    $('#session-chip').textContent = sid() || '없음';
    document.body.classList.toggle('mode-mfg', mfg());  // 모드별 테마 색 (정비: 네이비, 제조: 청록)
    var on = 'px-3 py-1.5 bg-primary-container text-on-primary font-semibold', off = 'px-3 py-1.5 bg-chip-bg text-chip-text hover:bg-surface-variant';
    $('#mode-toggle').innerHTML = '<a href="index.html?mode=maint" class="' + (mfg() ? off : on) + '"' + (mfg() ? '' : ' aria-current="true"') + '>정비 점검</a>' +
      '<a href="index.html?mode=mfg" class="' + (mfg() ? on : off) + '"' + (mfg() ? ' aria-current="true"' : '') + '>제조 검사</a>';
  }
  var QUICK_MFG = {
    home: ['제조 검사 모드는 무엇을 해?', 'NCR이 뭐야?', '개정번호는 왜 물어봐?'],
    request: ['고객사양이 뭐야?', '개정번호를 비워 두면 어떻게 돼?', 'EXAMPLE_ONLY가 뭐야?'],
    agent: ['개정번호는 왜 물어봐?', '절차 적합성이 뭐야?', '6 dB drop이 뭐야?'],
    results: ['보류는 무슨 뜻이야?', 'NCR이 뭐야?', '가장자리 경고는 뭐야?'],
    report: ['전체 결과를 요약해 줘', 'MRB가 뭐야?', '처분은 누가 확정해?'],
    email: ['전체 결과를 요약해 줘', 'EXAMPLE_ONLY가 뭐야?'],
    history: ['처분은 누가 확정해?', '6 dB drop이 뭐야?']
  };
  var QUICK = {
    home: ['이 시스템은 무엇을 해?', '6 dB drop이 뭐야?', '개정번호는 왜 물어봐?'],
    request: ['개정번호를 비워 두면 어떻게 돼?', '절차 적합성이 뭐야?', 'EXAMPLE_ONLY가 뭐야?'],
    agent: ['개정번호는 왜 물어봐?', '절차 적합성이 뭐야?', '6 dB drop이 뭐야?'],
    results: ['CARD-03 결과를 설명해 줘', '처분은 어떤 종류가 있어?', '가장자리 경고는 뭐야?'],
    report: ['전체 결과를 요약해 줘', '처분은 누가 확정해?', '이전 점검 기록은 실제 기록이야?'],
    email: ['전체 결과를 요약해 줘', 'EXAMPLE_ONLY가 뭐야?'],
    history: ['처분은 누가 확정해?', '6 dB drop이 뭐야?']
  };
  var SRC = { llm: 'LLM 답변 · 숫자 검증 통과', glossary: '용어집', session: '코드가 만든 검사 결과 문장', none: '자료 없음' };
  function chatAdd(who, text, meta) {
    var th = $('#chat-thread');
    var mine = who === 'me';
    var d = document.createElement('div');
    d.className = 'rounded-lg px-space-sm py-2 text-[13px] leading-relaxed whitespace-pre-wrap ' + (mine ? 'bg-primary-container text-on-primary self-end max-w-[90%]' : 'bg-background border border-border text-on-surface');
    d.textContent = text;
    if (meta) {
      var m = document.createElement('div');
      m.className = 'mt-1 text-[11px] text-outline font-code-mono';
      m.textContent = meta;
      d.appendChild(m);
    }
    th.appendChild(d);
    th.scrollTop = th.scrollHeight;
    return d;
  }
  function chatAsk(q) {
    q = (q || '').trim();
    if (!q) { return; }
    chatAdd('me', q);
    var wait = chatAdd('bot', '답을 찾는 중...');
    postJson('/api/chat', { question: q, session_id: state ? sid() : 'none' }).then(function (r) {
      wait.remove();
      chatAdd('bot', r.text, '근거: ' + (SRC[r.source] || r.source) + (r.fallback_reason && r.source !== 'llm' ? ' (' + r.fallback_reason + ')' : ''));
    }).catch(function (e) { wait.remove(); chatAdd('bot', '답하지 못했습니다: ' + e.message); });
  }
  // 챗봇 패널 열고 닫기. 상태는 브라우저에 기억한다. 본문 여백과 최대 너비는 CSS(body.chat-closed)가 맞춘다.
  function initChatToggle() {
    var body = document.body, tg = $('#chat-toggle');
    function paint() {
      var open = !body.classList.contains('chat-closed');
      tg.setAttribute('aria-expanded', open ? 'true' : 'false');
      $('#chat-toggle-label').textContent = open ? '도우미 닫기' : '도우미 열기';
    }
    function set(open) {
      body.classList.toggle('chat-closed', !open);
      try { localStorage.setItem('gnueye_chat', open ? 'open' : 'closed'); } catch (e) {}
      paint();
      if (open) { setTimeout(function () { $('#chat-input').focus(); }, 260); }
      setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 280);  // 너비가 바뀐 뒤 다시 맞출 요소용
    }
    tg.addEventListener('click', function () { set(body.classList.contains('chat-closed')); });
    $('#chat-close').addEventListener('click', function () { set(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && window.innerWidth < 1100 && !body.classList.contains('chat-closed')) { set(false); }
    });
    paint();
    setTimeout(function () { body.classList.remove('no-anim'); }, 50);  // 첫 화면에서는 움직임 없이 바로 배치
  }

  function initChat() {
    var q = $('#chat-quick');
    q.innerHTML = ((mfg() ? QUICK_MFG : QUICK)[PAGE] || []).map(function (t) {
      return '<button type="button" class="w-full text-left px-space-sm py-1.5 rounded bg-chip-bg hover:bg-surface-variant border border-border text-chip-text text-[13px] transition-colors">' + esc(t) + '</button>';
    }).join('');
    $all('button', q).forEach(function (b) { b.addEventListener('click', function () { chatAsk(b.textContent); }); });
    $('#chat-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var i = $('#chat-input'); chatAsk(i.value); i.value = '';
    });
  }

  // ---------------------------------------------------------------- 홈
  // 설명용 C-scan 미니 지도: 밝은 곳 = 건전부, 어두운 곳 = 초음파 신호가 약한 곳(내부 손상 의심).
  // 실제 측정값이 아니라 그림이다. 색은 결과 화면의 C-scan 그림과 같은 순서(노랑 → 보라)를 쓴다.
  function cscanMini(x, y, w, h) {
    var nx = 36, ny = 18, cw = w / nx, ch = h / ny, out = '';
    var c = ['#FDE725', '#C2DF23', '#86D549', '#52C569', '#2AB07F', '#1E9B8A', '#25858E', '#2D708E', '#38598C', '#433E85', '#481F70', '#440154'];
    for (var j = 0; j < ny; j++) {
      for (var i = 0; i < nx; i++) {
        var dx = (i - 22.5) / 6.4, dy = (j - 9) / 4.4;
        var v = Math.exp(-(dx * dx + dy * dy) * 1.1) * 1.08 + (Math.sin(i * 0.55 + j * 0.8) + Math.cos(i * 0.31 - j * 0.47) + 2) * 0.022;
        out += '<rect x="' + (x + i * cw).toFixed(1) + '" y="' + (y + j * ch).toFixed(1) + '" width="' + (cw + 0.4).toFixed(1) + '" height="' + (ch + 0.4).toFixed(1) + '" fill="' + c[Math.min(11, Math.max(0, Math.round(v * 11)))] + '"/>';
      }
    }
    return out;
  }
  function heroArt() {
    var ln = 'fill="rgba(255,255,255,.6)" stroke="#1f3a5f" stroke-width="1.4" stroke-linejoin="round"';
    var thin = 'fill="none" stroke="rgba(31,58,95,.28)" stroke-width="1"';
    var hi = '#2C7BE5';
    var part, zone, leader, cap;
    if (mfg()) {  // 생산 로트: 같은 부품 여러 장이 쌓인 묶음, 맨 앞 부품의 검사 구역
      part = [2, 1, 0].map(function (k) {
        var oy = -k * 30, ox = k * 18, a = k ? 0.4 : 1;
        return '<g opacity="' + a + '" transform="translate(' + ox + ',' + oy + ')"><path d="M60,210 L330,210 L410,150 L140,150 Z" ' + ln + '/><path d="M60,210 L60,220 L330,220 L330,210 M330,220 L410,160 L410,150" ' + ln + '/>' +
          (k ? '' : '<path d="M120,210 L200,150 M190,210 L270,150 M260,210 L340,150" ' + thin + '/><g fill="rgba(31,58,95,.45)">' + [0, 1, 2, 3, 4, 5, 6, 7].map(function (n) { return '<circle cx="' + (92 + n * 32) + '" cy="203" r="1.8"/>'; }).join('') + '</g>') + '</g>';
      }).join('');
      zone = '<path class="zone-pulse" d="M222,196 L262,196 L282,181 L242,181 Z" fill="rgba(44,123,229,.16)" stroke="' + hi + '" stroke-width="1.6"/>';
      leader = '<path d="M262,196 L300,262 L330,262" fill="none" stroke="' + hi + '" stroke-width="1.2" stroke-dasharray="3 3"/>';
      cap = ['생산 로트 = 같은 부품의 묶음', '부품마다 검사 구역을 초음파로 찍습니다'];
    } else {  // 정비: 기체 평면도(가상)와 작업카드가 가리키는 검사 부위
      part = '<path d="M300,118 L222,24 L198,26 L242,118 Z M300,152 L222,246 L198,244 L242,152 Z" ' + ln + '/>' +
        '<path d="M110,118 L78,72 L64,74 L86,118 Z M110,152 L78,198 L64,196 L86,152 Z" ' + ln + '/>' +
        '<path d="M70,135 C70,122 90,118 120,118 L430,118 C470,118 505,126 522,135 C505,144 470,152 430,152 L120,152 C90,152 70,148 70,135 Z" ' + ln + '/>' +
        '<rect x="252" y="62" width="34" height="11" rx="5" ' + ln + '/><rect x="252" y="197" width="34" height="11" rx="5" ' + ln + '/>' +
        '<path d="M52,135 L540,135" stroke="rgba(31,58,95,.25)" stroke-width="1" stroke-dasharray="6 5"/>' +
        '<path d="M70,268 L522,268 M70,262 L70,274 M522,262 L522,274" ' + thin + '/>';
      zone = '<rect class="zone-pulse" x="222" y="200" width="26" height="20" fill="rgba(44,123,229,.16)" stroke="' + hi + '" stroke-width="1.6"/>';
      leader = '<path d="M248,212 L300,262 L330,262" fill="none" stroke="' + hi + '" stroke-width="1.2" stroke-dasharray="3 3"/>';
      cap = ['작업카드 1장 = 검사 부위 1곳', '정기점검에서 지정된 부위를 초음파로 찍습니다'];
    }
    var X = 330, Y = 246, Wd = 214, Ht = 108;
    return '<svg class="hero-art w-full h-auto" viewBox="0 0 560 400" role="img" aria-label="' + esc(cap[0] + ', C-scan 지도에서 어두운 곳이 내부 손상 의심') + '">' +
      '<defs><clipPath id="cs-clip"><rect x="' + X + '" y="' + Y + '" width="' + Wd + '" height="' + Ht + '" rx="6"/></clipPath>' +
      '<filter id="cs-shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#14213D" flood-opacity=".22"/></filter></defs>' +
      part + zone + leader +
      '<text x="40" y="306" fill="' + hi + '" font-size="13" font-weight="700">' + esc(cap[0]) + '</text>' +
      '<text x="40" y="326" fill="#43474e" font-size="12">' + esc(cap[1]) + '</text>' +
      '<text x="40" y="350" fill="#74777f" font-size="11">초음파가 약하게 돌아오는 곳이 어둡게 찍힙니다</text>' +
      '<g filter="url(#cs-shadow)"><rect x="' + X + '" y="' + Y + '" width="' + Wd + '" height="' + Ht + '" rx="6" fill="#fff"/></g>' +
      '<g clip-path="url(#cs-clip)">' + cscanMini(X, Y, Wd, Ht) +
      '<ellipse cx="' + (X + 134) + '" cy="' + (Y + 54) + '" rx="34" ry="23" fill="none" stroke="#fff" stroke-width="1.4" stroke-dasharray="4 3"/>' +
      '<rect x="' + (X + 97) + '" y="' + (Y + 28) + '" width="74" height="52" fill="none" stroke="#FF5252" stroke-width="1.6"/>' +
      '<g class="scanline" style="--sweep:' + (Wd - 4) + 'px"><rect x="' + X + '" y="' + Y + '" width="3" height="' + Ht + '" fill="rgba(255,255,255,.95)"/></g></g>' +
      '<rect x="' + X + '" y="' + Y + '" width="' + Wd + '" height="' + Ht + '" rx="6" fill="none" stroke="rgba(255,255,255,.9)" stroke-width="1.5"/>' +
      '<text x="' + X + '" y="' + (Y - 10) + '" fill="#14213D" font-size="13" font-weight="700">C-scan 지도</text>' +
      '<text x="' + (X + Wd) + '" y="' + (Y - 10) + '" fill="#74777f" font-size="11" text-anchor="end">흰 점선 = -6 dB 경계</text>' +
      '<text x="' + X + '" y="' + (Y + Ht + 22) + '" fill="#14213D" font-size="12" font-weight="600">어두울수록 내부 손상 의심</text>' +
      '<text x="' + X + '" y="' + (Y + Ht + 39) + '" fill="#74777f" font-size="11">설명용 그림 · 실측값은 판정 결과 화면</text></svg>';
  }
  function homeHero() {
    var m = mfg();
    return '<section class="hero panel rounded-xl p-space-xl grid grid-cols-1 lg:grid-cols-[1fr_1.05fr] gap-space-xl items-center">' +
      '<div class="flex flex-col gap-space-md">' +
      '<h1 class="hero-title">' + (m ? '항공 제조 공정<br>초음파 검사 AI 에이전트' : '항공 정비 점검<br>초음파 검사 AI 에이전트') + '</h1>' +
      '<p class="hero-lead">' + (m
        ? '부품의 초음파 검사 결과(C-scan, 복합재 속을 찍은 지도)를 올리면 결함 크기를 재고 고객사양·과거 NCR 이력과 대조해 검사 보고서와 부적합보고서(NCR) 초안까지 준비합니다. 최종 판단과 서명은 검사원이 합니다.'
        : '초음파 검사 결과(C-scan, 복합재 속을 찍은 지도)를 올리면 손상 크기를 재고 허용 기준·지난 점검 기록과 대조해 점검 보고서 초안까지 이어 갑니다. 최종 판단과 서명은 검사원이 합니다.') + '</p>' +
      '<div class="flex flex-wrap gap-space-md items-center pt-space-sm"><a href="request.html" class="hero-cta inline-flex items-center gap-2 rounded-lg bg-primary-container text-on-primary hover:bg-primary">' + (m ? '제조검사 시작하기' : '정비점검 시작하기') + '<span class="material-symbols-outlined">arrow_forward</span></a>' +
      '<span id="home-resume"></span></div>' +
      '<div><span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-chip-bg text-[12px] text-chip-text"><span class="material-symbols-outlined text-[16px]">' + (m ? 'precision_manufacturing' : 'flight') + '</span>' +
      (m ? '제조 검사 모드 · 생산 로트 출하 전 초음파 검사' : '정비 점검 모드 · 정기점검 SDI 작업 패키지') + '</span></div></div>' +
      '<div class="min-w-0">' + heroArt() + '</div></section>';
  }
  function homeFlow() {
    var m = mfg();
    var nodes = [
      ['human', '검사원', 'upload_file', m ? '로트 묶음 올리기' : '작업카드 묶음 올리기',
        m ? '생산 로트의 부품별 C-scan 격자 CSV와 부품 정보(부품번호, 고객사양, 개정번호)를 한 묶음으로 올립니다.' : '정기점검 작업카드 묶음(변환된 C-scan 격자 CSV와 카드 정보)을 올립니다.'],
      ['ai', 'AI 에이전트', null, '계획하고 되묻기',
        m ? '계획을 세우고, 부품마다 고객사양을 고르고, 개정번호가 빠져 있으면 추측하지 않고 되묻습니다.' : '계획을 세우고, 카드마다 기준을 고르고, 빠진 정보는 추측하지 않고 되묻습니다.'],
      ['code', '결정론 코드', 'straighten', '측정하고 대조하기',
        m ? '코드가 6 dB drop으로 측정하고 사양의 최대 치수, 지시 간 거리, 누적 면적 한도에 대조합니다.' : '코드가 6 dB drop으로 측정하고 절차 범위와 허용 손상 한도에 대조합니다.'],
      ['code', '코드 · AI 종합 의견', 'description', m ? '보고서와 NCR 초안' : '보고서 초안',
        m ? '로트 검사 보고서와 부적합 부품의 NCR 초안을 만들고 검사원이 부품별로 승인하거나 반려합니다.' : '기체 단위 점검 보고서 초안을 만들고 검사원이 카드별로 승인하거나 반려합니다.'],
      ['human', '검사원', 'verified', '승인하고 저장하기', '승인이 끝난 보고서를 .eml 파일로 저장합니다. 실제 발송은 하지 않습니다.']
    ];
    return box(h2('이렇게 진행됩니다') + '<div class="grid grid-cols-1 md:grid-cols-5 gap-space-md">' + nodes.map(function (n) {
      return '<div class="flow-node rounded-xl bg-background p-space-md flex flex-col gap-2">' +
        '<div class="h-16 flex items-center">' + (n[2] ? '<span class="w-12 h-12 rounded-full flex items-center justify-center role-' + n[0] + '"><span class="material-symbols-outlined text-[24px]">' + n[2] + '</span></span>' : '<span class="orb-slot rounded-full role-ai flex items-center justify-center">' + orb('working', 64, false) + '</span>') + '</div>' +
        '<span class="self-start px-2 py-0.5 rounded-full text-[11px] font-semibold role-' + n[0] + '">' + n[1] + '</span>' +
        '<div class="font-label-md text-label-md text-chip-text">' + n[3] + '</div><p class="text-[13px] text-on-surface-variant leading-relaxed">' + n[4] + '</p></div>';
    }).join('') + '</div><p class="mt-space-md text-[13px] text-on-surface-variant flex items-center gap-1.5"><span class="material-symbols-outlined text-[18px] text-primary-container">fact_check</span>모든 도구 호출, 질문과 답, 서명 기록을 감사 로그로 남기고 검토 이력 화면에서 볼 수 있습니다.</p>');
  }
  // 역할 분담, 데이터 상태, 한계는 접어 두고 필요할 때 펼쳐 본다 (내용은 그대로)
  function homeMore(blocks) {
    return '<details class="more panel rounded-xl p-space-lg"><summary class="flex items-center justify-between gap-space-md"><span class="font-headline-md text-headline-md font-bold text-chip-text">역할 분담과 데이터·한계</span>' +
      '<span class="flex items-center gap-1 text-[13px] text-on-surface-variant">자세히<span class="material-symbols-outlined chev">expand_more</span></span></summary>' +
      '<div class="mt-space-md flex flex-col gap-space-lg">' + blocks.join('') + '</div></details>';
  }
  function roleGrid(code, human) {
    return '<div><div class="font-label-md text-label-md text-chip-text mb-space-sm">누가 무엇을 하는가</div><div class="grid grid-cols-1 md:grid-cols-3 gap-space-md text-[13px] leading-relaxed">' +
      '<div class="rounded-lg bg-background p-space-md"><div class="mb-1.5"><span class="px-2 py-0.5 rounded-full text-[12px] font-semibold role-code">결정론 코드</span></div>' + code + '</div>' +
      '<div class="rounded-lg bg-background p-space-md"><div class="mb-1.5"><span class="px-2 py-0.5 rounded-full text-[12px] font-semibold role-ai">LLM (내부 서버)</span></div>처리 계획, 도구 호출 순서, 검사원 피드백 해석, 종합 의견 문단, 도우미 답변. LLM이 쓴 문장은 숫자와 ID 검증을 통과해야 쓰입니다.</div>' +
      '<div class="rounded-lg bg-background p-space-md"><div class="mb-1.5"><span class="px-2 py-0.5 rounded-full text-[12px] font-semibold role-human">검사원</span></div>' + human + '</div></div></div>';
  }
  function limitsList(items) {
    return '<div><div class="font-label-md text-label-md text-chip-text mb-space-sm">데이터와 한계</div><ul class="list-disc pl-5 text-[13px] leading-relaxed text-on-surface-variant flex flex-col gap-1">' +
      items.map(function (t) { return '<li>' + t + '</li>'; }).join('') + '</ul></div>';
  }
  function homeResume() {
    if (state) {
      $('#home-resume').innerHTML = '<a href="' + (state.report_ready ? 'results.html' : 'agent.html') + '" class="underline text-on-surface-variant text-[13px]">진행 중인 검사 ' + esc(state.session_id) + ' 이어서 보기</a>';
    }
  }

  function pageHomeMfg() {
    app.innerHTML = homeHero() + homeFlow() + homeMore([
      '<div><div class="font-label-md text-label-md text-chip-text mb-space-sm">지금 되는 것과 데이터 상태</div><div class="grid grid-cols-1 md:grid-cols-2 gap-space-md text-[13px] leading-relaxed">' +
        '<div class="rounded-lg bg-background p-space-md"><div class="font-label-md text-label-md text-chip-text mb-1">구축된 기능</div>로트 패키지 업로드, 고객사양 Rev A/B 대조(최대 치수, 지시 간 거리, 누적 면적), 개정번호 되묻기, 처분 초안(적합, 보류, 부적합), NCR 초안, 검사원 승인과 반려 후 재평가, .eml 저장, 감사 로그</div>' +
        '<div class="rounded-lg bg-background p-space-md"><div class="font-label-md text-label-md text-chip-text mb-1">데이터</div>제조 공정의 실제 C-scan 데이터는 확보하지 못했습니다. 내장 샘플 로트는 Cranfield 실측 충격 시편 2건(가상 부품번호, 취급 충격 손상)과 합성 결함 5건(크기·감쇠·노이즈는 가정값)을 섞은 것입니다. 형식에 맞는 로트 패키지를 올려도 동작합니다. 제조 현장 실데이터 검증은 하지 않았습니다.</div></div></div>',
      roleGrid('측정(6 dB drop), 절차 적합성, 고객사양 한도 대조, 처분 초안, 과거 NCR 조회, 보고서와 NCR 초안의 모든 숫자와 표',
        '빠진 정보에 답하고, 부품별로 승인하거나 반려합니다. 부적합 부품의 처분은 이 시스템이 정하지 않고 자재심의(MRB)에서 정합니다.'),
      limitsList(['고객사양(GNU-SPEC-UT-001 Rev A, Rev B)과 절차는 모두 가상(EXAMPLE_ONLY)이며 실제 고객 문서와 무관합니다.',
        '크기는 6 dB drop 기준 평면 치수이며 결함 깊이와 종류는 구분하지 않습니다.',
        '과거 NCR 이력은 가상 이력 60건(EXAMPLE_ONLY, 부품번호 GNU-P-1001~1005)입니다. 같은 부품번호의 기록 건수, 결함 유형, 기록된 원인을 보여 줄 뿐 이번 지시의 원인을 추정하지 않습니다.',
        '제조 실데이터로 검증하지 않았습니다. 실데이터를 확보하면 격자 간격과 사양 값을 그에 맞춰야 합니다.'])
    ]);
    homeResume();
  }

  function pageHome() {
    if (mfg()) { return pageHomeMfg(); }
    app.innerHTML = homeHero() + homeFlow() + homeMore([
      roleGrid('측정(6 dB drop), 절차 적합성, 한도 대조, 처분 초안, 이전 기록 비교, 보고서의 모든 숫자와 표',
        '빠진 정보에 답하고, 카드별로 승인하거나 반려합니다. 서명은 검사원이 이름을 밝히고 직접 요청할 때만 기록됩니다.'),
      '<div class="rounded-lg bg-info-box-bg text-info-box-text p-space-md flex flex-col gap-space-xs"><div class="font-label-md text-label-md">제조 검사에도 같은 에이전트를 씁니다</div>' +
        '<p class="text-[13px] leading-relaxed">측정, 기준 대조, 이력 조회, 보고서, 검사원 승인으로 이어지는 구조는 제조 단계의 C-scan 검사와 같습니다. 제조 검사 모드는 기준 묶음을 고객사양과 개정번호로, 보고서를 로트 검사 보고서와 부적합보고서(NCR) 초안으로 바꿔 같은 엔진으로 동작합니다. 제조 실데이터를 확보하지 못해 내장 샘플은 실측 충격 시편 2건과 합성 결함 5건을 섞은 시연용 로트입니다.</p>' +
        '<div><a href="index.html?mode=mfg" class="underline font-label-md text-[13px]">제조 검사 모드로 전환</a></div></div>',
      limitsList(['정기점검 중 지정 SDI 작업과, 발견되거나 의심된 손상의 범위 평가에 C-scan이 쓰입니다.',
        'C-scan 격자는 Cranfield CompInnova WP2 공개 데이터(Zenodo, DOI 10.5281/zenodo.4405277, CC BY 4.0)의 변환본입니다.',
        '기체, 작업카드, 부위, 절차, 허용 손상 기준, 이전 점검 기록은 모두 가상(EXAMPLE_ONLY)입니다.',
        '크기는 6 dB drop 기준 평면 치수이며 손상 깊이는 측정하지 않습니다.',
        '격자 간격은 공개 설명서에 없어 처리 영상 축에서 읽은 추정값입니다.'])
    ]);
    homeResume();
  }

  // ---------------------------------------------------------------- ① 검사 요청
  function cardTable(cards) {
    var FIELD = { criteria_rev: '기준 개정번호', procedure_id: '적용 절차', zone_id: '부위 구역', location_id: '부위 식별자', criteria_id: '허용 손상 기준', material: '재질', scan_file: '스캔 파일', meta_file: '스캔 메타데이터', part_number: '부품번호' };
    if (mfg()) { FIELD.criteria_rev = '고객사양 개정번호'; FIELD.criteria_id = '고객사양'; FIELD.zone_id = '검사 구역'; }
    return '<div class="overflow-x-auto"><table class="w-full text-[13px]"><thead><tr class="text-left text-on-surface-variant border-b border-border">' +
      (mfg() ? ['부품', '부품번호 / S/N', '적용 절차', '고객사양', '빠진 정보'] : ['카드', '부위', '적용 절차', '허용 손상 기준', '빠진 정보']).map(function (t) { return '<th class="py-2 pr-3 font-semibold">' + t + '</th>'; }).join('') + '</tr></thead><tbody>' +
      cards.map(function (c) {
        return '<tr class="border-b border-border align-top"><td class="py-2 pr-3 font-code-mono font-semibold">' + esc(c.card_id) + '</td><td class="py-2 pr-3">' + esc(c.title) + '<div class="text-outline font-code-mono text-[12px]">' + esc(c.location_id || '-') + ' · ' + (mfg() ? 'S/N ' + esc(c.serial_number || '-') + ' · 구역 ' : '') + esc(c.zone_id || '-') + '</div></td><td class="py-2 pr-3 font-code-mono text-[12px]">' + esc(c.procedure_id || '-') + '</td><td class="py-2 pr-3 font-code-mono text-[12px]">' + esc(c.criteria_id || '-') + ' Rev ' + esc(c.criteria_rev || '미기재') + '</td><td class="py-2 pr-3">' +
          (c.missing.length ? '<span class="text-verdict-conditional-text font-semibold">' + c.missing.map(function (m) { return FIELD[m] || m; }).join(', ') + '</span>' : '<span class="text-outline">없음</span>') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }
  function pageRequest() {
    var mode_ = 'sample', files = [];
    app.innerHTML = h1('검사 요청', mfg() ? '생산 로트의 부품 스캔 묶음(패키지)을 올리면 에이전트가 검사 보고서와 NCR 초안까지 진행합니다.' : '정기점검 작업카드 묶음(패키지)을 올리면 에이전트가 보고서 초안까지 진행합니다.') +
      box('<div class="flex gap-space-sm mb-space-md">' + btn('내장 샘플 패키지', 'tab-sample', '') + btn('패키지 업로드', 'tab-upload', 'ghost') + '</div>' +
        '<div id="pane-sample"><div id="sample-list" class="flex flex-col gap-space-sm text-[13px]">샘플을 불러오는 중...</div></div>' +
        '<div id="pane-upload" class="hidden">' +
        '<label id="drop" class="block rounded-lg border-2 border-dashed border-outline-variant bg-background p-space-xl text-center cursor-pointer hover:border-secondary">' +
        '<span class="material-symbols-outlined text-[36px] text-outline">cloud_upload</span>' +
        '<div class="font-label-md text-label-md text-chip-text mt-1">패키지 파일을 끌어다 놓거나 눌러서 고르세요</div>' +
        '<div class="text-[13px] text-on-surface-variant mt-1">zip 하나, 또는 package.json과 ' + W('unit') + '별 *_amplitude_db.csv, *_meta.json 여러 개</div>' +
        '<input id="file-input" type="file" multiple accept=".zip,.json,.csv" class="hidden"/></label>' +
        '<div id="file-list" class="mt-space-sm text-[13px] text-on-surface-variant"></div>' +
        '<details class="mt-space-sm text-[13px] text-on-surface-variant"><summary class="cursor-pointer font-semibold">패키지 형식</summary><div class="mt-2 leading-relaxed">' +
        (mfg() ? '<b>package.json</b>: domain("manufacturing"), lot_id, check_type, customer, cards[]. 부품마다 card_id, title, zone_id(A 또는 B), part_number, serial_number, procedure_id(GNU-UT-EX-MFG-01), criteria_id(GNU-SPEC-UT-001), criteria_rev, material, scan_file, meta_file. <a class="underline text-secondary" href="mfg_package_template.json" download>package.json 양식 내려받기</a><br>'
          : '<b>package.json</b>: aircraft, check_type, cards[]. 카드마다 card_id, title, zone_id, location_id, procedure_id, criteria_id, criteria_rev, material, scan_file, meta_file.<br>') +
        '<b>*_amplitude_db.csv</b>: 행=Y, 열=X, 값=건전부 대비 dB. 원시 파형이 아니라 변환된 격자입니다.<br>' +
        '<b>*_meta.json</b>: grid(pitch_mm, rows, cols), reference_db, thickness_mm, probe, equipment_id, scan_date.<br>' +
        '빠진 값은 추정해서 채우지 않습니다. 에이전트가 되묻거나 그 ' + W('unitObj') + ' 평가하지 않습니다.</div></details></div>') +
      box(h2('실행 방식') + '<div class="grid grid-cols-1 md:grid-cols-2 gap-space-md">' +
        '<label class="rounded-lg border border-border p-space-md flex gap-space-sm cursor-pointer"><input type="radio" name="mode" value="llm" checked class="mt-1 accent-[#1f3a5f]"/><div><div class="font-label-md text-label-md text-chip-text">LLM 에이전트</div><div class="text-[13px] text-on-surface-variant leading-relaxed">LLM이 계획을 세우고 도구 순서를 정합니다. 잘못된 호출은 코드가 거부하고, LLM이 멈추면 코드가 이어서 끝냅니다. <span id="mode-llm-note"></span></div></div></label>' +
        '<label class="rounded-lg border border-border p-space-md flex gap-space-sm cursor-pointer"><input type="radio" name="mode" value="fixed" class="mt-1 accent-[#1f3a5f]"/><div><div class="font-label-md text-label-md text-chip-text">고정 순서 (LLM 없음)</div><div class="text-[13px] text-on-surface-variant leading-relaxed">같은 도구를 정해진 순서로 호출합니다. LLM 서버가 없을 때의 대비책이며 결과 수치는 같습니다.</div></div></label></div>') +
      '<div id="req-msg"></div><div class="flex justify-end">' + btn('검사 요청 생성', 'btn-create', '') + '</div><div id="preview"></div>';

    function tabs() {
      $('#pane-sample').classList.toggle('hidden', mode_ !== 'sample');
      $('#pane-upload').classList.toggle('hidden', mode_ !== 'upload');
      $('#tab-sample').className = $('#tab-sample').className.replace(/bg-\S+ text-\S+( border border-border)?/, '');
    }
    $('#tab-sample').addEventListener('click', function () { mode_ = 'sample'; tabs(); paint(); });
    $('#tab-upload').addEventListener('click', function () { mode_ = 'upload'; tabs(); paint(); });
    function paint() {
      var on = 'bg-primary-container text-on-primary', off = 'bg-chip-bg text-chip-text border border-border';
      [['#tab-sample', 'sample'], ['#tab-upload', 'upload']].forEach(function (p) {
        var b = $(p[0]);
        b.className = 'px-4 py-2.5 rounded-lg font-label-md text-label-md transition-colors ' + (mode_ === p[1] ? on : off);
      });
    }
    paint();
    api('/api/samples?domain=' + mode()).then(function (list) {
      if (!list.length && mfg()) {
        // 제조 실데이터가 없어 내장 샘플을 두지 않았다. 업로드 탭을 먼저 보여 준다.
        $('#sample-list').innerHTML = note('제조 검사 모드에는 내장 샘플이 없습니다. 제조 공정의 실제 C-scan 데이터를 확보하지 못했기 때문입니다. "패키지 업로드"에서 형식에 맞는 로트 패키지를 올리면 실행됩니다.', 'warn');
        mode_ = 'upload'; tabs(); paint();
        return;
      }
      $('#sample-list').innerHTML = list.length ? list.map(function (s, i) {
        return '<label class="rounded-lg border border-border p-space-md flex gap-space-sm cursor-pointer"><input type="radio" name="sample" value="' + esc(s.id) + '"' + (i === 0 ? ' checked' : '') + ' class="mt-1 accent-[#1f3a5f]"/><div class="flex-1"><div class="font-code-mono font-semibold text-chip-text">' + esc(s.id) + '</div><div class="text-on-surface-variant">' + W('subject') + ' ' + esc(s.aircraft) + ' · ' + esc(s.check_type) + ' · ' + W('unitLong') + ' ' + s.cards + '건</div><div class="text-outline leading-relaxed mt-1">' + esc(s.data_note) + '</div>' +
          (s.zip ? '<a class="underline text-secondary" href="' + s.zip + '">zip 내려받기</a> <span class="text-outline">(내려받은 파일을 "패키지 업로드"로 올려 볼 수 있습니다)</span>' : '') + '</div></label>';
      }).join('') : '내장 샘플이 없습니다.';
    });
    function setFiles(list) {
      files = Array.prototype.slice.call(list);
      $('#file-list').innerHTML = files.length ? '선택한 파일 ' + files.length + '개: ' + files.map(function (f) { return esc(f.name); }).join(', ') : '';
    }
    $('#file-input').addEventListener('change', function (e) { setFiles(e.target.files); });
    var drop = $('#drop');
    ['dragover', 'dragenter'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('border-secondary'); }); });
    drop.addEventListener('dragleave', function () { drop.classList.remove('border-secondary'); });
    drop.addEventListener('drop', function (e) { e.preventDefault(); drop.classList.remove('border-secondary'); setFiles(e.dataTransfer.files); });
    setTimeout(function () {
      if (window.__llm && !window.__llm.ok) { $('#mode-llm-note').innerHTML = '<b class="text-verdict-fail-text">지금은 LLM 서버에 연결되지 않아 고정 순서로 실행됩니다.</b>'; }
      else if (window.__llm) { $('#mode-llm-note').innerHTML = '<span class="font-code-mono">' + esc(window.__llm.model) + '</span> 사용.'; }
    }, 800);

    $('#btn-create').addEventListener('click', function () {
      var fd = new FormData();
      fd.append('mode', $('input[name=mode]:checked').value);
      fd.append('domain', mode());
      if (mode_ === 'sample') {
        var s = $('input[name=sample]:checked');
        if (!s) { $('#req-msg').innerHTML = note('샘플을 고르세요.', 'err'); return; }
        fd.append('sample', s.value);
      } else {
        if (!files.length) { $('#req-msg').innerHTML = note('올릴 파일을 고르세요.', 'err'); return; }
        files.forEach(function (f) { fd.append('files', f, f.name); });
      }
      $('#btn-create').disabled = true;
      $('#req-msg').innerHTML = note('패키지를 확인하는 중...');
      api('/api/sessions', { method: 'POST', body: fd }).then(function (st) {
        state = st; setSid(st.session_id); $('#session-chip').textContent = st.session_id;
        $('#req-msg').innerHTML = note('검사 요청을 만들었습니다. 세션 ' + esc(st.session_id) + ' · ' + esc(st.origin));
        $('#preview').innerHTML = box(h2('패키지 ' + st.package.package_id) +
          '<div class="text-[13px] text-on-surface-variant mb-space-sm">' + W('subject') + ' ' + esc(st.package.aircraft) + ' ' + esc(st.package.aircraft_note || '') + ' · ' + esc(st.package.check_type) + ' · ' + W('unitLong') + ' ' + st.cards.length + '건<br>실행 방식: ' + esc(st.mode) + '</div>' +
          cardTable(st.cards) + '<div class="flex justify-end mt-space-md">' + linkBtn('에이전트 실행', 'agent.html') + '</div>');
        $('#preview').scrollIntoView({ behavior: 'smooth' });
      }).catch(function (e) { $('#req-msg').innerHTML = note('요청을 만들지 못했습니다: ' + esc(e.message), 'err'); })
        .then(function () { $('#btn-create').disabled = false; });
    });
  }

  // ---------------------------------------------------------------- ② 에이전트
  var TOOL_KO = {
    declare_plan: '계획 수립', list_package: '패키지 항목 확인', validate_scan: '스캔 검증', select_criteria: '기준 선택',
    inspect_package: '측정과 한도 대조', search_history: '이전 점검 기록 비교', draft_item_report: '카드별 평가 초안',
    compile_package_report: '기체 단위 보고서 초안', record_signoff: '검사원 서명 기록'
  };
  var TOOL_KO_MFG = {
    list_package: '로트 패키지 항목 확인', select_criteria: '고객사양 선택', inspect_package: '측정과 사양 한도 대조',
    search_history: '과거 NCR 이력 조회', draft_item_report: '부품별 평가 초안', compile_package_report: '로트 보고서와 NCR 초안'
  };
  function toolKo(name) { return (mfg() && TOOL_KO_MFG[name]) || TOOL_KO[name] || name; }
  var STAGES = ['list_package', 'validate_scan', 'select_criteria', 'inspect_package', 'search_history', 'draft_item_report', 'compile_package_report'];
  var BY = { llm: 'LLM', fixed: '코드', user: '검사원' };
  function toolLine(name, args, by, ok, result) {
    var detail = '';
    if (!ok) { detail = '거부: ' + (result && result.error || ''); }
    else if (!result) { detail = ''; }
    else if (name === 'declare_plan') { detail = (result.steps || []).length + '단계'; }
    else if (name === 'list_package') { detail = W('unit') + ' ' + result.cards.length + '건' + (result.cards_with_missing_info.length ? ', 정보 누락 ' + result.cards_with_missing_info.join(', ') : ''); }
    else if (name === 'validate_scan') { detail = result.checked + '건 확인' + (result.failed.length ? ', 실패 ' + result.failed.join(', ') : ', 모두 통과'); }
    else if (name === 'select_criteria') { detail = result.cards.map(function (c) { return c.card_id + ' ' + ({ selected: '선택', needs_revision: '개정번호 필요', blocked: '불가', held: '보류' }[c.status] || c.status); }).join(', '); }
    else if (name === 'inspect_package') { detail = result.cards.map(function (c) { return c.card_id + ' ' + (c.status === 'evaluated' ? c.disposition_ko : c.status === 'procedure_mismatch' ? '절차 부적합' : '건너뜀'); }).join(', '); }
    else if (name === 'search_history' && mfg()) { detail = (result.with_past_ncr || []).length ? '같은 부품번호의 과거 NCR 있음 ' + result.with_past_ncr.join(', ') : '과거 NCR 없음 (' + result.source + ')'; }
    else if (name === 'search_history') { detail = result.growth_suspected.length ? '손상 확대 의심 ' + result.growth_suspected.join(', ') : '확대 의심 없음'; }
    else if (name === 'draft_item_report') { detail = result.drafted + '건 작성'; }
    else if (name === 'compile_package_report') { detail = result.report_id + ' · 종합 의견 ' + (result.opinion_source === 'llm' ? 'LLM 작성(검증 통과)' : '코드 문장'); }
    else if (name === 'record_signoff') { detail = result.signoffs.map(function (s) { return s.card_id + ' ' + (s.decision === 'approve' ? '승인' : '반려'); }).join(', '); }
    var shown = {};
    Object.keys(args || {}).forEach(function (k) { var v = args[k]; if (v !== null && v !== '' && !(Array.isArray(v) && !v.length)) { shown[k] = v; } });
    var argText = Object.keys(shown).length && name !== 'declare_plan' ? ' ' + JSON.stringify(shown) : '';
    return '<div class="flex items-start gap-2 py-1.5 border-b border-border text-[13px]"><span class="material-symbols-outlined text-[18px] ' + (ok ? 'text-verdict-pass-graphic' : 'text-verdict-fail-graphic') + '">' + (ok ? 'check_circle' : 'block') + '</span>' +
      '<div class="flex-1 min-w-0"><span class="font-label-md text-[13px] text-chip-text">' + toolKo(name) + '</span> <span class="font-code-mono text-[12px] text-outline break-all">' + esc(name) + esc(argText) + '</span><div class="' + (ok ? 'text-on-surface-variant' : 'text-verdict-fail-text') + ' break-words">' + esc(detail) + '</div></div>' +
      '<span class="px-1.5 py-0.5 rounded font-code-mono text-[11px] font-semibold ' + ({ llm: 'role-ai', fixed: 'role-code', user: 'role-human' }[by] || 'bg-chip-bg text-chip-text') + '">' + (BY[by] || by) + '</span></div>';
  }
  function pageAgent() {
    if (!state) { return noSession(); }
    var busy = false;
    app.innerHTML = h1('에이전트 진행', '계획, 도구 호출, 되묻기가 실제 실행 순서대로 표시됩니다.') +
      '<div class="flex flex-wrap gap-2 text-[13px]">' + chip('세션 ' + state.session_id) + chip('패키지 ' + state.package.package_id) + chip(W('unit') + ' ' + state.cards.length + '건') + '</div>' +
      '<div class="text-[13px] text-on-surface-variant">실행 방식: ' + esc(state.mode) + '</div>' +
      '<section id="stages" class="grid grid-cols-2 md:grid-cols-7 gap-space-xs"></section>' +
      '<div id="questions" class="flex flex-col gap-space-md"></div>' +
      '<div class="grid grid-cols-1 lg:grid-cols-3 gap-space-lg items-start">' +
      box(h2('계획') + '<ol id="plan" class="list-decimal pl-5 text-[13px] leading-relaxed text-on-surface-variant"></ol>', 'lg:col-span-1') +
      box('<div class="flex items-center justify-between">' + h2('도구 호출 기록') + '<span class="flex items-center gap-2">' + orb('working', 20, false, 'orb-busy') + '<span id="busy" class="text-[13px] text-secondary"></span></span></div><div id="log"></div><div id="final" class="mt-space-md"></div>', 'lg:col-span-2') + '</div>' +
      box(h2('에이전트에게 말하기') + '<p class="text-[13px] text-on-surface-variant mb-space-sm">질문에 대한 답이나 검사원 피드백을 문장으로 쓸 수 있습니다. 예: "' + (mfg() ? 'PART-04' : 'CARD-05') + ' 개정번호는 Rev B입니다", "검사원 김검사: ' + (mfg() ? 'PART-03' : 'CARD-03') + ' 반려합니다. IND-02는 제외."</p><form id="say" class="flex gap-space-sm"><input id="say-input" class="' + INPUT + '" placeholder="에이전트에게 보낼 문장" autocomplete="off"/>' + btn('보내기', 'say-btn', '', 'data-submit="1"') + '</form>') +
      '<div class="flex justify-end" id="next"></div>';

    function paint() {
      var done = {};
      state.calls.forEach(function (c) { if (c.ok) { done[c.tool] = true; } });
      var waiting = state.questions.some(function (q) { return !q.answered; });
      $('#stages').innerHTML = STAGES.map(function (t, i) {
        var st = done[t] ? 'done' : 'todo';
        if (t === 'select_criteria' && waiting) { st = 'wait'; }
        if (waiting && STAGES.indexOf(t) > 2) { st = 'todo'; }
        if (!state.report_ready && STAGES.indexOf(t) > 2 && state.next !== 'DONE' && !waiting && done[t] && state.next && STAGES.indexOf(state.next) <= i) { st = 'todo'; }
        var c = st === 'done' ? 'bg-verdict-pass-bg text-verdict-pass-text' : st === 'wait' ? 'bg-verdict-conditional-bg text-verdict-conditional-text' : 'bg-chip-bg text-outline';
        return '<div class="rounded-lg p-space-sm ' + c + '"><div class="font-code-mono text-[11px]">0' + (i + 1) + '</div><div class="font-label-md text-[12px] leading-tight">' + toolKo(t) + '</div><div class="text-[11px]">' + (st === 'done' ? '완료' : st === 'wait' ? '답 대기' : '대기') + '</div></div>';
      }).join('');
      $('#plan').innerHTML = state.plan.length ? state.plan.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') : '<span class="text-outline">아직 계획이 없습니다.</span>';
      var qs = state.questions.filter(function (q) { return !q.answered; });
      $('#questions').innerHTML = qs.map(function (q) {
        return '<section class="rounded-xl border-2 border-verdict-conditional-graphic bg-verdict-conditional-bg p-space-lg flex flex-col gap-space-sm">' +
          '<div class="flex items-center gap-2 text-verdict-conditional-text font-label-md text-label-md"><span class="material-symbols-outlined">contact_support</span>에이전트가 정보를 물어봅니다 · ' + esc(q.card_id) + '</div>' +
          '<p class="text-body-sm text-on-surface">' + esc(q.text) + '</p><div class="flex flex-wrap gap-space-sm">' +
          q.options.map(function (o) { return '<button type="button" class="q-rev px-4 py-2 rounded-lg bg-primary-container text-on-primary font-label-md text-label-md hover:bg-primary" data-card="' + esc(q.card_id) + '" data-rev="' + esc(o) + '">Rev ' + esc(o) + ' 적용</button>'; }).join('') +
          '<button type="button" class="q-hold px-4 py-2 rounded-lg bg-surface border border-border text-chip-text font-label-md text-label-md" data-card="' + esc(q.card_id) + '">모름 · 이 ' + W('unitTopic') + ' 보류</button></div></section>';
      }).join('');
      $all('.q-rev').forEach(function (b) { b.addEventListener('click', function () { go({ kind: 'answer', card_id: b.dataset.card, rev: b.dataset.rev }); }); });
      $all('.q-hold').forEach(function (b) { b.addEventListener('click', function () { go({ kind: 'answer', card_id: b.dataset.card, hold: true, reason: '개정번호 확인 불가' }); }); });
      $('#next').innerHTML = state.report_ready ? linkBtn('판정 결과 보기', 'results.html') : '';
      var g = state.guard;
      if (g && g.llm_calls) {
        $('#busy').textContent = busy ? '실행 중...' : 'LLM 호출 ' + g.llm_calls + '건 중 코드가 거부 ' + g.llm_calls_blocked + '건';
      }
    }
    function logFromState() {
      $('#log').innerHTML = state.calls.map(function (c) { return toolLine(c.tool, c.args, c.by, c.ok, c.ok ? c.result : { error: c.error }); }).join('');
    }
    function go(body) {
      if (busy) { return; }
      busy = true; $('#busy').textContent = '실행 중...'; $('#final').innerHTML = '';
      document.body.classList.add('busy'); mountOrbs(app);
      $all('.q-rev,.q-hold,#say-btn').forEach(function (b) { b.disabled = true; });
      runTurn(body, function (kind, d) {
        if (kind === 'tool') {
          $('#log').insertAdjacentHTML('beforeend', toolLine(d.name, d.args, d.by, d.ok, d.result));
          $('#log').lastElementChild.classList.add('log-in');  // 새로 들어온 호출만 살짝 올라오며 나타난다
          if (d.name === 'declare_plan' && d.ok) { $('#plan').innerHTML = d.result.steps.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join(''); }
        } else if (kind === 'llm') {
          $('#busy').textContent = '실행 중... (LLM 응답 ' + d.sec + '초)';
        } else if (kind === 'fallback') {
          $('#log').insertAdjacentHTML('beforeend', '<div class="py-1.5 border-b border-border text-[13px] text-verdict-conditional-text">대체 경로: ' + esc(d.reason) + '</div>');
        } else if (kind === 'error') {
          $('#log').insertAdjacentHTML('beforeend', '<div class="py-1.5 text-[13px] text-verdict-fail-text">오류: ' + esc(d.error) + '</div>');
        } else if (kind === 'final') {
          $('#final').innerHTML = note(esc(d.text).replace(/\n/g, '<br>'));
        }
      }).catch(function (e) { $('#final').innerHTML = note('실행하지 못했습니다: ' + esc(e.message), 'err'); })
        .then(function () { busy = false; document.body.classList.remove('busy'); $('#busy').textContent = ''; $('#say-btn').disabled = false; paint(); });
    }
    $('#say').addEventListener('submit', function (e) {
      e.preventDefault();
      var v = $('#say-input').value.trim();
      if (v) { $('#say-input').value = ''; go({ kind: 'feedback', text: v }); }
    });
    $('#say-btn').addEventListener('click', function () { $('#say').dispatchEvent(new Event('submit', { cancelable: true })); });
    logFromState(); paint();
    if (!state.started) { go({ kind: 'start' }); }
  }

  // ---------------------------------------------------------------- ③ 판정 결과
  function gauge(ev, major) {
    var lim = ev.limits;
    if (lim.max_dimension_mm !== undefined) { return gaugeMfg(ev, major); }
    var max = Math.max(lim.repairable_mm * 1.4, major * 1.1);
    function pct(v) { return Math.min(100, v / max * 100).toFixed(1); }
    return '<div class="mt-space-sm"><div class="relative h-6 rounded bg-chip-bg overflow-hidden">' +
      '<div class="absolute inset-y-0 left-0" style="width:' + pct(lim.allowable_mm) + '%;background:rgba(31,157,92,.22)"></div>' +
      '<div class="absolute inset-y-0" style="left:' + pct(lim.allowable_mm) + '%;width:' + (pct(lim.repairable_mm) - pct(lim.allowable_mm)) + '%;background:rgba(224,148,34,.22)"></div>' +
      '<div class="absolute inset-y-0" style="left:' + pct(lim.repairable_mm) + '%;right:0;background:rgba(214,69,53,.24)"></div>' +
      '<div class="absolute inset-y-0 w-[3px] bg-primary" style="left:calc(' + pct(major) + '% - 1px)"></div></div>' +
      '<div class="flex justify-between text-[12px] text-on-surface-variant font-code-mono mt-1"><span>0</span><span>허용 ' + lim.allowable_mm + ' mm</span><span>수리 가능 ' + lim.repairable_mm + ' mm</span><span>측정 ' + major + ' mm</span></div></div>';
  }
  // 제조: 사양 한도 하나와 그 주변의 보류 구간(측정 불확실도)을 표시한다
  function gaugeMfg(ev, major) {
    var L = ev.limits.max_dimension_mm, near = ev.near_limit_ratio || 0, lo = L * (1 - near), hi = L * (1 + near);
    var max = Math.max(L * 1.6, major * 1.1);
    function pct(v) { return Math.min(100, v / max * 100).toFixed(1); }
    return '<div class="mt-space-sm"><div class="relative h-6 rounded bg-chip-bg overflow-hidden">' +
      '<div class="absolute inset-y-0 left-0" style="width:' + pct(lo) + '%;background:rgba(31,157,92,.22)"></div>' +
      '<div class="absolute inset-y-0" style="left:' + pct(lo) + '%;width:' + (pct(hi) - pct(lo)) + '%;background:rgba(224,148,34,.22)"></div>' +
      '<div class="absolute inset-y-0" style="left:' + pct(hi) + '%;right:0;background:rgba(214,69,53,.24)"></div>' +
      '<div class="absolute inset-y-0 w-[3px] bg-primary" style="left:calc(' + pct(major) + '% - 1px)"></div></div>' +
      '<div class="flex justify-between text-[12px] text-on-surface-variant font-code-mono mt-1"><span>0</span><span>사양 한도 ' + L + ' mm (±' + Math.round(near * 100) + '%는 보류)</span><span>측정 ' + major + ' mm</span></div></div>';
  }
  function cardDetail(c) {
    var o = '<div class="flex flex-wrap items-center gap-2 mb-space-sm"><span class="font-headline-md text-headline-md font-bold text-primary">' + esc(c.card_id) + '</span>' + tag(c.disposition) +
      (c.approved ? chip('검사원 승인') : '') + (c.stale ? chip('재평가 필요') : '') + '</div>' +
      '<div class="text-[13px] text-on-surface-variant mb-space-sm">' + esc(c.title) + '</div>';
    if (c.summary) { o += note(esc(c.summary)); }
    else if (c.blocked_reason) { o += note(esc(c.blocked_reason), 'warn'); }
    o += '<div class="grid grid-cols-2 md:grid-cols-4 gap-space-sm text-[13px] my-space-md">' +
      [mfg() ? ['부품번호 / S/N', (c.part_number || '-') + ' / ' + (c.serial_number || '-') + ' · 구역 ' + (c.zone_id || '-')] : ['부위', (c.location_id || '-') + ' · ' + (c.zone_id || '-')], ['적용 절차', c.procedure_id || '-'], [W('criteria'), (c.criteria_id || '-') + ' Rev ' + (c.criteria_rev || '미지정') + (c.rev_source === 'user' ? ' (사용자 답)' : c.rev_source === 'inspector' ? ' (검사원 정정)' : '')], ['재질 / 두께', (c.material || '-') + ' / ' + (c.thickness_mm || '-') + ' mm'],
        ['데이터', c.data_source || '-'], ['스캔 일자', c.scan_date || '-'], ['격자', c.grid ? c.grid.rows + ' × ' + c.grid.cols + ', ' + c.grid.pitch_mm + ' mm' : '-'],
        ['절차 적합성', c.procedure_check ? (c.procedure_check.ok ? '적합 (' + c.procedure_check.range_mm.join('~') + ' mm)' : '부적합') : '확인 전']].map(function (p) {
          return '<div class="rounded bg-background p-space-sm"><div class="text-outline text-[12px]">' + p[0] + '</div><div class="font-code-mono text-[12px] text-chip-text break-words">' + esc(p[1]) + '</div></div>';
        }).join('') + '</div>';
    if (c.validation && c.validation.ok) {
      o += '<img class="w-full rounded border border-border" alt="C-scan ' + esc(c.card_id) + '" src="/api/sessions/' + state.session_id + '/cards/' + c.card_id + '/heatmap.png?t=' + Date.now() + '"/>' +
        '<div class="text-[12px] text-outline mt-1">색: 건전부 대비 dB. 흰 선: 6 dB drop 경계. 빨간 상자: 측정된 지시' + (c.evaluation ? '' : ' (이 카드는 측정하지 않아 지시 표시 없음)') + '.</div>';
    }
    if (c.evaluation) {
      var ev = c.evaluation, act = c.indications.filter(function (i) { return c.excluded.indexOf(i.id) < 0; });
      if (act.length) { o += gauge(ev, act[0].major_mm); }
      o += '<div class="overflow-x-auto mt-space-md"><table class="w-full text-[13px]"><thead><tr class="text-left text-on-surface-variant border-b border-border">' +
        ['지시', '중심 (x, y) mm', '장축 mm', '단축 mm', '면적 mm²', '최대 감쇠 dB', '비고'].map(function (t) { return '<th class="py-1.5 pr-3 font-semibold">' + t + '</th>'; }).join('') + '</tr></thead><tbody>' +
        (c.indications.length ? c.indications.map(function (i) {
          var ex = c.excluded.indexOf(i.id) >= 0;
          return '<tr class="border-b border-border font-code-mono text-[12px]' + (ex ? ' text-outline line-through' : '') + '"><td class="py-1.5 pr-3 font-semibold">' + i.id + '</td><td class="pr-3">(' + i.centroid_x_mm + ', ' + i.centroid_y_mm + ')</td><td class="pr-3">' + i.major_mm + '</td><td class="pr-3">' + i.minor_mm + '</td><td class="pr-3">' + i.area_mm2 + '</td><td class="pr-3">' + i.peak_drop_db + '</td><td class="pr-3 font-body-sm no-underline">' + (ex ? '검사원 제외' : i.touches_scan_edge ? '스캔 가장자리 접촉' : '') + '</td></tr>';
        }).join('') : '<tr><td colspan="7" class="py-2 text-outline">6 dB drop으로 잡힌 지시 없음</td></tr>') + '</tbody></table></div>';
      if (ev.findings.length) {
        o += '<div class="mt-space-md"><div class="font-label-md text-label-md text-chip-text mb-1">한도 대조 근거 (' + esc(ev.rule_set) + ', ' + esc(ev.zone_id) + ' ' + esc(ev.zone_name) + ')</div>' + ev.findings.map(function (f) {
          return '<div class="text-[13px] py-1 border-b border-border"><span class="font-code-mono font-semibold">' + esc(f.rule_id) + '</span> · ' + esc(f.indication) + ' · ' + esc(f.text) + '</div>';
        }).join('') + '</div>';
      }
      if (ev.area_pct !== undefined && ev.area_pct !== null && ev.limits.max_area_pct !== null) {
        o += '<div class="text-[13px] text-on-surface-variant mt-space-sm">누적 지시 면적 <span class="font-code-mono">' + ev.area_pct + '%</span> (스캔 영역 대비, 사양 한도 <span class="font-code-mono">' + ev.limits.max_area_pct + '%</span>)</div>';
      }
      ev.warnings.forEach(function (w) { o += '<div class="mt-space-sm">' + note('주의: ' + esc(w.text), 'warn') + '</div>'; });
      if (mfg() && c.disposition === 'EXCEED') { o += '<div class="mt-space-sm">' + note('보고서에 이 부품의 부적합보고서(NCR) 초안이 들어갑니다. 처분은 검사원 확인 뒤 자재심의(MRB)에서 정합니다.', 'err') + '</div>'; }
    }
    if (c.history) {
      o += '<div class="mt-space-md">' + note('<b>' + W('history') + '</b> · ' + esc(c.history.text), c.history.grew || (mfg() && c.history.found) ? 'warn' : '') + '</div>';
    }
    return o;
  }
  function pageResults() {
    if (!state) { return noSession(); }
    if (!state.started) { app.innerHTML = h1('판정 결과') + note('아직 에이전트를 실행하지 않았습니다.') + '<div>' + linkBtn('에이전트 실행', 'agent.html') + '</div>'; return; }
    var counts = { ALLOW: 0, REPAIR: 0, EXCEED: 0, NOT_EVALUATED: 0 };
    state.cards.forEach(function (c) { counts[c.disposition]++; });
    var pending = state.questions.filter(function (q) { return !q.answered; });
    app.innerHTML = h1('판정 결과', W('subject') + ' ' + state.package.aircraft + ' · ' + state.package.check_type + ' · ' + W('unitLong') + ' ' + state.cards.length + '건') +
      (pending.length ? note('답을 기다리는 질문이 있습니다. <a class="underline" href="agent.html">에이전트 화면</a>에서 답해 주세요.', 'warn') : '') +
      (state.report ? note(esc(state.report.summary)) : '') +
      '<div class="grid grid-cols-2 md:grid-cols-4 gap-space-md">' + ['ALLOW', 'REPAIR', 'EXCEED', 'NOT_EVALUATED'].map(function (k) {
        return '<div class="stat-tile rounded-xl p-space-md ' + DISP[k].cls + '"><div class="font-label-md text-[13px]">' + dispKo(k) + '</div><div class="font-display-stat text-display-stat glow-num">' + counts[k] + '</div></div>';
      }).join('') + '</div>' +
      box(h2(W('unitLong') + '별 처분 초안') + '<div class="overflow-x-auto"><table class="w-full text-[13px]"><thead><tr class="text-left text-on-surface-variant border-b border-border">' +
        (mfg() ? ['부품', '부품번호', '사양', '지시', '최대 장축', '과거 NCR', '처분 초안', '검사원'] : ['카드', '부위', '기준', '지시', '최대 장축', '이전 기록 대비', '처분 초안', '검사원']).map(function (t) { return '<th class="py-2 pr-3 font-semibold">' + t + '</th>'; }).join('') + '</tr></thead><tbody id="rows"></tbody></table></div>' +
        '<div class="text-[12px] text-outline mt-space-sm">행을 누르면 아래에 상세가 표시됩니다. 처분은 초안이며 기준 값은 시연용 가상 값입니다.</div>') +
      '<div id="detail"></div><div class="flex justify-end">' + (state.report_ready ? linkBtn('보고서 검토와 승인', 'report.html') : '') + '</div>';
    $('#rows').innerHTML = state.cards.map(function (c) {
      var act = c.indications.filter(function (i) { return c.excluded.indexOf(i.id) < 0; });
      var h = c.history, hist = !h ? '-' : mfg() ? (h.found ? h.records + '건' : '없음') : !h.found ? '기록 없음' : h.change_mm === null ? '측정 없음' : ((h.change_mm > 0 ? '+' : '') + h.change_mm + ' mm' + (h.grew ? ' · 확대 의심' : ''));
      var so = c.signoffs.length ? c.signoffs[c.signoffs.length - 1] : null;
      return '<tr class="border-b border-border cursor-pointer hover:bg-background" data-card="' + esc(c.card_id) + '"><td class="py-2 pr-3 font-code-mono font-semibold">' + esc(c.card_id) + '</td><td class="pr-3 font-code-mono text-[12px]">' + esc(c.location_id || '-') + '<br><span class="text-outline">' + (mfg() ? 'S/N ' + esc(c.serial_number || '-') + ' · 구역 ' : '') + esc(c.zone_id || '') + '</span></td><td class="pr-3 font-code-mono text-[12px]">Rev ' + esc(c.criteria_rev || '미지정') + '</td><td class="pr-3">' + (c.evaluation ? act.length : '-') + '</td><td class="pr-3 font-code-mono">' + (act.length ? act[0].major_mm + ' mm' : '-') + '</td><td class="pr-3' + (h && h.grew ? ' text-verdict-fail-text font-semibold' : '') + '">' + esc(hist) + '</td><td class="pr-3">' + tag(c.disposition) + '</td><td class="pr-3">' + (c.approved ? esc(so.user) + ' 승인' : so && so.decision === 'reject' ? '반려 후 재평가' : '대기') + '</td></tr>';
    }).join('');
    function show(id) {
      var c = state.cards.filter(function (x) { return x.card_id === id; })[0];
      $all('#rows tr').forEach(function (r) { r.classList.toggle('bg-surface-container-low', r.dataset.card === id); });
      $('#detail').innerHTML = box(cardDetail(c));
    }
    $all('#rows tr').forEach(function (r) { r.addEventListener('click', function () { show(r.dataset.card); $('#detail').scrollIntoView({ behavior: 'smooth' }); }); });
    var first = state.cards.filter(function (c) { return c.disposition === 'EXCEED'; })[0] || state.cards[0];
    if (first) { show(first.card_id); }
  }

  // ---------------------------------------------------------------- ④ 보고서
  function pageReport() {
    if (!state) { return noSession(); }
    var busy = false;
    app.className = 'max-w-[1500px] mx-auto p-margin flex flex-col gap-space-lg';
    app.setAttribute('data-wide', '1');
    var name = ''; try { name = localStorage.getItem(NAME_KEY) || ''; } catch (e) {}
    app.innerHTML = h1('보고서 검토와 승인', W('report') + ' 초안입니다. ' + W('unit') + '별로 승인하거나 반려하면 반영해서 다시 평가합니다.') +
      '<div id="rep-status"></div>' +
      '<div class="grid grid-cols-1 xl:grid-cols-5 gap-space-lg items-start">' +
      '<div class="xl:col-span-3 panel bg-surface rounded-xl shadow-[0_0_0_1px_#E1E4EA] overflow-hidden"><div class="flex items-center justify-between px-space-md py-space-sm border-b border-border"><span class="font-label-md text-label-md text-chip-text">보고서 미리보기</span><span class="flex gap-space-sm">' + btn('인쇄 / PDF 저장', 'btn-print', 'ghost') + '<a id="open-report" target="_blank" class="px-4 py-2.5 rounded-lg font-label-md text-label-md bg-chip-bg text-chip-text border border-border">새 창</a></span></div><iframe id="frame" class="w-full h-[900px] bg-background" title="보고서"></iframe></div>' +
      '<div class="xl:col-span-2 flex flex-col gap-space-md">' +
      box(h2('검사원') + '<input id="insp" class="' + INPUT + '" placeholder="검사원 이름 (예: 김검사)" value="' + esc(name) + '"/><p class="text-[12px] text-outline mt-1">서명은 이름을 적은 검사원이 버튼을 눌러 직접 요청할 때만 기록됩니다. 이름이 비었거나 AI이면 거부됩니다.</p><div class="mt-space-sm">' + btn('남은 ' + W('unit') + ' 전체 승인', 'btn-all', '') + '</div>') +
      box(h2(W('unit') + '별 검토') + '<div id="cards" class="flex flex-col gap-space-sm"></div>') +
      box(h2('처리 기록') + '<div id="log" class="text-[13px]"></div><div id="final" class="mt-space-sm"></div>') + '</div></div>' +
      '<div class="flex justify-end" id="next"></div>';

    function paint() {
      var r = state.report;
      if (!state.report_ready) {
        $('#rep-status').innerHTML = note(state.report ? '반려·정정 후 재평가가 끝나지 않아 보고서를 표시할 수 없습니다.' : '보고서 초안이 아직 없습니다. <a class="underline" href="agent.html">에이전트 화면</a>에서 진행해 주세요.', 'warn');
        $('#frame').removeAttribute('src');
      } else {
        $('#rep-status').innerHTML = note('<b>' + esc(r.status_ko) + '</b> · ' + esc(r.report_id) + ' · 승인 ' + r.approved_cards.length + '/' + state.cards.length + '건', r.status === 'APPROVED' ? '' : 'warn');
        var url = '/api/sessions/' + state.session_id + '/report?t=' + Date.now();
        $('#frame').src = url; $('#open-report').href = url;
      }
      $('#cards').innerHTML = state.cards.map(function (c) {
        var so = c.signoffs.length ? c.signoffs[c.signoffs.length - 1] : null;
        var procs = state.procedures || [];
        return '<div class="rounded-lg border border-border p-space-sm" data-card="' + esc(c.card_id) + '">' +
          '<div class="flex flex-wrap items-center gap-2"><span class="font-code-mono font-semibold text-chip-text">' + esc(c.card_id) + '</span>' + tag(c.disposition) +
          '<span class="ml-auto text-[12px] ' + (c.approved ? 'text-verdict-pass-text font-semibold' : 'text-outline') + '">' + (c.approved ? esc(so.user) + ' 승인 ' + esc(so.ts.slice(11)) : so && so.decision === 'reject' ? '반려됨 · 재평가 후 승인 대기' : '승인 대기') + '</span></div>' +
          '<div class="text-[12px] text-on-surface-variant mt-1 leading-relaxed">' + esc(c.summary || c.blocked_reason || '') + '</div>' +
          (c.approved ? '' : '<div class="flex gap-space-sm mt-space-sm"><button type="button" class="b-approve px-3 py-1.5 rounded-lg bg-verdict-pass-graphic text-white font-label-md text-[13px]">승인</button><button type="button" class="b-toggle px-3 py-1.5 rounded-lg bg-chip-bg border border-border text-chip-text font-label-md text-[13px]">반려 / 정정</button></div>' +
            '<div class="rej hidden mt-space-sm flex flex-col gap-space-xs text-[13px]"><input class="r-reason ' + INPUT + '" placeholder="반려 사유"/>' +
            (c.indications.length ? '<div class="flex flex-wrap gap-space-sm items-center"><span class="text-outline">제외할 지시:</span>' + c.indications.filter(function (i) { return c.excluded.indexOf(i.id) < 0; }).map(function (i) { return '<label class="flex items-center gap-1 font-code-mono text-[12px]"><input type="checkbox" class="r-ind" value="' + i.id + '"/>' + i.id + ' (' + i.major_mm + ' mm)</label>'; }).join('') + '</div>' : '') +
            '<div class="flex flex-wrap gap-space-sm items-center"><span class="text-outline">절차 정정:</span><select class="r-proc h-9 px-2 rounded border border-border bg-background font-code-mono text-[12px]"><option value="">정정 안 함</option>' + procs.filter(function (p) { return p !== c.procedure_id; }).map(function (p) { return '<option>' + p + '</option>'; }).join('') + '</select>' +
            '<span class="text-outline">개정번호 정정:</span><select class="r-rev h-9 px-2 rounded border border-border bg-background font-code-mono text-[12px]"><option value="">정정 안 함</option>' + (c.rev_options || []).filter(function (v) { return v !== c.criteria_rev; }).map(function (v) { return '<option>' + v + '</option>'; }).join('') + '</select></div>' +
            '<div><button type="button" class="b-reject px-3 py-1.5 rounded-lg bg-verdict-fail-graphic text-white font-label-md text-[13px]">반려하고 재평가</button></div></div>') + '</div>';
      }).join('');
      $all('#cards > div').forEach(function (el) {
        var id = el.dataset.card;
        var a = $('.b-approve', el), t = $('.b-toggle', el), rj = $('.b-reject', el);
        if (a) { a.addEventListener('click', function () { sign({ card_id: id, decision: 'approve' }); }); }
        if (t) { t.addEventListener('click', function () { $('.rej', el).classList.toggle('hidden'); }); }
        if (rj) {
          rj.addEventListener('click', function () {
            sign({ card_id: id, decision: 'reject', reason: $('.r-reason', el).value.trim(),
              exclude_indications: $all('.r-ind:checked', el).map(function (x) { return x.value; }),
              procedure_id: $('.r-proc', el).value || null, criteria_rev: $('.r-rev', el).value || null });
          });
        }
      });
      $('#btn-all').disabled = !state.report_ready || state.cards.every(function (c) { return c.approved; });
      $('#next').innerHTML = state.report && state.report.status === 'APPROVED' && state.report_ready ? linkBtn('이메일 발송으로', 'email.html') : '';
    }
    function sign(body) {
      if (busy) { return; }
      var nm = $('#insp').value.trim();
      try { localStorage.setItem(NAME_KEY, nm); } catch (e) {}
      body.kind = 'signoff'; body.inspector = nm;
      busy = true; $('#final').innerHTML = note('처리 중...');
      runTurn(body, function (kind, d) {
        if (kind === 'tool') { $('#log').insertAdjacentHTML('beforeend', toolLine(d.name, d.args, d.by, d.ok, d.result)); }
        else if (kind === 'final') { $('#final').innerHTML = note(esc(d.text).replace(/\n/g, '<br>'), /기록하지 않았습니다/.test(d.text) ? 'err' : ''); }
        else if (kind === 'error') { $('#final').innerHTML = note('오류: ' + esc(d.error), 'err'); }
      }).catch(function (e) { $('#final').innerHTML = note('처리하지 못했습니다: ' + esc(e.message), 'err'); })
        .then(function () { busy = false; paint(); });
    }
    $('#btn-all').addEventListener('click', function () { sign({ card_id: 'ALL', decision: 'approve' }); });
    $('#btn-print').addEventListener('click', function () { var f = $('#frame'); if (f.src) { f.contentWindow.focus(); f.contentWindow.print(); } });
    paint();
  }

  // ---------------------------------------------------------------- ⑤ 이메일
  function pageEmail() {
    if (!state) { return noSession(); }
    var r = state.report, ok = state.report_ready && r && r.status === 'APPROVED';
    var waiting = state.cards.filter(function (c) { return !c.approved; }).map(function (c) { return c.card_id; });
    var body = r ? '안녕하세요.\n\n' + W('subject') + ' ' + state.package.aircraft + ' ' + state.package.check_type + (mfg() ? '의 복합재 초음파 검사 보고서와 NCR 초안을 첨부합니다.\n\n' : '의 복합재 NDT 점검 보고서를 첨부합니다.\n\n') + r.summary + '\n\n기준 값은 시연용 예시(EXAMPLE_ONLY)이며, 처분의 최종 판단과 서명은 검사원이 했습니다.\n첨부 보고서를 검토하신 뒤 회신 부탁드립니다.' : '';
    app.innerHTML = h1('이메일 발송', '검사원 승인이 끝난 보고서를 유관 부서에 보냅니다.') +
      note('시연 모드: 실제로 인터넷으로 발송하지 않고 서버의 outputs/outbox/ 폴더에 .eml 파일로 저장합니다.', 'warn') +
      (ok ? '' : note('검사원 승인이 끝나지 않아 발송할 수 없습니다.' + (waiting.length ? ' 승인 대기: ' + esc(waiting.join(', ')) : '') + ' <a class="underline" href="report.html">보고서 화면</a>에서 승인해 주세요.', 'err')) +
      box('<form id="mail" class="flex flex-col gap-space-md text-[13px]">' +
        '<label>수신자 (To)<input id="to" class="' + INPUT + ' mt-1" value="quality@example.com, engineering@example.com"/></label>' +
        '<label>참조 (CC)<input id="cc" class="' + INPUT + ' mt-1" value="ndt-lead@example.com"/></label>' +
        '<label>제목<input id="subj" class="' + INPUT + ' mt-1" value="' + esc(r ? (mfg() ? '[초음파 검사 보고서] 로트 ' : '[NDT 점검 보고서] ') + state.package.aircraft + ' ' + state.package.check_type : '') + '"/></label>' +
        '<label>본문<textarea id="body" rows="9" class="w-full p-3 rounded-lg bg-background border border-border mt-1 leading-relaxed">' + esc(body) + '</textarea></label>' +
        '<div class="text-on-surface-variant">첨부: ' + (r ? '<span class="font-code-mono">' + esc(r.report_id) + '.html</span> (C-scan 그림 포함)' : '없음') + '</div>' +
        '<div class="flex justify-end">' + btn('.eml로 저장 (발송)', 'btn-send', '', ok ? '' : 'disabled') + '</div></form>') +
      '<div id="sent"></div>';
    function paintSent() {
      $('#sent').innerHTML = state.dispatched.length ? box(h2('저장된 발송 기록') + state.dispatched.map(function (d) {
        return '<div class="text-[13px] py-2 border-b border-border leading-relaxed"><b>' + esc(d.ts) + '</b> · ' + esc(d.to) + '<br><span class="font-code-mono text-[12px]">' + esc(d.file) + '</span><br><span class="text-outline font-code-mono text-[12px]">첨부 ' + esc(d.attachment) + ' · ' + d.attachment_bytes + ' B · SHA-256 ' + esc(d.attachment_sha256) + '</span></div>';
      }).join('') + '<div class="flex justify-end mt-space-md">' + linkBtn('검토 이력 보기', 'history.html') + '</div>') : '';
    }
    paintSent();
    $('#btn-send').addEventListener('click', function () {
      $('#btn-send').disabled = true;
      postJson('/api/sessions/' + sid() + '/dispatch', { to: $('#to').value, cc: $('#cc').value, subject: $('#subj').value, body: $('#body').value })
        .then(function (d) { state.dispatched.push(d); paintSent(); })
        .catch(function (e) { $('#sent').innerHTML = note('저장하지 못했습니다: ' + esc(e.message), 'err'); })
        .then(function () { $('#btn-send').disabled = false; });
    });
  }

  // ---------------------------------------------------------------- ⑥ 검토 이력
  function pageHistory() {
    var EV = { tool: '도구 호출', signoff: '검사원 서명', hear: '사용자 입력', question: '에이전트 질문', hold: '카드 보류', dispatch: '발송(.eml 저장)', upload: '패키지 접수', session_start: '세션 시작', llm_fallback: 'LLM 대체 경로', llm_opinion: 'LLM 의견 검증', chat: '도우미 질문' };
    var rows = [], scope = state ? 'session' : 'all';
    app.innerHTML = h1('검토 이력', '도구 호출, 질문과 답, 서명, 발송 기록을 최신순으로 보여 줍니다. 서버의 outputs/audit_log.jsonl 내용입니다.') +
      '<div id="tiles" class="grid grid-cols-2 md:grid-cols-4 gap-space-md"></div>' +
      box('<div class="flex flex-wrap items-center gap-space-sm mb-space-md"><select id="f-scope" class="h-10 px-2 rounded-lg border border-border bg-background text-[13px]">' + (state ? '<option value="session">현재 세션만</option>' : '') + '<option value="all">전체 세션</option></select>' +
        '<select id="f-ev" class="h-10 px-2 rounded-lg border border-border bg-background text-[13px]"><option value="">전체 동작</option>' + Object.keys(EV).map(function (k) { return '<option value="' + k + '">' + EV[k] + '</option>'; }).join('') + '</select>' +
        '<span id="count" class="text-[13px] text-on-surface-variant"></span><span class="ml-auto">' + btn('CSV 내보내기', 'btn-csv', 'ghost') + '</span></div>' +
        '<div class="overflow-x-auto"><table class="w-full text-[13px]"><thead><tr class="text-left text-on-surface-variant border-b border-border"><th class="py-2 pr-3">시각</th><th class="pr-3">세션</th><th class="pr-3">동작</th><th class="pr-3">내용</th></tr></thead><tbody id="rows"></tbody></table></div>');
    function describe(r) {
      if (r.event === 'tool') { return toolKo(r.tool) + ' [' + (BY[r.by] || r.by || '') + '] ' + (r.ok ? '성공' : '거부') + ' · ' + (r.result || '').slice(0, 220); }
      if (r.event === 'signoff') { return r.card_id + ' · ' + r.user + ' · ' + (r.decision === 'approve' ? '승인' : '반려') + (r.reason ? ' · ' + r.reason : '') + (r.excluded && r.excluded.length ? ' · 제외 ' + r.excluded.join(', ') : '') + (r.procedure_id ? ' · 절차 ' + r.procedure_id : '') + (r.criteria_rev ? ' · Rev ' + r.criteria_rev : ''); }
      if (r.event === 'hear') { return r.text; }
      if (r.event === 'question') { return r.card_id + ' · ' + r.text; }
      if (r.event === 'dispatch') { return r.to + ' · ' + r.file; }
      if (r.event === 'llm_fallback') { return r.reason; }
      if (r.event === 'llm_opinion') { return (r.ok ? '통과' : '실패 → 코드 문장으로 대체') + ' · ' + (r.text || ''); }
      if (r.event === 'chat') { return 'Q: ' + r.question + ' → [' + r.source + '] ' + r.answer; }
      if (r.event === 'upload') { return r.origin + ' · ' + r.mode; }
      if (r.event === 'session_start') { return r['package'] + ' · ' + (r.domain === 'manufacturing' ? '제조 검사 · 부품 ' : '카드 ') + (r.cards || []).length + '건'; }
      if (r.event === 'hold') { return r.card_id + ' · ' + (r.reason || ''); }
      return JSON.stringify(r).slice(0, 200);
    }
    function paint() {
      var f = $('#f-ev').value;
      var list = rows.filter(function (r) { return !f || r.event === f; });
      $('#count').textContent = list.length + '건';
      $('#rows').innerHTML = list.map(function (r) {
        var bad = (r.event === 'tool' && !r.ok) || r.event === 'llm_fallback';
        return '<tr class="border-b border-border align-top"><td class="py-1.5 pr-3 font-code-mono text-[12px] whitespace-nowrap">' + esc((r.ts || '').replace('T', ' ')) + '</td><td class="pr-3 font-code-mono text-[12px] whitespace-nowrap">' + esc(r.session || '') + '</td><td class="pr-3 whitespace-nowrap ' + (bad ? 'text-verdict-fail-text font-semibold' : '') + '">' + (EV[r.event] || esc(r.event)) + '</td><td class="pr-3 break-words">' + esc(describe(r)) + '</td></tr>';
      }).join('') || '<tr><td colspan="4" class="py-3 text-outline">기록이 없습니다.</td></tr>';
      var tools = rows.filter(function (r) { return r.event === 'tool'; });
      var llm = tools.filter(function (r) { return r.by === 'llm'; });
      var tiles = [['도구 호출', tools.length + '건'], ['코드가 거부한 호출', tools.filter(function (r) { return !r.ok; }).length + '건'],
        ['LLM 호출 중 거부', llm.length ? llm.filter(function (r) { return !r.ok; }).length + ' / ' + llm.length + '건' : 'LLM 호출 없음'],
        ['검사원 서명', rows.filter(function (r) { return r.event === 'signoff'; }).length + '건']];
      $('#tiles').innerHTML = tiles.map(function (t) { return '<div class="panel bg-surface rounded-xl p-space-md shadow-[0_0_0_1px_#E1E4EA]"><div class="text-[13px] text-on-surface-variant">' + t[0] + '</div><div class="font-headline-lg text-headline-lg text-primary">' + t[1] + '</div></div>'; }).join('');
    }
    function load() {
      api('/api/audit?limit=2000' + (scope === 'session' ? '&session=' + sid() : '')).then(function (r) { rows = r; paint(); });
    }
    $('#f-scope').addEventListener('change', function (e) { scope = e.target.value; load(); });
    $('#f-ev').addEventListener('change', paint);
    $('#btn-csv').addEventListener('click', function () {
      var csv = '﻿시각,세션,동작,내용\n' + rows.map(function (r) { return [r.ts, r.session, EV[r.event] || r.event, describe(r)].map(function (v) { return '"' + String(v || '').replace(/"/g, '""') + '"'; }).join(','); }).join('\n');
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'audit_log.csv'; a.click();
    });
    load();
  }


  function enter() {
    if (!window.gsap || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }
    window.gsap.from(Array.prototype.slice.call(app.children), { y: 16, opacity: 0, duration: 0.7, ease: 'power3.out', stagger: 0.06, clearProps: 'transform,opacity' });
    window.gsap.from('header.fixed', { y: -10, opacity: 0, duration: 0.5, ease: 'power2.out', clearProps: 'transform,opacity' });
  }
  // ---------------------------------------------------------------- 시작
  initHeader(); initChat(); initChatToggle();
  var pages = { home: pageHome, request: pageRequest, agent: pageAgent, results: pageResults, report: pageReport, email: pageEmail, history: pageHistory };
  loadState().then(function () {
    $('#session-chip').textContent = state ? state.session_id : '없음';
    try { (pages[PAGE] || pageHome)(); mountOrbs(app); enter(); }
    catch (e) { app.innerHTML = note('화면을 그리지 못했습니다: ' + esc(e.message), 'err'); throw e; }
  });
})();
