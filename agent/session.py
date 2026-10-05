"""세션 상태 + 도구 9종 + 가드레일 + 감사 로그. 수치는 전부 core/에서 나오고 LLM은 만들지 않는다.

코드로 강제하는 것
- 순서: 선행 단계가 끝나지 않으면 도구가 오류를 돌려준다.
- 근거: 개정번호·정정 값·검사원 이름은 사용자 발화에 실제로 있어야 한다. 없으면 거부하고 되묻는다.
- 서명: 이번 발화에 검사원 이름과 승인/반려 의사가 모두 있어야 하고, 한 발화에 카드당 한 번만 기록한다.
- 반려 후에는 재평가 전까지 보고서 생성을 막는다(stale).
- 모든 입력은 hear()로 기록하고, 모든 도구 호출은 outputs/audit_log.jsonl에 남긴다.
"""
import json
import re
import time
from pathlib import Path

from core import criteria as cr
from core import domain as dm
from core import history as hist
from core import measure
from core import package as pkg
from core import report as rpt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"

BOT_NAMES = {"ai", "assistant", "agent", "claude", "system", "llm", "bot", "gnu-eye", "지누아이",
             "시스템", "에이전트", "ai 에이전트", "검사원", "inspector", "user", "사용자"}
DECISION_WORDS = {"approve": ["승인", "approve", "서명"], "reject": ["반려", "reject", "거부"]}
OPINION_RETRIES = 2  # 종합 의견이 검증에 걸리면 사유를 돌려주고 다시 쓰게 하는 횟수 (넘으면 코드 문장)
OPINION_BANNED = ("판정", "결정", "권장", "필요하지 않", "필요 없")


class ToolError(Exception):
    pass


def _s(desc):
    return {"type": "string", "description": desc}


_CARDS = {"type": "array", "items": {"type": "string"}, "description": "작업카드 ID 목록. 생략하면 전체"}

TOOL_SPECS = [
    {"name": "declare_plan", "description": "작업을 시작할 때 가장 먼저 호출한다. 수행할 단계 계획을 기록한다.",
     "properties": {"steps": {"type": "array", "items": {"type": "string"}, "description": "단계 목록"}},
     "required": ["steps"]},
    {"name": "list_package", "description": "패키지의 작업카드 목록과 카드별로 빠진 정보를 보고한다.",
     "properties": {}, "required": []},
    {"name": "validate_scan", "description": "모든 카드의 스캔 파일 형식·크기·메타데이터를 검증한다.",
     "properties": {}, "required": []},
    {"name": "select_criteria",
     "description": "카드별 절차와 허용 손상 기준을 고른다. 인자 없이 호출하면 전체 카드를 처리한다. "
                    "개정번호가 빠진 카드는 사용자가 답한 뒤 card_id와 rev를 넣어 다시 호출한다. rev는 사용자가 말한 값만 쓴다.",
     "properties": {"card_id": _s("작업카드 ID (예: CARD-05)"), "rev": _s("사용자가 말한 기준 개정번호 (A, B ...)")},
     "required": []},
    {"name": "inspect_package",
     "description": "기준이 정해진 카드를 한꺼번에 처리한다: 절차 적합성 확인, 6 dB drop 측정, 한도 대조, 처분 초안. "
                    "검사원 반려 후 재평가에도 쓴다.",
     "properties": {"card_ids": _CARDS}, "required": []},
    {"name": "search_history", "description": "같은 기체·같은 부위의 이전 점검 기록을 찾아 손상 크기 변화를 비교한다.",
     "properties": {}, "required": []},
    {"name": "draft_item_report", "description": "카드별 손상 평가 초안을 만든다.", "properties": {}, "required": []},
    {"name": "compile_package_report", "description": "기체 단위 NDT 점검 보고서 초안을 만든다. 카드별 초안이 모두 최신일 때만 가능하다.",
     "properties": {}, "required": []},
    {"name": "record_signoff",
     "description": "검사원이 이름을 밝히고 직접 승인/반려를 말했을 때만 기록한다(스스로 호출 금지). "
                    "반려하면서 지시 제외, 절차 정정, 개정번호 정정을 함께 기록할 수 있고, 그 뒤 inspect_package로 재평가한다.",
     "properties": {"card_id": _s("작업카드 ID. 전체 승인은 ALL"), "user": _s("검사원 이름"),
                    "decision": {"type": "string", "enum": ["approve", "reject"]}, "reason": _s("사유"),
                    "exclude_indications": {"type": "array", "items": {"type": "string"},
                                            "description": "제외할 지시 ID (예: IND-02). 반려일 때만"},
                    "procedure_id": _s("정정할 절차 ID. 반려일 때만, 검사원이 말한 값만"),
                    "criteria_rev": _s("정정할 기준 개정번호. 반려일 때만, 검사원이 말한 값만")},
     "required": ["card_id", "user", "decision"]},
]


# 제조 검사 패키지일 때 LLM에 보여 주는 도구 설명 (인자와 동작은 같다)
MFG_DESCRIPTIONS = {
    "list_package": "생산 로트 패키지의 검사 부품 목록과 부품별로 빠진 정보를 보고한다.",
    "select_criteria": "부품별 절차와 고객사양을 고른다. 인자 없이 호출하면 전체 부품을 처리한다. "
                       "개정번호가 빠진 부품은 사용자가 답한 뒤 card_id와 rev를 넣어 다시 호출한다. rev는 사용자가 말한 값만 쓴다.",
    "inspect_package": "기준이 정해진 부품을 한꺼번에 처리한다: 절차 적합성 확인, 6 dB drop 측정, 고객사양 한도 대조, 처분 초안. "
                       "검사원 반려 후 재평가에도 쓴다.",
    "search_history": "같은 부품번호의 과거 부적합보고서(NCR) 이력을 조회한다.",
    "draft_item_report": "부품별 평가 초안을 만든다.",
    "compile_package_report": "로트 단위 검사 보고서와 NCR 초안을 만든다. 부품별 초안이 모두 최신일 때만 가능하다.",
}


def ollama_tools(domain=dm.MAINT):
    over = MFG_DESCRIPTIONS if domain == dm.MFG else {}
    return [{"type": "function", "function": {
        "name": t["name"], "description": over.get(t["name"], t["description"]),
        "parameters": {"type": "object", "properties": t["properties"], "required": t["required"]}}}
        for t in TOOL_SPECS]


def revs_in(text):
    """발화에서 개정번호 표현을 찾는다: 'Rev B', 'B 개정', '개정번호는 B', '개정 B'."""
    found = {m.upper() for m in re.findall(r"rev(?:ision)?\.?\s*([A-Za-z])(?![A-Za-z])", text, re.I)}
    found |= {m.upper() for m in re.findall(r"(?<![A-Za-z])([A-Za-z])\s*개정", text)}
    found |= {m.upper() for m in re.findall(r"개정(?:번호)?(?:는|은|:|=)?\s*([A-Za-z])(?![A-Za-z])", text)}
    return found


class Card:
    def __init__(self, info):
        self.id = info["card_id"]
        self.info = info
        self.meta = None
        self.validation = None
        self.rev = info.get("criteria_rev")
        self.rev_source = "package" if self.rev else None
        self.procedure_id = info.get("procedure_id")
        self.proc = self.limits = self.proc_check = None
        self.amp = None
        self.indications, self.excluded = [], set()
        self.eval = self.history = self.report = None
        self.signoffs = []
        self.held = False
        self.blocked_reason = None
        self.stale = False
        self.inspected = False

    @property
    def ready(self):
        """기준과 절차가 정해져 측정·판정을 시도할 수 있는 상태."""
        return bool(self.proc and self.limits and not self.held and self.validation and self.validation["ok"])

    def active(self):
        return [i for i in self.indications if i["id"] not in self.excluded]

    @property
    def approved(self):
        return bool(self.signoffs) and self.signoffs[-1]["decision"] == "approve" and not self.stale


class Session:
    def __init__(self, folder, session_id=None, llm=None, log=True, mode_info="고정 순서 모드 (LLM 없음)"):
        self.id = session_id or time.strftime("S%Y%m%d-%H%M%S")
        self.llm = llm  # callable(prompt)->str, 선택. 종합 의견 문단에만 쓴다.
        self.log = log
        self.mode_info = mode_info
        self.package = pkg.load_package(folder)
        self.domain = self.package["domain"]
        self.prof = dm.profile(self.domain)
        self.folder = Path(self.package["folder"])
        self.cards = {c["card_id"]: Card(c) for c in self.package["cards"]}
        self.utterances, self.last_user = [], ""
        self.rev_statements = set()  # 사용자가 말한 (카드, 개정번호)
        self.plan, self.calls, self.questions = [], [], []
        self.listed = self.validated = self.criteria_done = self.inspect_done = False
        self.history_ok = self.items_ok = False
        self.package_report = None
        self.report_stale = False
        self.signed = set()  # (발화, card_id): 한 발화에 카드당 서명 1회
        self.dispatched = []
        self._audit("session_start", package=self.package["package_id"], cards=sorted(self.cards), domain=self.domain)

    # ------------------------------------------------------------ 공통
    def hear(self, text):
        """사용자 입력을 기록한다. 개정번호·서명 근거 확인이 이 기록을 쓰므로 모든 입력 경로가 거쳐야 한다."""
        text = str(text)
        self.utterances.append(text)
        self.last_user = text
        revs = revs_in(text)
        if revs:
            named = [cid for cid in self.cards if cid in text.upper()]
            pend = [q["card_id"] for q in self.pending_questions() if q["field"] == "criteria_rev"]
            if not named and len(pend) == 1:  # 질문이 하나뿐일 때 카드 이름 없이 답한 경우
                named = pend
            self.rev_statements |= {(cid, r) for cid in named for r in revs}
        self._audit("hear", text=text[:500])

    def _audit(self, event, **kw):
        if not self.log:
            return
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": self.id, "event": event, **kw}
        OUT.mkdir(exist_ok=True)
        with open(OUT / "audit_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _need(self, cond, msg):
        if not cond:
            raise ToolError(msg)

    def _card(self, card_id):
        cid = str(card_id).strip().upper()
        self._need(cid in self.cards, f"{self.prof['unit_long']} {card_id} 없음. 패키지의 {self.prof['unit']}: {sorted(self.cards)}")
        return self.cards[cid]

    def _invalidate(self):
        self.history_ok = self.items_ok = False
        if self.package_report:
            self.report_stale = True

    def pending_questions(self):
        return [q for q in self.questions if not q["answered"]]

    def _user_said_rev(self, card, rev):
        """이 카드에 대해 사용자가 그 개정번호를 말했는가 (hear()가 발화 시점에 기록한 것만 인정)."""
        return (card.id, rev) in self.rev_statements

    # ------------------------------------------------------------ 도구
    def declare_plan(self, steps):
        self.plan = [str(s) for s in steps][:12]
        return {"recorded": True, "steps": self.plan}

    def list_package(self):
        self.listed = True
        rows = []
        for c in self.cards.values():
            rows.append({"card_id": c.id, "title": c.info.get("title", ""), "zone_id": c.info.get("zone_id"),
                         "procedure_id": c.procedure_id, "criteria": c.info.get("criteria_id"),
                         "criteria_rev": c.rev, "missing": c.info["missing"]})
        return {"package_id": self.package["package_id"], "aircraft": self.package["aircraft"],
                "check_type": self.package["check_type"], "cards": rows,
                "cards_with_missing_info": [r["card_id"] for r in rows if r["missing"]]}

    def validate_scan(self):
        self._need(self.listed, "먼저 list_package로 패키지 항목을 확인해야 한다.")
        rows = []
        for c in self.cards.values():
            miss = [m for m in c.info["missing"] if m in ("scan_file", "meta_file")]
            if miss:
                c.validation = {"ok": False, "missing_fields": miss, "problems": ["스캔 또는 메타데이터 파일이 패키지에 없음"]}
            else:
                try:
                    c.meta = measure.load_meta(self.folder / c.info["meta_file"])
                    if not isinstance(c.meta, dict):
                        raise ValueError("메타데이터 최상위는 객체여야 함")
                    c.validation = measure.validate_scan(self.folder / c.info["scan_file"], c.meta)
                except (ValueError, OSError) as e:
                    c.meta = None
                    c.validation = {"ok": False, "missing_fields": [], "problems": [f"메타데이터를 읽을 수 없음: {e}"]}
            if not c.validation["ok"]:
                c.blocked_reason = ("입력 오류: " + "; ".join(
                    [f"빠진 항목 {c.validation['missing_fields']}"] * bool(c.validation["missing_fields"])
                    + c.validation["problems"]) + ". 추정값으로 판정하지 않음.")
            rows.append({"card_id": c.id, "ok": c.validation["ok"], "missing_fields": c.validation["missing_fields"],
                         "problems": c.validation["problems"]})
        self.validated = True
        return {"checked": len(rows), "failed": [r["card_id"] for r in rows if not r["ok"]], "cards": rows}

    def _select_one(self, c, rev=None):
        if c.held:
            return {"card_id": c.id, "status": "held"}
        if not c.validation["ok"]:
            return {"card_id": c.id, "status": "blocked", "reason": c.blocked_reason}
        miss = [m for m in c.info["missing"] if m != "criteria_rev"]
        if miss:
            c.blocked_reason = (f"{self.prof['unit']} 정보 누락: "
                                + ", ".join(pkg.field_ko(self.domain).get(m, m) for m in miss) + ". 추정하지 않음.")
            return {"card_id": c.id, "status": "blocked", "reason": c.blocked_reason}
        if rev is not None:
            rev = str(rev).strip().upper()
            if c.rev_source == "package" and rev != c.rev:
                raise ToolError(f"{c.id}는 패키지에 Rev {c.rev}로 지정돼 있다. 바꾸려면 검사원이 반려하면서 정정해야 한다.")
            if c.rev_source != "package":
                self._need(self._user_said_rev(c, rev),
                           f"사용자가 {c.id}의 기준 개정번호를 Rev {rev}라고 말한 적이 없다. 추측하지 말고 사용자에게 묻는다.")
                c.rev, c.rev_source = rev, "user"
                for q in self.questions:
                    if q["card_id"] == c.id and q["field"] == "criteria_rev" and not q["answered"]:
                        q["answered"], q["answer"] = True, rev
        if not c.rev:
            if not any(q["card_id"] == c.id and q["field"] == "criteria_rev" and not q["answered"] for q in self.questions):
                opts = cr.available_revisions(c.info["criteria_id"])
                q = {"id": f"Q{len(self.questions) + 1}", "card_id": c.id, "field": "criteria_rev", "options": opts,
                     "answered": False,
                     "text": f"{c.id}에 {self.prof['criteria_word']} {c.info['criteria_id']}의 개정번호가 적혀 있지 않습니다. "
                             f"개정본에 따라 한도가 달라 추측하지 않습니다. 적용할 개정번호를 알려 주세요. "
                             f"(등록된 개정: {', '.join(opts)})"}
                self.questions.append(q)
                self._audit("question", **{k: q[k] for k in ("id", "card_id", "field", "text")})
            return {"card_id": c.id, "status": "needs_revision",
                    "action": "개정번호를 추측하지 말고 사용자에게 묻는다."}
        try:
            c.proc = cr.load_procedure(c.procedure_id)
            c.limits = cr.load_limits(c.info["criteria_id"], c.rev)
            self._check_domain(c.proc, c.limits)
            if c.info["zone_id"] not in c.limits["zones"]:
                raise cr.CriteriaError(f"기준에 구역 {c.info['zone_id']} 없음")
        except cr.CriteriaError as e:
            c.proc = c.limits = None
            c.blocked_reason = f"기준 선택 실패: {e}"
            return {"card_id": c.id, "status": "blocked", "reason": c.blocked_reason}
        c.blocked_reason = None
        c.stale = c.stale or c.inspected  # 기준이 바뀌었으면 재평가 필요
        return {"card_id": c.id, "status": "selected", "procedure": c.procedure_id,
                "criteria": f"{c.info['criteria_id']} Rev {c.rev}", "rev_source": c.rev_source, "source": c.limits["source"]}

    def _check_domain(self, proc=None, limits=None):
        """정비 패키지에 제조 사양을(또는 반대로) 적용하지 못하게 막는다."""
        for kind, doc in (("절차", proc), ("기준", limits)):
            if doc is not None and doc.get("domain", dm.MAINT) != self.domain:
                raise cr.CriteriaError(f"{kind} {doc.get('id') or doc.get('criteria_id')}는 "
                                       f"{dm.profile(doc.get('domain', dm.MAINT))['name']}용이라 "
                                       f"{self.prof['name']} 패키지에 쓸 수 없음")

    def select_criteria(self, card_id=None, rev=None):
        self._need(self.validated, "먼저 validate_scan을 실행해야 한다.")
        if card_id is None:
            self._need(rev is None, "rev를 넣을 때는 card_id도 함께 넣어야 한다.")
            rows = [self._select_one(c) for c in self.cards.values() if not (c.proc and c.limits)]
        else:
            rows = [self._select_one(self._card(card_id), rev)]
        self.criteria_done = True
        self._invalidate()
        res = {"cards": rows}
        qs = self.pending_questions()
        if qs:
            res["questions"] = [{"id": q["id"], "card_id": q["card_id"], "text": q["text"]} for q in qs]
            res["action"] = "질문에 대한 사용자 답을 기다린다. 값을 추측하지 않는다."
        return res

    def inspect_package(self, card_ids=None):
        self._need(self.criteria_done, "먼저 select_criteria로 기준을 정해야 한다. 기준 없이 평가하지 않는다.")
        targets = [self._card(i) for i in card_ids] if card_ids else list(self.cards.values())
        rows = []
        for c in targets:
            if not c.ready:
                why = ("검사원 보류" if c.held else c.blocked_reason
                       or ("기준 개정번호 미지정 - 사용자 답 대기" if not c.rev else "기준 미선택"))
                rows.append({"card_id": c.id, "status": "skipped", "reason": why})
                continue
            c.proc_check = cr.check_procedure(c.proc, c.meta["thickness_mm"], c.info["material"])
            c.inspected, c.stale = True, False
            if not c.proc_check["ok"]:
                c.eval, c.indications, c.amp = None, [], None
                c.blocked_reason = "절차 부적합: " + "; ".join(c.proc_check["reasons"]) + ". 측정·판정하지 않음."
                rows.append({"card_id": c.id, "status": "procedure_mismatch", "reason": c.blocked_reason})
                continue
            c.blocked_reason = None
            c.amp = measure.load_cscan(self.folder / c.info["scan_file"])
            c.indications = measure.extract_indications(
                c.amp, c.meta["grid"]["pitch_mm"], c.proc["drop_db"], c.meta["reference_db"],
                c.proc["min_indication_area_mm2"])
            c.excluded &= {i["id"] for i in c.indications}
            c.eval = cr.evaluate(c.active(), c.limits, c.info["zone_id"],
                                 scan_area_mm2=c.amp.size * c.meta["grid"]["pitch_mm"] ** 2)
            rows.append({"card_id": c.id, "status": "evaluated", "indications": len(c.active()),
                         "largest_major_mm": c.active()[0]["major_mm"] if c.active() else None,
                         "disposition": c.eval["disposition"], "disposition_ko": c.eval["disposition_ko"],
                         "findings": [f"{f['rule_id']} {f['indication']}" for f in c.eval["findings"]],
                         "warnings": len(c.eval["warnings"]), "excluded": sorted(c.excluded)})
        self.inspect_done = True
        self._invalidate()
        return {"processed": len(rows), "cards": rows, "status": cr.DRAFT_STATUS}

    def search_history(self):
        todo = [c.id for c in self.cards.values() if c.ready and (not c.inspected or c.stale)]
        self._need(not todo, f"먼저 inspect_package로 평가해야 한다 (미평가 또는 재평가 필요: {todo}).")
        self._need(self.inspect_done, "먼저 inspect_package를 실행해야 한다.")
        rows = []
        for c in self.cards.values():
            if not c.eval:
                c.history = None
                continue
            act = c.active()
            if self.domain == dm.MFG:
                c.history = hist.ncr_lookup(c.info["part_number"])
            else:
                c.history = hist.compare(self.package["aircraft"], c.info["location_id"],
                                         act[0]["major_mm"] if act else None, c.limits["growth_flag_mm"])
            rows.append({"card_id": c.id, "found": c.history["found"], "grew": c.history.get("grew", False),
                         "text": c.history["text"]})
        self.history_ok = True
        self.items_ok = False
        source = self.prof["history_source"]
        if self.domain == dm.MFG:  # 이력 파일이 없으면 없다고 그대로 알린다
            source = next((c.history["source"] for c in self.cards.values() if c.history), source)
        return {"source": source, "cards": rows,
                "growth_suspected": [r["card_id"] for r in rows if r["grew"]],
                "with_past_ncr": [r["card_id"] for r in rows if r["found"]] if self.domain == dm.MFG else []}

    def draft_item_report(self):
        self._need(self.history_ok, "먼저 search_history로 이전 기록을 비교해야 한다.")
        stale = [c.id for c in self.cards.values() if c.stale]
        self._need(not stale, f"반려·정정 후 재평가하지 않은 카드가 있다: {stale}. inspect_package로 재평가한다.")
        for c in self.cards.values():
            c.report = rpt.build_item_report(c, domain=self.domain)
        self.items_ok = True
        if self.package_report:
            self.report_stale = True
        return {"drafted": len(self.cards),
                "cards": [{"card_id": c.id, "disposition_ko": c.report["disposition_ko"], "summary": c.report["summary"]}
                          for c in self.cards.values()]}

    def compile_package_report(self):
        self._need(self.items_ok, "먼저 draft_item_report로 카드별 초안을 만들어야 한다.")
        stale = [c.id for c in self.cards.values() if c.stale]
        self._need(not stale, f"반려·정정 후 재평가하지 않은 카드가 있다: {stale}.")
        qs = self.pending_questions()
        self._need(not qs, f"답을 받지 못한 질문이 있다: {[q['card_id'] for q in qs]}. 사용자 답을 기다린다.")
        self._build_report(with_opinion=True)
        p = self._save_report()
        return {"report_id": self.package_report["report_id"], "status": self.package_report["status_ko"],
                "summary": self.package_report["summary"], "opinion_source": self.package_report["opinion_source"],
                "saved": p}

    def _build_report(self, with_opinion=False):
        prev = self.package_report
        for c in self.cards.values():
            c.report["signoffs"] = list(c.signoffs)
        all_signs = [s for c in self.cards.values() for s in c.signoffs]
        rep = rpt.build_package_report(self.package, [c.report for c in self.cards.values()], all_signs,
                                       self.mode_info)
        if with_opinion and self.llm:
            rep["opinion"], rep["opinion_source"], rep["opinion_check"] = self._llm_opinion(rep)
        elif prev and not with_opinion:
            # 서명만 반영해 다시 만들 때는 검증을 통과한 의견과 문서번호를 유지한다
            rep["report_id"] = prev["report_id"]
            if prev["opinion_source"] == "llm":
                rep["opinion"], rep["opinion_source"] = prev["opinion"], "llm"
        self.package_report = rep
        self.report_stale = False

    def _llm_opinion(self, rep):
        facts = rep["summary"] + "\n" + "\n".join(r["summary"] for r in rep["items"])
        act = rep["actions"]
        groups = {w: act[k] for w, k in self.prof["opinion_groups"].items()}
        prompt = (self.prof["opinion_intro"] + "\n"
                  "규칙: 아래 사실에 있는 숫자와 카드 ID만 쓴다. 새 숫자를 만들지 않는다. "
                  "'합격', '불합격', '안전' 같은 단정은 쓰지 않는다. 영어 단어를 괄호로 덧붙이지 않는다. "
                  "조치마다 문장을 나눈다. 한 문장에는 한 가지 조치와 그 조치에 해당하는 ID만 쓰고, "
                  "건수를 요약하는 문장에는 ID를 쓰지 않는다. "
                  "처분은 모두 '처분 초안'이라고 쓰고 '판정', '결정', '권장'이라는 말은 쓰지 않는다. "
                  "이유는 사실에 적힌 표현 그대로만 쓰고 새 이유나 조치를 덧붙이지 않는다. "
                  "여러 ID를 한 문장에 묶을 때는 근거 규칙이 같은 것끼리만 묶고, 규칙이 다르면 ID마다 그 규칙을 따로 쓴다. "
                  + self.prof["opinion_must"] + " "
                  "마지막 문장은 '최종 판단과 서명은 자격 검사원이 한다.'로 끝낸다.\n사실:\n" + facts
                  + "\n조치별 대상:\n" + "\n".join(f"- {w}: {', '.join(ids) or '없음'}" for w, ids in groups.items()))
        tries, ask = [], prompt
        for _ in range(1 + OPINION_RETRIES):
            try:
                text = (self.llm(ask) or "").strip()
            except Exception as e:  # LLM 오류면 템플릿으로 대체
                return rep["summary"], "template", {"error": f"{type(e).__name__}: {e}", "attempts": tries}
            ok, detail = rpt.verify_narrative(text, facts, act["oem_inquiry"], groups, card_ids=set(self.cards))
            said = [w for w in OPINION_BANNED if w in text]  # 초안을 확정처럼 말하거나 조치를 지어내는 표현
            if said:
                ok, detail["banned"] = False, detail["banned"] + said
            tries.append({"ok": ok, "text": text[:400], **{k: v for k, v in detail.items() if v}})
            if ok:
                break
            # 검증에서 걸린 점을 돌려주고 다시 쓰게 한다
            ask = (prompt + "\n\n앞서 쓴 글:\n" + text[:600] + "\n검증에서 걸린 점:\n"
                   + "\n".join("- " + p for p in self._opinion_problems(detail, groups, len(text)))
                   + "\n걸린 점을 고쳐 처음부터 다시 써라. 글만 쓴다.")
        detail["attempts"] = tries
        n = len(tries)
        note = "" if n == 1 else (f"(검증 사유를 받아 {n}번째 작성) " if ok else f"({n}회 작성 모두 검증 실패) ")
        self._audit("llm_opinion", ok=ok, detail=detail, text=note + text[:400])
        return (text, "llm", detail) if ok else (rep["summary"], "template", detail)

    @staticmethod
    def _opinion_problems(detail, groups, length):
        out = []
        if detail["unsupported_numbers"]:
            out.append(f"사실에 없는 숫자를 썼다: {detail['unsupported_numbers'][:5]}. 사실에 있는 숫자만 쓴다.")
        if detail["missing_ids"]:
            out.append(f"반드시 써야 하는 ID가 빠졌다: {', '.join(detail['missing_ids'])}.")
        if detail["banned"]:
            out.append(f"쓰면 안 되는 표현을 썼다: {', '.join(detail['banned'])}.")
        if detail["stray_english"]:
            out.append(f"괄호 안 영어를 썼다: {', '.join(detail['stray_english'][:3])}.")
        for m in detail["mislinked"]:
            out.append(f"'{m['word']}'라는 낱말이 있는 문장에 {', '.join(m['cards'])}를 함께 썼다. 그 낱말이 있는 문장에는 "
                       f"{', '.join(groups.get(m['word'], [])) or '어떤 ID도'}만 쓸 수 있다. 문장을 나누고, "
                       f"{', '.join(m['cards'])}가 있는 문장에는 '{m['word']}'라는 낱말을 쓰지 않는다.")
        if not 10 <= length <= 600:
            out.append("글 길이는 600자 이내로 한다.")
        return out or ["형식 규칙을 다시 확인한다."]

    def _save_report(self):
        d = OUT / "reports"
        d.mkdir(parents=True, exist_ok=True)
        base = d / f"{self.id}_{self.package_report['report_id']}"
        base.with_suffix(".json").write_text(json.dumps(self.package_report, ensure_ascii=False, indent=2, default=str),
                                             encoding="utf-8")
        return str(base.with_suffix(".json").relative_to(ROOT)).replace("\\", "/")

    def record_signoff(self, card_id, user, decision, reason="", exclude_indications=None,
                       procedure_id=None, criteria_rev=None):
        self._need(self.package_report is not None, "보고서 초안이 아직 없다. 판정과 보고서 초안이 나온 뒤에만 서명을 기록한다.")
        said, said_up = self.last_user.lower(), self.last_user.upper()
        name = str(user).strip()
        self._need(len(name) >= 2 and name.lower() not in BOT_NAMES and name.lower() in said,
                   "검사원 이름이 이번 사용자 발화에 없다. 서명은 검사원이 이름을 밝히고 직접 요청할 때만 기록한다. 스스로 호출하지 않는다.")
        self._need(any(w in said for w in DECISION_WORDS[decision]),
                   f"이번 사용자 발화에 '{'승인' if decision == 'approve' else '반려'}' 의사 표현이 없다. 검사원이 직접 말하기 전에는 기록하지 않는다.")
        corrections = bool(exclude_indications or procedure_id or criteria_rev)
        self._need(not (corrections and decision == "approve"), "지시 제외나 정정은 반려할 때만 기록할 수 있다.")
        if str(card_id).strip().upper() == "ALL":
            self._need(decision == "approve", "전체(ALL)는 승인에만 쓸 수 있다. 반려는 카드를 지정한다.")
            self._need(any(w in said for w in ("전체", "모두", "모든", "all")), "이번 발화에 전체 승인 의사가 없다.")
            targets = [c for c in self.cards.values() if not c.approved]
            self._need(targets, "이미 모든 카드가 승인됐다.")
        else:
            c = self._card(card_id)
            self._need(c.id in said_up, f"이번 사용자 발화에 {c.id}가 없다. 검사원이 지정한 카드만 기록한다.")
            targets = [c]
        dup = [c.id for c in targets if (self.last_user, c.id) in self.signed]
        self._need(not dup, f"이번 발화의 서명은 이미 기록했다 ({dup}). 같은 발화로 반복 기록하지 않는다.")
        if decision == "approve":
            bad = [c.id for c in targets if c.stale]
            self._need(not bad and not self.report_stale and self.items_ok,
                       "재평가가 끝나지 않았거나 보고서가 최신이 아니다. 재평가와 보고서 갱신 뒤에 승인한다.")
        ids = [str(i).strip().upper() for i in (exclude_indications or [])]
        new_proc = new_rev = None
        if decision == "reject" and corrections:
            c = targets[0]
            known = {i["id"] for i in c.indications}
            unknown = [i for i in ids if i not in known]
            self._need(not unknown, f"{c.id}에 없는 지시 ID {unknown}. 현재 지시: {sorted(known)}")
            miss = [i for i in ids if i not in said_up]
            self._need(not miss, f"제외할 지시 {miss}가 이번 발화에 없다. 검사원이 말한 지시만 제외한다.")
            if procedure_id:
                new_proc = str(procedure_id).strip().upper()
                self._need(new_proc in said_up, f"절차 {new_proc}가 이번 발화에 없다. 검사원이 말한 값만 쓴다.")
                try:
                    self._check_domain(proc=cr.load_procedure(new_proc))
                except cr.CriteriaError as e:
                    raise ToolError(str(e))
            if criteria_rev:
                new_rev = str(criteria_rev).strip().upper()
                self._need(new_rev in revs_in(self.last_user), f"개정번호 Rev {new_rev}가 이번 발화에 없다. 검사원이 말한 값만 쓴다.")
                try:
                    self._check_domain(limits=cr.load_limits(c.info["criteria_id"], new_rev))
                except cr.CriteriaError as e:
                    raise ToolError(str(e))
        recs = []
        for c in targets:
            rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "card_id": c.id, "user": name, "decision": decision,
                   "reason": str(reason or ""), "draft_disposition": c.report["disposition"] if c.report else None}
            if decision == "reject":
                rec.update(excluded=ids, procedure_id=new_proc, criteria_rev=new_rev)
                c.excluded |= set(ids)
                if new_proc:
                    c.procedure_id, c.proc = new_proc, cr.load_procedure(new_proc)
                if new_rev:
                    c.rev, c.rev_source, c.limits = new_rev, "inspector", cr.load_limits(c.info["criteria_id"], new_rev)
                if c.proc and c.limits and c.validation["ok"]:
                    c.blocked_reason = None
                c.stale = True
            c.signoffs.append(rec)
            self.signed.add((self.last_user, c.id))
            self._audit("signoff", **rec)
            recs.append(rec)
        if decision == "reject":
            self._invalidate()
            nxt = "반려를 기록했다. inspect_package로 해당 카드를 재평가한 뒤 보고서를 다시 만든다."
        else:
            self._build_report()
            self._save_report()
            nxt = "검사원 승인을 기록했다. 최종 판단과 서명 책임은 검사원에게 있다."
        return {"recorded": True, "signoffs": recs, "next": nxt}

    # ------------------------------------------------------------ 사용자 직접 동작 (도구 아님)
    def hold_card(self, card_id, reason):
        """사용자가 질문에 답하지 않고 카드를 보류한다. 그 카드는 미평가로 보고된다."""
        c = self._card(card_id)
        c.held, c.blocked_reason = True, f"검사원 보류: {reason or '사유 미기재'}"
        for q in self.questions:
            if q["card_id"] == c.id and not q["answered"]:
                q["answered"], q["answer"] = True, "HOLD"
        self._invalidate()
        self._audit("hold", card_id=c.id, reason=reason)

    # ------------------------------------------------------------ 진행 상태
    def next_required(self):
        """고정 순서 기준으로 다음에 필요한 도구. LLM 없이 돌 때와, LLM이 멈췄을 때 이어 가는 데 쓴다."""
        if not self.plan:
            return ("declare_plan", {"steps": list(self.prof["plan"])})
        if not self.listed:
            return ("list_package", {})
        if not self.validated:
            return ("validate_scan", {})
        if not self.criteria_done:
            return ("select_criteria", {})
        if self.pending_questions():
            return ("WAIT", {})
        todo = [c.id for c in self.cards.values() if c.ready and (not c.inspected or c.stale)]
        untried = [c.id for c in self.cards.values()
                   if not c.ready and not c.held and not c.blocked_reason and c.validation["ok"]]
        if untried:
            return ("select_criteria", {})
        if todo or not self.inspect_done:
            return ("inspect_package", {"card_ids": todo} if len(todo) < len(self.cards) else {})
        stale = [c.id for c in self.cards.values() if c.stale]  # 정정 뒤에도 평가 불가인 카드
        for cid in stale:
            self.cards[cid].stale = False
        if not self.history_ok:
            return ("search_history", {})
        if not self.items_ok:
            return ("draft_item_report", {})
        if self.package_report is None or self.report_stale:
            return ("compile_package_report", {})
        return ("DONE", {})

    def call(self, name, args, by="fixed"):
        """by: 누가 호출했는가 (llm / fixed / user). 가드레일 지표를 낼 때 구분한다. 거부된 호출도 모두 기록한다."""
        spec = next((t for t in TOOL_SPECS if t["name"] == name), None)
        args = {k: v for k, v in (args or {}).items()
                if v not in (None, "", []) and (spec is None or k in spec["properties"])}
        t0 = time.time()
        res = self._dispatch(spec, name, args)
        ok = "error" not in res
        self.calls.append({"tool": name, "args": args, "ok": ok, "by": by, "sec": round(time.time() - t0, 2),
                           "ts": time.strftime("%H:%M:%S"), "error": res.get("error"),
                           "result": res if ok else None})
        self._audit("tool", tool=name, by=by, args=args, ok=ok,
                    result=json.dumps(res, ensure_ascii=False, default=str)[:600])
        return res

    def _dispatch(self, spec, name, args):
        if not spec:
            return {"error": f"알 수 없는 도구: {name}"}
        miss = [r for r in spec["required"] if r not in args]
        if miss:
            return {"error": f"필수 인자 누락: {miss}. 사용자가 말하지 않은 값이면 추측하지 말고 되묻는다."}
        for k, v in args.items():
            p = spec["properties"][k]
            if p.get("enum") and v not in p["enum"]:
                return {"error": f"{k}는 {p['enum']} 중 하나여야 한다 (받은 값: {v})"}
            if p["type"] == "array" and not isinstance(v, list):
                return {"error": f"{k}는 목록이어야 한다"}
            if p["type"] == "string" and not isinstance(v, str):
                args[k] = str(v)
        try:
            return getattr(self, name)(**args)
        except ToolError as e:
            return {"error": str(e)}
        except Exception as e:  # 예기치 못한 오류도 루프를 죽이지 않고 알린다
            return {"error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------ 화면용 상태
    def public_state(self):
        cards = []
        for c in self.cards.values():
            disp = c.eval["disposition"] if c.eval else cr.NOT_EVALUATED
            try:
                rev_options = cr.available_revisions(c.info["criteria_id"]) if c.info.get("criteria_id") else []
            except OSError:
                rev_options = []
            cards.append({
                "part_number": c.info.get("part_number"), "serial_number": c.info.get("serial_number"),
                "rev_options": rev_options,
                "card_id": c.id, "title": c.info.get("title", ""), "zone_id": c.info.get("zone_id"),
                "location_id": c.info.get("location_id"), "procedure_id": c.procedure_id,
                "criteria_id": c.info.get("criteria_id"), "criteria_rev": c.rev, "rev_source": c.rev_source,
                "material": c.info.get("material"), "thickness_mm": (c.meta or {}).get("thickness_mm"),
                "missing": c.info["missing"], "validation": c.validation, "procedure_check": c.proc_check,
                "inspected": c.inspected, "stale": c.stale, "held": c.held, "blocked_reason": c.blocked_reason,
                "indications": c.indications, "excluded": sorted(c.excluded), "evaluation": c.eval,
                "history": c.history, "disposition": disp, "disposition_ko": self.prof["ko"][disp],
                "summary": c.report["summary"] if c.report else None, "signoffs": c.signoffs,
                "approved": c.approved, "grid": (c.meta or {}).get("grid"),
                "data_source": c.report["data_source"] if c.report else None,
                "scan_date": (c.meta or {}).get("scan_date"),
            })
        nxt = self.next_required()[0]
        rep = self.package_report
        return {
            "session_id": self.id, "mode": self.mode_info, "domain": self.domain,
            "procedures": cr.procedure_ids(self.domain),
            "package": {k: self.package.get(k) for k in ("package_id", "aircraft", "aircraft_note", "check_type",
                                                         "operator", "customer", "data_note")},
            "plan": self.plan, "cards": cards, "questions": self.questions, "calls": self.calls,
            "next": nxt, "report_ready": rep is not None and not self.report_stale,
            "report": ({k: rep[k] for k in ("report_id", "status", "status_ko", "summary", "opinion", "opinion_source",
                                            "counts", "actions", "approved_cards", "generated")} if rep else None),
            "dispatched": self.dispatched,
        }
