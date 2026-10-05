"""제조 검사 모드 대표 Test Case 8건을 시연 로트(하이브리드)로 실행하고 기록한다.

    python tools/build_mfg_lot.py                       # 시연 로트 zip을 먼저 만든다
    python tools/run_test_cases_mfg.py [LLM 반복 횟수, 기본 3] [파일 이름 꼬리표]

- 입력: demo_files/4_mfg_lot_GNU-LOT-2610-07_hybrid.zip (부품 7건: Cranfield 실측 2, 합성 5).
- 고정 순서 모드로 1회, LLM 모드로 N회 돌린다. 같은 사용자 문장 5개를 순서대로 넣는다.
- 기대 결과는 tools/build_mfg_lot.py의 설계다. 처분 수치는 같은 측정 코드가 내므로 측정 정확도의 독립 검증이 아니라
  "에이전트가 제조 시나리오대로 끝까지 동작하는가"의 확인이다.
- 합성 부품은 정답 파일(노이즈 없는 미세 격자에서 같은 6 dB 정의로 잰 장축)과 비교한 값도 적는다. 같은 정의를 쓰므로
  정확도가 아니라 노이즈·격자 영향이다. 실측 부품은 정답이 없다.
- 결과는 outputs/test_cases_mfg[_꼬리표].json 과 .md 에 쓴다. 숫자는 모두 이 실행에서 잰 값이다.
"""
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import llm  # noqa: E402
from agent.loop import Runner  # noqa: E402
from agent.session import Session  # noqa: E402

ZIP = ROOT / "demo_files" / "4_mfg_lot_GNU-LOT-2610-07_hybrid.zip"
TURNS = [
    ("start", "생산 로트 패키지 GNU-LOT-2610-07_hybrid의 검사 부품 7건을 고객사양과 대조하고 로트 검사 보고서와 NCR 초안을 만들어 줘."),
    ("answer", "PART-04의 고객사양 개정번호는 Rev B입니다."),
    ("no_name", "PART-01 승인합니다."),
    ("reject", "검사원 김검사: PART-06 반려합니다. IND-01은 표면 신호라 제외."),
    ("approve", "검사원 김검사: 전체 부품 승인합니다."),
]
EXPECT = {"PART-01": "ALLOW", "PART-02": "REPAIR", "PART-03": "EXCEED", "PART-04": "ALLOW", "PART-05": "EXCEED",
          "PART-06": "EXCEED", "PART-07": "EXCEED"}
CASES = [
    ("MTC1", "PART-01 결함 없음 [합성]", "적합(기록), NCR 초안 없음"),
    ("MTC2", "PART-03 중요 구역 충격 손상 [실측]", "부적합(NCR 대상), 근거 A-1·A-3, NCR 시스템 기입 10/10칸, 과거 NCR 조회"),
    ("MTC3", "PART-04 고객사양 개정번호 미기재 [합성]", "추측하지 않고 되묻고, 답(Rev B) 뒤 적합(기록)"),
    ("MTC4", "PART-02 한도 경계 층간 분리 [합성]", "보류(재검사 권고)"),
    ("MTC5", "PART-05 일반 구역 충격 손상 [실측]", "누적 면적 규칙 B-3으로 부적합(NCR 대상)"),
    ("MTC6", "PART-07 기공 군집 [합성]", "최대 치수 규칙 B-1로 부적합(NCR 대상)"),
    ("MTC7", "이름 없는 승인 요청", "서명을 기록하지 않음"),
    ("MTC8", "PART-06 표면 신호 반려(IND-01 제외) 후 전체 승인", "재평가로 적합(기록), 보고서 승인 완료"),
]


def one_run(folder, use_llm):
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
            snap["guessed_rev"] = s.cards["PART-04"].rev
        elif key == "answer":
            rep = s.package_report or {"items": []}
            snap["disp"] = {c.id: (c.report or {}).get("disposition") for c in s.cards.values()}
            snap["major"] = {c.id: [i["major_mm"] for i in c.active()] for c in s.cards.values()}
            snap["rules"] = {c.id: [f["rule_id"] for f in (c.eval or {}).get("findings", [])] for c in s.cards.values()}
            snap["ncr"] = {i["card_id"]: {k: i["ncr_draft"][k] for k in ("system_filled", "system_fields", "total")}
                           for i in rep["items"] if i.get("ncr_draft")}
            snap["history3"] = (s.cards["PART-03"].history or {}).get("text", "")
            snap["opinion"] = rep.get("opinion"), rep.get("opinion_source")
        elif key == "no_name":
            snap["signoffs_after_no_name"] = sum(len(c.signoffs) for c in s.cards.values())
        elif key == "reject":
            c6 = s.cards["PART-06"]
            snap["excluded6"] = sorted(c6.excluded)
            snap["disp6_after"] = (c6.report or {}).get("disposition")
    rep = s.package_report
    snap["status"] = rep and rep["status"]
    snap["opinion_final"] = rep and (rep["opinion"], rep["opinion_source"])
    d = snap.get("disp", {})
    ok = {
        "MTC1": d.get("PART-01") == "ALLOW" and "PART-01" not in snap.get("ncr", {}),
        "MTC2": d.get("PART-03") == "EXCEED" and snap["rules"].get("PART-03") == ["A-1", "A-3"]
                and snap["ncr"].get("PART-03", {}).get("system_filled") == 10 and "과거 NCR" in snap["history3"],
        "MTC3": snap["asked"] == ["PART-04"] and not snap["report_before_answer"] and snap["guessed_rev"] is None
                and d.get("PART-04") == "ALLOW",
        "MTC4": d.get("PART-02") == "REPAIR",
        "MTC5": d.get("PART-05") == "EXCEED" and snap["rules"].get("PART-05") == ["B-3"],
        "MTC6": d.get("PART-07") == "EXCEED" and snap["rules"].get("PART-07") == ["B-1"],
        "MTC7": snap.get("signoffs_after_no_name") == 0,
        "MTC8": snap.get("excluded6") == ["IND-01"] and snap.get("disp6_after") == "ALLOW" and snap["status"] == "APPROVED",
    }
    g = r.guard_metrics()
    by = lambda who: sum(c.get("by") == who for c in s.calls)  # noqa: E731
    return {"mode": f"LLM {llm.model()}" if use_llm else "고정 순서 (LLM 없음)", "ok": ok, "sec": sec,
            "total_sec": round(sum(sec.values()), 1), "snap": snap,
            "llm_calls": g["llm_calls"], "llm_calls_blocked": g["llm_calls_blocked"], "fallbacks": g["fallbacks"],
            "nudges": g["nudges"], "tool_calls": len(s.calls), "code_calls": by("fixed"),
            "inspect_sec": [c["sec"] for c in s.calls if c["tool"] == "inspect_package" and c["ok"]][:1]}


def truth_table(folder, run):
    rows = []
    for p in sorted(Path(folder).glob("PART-*_truth.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        meas = run["snap"]["major"].get(t["part"], [])
        for i, ti in enumerate(t["truth_indications"]):
            m = meas[i] if i < len(meas) else None
            rows.append((t["part"], ti["id"], ti["major_mm"], m, None if m is None else round(m - ti["major_mm"], 2)))
    return rows


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tag = ("_" + sys.argv[2]) if len(sys.argv) > 2 else ""
    st = llm.status()
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(ZIP).extractall(tmp)
        runs = [one_run(tmp, False)]
        print("고정 순서:", runs[0]["ok"], runs[0]["sec"])
        truth = truth_table(tmp, runs[0])
        if st["ok"]:
            for i in range(n):
                runs.append(one_run(tmp, True))
                print(f"LLM {i + 1}/{n}:", runs[-1]["ok"], runs[-1]["sec"], "거부", runs[-1]["llm_calls_blocked"],
                      "대체", len(runs[-1]["fallbacks"]), "진행확인", len(runs[-1]["nudges"]))
        else:
            print("LLM 연결 안 됨:", st["error"])
    out = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "llm": {k: st.get(k) for k in ("ok", "host", "model", "error")},
           "package": ZIP.name, "turns": [t for _, t in TURNS], "runs": runs, "truth": truth}
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs" / f"test_cases_mfg{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    fx, lr = runs[0], runs[1:]
    sn = fx["snap"]
    L = [f"# 제조 검사 대표 Test Case 실행 기록 ({out['when']})", "",
         f"- 입력: `{ZIP.name}` (부품 7건. PART-03·PART-05는 Cranfield WP2 실측 충격 시편 변환본, 나머지 5건은 합성. "
         "로트·부품번호·고객사양·절차·과거 NCR 이력은 가상)",
         f"- 실행: 고정 순서 모드 1회, LLM 모드 {len(lr)}회 ({st['model']}, {st['host']})" if lr else "- 실행: 고정 순서 모드 1회 (LLM 연결 안 됨)",
         "- 기대 결과는 `tools/build_mfg_lot.py`의 설계다. 측정 정확도의 독립 검증이 아니라 시나리오대로 끝까지 동작하는지의 확인이다.",
         "- 실행 횟수가 적어 성공률로 쓰지 않는다.", "",
         "## 1. Test Case별 결과", "",
         "| 번호 | 입력 | 기대 결과 | 실제 결과 (고정 순서) | 고정 순서 | LLM 모드 |", "|---|---|---|---|---|---|"]
    m, d, rl = sn["major"], sn["disp"], sn["rules"]
    ncr3 = sn["ncr"].get("PART-03", {})
    actual = {
        "MTC1": f"지시 {len(m['PART-01'])}건, {d['PART-01']}, NCR 초안 {'있음' if 'PART-01' in sn['ncr'] else '없음'}",
        "MTC2": f"장축 {m['PART-03']} mm, {d['PART-03']}, 근거 {', '.join(rl['PART-03'])}, "
                f"NCR 시스템 기입 {ncr3.get('system_filled')}/{ncr3.get('system_fields')}칸",
        "MTC3": f"질문 대상 {', '.join(sn['asked']) or '없음'}, 답 전 보고서 {'생성됨' if sn['report_before_answer'] else '없음'}, "
                f"답 후 장축 {m['PART-04']} mm, {d['PART-04']}",
        "MTC4": f"장축 {m['PART-02']} mm, {d['PART-02']}",
        "MTC5": f"장축 {m['PART-05']} mm, {d['PART-05']}, 근거 {', '.join(rl['PART-05'])}",
        "MTC6": f"장축 {m['PART-07']} mm, {d['PART-07']}, 근거 {', '.join(rl['PART-07'])}",
        "MTC7": f"기록된 서명 {sn['signoffs_after_no_name']}건",
        "MTC8": f"제외 {', '.join(sn['excluded6']) or '없음'}, 재평가 후 {sn['disp6_after']}, 보고서 상태 {sn['status']}",
    }
    for cid, inp, exp in CASES:
        llm_ok = f"{sum(r['ok'][cid] for r in lr)}/{len(lr)}회 일치" if lr else "-"
        L.append(f"| {cid} | {inp} | {exp} | {actual[cid]} | {'일치' if fx['ok'][cid] else '불일치'} | {llm_ok} |")
    L += ["", "## 2. 처리 시간과 호출자", "",
          "| 실행 | 처리 시작 → 되묻기 | 답 → 보고서 초안 | 이름 없는 승인 | 반려 → 재평가 | 전체 승인 | 합계(초) | 도구 호출 | LLM이 부름 (그중 거부) | 코드가 대신 | 대체 경로 | 진행 확인 | 종합 의견 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(runs):
        s_ = r["sec"]
        L.append(f"| {'고정 순서' if i == 0 else f'LLM {i}회차'} | {s_['start']} | {s_['answer']} | {s_['no_name']} | {s_['reject']} | "
                 f"{s_['approve']} | {r['total_sec']} | {r['tool_calls']} | {r['llm_calls']} ({r['llm_calls_blocked']}) | "
                 f"{r['code_calls']} | {len(r['fallbacks'])} | {len(r['nudges'])} | "
                 f"{'LLM 문장(검증 통과)' if (r['snap']['opinion_final'] or ('', ''))[1] == 'llm' else '코드 문장'} |")
    L += ["", f"- 측정과 사양 대조(부품 7건, 결정론 코드)만의 시간: {fx['inspect_sec'][0] if fx['inspect_sec'] else '-'}초.",
          "- 시간에는 사람이 읽고 답을 입력하는 시간이 들어 있지 않다. 수작업 시간은 재지 않았다."]
    for i, r in enumerate(lr, 1):
        for fb in r["fallbacks"]:
            L.append(f"  - LLM {i}회차 대체 경로: {fb}")
        for nd in r["nudges"]:
            L.append(f"  - LLM {i}회차 진행 확인: {nd}")
    L += ["", "## 3. 합성 부품의 측정값과 정답 파일 비교", "",
          "정답은 노이즈 없는 미세 격자(0.25 mm)에서 같은 6 dB 정의로 잰 장축이다. 같은 정의를 쓰므로 정확도가 아니라 "
          "노이즈·격자(1 mm)·빔 평균의 영향이다. 실측 부품(PART-03, PART-05)은 정답이 없어 빠진다.", "",
          "| 부품 | 지시 | 정답 장축 (mm) | 측정 장축 (mm) | 차이 (mm) |", "|---|---|---|---|---|"]
    L += [f"| {p} | {i} | {t} | {mm if mm is not None else '-'} | {df if df is not None else '-'} |" for p, i, t, mm, df in truth]
    diffs = [abs(x[4]) for x in truth if x[4] is not None]
    if diffs:
        L.append(f"\n- 지시 {len(diffs)}건의 절대 차이 평균 {round(sum(diffs) / len(diffs), 2)} mm, 최대 {max(diffs)} mm. "
                 "계획서 목표(합성 데이터 30건 기준 평균 2 mm 이내)와 표본 수가 달라 같은 지표로 쓰지 않는다.")
    if lr:
        L += ["", "## 4. LLM 종합 의견 (마지막 보고서)", ""]
        for i, r in enumerate(lr, 1):
            op = r["snap"]["opinion_final"] or ("", "")
            L.append(f"- {i}회차 ({'LLM' if op[1] == 'llm' else '코드 문장'}): {op[0]}")
    (ROOT / "outputs" / f"test_cases_mfg{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"저장: outputs/test_cases_mfg{tag}.json, outputs/test_cases_mfg{tag}.md")


if __name__ == "__main__":
    main()
