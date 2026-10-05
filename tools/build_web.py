"""사이트 껍데기 생성.

web/*.html: 원본 사이트(Stitch)의 <head>(Tailwind 설정, 글꼴)와 상단·챗봇 틀을 그대로 쓰고,
본문은 web/app.js가 API에서 받아 그린다. 정비 점검과 제조 검사 모드가 같은 껍데기를 쓴다
(상단의 모드 전환은 app.js가 그린다). web/mfg/index.html은 제조 검사 모드로 넘기는 주소만 남긴다.

    python tools/build_web.py [원본 사이트 폴더]
"""
import re  # noqa: F401
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "gnu-eye-site"

PAGES = [  # 파일, 메뉴 이름, 페이지 키
    ("index.html", "⌂ 홈", "home"),
    ("request.html", "① 검사 요청", "request"),
    ("agent.html", "② 에이전트", "agent"),
    ("results.html", "③ 판정 결과", "results"),
    ("report.html", "④ 보고서", "report"),
    ("email.html", "⑤ 이메일 발송", "email"),
    ("history.html", "⑥ 검토 이력", "history"),
]

NAV_ON = ""
NAV_OFF = ""

# 챗봇 패널 열고 닫기: body.chat-closed 하나로 패널, 본문 여백, 본문 최대 너비를 함께 바꾼다.
# 좁은 화면(1100px 미만)에서는 패널이 본문을 밀지 않고 위에 겹쳐 뜬다.
# 패널은 기본으로 닫혀 있다. 사용자가 연 적이 있을 때만(gnueye_chat=open) 열린 채로 시작한다.
CHAT_CSS = """<style>
#chat{{transition:transform .25s ease}}
#main,#foot{{transition:padding-left .25s ease}}
#app{{transition:max-width .25s ease}}
body.chat-closed #chat{{transform:translateX(-100%);visibility:hidden;transition:transform .25s ease,visibility 0s .25s}}
body.chat-closed #main,body.chat-closed #foot{{padding-left:0}}
/* 닫혔을 때 본문 글줄이 상단 메뉴(최대 1280px) 좌우 끝과 맞도록 한다: 1280 + 여백 차이 16 */
body.chat-closed #app{{max-width:1296px}}
body.chat-closed #app[data-wide]{{max-width:1500px}}
body.chat-closed #foot>div{{max-width:1296px}}
#chat-toggle[aria-expanded=false]{{background:#1f3a5f;color:#fff;border-color:#1f3a5f}}
#chat-toggle[aria-expanded=false]:hover{{background:#032448}}
body.no-anim #chat,body.no-anim #main,body.no-anim #foot,body.no-anim #app{{transition:none}}
/* 제조 검사 모드 테마: 청록. 정비 점검 모드는 기본 네이비(#1f3a5f)를 그대로 쓴다. */
body.mode-mfg .bg-primary-container{{background-color:#0E5A5C}}
body.mode-mfg .text-primary-container{{color:#0E5A5C}}
body.mode-mfg .border-primary-container{{border-color:#0E5A5C}}
body.mode-mfg .bg-primary,body.mode-mfg .hover\\:bg-primary:hover{{background-color:#073B3D}}
body.mode-mfg .text-primary{{color:#073B3D}}
body.mode-mfg #chat-toggle[aria-expanded=false]{{background:#0E5A5C;border-color:#0E5A5C}}
body.mode-mfg #chat-toggle[aria-expanded=false]:hover{{background:#073B3D}}
body.mode-mfg input[type=radio],body.mode-mfg input[type=checkbox]{{accent-color:#0E5A5C}}
@media (max-width:1099px){{
  #main,#foot{{padding-left:0!important}}
  #chat{{box-shadow:8px 0 24px rgba(20,33,61,.18);max-width:88vw}}
}}
</style>"""

# 디자인 조각(로고, 글꼴, 리퀴드 글래스 CSS)은 tools/web_glass.py에 있다. 이전 시도(밝은 모눈, 관제실 다크)는
# _backup_web_20261006/와 DESIGN.md §15에 기록돼 있다.
from web_glass import FONTS, GLASS_CSS, LOGO_SVG  # noqa: E402


SHELL = """{head}<body class="bg-background font-body-sm text-on-surface antialiased no-anim" data-page="{key}">
<script>(function(){{try{{var q=location.search.match(/[?&]mode=(mfg|maint)/);if(q?q[1]==='mfg':localStorage.getItem('gnueye_mode')==='manufacturing'){{document.body.classList.add('mode-mfg');}}}}catch(e){{}}}})();</script>
<script>(function(){{var v=null;try{{v=localStorage.getItem('gnueye_chat');}}catch(e){{}}if(v!=='open'){{document.body.classList.add('chat-closed');}}}})();</script>
<header class="fixed top-0 left-0 w-full z-50 bg-surface">
<div class="w-full bg-notice-band-bg"><div class="max-w-7xl mx-auto px-gutter h-7 flex items-center justify-between gap-space-md text-notice-band-text text-[12px]">
<div class="notice flex items-center gap-1.5 min-w-0"><span class="material-symbols-outlined text-[15px] text-notice-band-text">warning</span><span class="font-semibold truncate">예시 기준(EXAMPLE_ONLY) · 처분은 초안 · 최종 판단과 서명은 검사원이 합니다</span></div>
<div class="flex items-center gap-1.5 font-code-mono text-[11.5px] text-notice-band-text shrink-0"><span id="llm-dot" class="w-2 h-2 rounded-full bg-outline inline-block"></span><span id="llm-status">LLM 확인 중</span></div>
</div></div>
<div class="w-full bg-surface"><div class="bar max-w-7xl mx-auto px-gutter h-14 flex items-center justify-between gap-space-md relative">
<a href="index.html" class="brand flex items-center gap-2.5 min-w-0 shrink-0">{logo}<span class="brand-stack"><span class="brand-word wordmark">지누아이<small>GNU-Eye</small></span><span class="sub">항공 복합재 C-scan 검사 보조 에이전트</span></span></a>
<nav id="tabs" class="tabs glass" aria-label="화면 이동 (마우스를 올리면 펼쳐짐)">{nav}<span class="tabs-hint" aria-hidden="true"><span class="material-symbols-outlined text-[18px]">more_horiz</span></span></nav>
<div class="right flex items-center gap-2 shrink-0">
<button id="chat-toggle" type="button" aria-controls="chat" aria-expanded="false" title="AI 도우미 열기/닫기" class="shrink-0 flex items-center gap-1 h-8 px-3 rounded-lg border border-border bg-chip-bg text-chip-text hover:bg-surface-variant font-label-md text-[13px] transition-colors"><span class="material-symbols-outlined text-[18px]">smart_toy</span><span id="chat-toggle-label">도우미 열기</span></button>
<div id="mode-toggle" class="flex items-center rounded-lg border border-border overflow-hidden font-label-md text-[13px]"><a href="index.html?mode=maint" class="px-3 py-1.5 bg-chip-bg text-chip-text">정비 점검</a><a href="index.html?mode=mfg" class="px-3 py-1.5 bg-chip-bg text-chip-text">제조 검사</a></div>
<div class="session flex items-center gap-1.5 h-8 px-3 rounded-full bg-chip-bg text-chip-text text-[12.5px]"><span class="font-label-md text-[12.5px]">세션</span><span id="session-chip" class="font-code-mono text-[11.5px] font-semibold">없음</span></div>
</div></div></div>
</header>
<aside id="chat" aria-label="AI 도우미" class="fixed top-[84px] left-0 w-[340px] h-[calc(100vh-84px)] bg-surface border-r border-border z-40 flex flex-col p-space-md gap-space-sm">
<div class="flex items-center justify-between border-b border-border pb-space-sm"><div class="flex items-center gap-space-xs"><span class="material-symbols-outlined text-primary-container text-[20px]">smart_toy</span><h2 class="font-headline-md text-[16px] font-bold text-primary-container">AI 도우미</h2></div><div class="flex items-center gap-1"><span class="px-2 py-0.5 rounded bg-chip-bg text-chip-text font-code-mono text-[11px] font-semibold border border-border">질문 전용</span><button id="chat-close" type="button" aria-label="AI 도우미 닫기" title="닫기" class="p-1 rounded hover:bg-chip-bg text-on-surface-variant flex items-center"><span class="material-symbols-outlined text-[20px]">left_panel_close</span></button></div></div>
<div class="bg-background p-space-sm rounded border border-border"><p class="font-body-sm text-[13px] leading-relaxed text-on-surface-variant">현재 검사 결과, 판정 기준(예시), 용어 설명을 근거로만 답합니다. 자료에 없으면 모른다고 답하고, 판정은 바꾸지 못합니다.</p></div>
<div id="chat-thread" class="flex-1 overflow-y-auto flex flex-col gap-space-sm min-h-0"></div>
<div id="chat-quick" class="flex flex-col gap-1.5"></div>
<form id="chat-form" class="pt-space-sm border-t border-border"><div class="relative flex items-center"><input id="chat-input" autocomplete="off" class="w-full pl-3 pr-10 py-2.5 rounded bg-background border border-border text-on-surface placeholder:text-outline font-body-sm text-[13px] focus:outline-none focus:border-secondary transition-colors" placeholder="질문을 입력하세요" type="text"/><button aria-label="전송" class="absolute right-2 text-primary-container hover:text-secondary p-1 flex items-center justify-center transition-colors" type="submit"><span class="material-symbols-outlined text-[20px]">send</span></button></div></form>
</aside>
<main id="main" class="w-full pt-[84px] pl-[340px] min-h-screen bg-background"><div id="app" class="max-w-[1120px] mx-auto p-margin flex flex-col gap-space-lg"><div class="text-on-surface-variant">불러오는 중...</div></div></main>
<footer id="foot" class="w-full bg-surface border-t border-border py-space-md pl-[340px]"><div class="max-w-[1120px] mx-auto px-margin flex flex-col md:flex-row items-center justify-between text-on-surface-variant font-body-sm text-[13px] gap-space-xs"><div>측정과 판정은 결정론 코드가 하고, 최종 판단과 서명은 검사원이 합니다 · GNU-Eye</div><div class="font-code-mono text-[12px] text-outline">기관 내부 GPU 서버 실행 · 외부 API 미사용</div></div></footer>
<script src="vendor/gsap.min.js"></script>
<script src="vendor/thinking-orbs.js"></script>
<script src="app.js"></script>
</body></html>
"""

MFG_REDIRECT = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/><title>지누아이(GNU-Eye) - 제조 검사 모드</title>
<meta http-equiv="refresh" content="0; url=../index.html?mode=mfg"/><link rel="icon" href="data:,"/></head>
<body><a href="../index.html?mode=mfg">제조 검사 모드로 이동</a></body></html>
"""


def nav_label(lab):
    """'① 검사 요청' → 동그라미 숫자 배지 + 글자. ①②③ 기호는 글꼴마다 크기가 달라 직접 그린다."""
    n = "①②③④⑤⑥".find(lab[0])
    return f'<span class="nav-num" aria-hidden="true">{n + 1}</span>{lab[2:]}' if n >= 0 else lab


def main():
    src2 =(SRC / "2.html").read_text(encoding="utf-8")
    head = src2[:src2.index("</head>")] + '<link rel="icon" href="data:,"/>' + CHAT_CSS.replace("{{", "{").replace("}}", "}") \
        + FONTS + "<style>" + GLASS_CSS + "</style></head>"
    # 한글 글꼴. ①②③ 같은 기호는 Pretendard 부분 글꼴에 없어 맑은 고딕으로 받는다
    head = head.replace('["Noto Sans"]', '["Pretendard Variable","Pretendard","Noto Sans","Malgun Gothic","sans-serif"]')
    WEB.mkdir(exist_ok=True)
    for fname, label, key in PAGES:
        nav = "".join(
            f'<a class="{NAV_ON if k == key else NAV_OFF}" href="{f}"{" aria-current=page" if k == key else ""}>{nav_label(lab)}</a>'
            for f, lab, k in PAGES)
        (WEB / fname).write_text(SHELL.format(head=head, key=key, nav=nav, logo=LOGO_SVG), encoding="utf-8", newline="\n")
    mfg = WEB / "mfg"
    mfg.mkdir(exist_ok=True)
    (mfg / "index.html").write_text(MFG_REDIRECT, encoding="utf-8", newline="\n")
    print("화면 껍데기", len(PAGES), "장 생성:", WEB)


if __name__ == "__main__":
    main()
