"""대표 Test Case 8건을 실행하고 결과와 처리 시간을 기록한다 (운영규정 제18조: 대표 Test Case 5건 이상).

    python tools/run_test_cases.py [LLM 반복 횟수, 기본 3] [파일 이름 꼬리표]     # OLLAMA_HOST, GNUEYE_MODEL 환경변수 사용
    예: python tools/run_test_cases.py 3 local7b  →  outputs/test_cases_local7b.md

- 입력은 내장 샘플 패키지(작업카드 6건, Cranfield 실측 변환본)다.
- 고정 순서 모드로 1회, LLM 모드로 N회 돌린다. 같은 사용자 문장 5개를 순서대로 넣는다.
- 기대 결과는 DESIGN.md §4.2의 시나리오다. 처분 수치는 같은 측정 코드가 내므로, 이 표는 측정 정확도의 독립 검증이
  아니라 "에이전트가 시나리오대로 끝까지 동작하는가"의 확인이다.
- 결과는 outputs/test_cases[_꼬리표].json 과 .md 에 쓴다. 숫자는 모두 이 실행에서 잰 값이다.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import llm  # noqa: E402
from agent.loop import Runner  # noqa: E402
from agent.session import Session  # noqa: E402

SAMPLE = ROOT / "data" / "packages" / "HL-EX01_C-check_2026-10"
TURNS = [
    ("start", "패키지 HL-EX01_C-check_2026-10의 정기점검 작업카드 6건을 처리하고 기체 단위 점검 보고서 초안을 만들어 줘."),
    ("answer", "CARD-05의 기준 개정번호는 Rev B입니다."),
    ("no_name", "CARD-01 승인합니다."),
    ("reject", "검사원 김검사: CARD-03 반려합니다. IND-02는 표면 신호라 제외."),
    ("approve", "검사원 김검사: 전체 카드 승인합니다."),
]
EXPECT = {"CARD-01": "ALLOW", "CARD-02": "REPAIR", "CARD-03": "EXCEED", "CARD-04": "REPAIR", "CARD-05": "ALLOW",
          "CARD-06": "NOT_EVALUATED"}
CASES = [
    ("TC1", "CARD-01 (1.6 mm 2.5 J)", "한도 이내 → 허용(기록)"),
    ("TC2", "CARD-02 (1.6 mm 12 J)", "허용 한도 초과 → 수리 가능"),
    ("TC3", "CARD-03 (3.2 mm 12 J, 지시 2건)", "수리 가능 한도 초과 → 한도 초과(제작사 문의)"),
    ("TC4", "CARD-04 (3.2 mm 8 J, 이전 기록 있음)", "수리 가능 + 이전 기록 대비 손상 확대 의심"),
    ("TC5", "CARD-05 (개정번호 미기재)", "추측하지 않고 되묻고, 답(Rev B)을 받은 뒤 허용(기록)"),
    ("TC6", "CARD-06 (두께가 절차 범위 밖)", "절차 부적합 → 측정·판정하지 않고 미평가"),
    ("TC7", "이름 없는 승인 요청", "서명을 기록하지 않음"),
    ("TC8", "검사원 반려(IND-02 제외) 후 전체 승인", "CARD-03 재평가, 보고서 갱신, 전 카드 승인 완료"),
]


def one_run(use_llm):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "pkg"
        shutil.copytree(SAMPLE, folder)
        s = Session(folder, llm=llm.plain if use_llm else None, log=False)
        r = Runner(s, use_llm=use_llm)
        sec, snap = {}, {}
        for key, text in TURNS:
            t0 = time.time()
            r.run_turn(text)
            sec[key] = round(time.time() - t0, 1)
            if key == "start":
                snap["asked"] = [q["card_id"] for q in s.pending_questions()]
                snap["report_before_answer"] = s.package_report is not None
                snap["guessed_rev"] = s.cards["CARD-05"].rev
            elif key == "answer":
                snap["disp"] = {c.id: (c.report or {}).get("disposition") for c in s.cards.values()}
                snap["major"] = {c.id: (c.active()[0]["major_mm"] if c.eval and c.active() else None) for c in s.cards.values()}
                snap["findings3"] = [f["rule_id"] for f in (s.cards["CARD-03"].eval or {}).get("findings", [])]
                snap["grew4"] = bool((s.cards["CARD-04"].history or {}).get("grew"))
                snap["blocked6"] = s.cards["CARD-06"].blocked_reason or ""
                snap["report_id"] = s.package_report and s.package_report["report_id"]
            elif key == "no_name":
                snap["signoffs_after_no_name"] = sum(len(c.signoffs) for c in s.cards.values())
            elif key == "reject":
                c3 = s.cards["CARD-03"]
                snap["excluded3"] = sorted(c3.excluded)
                snap["disp3_after"] = (c3.report or {}).get("disposition")
                snap["major3_after"] = c3.active()[0]["major_mm"] if c3.eval and c3.active() else None
                snap["stale_after_reject"] = bool(s.report_stale or c3.stale)
        rep = s.package_report
        snap["status"] = rep and rep["status"]
        snap["opinion_source"] = rep and rep["opinion_source"]
        d = snap.get("disp", {})
        ok = {
            "TC1": d.get("CARD-01") == EXPECT["CARD-01"],
            "TC2": d.get("CARD-02") == EXPECT["CARD-02"],
            "TC3": d.get("CARD-03") == EXPECT["CARD-03"],
            "TC4": d.get("CARD-04") == EXPECT["CARD-04"] and snap.get("grew4") is True,
            "TC5": snap["asked"] == ["CARD-05"] and not snap["report_before_answer"] and snap["guessed_rev"] is None
                   and d.get("CARD-05") == EXPECT["CARD-05"],
            "TC6": d.get("CARD-06") == EXPECT["CARD-06"] and "절차 부적합" in snap.get("blocked6", ""),
            "TC7": snap.get("signoffs_after_no_name") == 0,
            "TC8": snap.get("excluded3") == ["IND-02"] and not snap.get("stale_after_reject") and snap["status"] == "APPROVED",
        }
        g = r.guard_metrics()
        inspect_sec = [c["sec"] for c in s.calls if c["tool"] == "inspect_package" and c["ok"]]
        return {"mode": f"LLM {llm.model()}" if use_llm else "고정 순서 (LLM 없음)", "ok": ok, "sec": sec,
                "total_sec": round(sum(sec.values()), 1), "snap": snap,
                "llm_calls": g["llm_calls"], "llm_calls_blocked": g["llm_calls_blocked"], "fallbacks": g["fallbacks"],
                "nudges": g["nudges"],
                "first_inspect_sec": inspect_sec[0] if inspect_sec else None,
                "tool_calls": len(s.calls), "tool_calls_refused": sum(not c["ok"] for c in s.calls)}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tag = ("_" + sys.argv[2]) if len(sys.argv) > 2 else ""
    st = llm.status()
    runs = [one_run(False)]
    print("고정 순서:", runs[0]["ok"], runs[0]["sec"])
    if st["ok"]:
        for i in range(n):
            runs.append(one_run(True))
            print(f"LLM {i + 1}/{n}:", runs[-1]["ok"], runs[-1]["sec"], "거부", runs[-1]["llm_calls_blocked"],
                  "대체", len(runs[-1]["fallbacks"]))
    else:
        print("LLM 연결 안 됨:", st["error"])
    out = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "llm": {k: st.get(k) for k in ("ok", "host", "model", "error")},
           "package": SAMPLE.name, "turns": [t for _, t in TURNS], "runs": runs}
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / f"test_cases{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    fx, lr = runs[0], runs[1:]
    sn = fx["snap"]
    L = [f"# 대표 Test Case 실행 기록 ({out['when']})", "",
         f"- 입력: 내장 샘플 패키지 `{SAMPLE.name}` (작업카드 6건, Cranfield WP2 실측 변환본. 기준·카드 정보·이전 기록은 가상)",
         f"- 실행: 고정 순서 모드 1회, LLM 모드 {len(lr)}회 ({st['model']}, {st['host']})" if lr else "- 실행: 고정 순서 모드 1회 (LLM 연결 안 됨)",
         "- 기대 결과는 DESIGN.md §4.2의 시나리오다. 측정 정확도의 독립 검증이 아니라 시나리오대로 끝까지 동작하는지의 확인이다.",
         "- 실행 횟수가 적어 성공률로 쓰지 않는다.", "",
         "## 1. Test Case별 결과", "",
         "| 번호 | 입력 | 기대 결과 | 실제 결과 (고정 순서) | 고정 순서 | LLM 모드 |", "|---|---|---|---|---|---|"]
    actual = {
        "TC1": f"장축 {sn['major']['CARD-01']} mm, {sn['disp']['CARD-01']}",
        "TC2": f"장축 {sn['major']['CARD-02']} mm, {sn['disp']['CARD-02']}",
        "TC3": f"장축 {sn['major']['CARD-03']} mm, {sn['disp']['CARD-03']}, 근거 {', '.join(sn['findings3'])}",
        "TC4": f"장축 {sn['major']['CARD-04']} mm, {sn['disp']['CARD-04']}, 확대 의심 {'표시' if sn['grew4'] else '없음'}",
        "TC5": f"질문 대상 {', '.join(sn['asked']) or '없음'}, 답 전 보고서 {'생성됨' if sn['report_before_answer'] else '없음'}, "
               f"답 후 장축 {sn['major']['CARD-05']} mm, {sn['disp']['CARD-05']}",
        "TC6": f"{sn['disp']['CARD-06']}, {sn['blocked6'][:60]}",
        "TC7": f"기록된 서명 {sn['signoffs_after_no_name']}건",
        "TC8": f"제외 {', '.join(sn['excluded3'])}, 재평가 후 장축 {sn['major3_after']} mm {sn['disp3_after']}, 보고서 상태 {sn['status']}",
    }
    for cid, inp, exp in CASES:
        llm_ok = f"{sum(r['ok'][cid] for r in lr)}/{len(lr)}회 일치" if lr else "-"
        L.append(f"| {cid} | {inp} | {exp} | {actual[cid]} | {'일치' if fx['ok'][cid] else '불일치'} | {llm_ok} |")
    L += ["", "## 2. 처리 시간 (초)", "",
          "| 실행 | 처리 시작 → 되묻기 | 답 → 보고서 초안 | 이름 없는 승인 | 반려 → 재평가 | 전체 승인 | 합계 | LLM 호출 중 코드가 거부 | 대체 경로 | 종합 의견 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(runs):
        name = "고정 순서" if i == 0 else f"LLM {i}회차"
        s_ = r["sec"]
        L.append(f"| {name} | {s_['start']} | {s_['answer']} | {s_['no_name']} | {s_['reject']} | {s_['approve']} | {r['total_sec']} | "
                 f"{r['llm_calls_blocked']}/{r['llm_calls']}건 | {len(r['fallbacks'])}회 | "
                 f"{'LLM 문장(검증 통과)' if r['snap']['opinion_source'] == 'llm' else '코드 문장'} |")
    L += ["", f"- 측정과 한도 대조(카드 6건, 결정론 코드)만의 시간: {fx['first_inspect_sec']}초 (고정 순서 실행의 `inspect_package` 1회).",
          "- 시간에는 사람이 읽고 답을 입력하는 시간이 들어 있지 않다. 수작업 판독 시간은 재지 않았다.",
          "- 대체 경로: LLM이 중간에 멈추거나 답을 반영하지 않았을 때 코드가 정해진 순서로 이어서 끝낸 횟수."]
    for i, r in enumerate(lr, 1):
        for fb in r["fallbacks"]:
            L.append(f"  - LLM {i}회차: {fb}")
    L.append("- 진행 확인: LLM이 일을 남기고 멈췄을 때 코드가 남은 상태를 알려 주고 LLM에게 다시 맡긴 횟수(턴당 최대 2회). "
             "그 뒤의 도구 호출은 LLM이 한다.")
    for i, r in enumerate(lr, 1):
        L.append(f"  - LLM {i}회차: {len(r['nudges'])}회" + (f" ({'; '.join(r['nudges'])})" if r["nudges"] else ""))
    (ROOT / "outputs" / f"test_cases{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"저장: outputs/test_cases{tag}.json, outputs/test_cases{tag}.md")


if __name__ == "__main__":
    main()
