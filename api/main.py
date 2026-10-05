"""GNU-Eye v2 백엔드 (FastAPI). 정적 사이트(web/)도 함께 서빙한다.

    cd 지누아이
    ..\\projects\\.venv\\Scripts\\python.exe -m uvicorn api.main:app --port 8000
    브라우저: http://localhost:8000
"""
import base64
import hashlib
import json
import os
import queue
import shutil
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import chat as chatbot
from agent import llm
from agent.loop import Runner
from agent.session import OUT, ROOT, Session
from core import domain as dm
from core import heatmap, measure
from core import package as pkg
from core import report as rpt

PACKAGES = ROOT / "data" / "packages"
UPLOADS = ROOT / "data" / "uploads"
MAX_UPLOAD = 100 * 1024 * 1024

app = FastAPI(title="GNU-Eye v2", docs_url="/api/docs", openapi_url="/api/openapi.json")

SESSIONS = {}  # id -> {"session", "runner", "lock", "started"}
LATEST = {"id": None}


def _get(sid):
    if sid == "latest":
        sid = LATEST["id"]
    if sid not in SESSIONS:
        raise HTTPException(404, "세션이 없습니다. 검사 요청 화면에서 패키지를 다시 올려 주세요.")
    return SESSIONS[sid]


def _mode(want_llm):
    """LLM을 쓸 수 있는지 확인하고 실행 방식을 정한다."""
    if not want_llm:
        return False, "고정 순서 모드 (LLM 없음). 측정·판정은 결정론 코드"
    st = llm.status()
    if st["ok"]:
        return True, f"LLM {st['model']} (내부 서버, 외부 API 미사용)가 계획·도구 순서·종합 의견 담당. 측정·판정은 결정론 코드"
    return False, f"고정 순서 모드 (LLM 연결 실패: {st['error']}). 측정·판정은 결정론 코드"


# ------------------------------------------------------------------ 기본 정보
@app.get("/api/health")
def health():
    st = llm.status()
    return {"ok": True, "llm": st, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "latest_session": LATEST["id"]}


@app.get("/api/samples")
def samples(domain: Optional[str] = None):
    out = []
    for d in sorted(PACKAGES.iterdir()) if PACKAGES.exists() else []:
        if (d / "package.json").exists():
            try:
                p = pkg.load_package(d)
            except pkg.PackageError:
                continue
            if domain and p["domain"] != domain:
                continue
            out.append({"id": d.name, "domain": p["domain"], "aircraft": p["aircraft"], "check_type": p["check_type"],
                        "cards": len(p["cards"]), "data_note": p.get("data_note", ""),
                        "zip": f"/api/samples/{d.name}.zip" if (PACKAGES / f"{d.name}.zip").exists() else None})
    return out


@app.get("/api/samples/{name}.zip")
def sample_zip(name: str):
    p = PACKAGES / f"{pkg.safe_name(name)}.zip"
    if not p.exists():
        raise HTTPException(404, "없는 샘플입니다.")
    return Response(p.read_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


# ------------------------------------------------------------------ 세션 생성
@app.post("/api/sessions")
async def create_session(sample: Optional[str] = Form(None), mode: str = Form("llm"),
                         domain: Optional[str] = Form(None), files: List[UploadFile] = File(default=[])):
    sid = time.strftime("S%Y%m%d-%H%M%S")
    while sid in SESSIONS:
        sid += "x"
    folder = UPLOADS / sid
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sample:
            src = PACKAGES / pkg.safe_name(sample)
            if not (src / "package.json").exists():
                raise pkg.PackageError(f"없는 샘플: {sample}")
            for f in src.iterdir():
                if f.is_file():
                    shutil.copyfile(f, folder / f.name)
            origin = f"내장 샘플 {sample}"
        else:
            if not files:
                raise pkg.PackageError("파일이 없습니다. zip 하나 또는 package.json과 카드별 CSV·메타 파일을 올려 주세요.")
            total = 0
            for up in files:
                data = await up.read()
                total += len(data)
                if total > MAX_UPLOAD:
                    raise pkg.PackageError("업로드가 100 MB를 넘습니다. 변환된 격자 CSV만 올려 주세요.")
                name = pkg.safe_name(up.filename or "")
                (folder / name).write_bytes(data)
                if name.lower().endswith(".zip"):
                    pkg.safe_extract(folder / name, folder)
                    (folder / name).unlink()
            origin = f"업로드 {len(files)}개 파일"
        got = pkg.load_package(folder)["domain"]
        if domain in dm.PROFILES and got != domain:
            raise pkg.PackageError(f"{dm.profile(domain)['name']} 모드인데 올린 패키지는 {dm.profile(got)['name']}용입니다. "
                                   "상단에서 모드를 바꾸거나 맞는 패키지를 올려 주세요.")
        use_llm, mode_info = _mode(mode == "llm")
        # GNUEYE_LLM_OPINION=0 이면 LLM 모드에서도 종합 의견은 코드 문장만 쓴다
        opinion_llm = llm.plain if use_llm and os.environ.get("GNUEYE_LLM_OPINION", "1") != "0" else None
        s = Session(folder, session_id=sid, llm=opinion_llm, mode_info=mode_info)
    except pkg.PackageError as e:
        for f in folder.iterdir():
            f.unlink()
        raise HTTPException(400, str(e))
    s._audit("upload", origin=origin, mode=mode_info)
    for old in SESSIONS.values():  # 진행 중이던 이전 세션은 지금 LLM 호출만 마치고 멈춘다 (LLM은 한 번에 하나만 처리)
        old["runner"].cancelled = True
    SESSIONS[sid] ={"session": s, "runner": Runner(s, use_llm=use_llm), "lock": threading.Lock(),
                     "started": False, "origin": origin}
    LATEST["id"] = sid
    return _state(sid)


def _state(sid):
    e = _get(sid)
    st = e["session"].public_state()
    st.update(started=e["started"], origin=e["origin"], use_llm=e["runner"].use_llm,
              guard=e["runner"].guard_metrics())
    return st


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return _state(_get(sid)["session"].id)


# ------------------------------------------------------------------ 턴 실행 (SSE)
class Turn(BaseModel):
    kind: str  # start | answer | signoff | feedback
    text: Optional[str] = None
    card_id: Optional[str] = None
    rev: Optional[str] = None
    hold: bool = False
    inspector: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    exclude_indications: Optional[List[str]] = None
    procedure_id: Optional[str] = None
    criteria_rev: Optional[str] = None


def _do_turn(entry, t: Turn):
    s, r = entry["session"], entry["runner"]
    if t.kind == "start":
        if entry["started"]:
            r.emit("final", {"text": "이미 처리한 패키지입니다. 현재 상태를 표시합니다."})
            return
        entry["started"] = True
        if s.domain == dm.MFG:
            r.run_turn(f"생산 로트 패키지 {s.package['package_id']}의 검사 부품 {len(s.cards)}건을 고객사양과 대조하고 "
                       "로트 검사 보고서와 NCR 초안을 만들어 줘.")
        else:
            r.run_turn(f"패키지 {s.package['package_id']}의 정기점검 작업카드 {len(s.cards)}건을 처리하고 "
                       "기체 단위 점검 보고서 초안을 만들어 줘.")
    elif t.kind == "answer":
        cid = (t.card_id or "").strip().upper()
        if t.hold:
            text = f"{cid}는 보류합니다. 사유: {t.reason or '미기재'}"
            s.hear(text)
            s.hold_card(cid, t.reason or "")
            n0 = len(s.calls)
            r.resume(text)
            r.emit("final", {"text": r.render_final(s.calls[n0:])})
        else:
            r.run_turn(f"{cid}의 기준 개정번호는 Rev {(t.rev or '').strip().upper()}입니다.")
    elif t.kind == "signoff":
        # 버튼 클릭은 검사원의 명시적 요청이다. LLM을 거치지 않고 도구를 직접 호출한다.
        cid = (t.card_id or "").strip().upper()
        name = (t.inspector or "").strip()
        target = f"전체 {s.prof['unit']}" if cid == "ALL" else cid
        if t.decision == "approve":
            text = f"검사원 {name}: {target} 승인합니다."
        else:
            text = f"검사원 {name}: {target} 반려합니다. 사유: {t.reason or '미기재'}."
            if t.exclude_indications:
                text += f" 제외할 지시: {', '.join(t.exclude_indications)}."
            if t.procedure_id:
                text += f" 절차 정정: {t.procedure_id}."
            if t.criteria_rev:
                text += f" 개정번호 정정: Rev {t.criteria_rev}."
        s.hear(text)
        n0 = len(s.calls)
        r._tool("record_signoff", {"card_id": cid, "user": name, "decision": t.decision, "reason": t.reason or "",
                                   "exclude_indications": t.exclude_indications, "procedure_id": t.procedure_id,
                                   "criteria_rev": t.criteria_rev}, "user")
        r.resume(text)
        r.emit("final", {"text": r.render_final(s.calls[n0:])})
    elif t.kind == "feedback":
        if not (t.text or "").strip():
            raise ValueError("내용이 비어 있습니다.")
        r.run_turn(t.text.strip()[:1000])
    else:
        raise ValueError(f"알 수 없는 kind: {t.kind}")


@app.post("/api/sessions/{sid}/turn")
def turn(sid: str, t: Turn):
    entry = _get(sid)
    sid = entry["session"].id
    q = queue.Queue()

    def work():
        with entry["lock"]:
            entry["runner"].emit = lambda kind, data: q.put((kind, data))
            try:
                _do_turn(entry, t)
            except Exception as e:
                q.put(("error", {"error": f"{type(e).__name__}: {e}"}))
            finally:
                entry["runner"].emit = lambda kind, data: None
                q.put(("state", _state(sid)))
                q.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            kind, data = item
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ 그림, 보고서
def _heatmap_png(s, card_id, dark=False):
    c = s.cards.get(card_id.upper())
    if c is None or not c.validation or not c.validation["ok"]:
        raise HTTPException(404, "그림을 만들 수 없는 카드입니다.")
    amp = c.amp if c.amp is not None else measure.load_cscan(s.folder / c.info["scan_file"])
    return heatmap.render_png(amp, c.meta["grid"]["pitch_mm"], c.indications if c.eval else (), c.excluded,
                              c.meta["reference_db"], c.proc["drop_db"] if c.proc else 6.0, dark=dark)


@app.get("/api/sessions/{sid}/cards/{card_id}/heatmap.png")
def card_heatmap(sid: str, card_id: str, theme: str = ""):
    # theme=dark: 화면용 어두운 그림. 보고서(인쇄용 문서)는 기본 흰 바탕을 쓴다
    return Response(_heatmap_png(_get(sid)["session"], card_id, dark=theme == "dark"), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


def _report_html(s, embed):
    if s.package_report is None:
        raise HTTPException(409, "보고서 초안이 아직 없습니다.")
    if s.report_stale:
        raise HTTPException(409, "반려·정정 후 재평가가 끝나지 않아 보고서를 만들 수 없습니다.")
    if embed:
        def url(cid):
            return "data:image/png;base64," + base64.b64encode(_heatmap_png(s, cid)).decode()
    else:
        def url(cid):
            return f"/api/sessions/{s.id}/cards/{cid}/heatmap.png?t={int(time.time())}"
    return rpt.render_html(s.package_report, url)


@app.get("/api/sessions/{sid}/report", response_class=HTMLResponse)
def report(sid: str, embed: int = 0):
    return _report_html(_get(sid)["session"], bool(embed))


# ------------------------------------------------------------------ 발송(.eml 저장)
class Dispatch(BaseModel):
    to: str
    cc: str = ""
    subject: str
    body: str


@app.post("/api/sessions/{sid}/dispatch")
def dispatch(sid: str, d: Dispatch):
    s = _get(sid)["session"]
    rep = s.package_report
    if rep is None or s.report_stale:
        raise HTTPException(409, "최신 보고서가 없습니다.")
    if rep["status"] != "APPROVED":
        waiting = [c.id for c in s.cards.values() if not c.approved]
        raise HTTPException(409, f"검사원 승인이 끝나지 않아 발송할 수 없습니다. 승인 대기: {', '.join(waiting)}")
    if "@" not in d.to:
        raise HTTPException(400, "수신자 주소를 확인해 주세요.")
    html_bytes = _report_html(s, True).encode("utf-8")
    msg = EmailMessage()
    msg["From"] = "gnu-eye@example.com"
    msg["To"] = d.to
    if d.cc:
        msg["Cc"] = d.cc
    msg["Subject"] = d.subject
    msg["Date"] = time.strftime("%a, %d %b %Y %H:%M:%S +0900")
    msg.set_content(d.body)
    fname = f"{rep['report_id']}.html"
    msg.add_attachment(html_bytes, maintype="text", subtype="html", filename=fname)
    outbox = OUT / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{s.id}_{time.strftime('%H%M%S')}.eml"
    path.write_bytes(bytes(msg))
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "to": d.to, "cc": d.cc, "subject": d.subject,
           "file": str(path.relative_to(ROOT)).replace("\\", "/"), "attachment": fname,
           "attachment_bytes": len(html_bytes), "attachment_sha256": hashlib.sha256(html_bytes).hexdigest(),
           "sent_over_network": False}
    s.dispatched.append(rec)
    s._audit("dispatch", **rec)
    return rec


# ------------------------------------------------------------------ 감사 로그, 챗봇
@app.get("/api/audit")
def audit(session: Optional[str] = None, limit: int = 300):
    path = OUT / "audit_log.jsonl"
    if not path.exists():
        return []
    sid = LATEST["id"] if session == "latest" else session
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sid and r.get("session") != sid:
            continue
        rows.append(r)
    return rows[-max(1, min(limit, 2000)):][::-1]


class Chat(BaseModel):
    question: str
    session_id: Optional[str] = None


@app.post("/api/chat")
def chat(c: Chat):
    entry = SESSIONS.get(LATEST["id"] if c.session_id in (None, "latest") else c.session_id)
    s = entry["session"] if entry else None
    use_llm = llm.status()["ok"]
    res = chatbot.answer(c.question, s, use_llm=use_llm)
    if s:
        s._audit("chat", question=c.question[:300], source=res["source"], answer=res["text"][:300])
    return res


@app.get("/", include_in_schema=False)
def root():
    # 첫 접속은 시작 화면(로고와 3D 비행기)으로. 홈은 그대로 index.html이다.
    return RedirectResponse("/start.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.exception_handler(HTTPException)
def http_error(_, e: HTTPException):
    return JSONResponse({"error": e.detail}, status_code=e.status_code)


app.mount("/", StaticFiles(directory=str(ROOT / "web"), html=True), name="web")
