"""에이전트 실행기: LLM 도구 호출 루프 + 고정 순서 모드.

- LLM 모드: LLM이 계획을 세우고 도구 순서를 정한다. 잘못된 호출은 세션의 가드레일이 거부한다.
  LLM이 중간에 멈추거나 서버 오류가 나면 코드가 고정 순서로 이어서 끝낸다(대체 경로).
- 고정 순서 모드: LLM 없이 같은 도구를 정해진 순서로 호출한다.
- 사용자에게 보이는 마무리 문장은 코드가 만든다. LLM 자유 서술은 쓰지 않는다.
"""
import json
import re
import time

from core import domain as dm

from . import llm
from .session import DECISION_WORDS, Session, ollama_tools, revs_in

MAX_ITERS = 14
MAX_FIXED_STEPS = 20
MAX_NUDGES = 2  # LLM이 일을 남기고 멈췄을 때 남은 상태를 알려 주고 다시 맡기는 횟수 (넘으면 대체 경로)

REMAINING = {
    "declare_plan": "계획을 아직 기록하지 않았다",
    "list_package": "패키지 항목을 아직 확인하지 않았다",
    "validate_scan": "스캔 검증을 아직 하지 않았다",
    "select_criteria": "기준을 정하지 않은 항목이 있다. 빠진 개정번호의 질문은 select_criteria가 등록한다",
    "inspect_package": "측정과 한도 대조(또는 반려 후 재평가)를 하지 않은 항목이 있다",
    "search_history": "이력 조회를 아직 하지 않았다",
    "draft_item_report": "항목별 초안이 없거나 최신이 아니다",
    "compile_package_report": "보고서 초안이 없거나 최신이 아니다",
}

SYSTEM = dm.PROFILES[dm.MAINT]["system"]


def compact(res, limit=1800):
    s = json.dumps(res, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…(생략)"


def parse_signoff(text, session):
    """고정 순서 모드용: 자유 문장에서 서명 요청을 찾는다. 이름은 '검사원 홍길동' 또는 '홍길동 검사원' 꼴만 인식한다."""
    low = text.lower()
    decision = next((d for d in ("reject", "approve") if any(w in low for w in DECISION_WORDS[d])), None)
    m = re.search(r"검사원\s*([가-힣A-Za-z]{2,10})|([가-힣A-Za-z]{2,10})\s*검사원", text)
    if not decision or not m:
        return None
    name = m.group(1) or m.group(2)
    cards = [cid for cid in session.cards if cid in text.upper()]
    if not cards and decision == "approve" and any(w in low for w in ("전체", "모두", "모든")):
        cards = ["ALL"]
    if len(cards) != 1:
        return None
    args = {"card_id": cards[0], "user": name, "decision": decision}
    if decision == "reject":
        inds = sorted(set(re.findall(r"IND-\d{2}", text.upper())))
        proc = re.search(r"GNU-(?:NTM|UT)-[A-Z0-9\-]+", text.upper())
        rev = sorted(revs_in(text))
        if inds:
            args["exclude_indications"] = inds
        if proc:
            args["procedure_id"] = proc.group(0)
        if len(rev) == 1:
            args["criteria_rev"] = rev[0]
        args["reason"] = text[:200]
    return args


class Runner:
    def __init__(self, session: Session, use_llm=True, emit=None):
        self.session = session
        self.use_llm = use_llm
        self.emit = emit or (lambda kind, data: None)
        self.messages = [{"role": "system", "content": session.prof["system"]}]
        self.llm_seconds = []
        self.fallbacks = []
        self.nudges = []
        # 새 검사 요청이 만들어지면 API가 True로 바꾼다. LLM은 한 번에 요청 하나만 처리하므로(-np 1)
        # 버려진 세션이 계속 돌면 새 세션이 그 뒤에 줄을 선다. 다음 턴을 시작하면 다시 False가 된다.
        self.cancelled = False

    # ------------------------------------------------------------ 한 턴
    def run_turn(self, user_text, hear=True):
        """사용자 입력 1건을 처리한다. 끝나면 코드가 만든 마무리 문장을 돌려준다."""
        s = self.session
        self.cancelled = False
        if hear:
            s.hear(user_text)
        n0 = len(s.calls)
        if self.use_llm:
            try:
                self._llm_turn(user_text)
            except Exception as e:  # LLM 서버 오류: 대체 경로로 간다
                self._fallback(f"LLM 호출 실패 ({type(e).__name__}: {e})")
        else:
            self._fixed_user_intent(user_text)
        self.finish()
        text = self.render_final(s.calls[n0:])
        self.emit("final", {"text": text})
        return text

    def _tool(self, name, args, by):
        res = self.session.call(name, args, by=by)
        self.emit("tool", {"name": name, "args": args, "by": by, "ok": "error" not in res, "result": res})
        return res

    def _fallback(self, reason):
        self.fallbacks.append(reason)
        self.session._audit("llm_fallback", reason=reason)
        self.emit("fallback", {"reason": reason})

    # ------------------------------------------------------------ LLM 루프
    def _llm_turn(self, user_text):
        self.messages.append({"role": "user", "content": user_text})
        seen = set()
        nudged = 0
        for _ in range(MAX_ITERS):
            if self.cancelled:
                self.session._audit("turn_cancelled", reason="새 검사 요청이 만들어져 이 세션의 LLM 진행을 멈춤")
                return
            t0 = time.time()
            r = llm.chat(self.messages, ollama_tools(self.session.domain))
            sec = round(time.time() - t0, 1)
            self.llm_seconds.append(sec)
            msg = r["message"]
            self.messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            calls = msg.get("tool_calls") or []
            self.emit("llm", {"sec": sec, "tool_calls": [c["function"]["name"] for c in calls]})
            if not calls:
                why = self._unfinished()
                if not why or nudged >= MAX_NUDGES:
                    return
                nudged += 1
                self.nudges.append(why)
                self.session._audit("llm_nudge", reason=why)
                self.messages.append({"role": "user", "content": (
                    f"[진행 확인] 작업이 아직 끝나지 않았다: {why}. 사용자에게 직접 묻거나 설명하지 말고 "
                    "규칙 2의 순서에서 남은 도구를 이어서 호출하라.")})
                continue
            for c in calls:
                name, args = c["function"]["name"], c["function"].get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                if key in seen:  # 같은 인자로 같은 도구 반복 방지
                    res = {"error": "같은 인자로 이미 호출했다. 이전 결과를 쓰거나 다음 단계로 진행한다."}
                    self.session.calls.append({"tool": name, "args": args, "ok": False, "by": "llm", "sec": 0,
                                               "ts": time.strftime("%H:%M:%S"), "error": res["error"]})
                    self.emit("tool", {"name": name, "args": args, "by": "llm", "ok": False, "result": res})
                else:
                    seen.add(key)
                    res = self._tool(name, args, "llm")
                self.messages.append({"role": "tool", "content": compact(res), "tool_name": name})
        self._fallback("LLM이 최대 반복 횟수를 넘김")

    def _unfinished(self):
        """LLM이 도구 호출 없이 멈췄을 때 남은 일이 있으면 그 상태를 문장으로 돌려준다. 사용자 답을 기다릴 때는 None."""
        s = self.session
        pend = s.pending_questions()
        if pend and s.criteria_done:
            if any((q["card_id"], r) in s.rev_statements for q in pend for r in q["options"]):
                return "사용자가 개정번호를 답했는데 select_criteria에 card_id와 rev로 반영하지 않았다"
            return None
        name, _ = s.next_required()
        return REMAINING.get(name)

    # ------------------------------------------------------------ 고정 순서
    def _fixed_user_intent(self, text):
        """LLM 없이 사용자 입력의 의도를 처리한다: 개정번호 답, 서명."""
        s = self.session
        self._apply_rev_answers()
        if s.package_report is not None:
            args = parse_signoff(text, s)
            if args:
                self._tool("record_signoff", args, "fixed")

    def _apply_rev_answers(self):
        s = self.session
        for q in s.pending_questions():
            said = sorted(r for (cid, r) in s.rev_statements if cid == q["card_id"])
            if q["field"] == "criteria_rev" and len(said) == 1:
                self._tool("select_criteria", {"card_id": q["card_id"], "rev": said[0]}, "fixed")

    def resume(self, note):
        """검사원이 버튼으로 한 동작(반려, 보류) 뒤의 남은 단계를 진행한다. LLM 모드면 재평가 순서를 LLM이 정하고,
        LLM이 없거나 멈추면 고정 순서로 끝낸다. 서명 자체는 버튼이 이미 기록했으므로 LLM을 거치지 않는다."""
        self.cancelled = False
        if self.use_llm and self.session.next_required()[0] not in ("WAIT", "DONE"):
            try:
                self._llm_turn(f"[검사원이 화면에서 한 동작] {note}\n이 동작은 이미 기록됐다. record_signoff를 다시 호출하지 말고 "
                               "남은 평가·이력·초안·보고서 단계를 순서대로 진행하라.")
            except Exception as e:
                self._fallback(f"LLM 호출 실패 ({type(e).__name__}: {e})")
        self.finish()

    def finish(self):
        """남은 단계를 고정 순서로 끝까지 진행한다. LLM 모드에서 여기서 도구가 호출되면 대체 경로로 기록한다."""
        s = self.session
        if self.cancelled:  # 버려진 세션은 이어서 끝내지 않는다 (종합 의견 작성도 LLM을 쓴다)
            return
        noted = False
        for _ in range(MAX_FIXED_STEPS):
            if s.pending_questions() and s.criteria_done:
                before = len(s.pending_questions())
                if self.use_llm and not noted and any(
                        (q["card_id"], r) in s.rev_statements for q in s.pending_questions() for r in q["options"]):
                    self._fallback("LLM이 사용자 답을 반영하지 않아 코드가 이어서 진행")
                    noted = True
                self._apply_rev_answers()
                if len(s.pending_questions()) == before:
                    return
                continue
            name, args = s.next_required()
            if name in ("WAIT", "DONE"):
                return
            if self.use_llm and not noted:
                self._fallback(f"LLM이 {name} 단계 전에 멈춰 코드가 이어서 진행")
                noted = True
            res = self._tool(name, args, "fixed")
            if "error" in res:
                self.emit("error", {"tool": name, "error": res["error"]})
                return

    # ------------------------------------------------------------ 마무리 문장 (코드가 만든다)
    def render_final(self, turn_calls):
        s = self.session
        lines = []
        for c in turn_calls:
            if c["tool"] == "record_signoff":
                if c["ok"]:
                    a = c["args"]
                    target = f"전체 {s.prof['unit']}" if str(a["card_id"]).upper() == "ALL" else a["card_id"]
                    lines.append(f"{a['user']} 검사원의 {target} "
                                 f"{'승인' if a['decision'] == 'approve' else '반려'} 기록을 남겼습니다.")
                else:
                    why = ("검사원 이름이 없습니다. 서명은 검사원이 이름을 밝히고 직접 요청할 때만 기록합니다."
                           if "필수 인자 누락" in c["error"] and "user" in c["error"] else c["error"])
                    lines.append(f"서명을 기록하지 않았습니다: {why}")
        qs = s.pending_questions()
        if qs:
            lines += [q["text"] for q in qs]
            return "\n".join(lines)
        rep = s.package_report
        if rep and not s.report_stale:
            lines.append(rep["summary"])
            waiting = [c.id for c in s.cards.values() if not c.approved]
            lines.append(f"모든 {s.prof['unit']}의 승인이 끝났습니다. 최종 판단과 서명 책임은 검사원에게 있습니다." if not waiting
                         else f"보고서 초안을 만들었습니다. 검사원 승인 대기: {', '.join(waiting)}.")
        else:
            errs = [c for c in turn_calls if not c["ok"]]
            lines.append("처리를 끝내지 못했습니다. " + (errs[-1]["error"] if errs else "다음 단계: " + s.next_required()[0]))
        return "\n".join(lines)

    def guard_metrics(self):
        """가드레일 지표: LLM이 한 호출 중 코드가 거부한 건수."""
        by_llm = [c for c in self.session.calls if c.get("by") == "llm"]
        return {"llm_calls": len(by_llm), "llm_calls_blocked": sum(not c["ok"] for c in by_llm),
                "fallbacks": self.fallbacks, "nudges": self.nudges, "llm_seconds": self.llm_seconds}
