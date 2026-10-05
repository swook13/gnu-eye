"""2026-10-06 흰 바탕 리퀴드 글래스 디자인 조각. tools/build_web.py가 가져다 쓴다.

- LOGO_SVG: 눈 모양 로고(눈꺼풀 곡선 + 끊긴 홍채 고리 + 동공 + 스캔선). 상단 바와 시작 화면에 같이 쓴다.
- GLASS_CSS: 모든 화면 공통. 밝은 바탕 위 옅은 오로라 빛과 모눈, 리퀴드 글래스 패널·탭·버튼, 마우스를 올리면 펼쳐지는 상단 탭.
- 움직임은 GSAP(web/vendor/gsap.min.js)과 CSS 전환을 쓴다. 곡선은 Emil Kowalski skills의 ease-out 값.
"""

LOGO_SVG = (
    '<svg class="logo-eye" viewBox="0 0 48 48" aria-hidden="true">'
    '<defs><linearGradient id="lg-iris" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2C7BE5"/>'
    '<stop offset="1" stop-color="#14B8A6"/></linearGradient></defs>'
    '<g class="eye-lid"><path class="lid" d="M4 24C11.5 13 36.5 13 44 24C36.5 35 11.5 35 4 24Z" fill="none" '
    'stroke="currentColor" stroke-width="2.6" stroke-linejoin="round" pathLength="100"/></g>'
    '<circle class="iris" cx="24" cy="24" r="7.6" fill="none" stroke="url(#lg-iris)" stroke-width="2.8" '
    'stroke-linecap="round" stroke-dasharray="40 7.8" transform="rotate(-60 24 24)"/>'
    '<circle class="pupil" cx="24" cy="24" r="3.1" fill="currentColor"/>'
    '<circle class="glint" cx="26.6" cy="21.4" r="1.1" fill="#fff"/>'
    '<line class="scan" x1="24" y1="11" x2="24" y2="37" stroke="#14B8A6" stroke-width="1.6" stroke-linecap="round" opacity="0"/>'
    '</svg>'
)

FONTS = ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/'
         'pretendardvariable-dynamic-subset.min.css"/>'
         '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet"/>')

GLASS_CSS = """
:root{--ease-out:cubic-bezier(0.23,1,0.32,1);--ease-in-out:cubic-bezier(0.77,0,0.175,1);--ink:#14213D;--accent:#1f3a5f;--accent2:#2C7BE5;--accent-soft:#D5E3FF;--grid:rgba(31,58,95,.045)}
body.mode-mfg{--accent:#0E5A5C;--accent2:#14B8A6;--accent-soft:#C7ECEA;--grid:rgba(14,90,92,.05)}
body{background-color:#F4F6FA;background-image:radial-gradient(900px 600px at 92% -10%,rgba(44,123,229,.16),transparent 65%),radial-gradient(800px 560px at -8% 30%,rgba(20,184,166,.12),transparent 62%),radial-gradient(700px 520px at 60% 110%,rgba(139,92,246,.08),transparent 60%),linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:auto,auto,auto,32px 32px,32px 32px;background-attachment:fixed;word-break:keep-all;overflow-wrap:break-word;letter-spacing:-.005em}
#main{background:transparent!important}
h1,h2,.font-headline-lg,.font-headline-md,.font-display-hero{letter-spacing:-.025em}
.font-display-hero{font-weight:700}
.wordmark{font-family:"Space Grotesk","Pretendard Variable",sans-serif;letter-spacing:-.02em}
table{font-variant-numeric:tabular-nums}
::selection{background:var(--accent-soft);color:#0d1b36}
:focus-visible{outline:2px solid var(--accent2);outline-offset:2px}
input:focus,select:focus{box-shadow:0 0 0 3px var(--accent-soft)}
::-webkit-scrollbar{display:block!important;width:10px;height:10px}
::-webkit-scrollbar-thumb{background:rgba(31,58,95,.18);border-radius:10px;border:2px solid transparent;background-clip:padding-box}
/* 리퀴드 글래스: 흐림 + 채도 + 위쪽 빛 반사 + 안쪽 테두리 + 부드러운 그림자 */
.glass,.panel{position:relative;background:linear-gradient(140deg,rgba(255,255,255,.78),rgba(255,255,255,.52))!important;-webkit-backdrop-filter:blur(22px) saturate(180%);backdrop-filter:blur(22px) saturate(180%);box-shadow:inset 0 1px 1px rgba(255,255,255,.95),inset 0 -1px 1px rgba(255,255,255,.4),inset 0 0 0 1px rgba(255,255,255,.55),0 0 0 1px rgba(31,58,95,.06),0 16px 40px -20px rgba(20,40,80,.28),0 3px 8px -4px rgba(20,40,80,.10)!important}
.panel::before,.glass-sheen::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:radial-gradient(120% 70% at 12% -10%,rgba(255,255,255,.65),transparent 48%),linear-gradient(180deg,rgba(255,255,255,.25),transparent 30%)}
.panel>*{position:relative}
.panel .bg-background{background-color:rgba(255,255,255,.55)!important;box-shadow:inset 0 0 0 1px rgba(31,58,95,.06)}
.rounded-xl.panel{border-radius:20px}
/* 상단 바 */
header.fixed{background:rgba(255,255,255,.62)!important;-webkit-backdrop-filter:blur(20px) saturate(180%);backdrop-filter:blur(20px) saturate(180%);box-shadow:inset 0 -1px 0 rgba(255,255,255,.8),0 8px 30px -18px rgba(20,40,80,.25)!important}
header.fixed .bg-surface,header.fixed .bg-notice-band-bg{background:transparent!important}
header .border-b{border-color:rgba(31,58,95,.07)!important}
header .bg-notice-band-bg{background:linear-gradient(90deg,rgba(255,246,214,.85),rgba(255,246,214,.55))!important}
.logo-eye{width:28px;height:28px;color:var(--ink);flex:none}
.brand-stack{display:flex;flex-direction:column;line-height:1.1;min-width:0}
.brand-word{font-size:17px;font-weight:700;color:var(--ink);white-space:nowrap}
.brand-word small{font-size:11px;font-weight:600;color:var(--accent2);margin-left:5px;letter-spacing:.03em}
.brand .sub{font-size:11.5px;color:#5f6368;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 상단 막대: 탭은 로고 바로 오른쪽에 붙어 있고, 펼치면 오른쪽 빈 공간으로만 자라서 다른 버튼을 덮지 않는다 */
.bar>#tabs{margin-left:14px;margin-right:auto}
.tabs:hover,.tabs:focus-within{background:rgba(255,255,255,.94)!important;box-shadow:inset 0 1px 1px #fff,0 0 0 1px rgba(31,58,95,.08),0 18px 40px -18px rgba(20,40,80,.4)!important}
.session{box-shadow:inset 0 0 0 1px rgba(31,58,95,.06)}
#chat-toggle{height:32px}
#mode-toggle{border:0!important;padding:3px;border-radius:999px;background:rgba(31,58,95,.06);box-shadow:inset 0 1px 2px rgba(20,40,80,.08)}
#mode-toggle a{border-radius:999px!important;background:transparent!important;color:#43474e!important;transition:background-color .25s var(--ease-out),color .25s ease,box-shadow .25s ease}
#mode-toggle a[aria-current]{background:rgba(255,255,255,.95)!important;color:var(--ink)!important;box-shadow:0 1px 2px rgba(20,40,80,.12),0 4px 12px -6px rgba(20,40,80,.3)}
/* 탭: 지금 화면만 보이다가 마우스를 올리면(또는 키보드로 들어오면) 펼쳐진다 */
.tabs{display:flex;align-items:center;gap:2px;height:38px;padding:3px;border-radius:999px;overflow:hidden;transition:background-color .3s ease,box-shadow .3s ease}
.tabs a{display:flex;align-items:center;height:32px;font-size:13.5px!important;border-radius:999px;white-space:nowrap;max-width:0;opacity:0;padding:0;margin:0;overflow:hidden;color:#43474e;font-weight:500;font-size:14px;transition:max-width .5s var(--ease-out),opacity .3s ease,padding .5s var(--ease-out),background-color .2s ease,color .2s ease}
.tabs a[aria-current]{max-width:220px;opacity:1;padding:0 14px;background:rgba(255,255,255,.95);color:var(--ink);font-weight:700;box-shadow:0 1px 2px rgba(20,40,80,.10),0 6px 16px -8px rgba(20,40,80,.35)}
.tabs .tabs-hint{display:flex;align-items:center;color:#74777f;padding:0 6px 0 4px;transition:opacity .2s ease,max-width .4s var(--ease-out);max-width:40px;overflow:hidden}
.tabs:hover a,.tabs:focus-within a{max-width:220px;opacity:1;padding:0 10px}
.tabs:hover .tabs-hint,.tabs:focus-within .tabs-hint{opacity:0;max-width:0;padding:0}
.tabs:hover a:nth-child(2),.tabs:focus-within a:nth-child(2){transition-delay:.02s}
.tabs:hover a:nth-child(3),.tabs:focus-within a:nth-child(3){transition-delay:.04s}
.tabs:hover a:nth-child(4),.tabs:focus-within a:nth-child(4){transition-delay:.06s}
.tabs:hover a:nth-child(5),.tabs:focus-within a:nth-child(5){transition-delay:.08s}
.tabs:hover a:nth-child(6),.tabs:focus-within a:nth-child(6){transition-delay:.10s}
.tabs:hover a:nth-child(7),.tabs:focus-within a:nth-child(7){transition-delay:.12s}
@media (hover:hover){.tabs a:not([aria-current]):hover{background:rgba(255,255,255,.7);color:var(--ink)}}
@media (hover:none){.tabs{overflow-x:auto}.tabs a{max-width:220px;opacity:1;padding:0 12px}.tabs .tabs-hint{display:none}}
.nav-num{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-right:6px;border-radius:999px;border:1.5px solid currentColor;font-size:11px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.tabs a[aria-current] .nav-num{background:var(--accent);border-color:var(--accent);color:#fff}
/* 버튼: 알약 모양, 위쪽 빛, 누르면 살짝 눌림 */
.bg-primary-container{background-image:linear-gradient(180deg,rgba(255,255,255,.16),rgba(255,255,255,0))}
button.rounded-lg,a.rounded-lg.inline-flex,.q-rev,.q-hold,#chat-toggle{border-radius:999px!important}
button,a.inline-flex,.q-rev,.q-hold{transition:transform .14s var(--ease-out),background-color .2s ease,box-shadow .2s ease,color .2s ease}
button:not(:disabled).bg-primary-container,a.inline-flex.bg-primary-container{box-shadow:inset 0 1px 0 rgba(255,255,255,.25),0 8px 20px -10px rgba(31,58,95,.6)}
button:active:not(:disabled),a.inline-flex:active{transform:scale(.97)}
.bg-chip-bg{background-color:rgba(238,241,245,.75)}
#chat{background:rgba(255,255,255,.7)!important;-webkit-backdrop-filter:blur(22px) saturate(180%);backdrop-filter:blur(22px) saturate(180%)}
#chat-toggle[aria-expanded=false]{background:var(--accent)!important;border-color:var(--accent)!important}
.log-in{animation:gnu-rise .28s var(--ease-out) both}
@keyframes gnu-rise{from{opacity:.001;transform:translateY(8px)}to{opacity:1;transform:none}}
/* 홈 */
.hero{background:linear-gradient(140deg,rgba(255,255,255,.8),rgba(255,255,255,.5))!important}
.hero h1{text-wrap:balance;color:var(--ink)}
.hero-title{font-size:clamp(34px,3.5vw,48px);line-height:1.18;font-weight:800;letter-spacing:-.035em;margin:0}
.hero-lead{font-size:17px;line-height:1.7;color:#43474e;max-width:34em;margin:0}
.hero-cta{height:56px;padding:0 30px;font-size:17px;font-weight:700;letter-spacing:-.01em}
.hero-cta .material-symbols-outlined{font-size:22px;transition:transform .25s var(--ease-out)}
@media (hover:hover){.hero-cta:hover .material-symbols-outlined{transform:translateX(3px)}}
.hero-art text{font-family:"Pretendard Variable","Noto Sans",sans-serif}
@keyframes gnu-sweep{from{transform:translateX(0)}to{transform:translateX(var(--sweep,180px))}}
.scanline{animation:gnu-sweep 3.2s linear infinite alternate}
@keyframes gnu-pulse{0%,100%{opacity:.45}50%{opacity:1}}
.zone-pulse{animation:gnu-pulse 2.4s ease-in-out infinite}
.flow-node{position:relative;transition:transform .25s var(--ease-out),box-shadow .25s ease}
@media (hover:hover){.flow-node:hover{transform:translateY(-3px)}}
@media (min-width:768px){.flow-node:not(:last-child)::after{content:"";position:absolute;top:48px;right:-14px;width:16px;height:2px;background:linear-gradient(90deg,var(--accent2),transparent)}}
.role-ai{background:rgba(20,184,166,.12);color:#0B6E70}.role-code{background:rgba(44,123,229,.10);color:#1f3a5f}.role-human{background:rgba(30,127,79,.10);color:#14633C}
.orb-slot{width:64px;height:64px}
#orb-busy{width:20px;height:20px;display:none}
body.busy #orb-busy{display:inline-block}
details.more>summary{list-style:none;cursor:pointer}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary .chev{transition:transform .3s var(--ease-out)}
details.more[open]>summary .chev{transform:rotate(180deg)}
@media (max-width:1180px){.brand .sub{display:none}}
@media (max-width:980px){.session{display:none!important}#chat-toggle-label{display:none}}
@media (max-width:820px){
  .brand-stack{display:none}
  .bar>#tabs{margin-left:8px;min-width:0}
  #llm-status,#mode-toggle a{white-space:nowrap}
  #mode-toggle a{padding:6px 9px}
}
@media (prefers-reduced-motion:reduce){
  .log-in,.scanline,.zone-pulse{animation:none}
  .tabs a,.tabs .tabs-hint{transition:none}
  button:active:not(:disabled),a.inline-flex:active{transform:none}
}
"""
