"""AI 도우미(챗봇). 현재 세션의 결과, 적용 기준, 용어집만 근거로 답한다.

- 판정을 바꾸지 못한다(도구를 쓰지 않는다).
- LLM 답에 근거 자료에 없는 숫자가 있으면 내보내지 않고, 용어집 답 또는 "자료에 없습니다"로 바꾼다.
- LLM이 없으면 용어집과 세션 요약으로만 답한다.
"""
import re

from core import report as rpt

from . import llm

GLOSSARY = {
    "C-scan": "초음파 탐촉자를 면 위에서 움직이며 위치마다 신호 세기를 기록해 평면 지도로 나타낸 검사 결과입니다. 내부 박리 같은 손상이 주변보다 신호가 약한 영역으로 보입니다.",
    "6 dB drop": "건전한 부위의 신호 세기보다 6 dB(절반) 이상 떨어진 영역을 손상 지시로 보는 크기 측정 방법입니다. 이 시스템은 이 영역의 장축, 단축, 면적을 계산합니다.",
    "개정번호": "기준 문서의 판(Rev)입니다. 개정본마다 허용 한도가 달라 같은 손상도 처분이 달라질 수 있습니다. 그래서 작업카드에 개정번호가 없으면 추측하지 않고 되묻습니다.",
    "절차 적합성": "스캔한 부품의 두께와 재질이 적용한 검사 절차의 범위 안에 있는지 보는 확인입니다. 범위 밖이면 그 절차로 잰 값을 믿을 수 없어 측정과 판정을 하지 않습니다.",
    "허용 손상 한도": "부위별로 손상을 그대로 둘 수 있는 크기와 수리로 해결할 수 있는 크기의 한도입니다. 이 시스템의 한도는 모두 시연용 가상 값(EXAMPLE_ONLY)입니다.",
    "처분": "허용(기록), 수리 가능, 한도 초과(제작사 문의) 세 가지입니다. 에이전트가 내는 처분은 초안이며 최종 판단과 서명은 자격 검사원이 합니다.",
    "SDI": "특수 상세 검사(Special Detailed Inspection)입니다. 육안으로 드러나지 않는 손상을 초음파 같은 특수 기법으로 찾는 검사입니다.",
    "BVID": "눈으로 거의 보이지 않는 충격 손상(Barely Visible Impact Damage)입니다. 겉은 멀쩡해 보여도 내부에 박리가 있을 수 있습니다.",
    "EXAMPLE_ONLY": "시연용 가상 값이라는 표시입니다. 이 시스템의 기준, 절차, 기체, 작업카드, 이전 점검 기록은 실제 제작사 문서와 무관합니다.",
    "이전 점검 기록": "같은 기체 같은 부위의 과거 점검 결과입니다. 현재 크기와 비교해 손상이 커졌는지 봅니다. 이 시스템의 기록은 가상입니다.",
    "가장자리": "손상 지시가 스캔 범위의 가장자리에 닿으면 실제 손상이 스캔 밖으로 이어질 수 있어 크기가 작게 측정됐을 가능성이 있습니다. 이 경우 범위를 넓혀 다시 스캔하라고 경고합니다.",
    "이 시스템": "지누아이(GNU-Eye)는 정기점검에서 나온 복합재 초음파 C-scan 작업카드 묶음을 받아 측정, 기준 대조, 이전 기록 비교를 하고 기체 단위 점검 보고서 초안을 만드는 검사 보조 에이전트입니다. 측정과 판정은 코드가 하고, 최종 판단과 서명은 검사원이 합니다. 제조 검사 모드에서는 같은 엔진이 생산 로트의 부품 스캔을 고객사양과 대조해 검사 보고서와 부적합보고서(NCR) 초안을 만듭니다.",
    "NCR": "부적합보고서(Non-Conformance Report)입니다. 제조 검사에서 고객사양 한도를 넘는 지시가 나온 부품에 대해 무엇이 어떤 규칙에 어긋났는지 적는 문서입니다. 이 시스템이 만드는 NCR은 초안이며 검사원이 확인합니다.",
    "MRB": "자재심의위원회(Material Review Board)입니다. 부적합 부품을 그대로 쓸지, 재작업할지, 폐기할지 정합니다. 이 시스템은 그 처분을 정하지 않습니다.",
    "고객사양": "제조 검사에서 부품을 받아들일 수 있는 지시 크기, 지시 간 거리, 누적 면적의 한도를 정한 고객 문서입니다. 개정본마다 한도가 다릅니다. 이 시스템의 사양은 시연용 가상 값(EXAMPLE_ONLY)입니다.",
    "보류": "제조 검사에서 지시 크기가 사양 한도의 5% 안팎이라 측정 불확실도로는 단정할 수 없는 경우입니다. 재검사를 권고합니다.",
    "제조 검사": "생산 로트의 부품별 C-scan을 고객사양과 대조해 적합(기록), 보류(재검사 권고), 부적합(NCR 대상)으로 처분 초안을 내는 모드입니다. 정비 점검과 같은 측정 코드와 가드레일을 쓰고 기준 묶음만 다릅니다. 제조 실데이터를 확보하지 못해 내장 샘플은 Cranfield 실측 충격 시편 2건과 합성 결함 5건을 섞은 시연용 로트입니다.",
}
ALIASES = {"6db": "6 dB drop", "6 db": "6 dB drop", "drop": "6 dB drop", "c스캔": "C-scan", "cscan": "C-scan",
           "c-scan": "C-scan", "rev": "개정번호", "개정": "개정번호", "절차": "절차 적합성", "한도": "허용 손상 한도",
           "처분": "처분", "sdi": "SDI", "bvid": "BVID", "example": "EXAMPLE_ONLY", "예시": "EXAMPLE_ONLY",
           "가상": "EXAMPLE_ONLY", "이력": "이전 점검 기록", "이전": "이전 점검 기록", "가장자리": "가장자리",
           "ncr": "NCR", "부적합": "NCR", "mrb": "MRB", "자재심의": "MRB", "사양": "고객사양",
           "제조": "제조 검사", "무엇": "이 시스템", "뭐하는": "이 시스템", "무엇을": "이 시스템", "시스템": "이 시스템"}
NOT_FOUND = "자료에 없습니다. 현재 검사 결과, 적용 기준(예시), 용어 설명 범위에서만 답할 수 있습니다."

SYSTEM = """너는 항공 복합재 C-scan 검사 보조 시스템의 안내 도우미다.
규칙:
1. 아래 [자료]에 있는 내용만 근거로 한국어 2~4문장으로 답한다.
2. [자료]에 없는 내용은 "자료에 없습니다"라고 답한다. 추측하지 않는다.
3. 숫자와 ID는 [자료]에 있는 것만 그대로 쓴다. 새 숫자를 만들거나 계산하지 않는다.
4. 판정이나 처분을 바꾸거나 새로 내리지 않는다. 처분은 초안이고 최종 판단과 서명은 검사원이 한다고 안내한다.
5. 기준 값은 시연용 가상 값이라는 점을 필요하면 밝힌다.
"""


def session_facts(session):
    """챗봇이 근거로 쓸 수 있는 현재 세션 자료 (코드가 만든 문장만)."""
    if session is None:
        return ""
    prof = session.prof
    lines = [f"패키지 {session.package['package_id']}: {prof['subject']} {session.package['aircraft']}, "
             f"{session.package['check_type']}, {prof['unit_long']} {len(session.cards)}건."]
    for c in session.cards.values():
        if c.report:
            lines.append(c.report["summary"])
            if c.history:
                lines.append(f"{c.id} {prof['history_label']}: {c.history['text']}.")
            if c.eval:
                lines.append(f"{c.id} 적용 한도({c.eval['rule_set']}, {c.eval['zone_id']}): {rpt.limits_text(c.eval)}.")
                lines += [f"{c.id} 주의: {w['text']}." for w in c.eval["warnings"]]
        elif c.blocked_reason:
            lines.append(f"{c.id}: {c.blocked_reason}")
    for q in session.pending_questions():
        lines.append(f"답을 기다리는 질문: {q['text']}")
    if session.package_report and not session.report_stale:
        lines.append("종합: " + session.package_report["summary"])
    return "\n".join(lines)


def glossary_answer(question):
    q = question.lower()
    for key in GLOSSARY:
        if key.lower() in q:
            return GLOSSARY[key], key
    for alias, key in ALIASES.items():
        if alias in q:
            return GLOSSARY[key], key
    return None, None


def answer(question, session=None, use_llm=True):
    """돌려주는 값: {text, source, basis}. source는 llm / glossary / session / none."""
    question = str(question).strip()[:500]
    facts = session_facts(session)
    gloss, key = glossary_answer(question)
    cards = [cid for cid in (session.cards if session else {}) if cid in question.upper()]
    if use_llm:
        material = "[자료]\n용어집:\n" + "\n".join(f"- {k}: {v}" for k, v in GLOSSARY.items())
        material += "\n현재 검사 결과:\n" + (facts or "아직 검사 결과가 없습니다.")
        try:
            text = llm.plain(material + "\n\n[질문]\n" + question, system=SYSTEM).strip()
            ok, detail = rpt.verify_narrative(text, material + question)
            # 챗봇 답에는 금지 표현 중 '합격/불합격'만 엄격히 볼 필요가 없으므로 숫자 검증만 쓴다
            if not detail["unsupported_numbers"] and 2 <= len(text) <= 900:
                return {"text": text, "source": "llm", "basis": "현재 세션 자료와 용어집", "checked": True}
            reason = f"근거에 없는 숫자 {detail['unsupported_numbers'][:5]}"
        except Exception as e:
            reason = f"LLM 호출 실패 ({type(e).__name__})"
    else:
        reason = "LLM 미사용"
    if cards and session:
        lines = [ln for ln in facts.split("\n") if any(ln.startswith(c) for c in cards)]
        if lines:
            return {"text": "\n".join(lines), "source": "session", "basis": "코드가 만든 검사 결과 문장", "fallback_reason": reason}
    if gloss:
        return {"text": gloss, "source": "glossary", "basis": f"용어집: {key}", "fallback_reason": reason}
    if session and session.package_report and re.search(r"결과|요약|종합|몇\s*건|처분", question):
        return {"text": session.package_report["summary"], "source": "session", "basis": "코드가 만든 종합 문장",
                "fallback_reason": reason}
    return {"text": NOT_FOUND, "source": "none", "basis": "", "fallback_reason": reason}
