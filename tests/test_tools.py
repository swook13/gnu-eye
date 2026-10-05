"""도구 계층 회귀 테스트 (LLM 없음).

    cd 지누아이 && python -m pytest tests -q

정답 여부를 엄격히 본다: 처분, 근거 규칙, 거부 사유까지 확인한다.
합성 스캔은 테스트 안에서 직접 만든다(사각형 손상). 측정기와 같은 가정(6 dB 임계)을 쓰므로
이 테스트는 측정 정확도가 아니라 배선과 가드레일을 확인하는 것이다.
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.loop import Runner, parse_signoff  # noqa: E402
from agent.session import Session  # noqa: E402
from core import criteria as cr  # noqa: E402
from core import measure  # noqa: E402
from core import package as pkg  # noqa: E402
from core import report as rpt  # noqa: E402

SAMPLE = ROOT / "data" / "packages" / "HL-EX01_C-check_2026-10"
P1, P2, ADL = "GNU-NTM-EX-51-01", "GNU-NTM-EX-51-02", "GNU-ADL-EX-001"


# ------------------------------------------------------------------ 합성 패키지
def make_scan(folder, cid, rects, rows=60, cols=120, pitch=1.0, thickness=2.0, meta_over=None, drop=-20.0):
    """rects: [(x0, y0, x1, y1)] mm 단위 사각형 손상."""
    amp = np.zeros((rows, cols))
    for x0, y0, x1, y1 in rects:
        amp[int(y0 / pitch):int(y1 / pitch), int(x0 / pitch):int(x1 / pitch)] = drop
    np.savetxt(folder / f"{cid}_amplitude_db.csv", amp, delimiter=",", fmt="%.1f")
    meta = {"synthetic": True, "equipment_id": "SYN", "probe": {"frequency_mhz": 10}, "reference_db": 0.0,
            "grid": {"pitch_mm": pitch, "rows": rows, "cols": cols, "width_mm": cols * pitch, "height_mm": rows * pitch},
            "thickness_mm": thickness, "scan_date": "2026-10-01"}
    meta.update(meta_over or {})
    (folder / f"{cid}_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def make_pkg(tmp_path, cards, aircraft="HL-TEST"):
    """cards: [(card_id, rects, {카드 덮어쓰기}, {make_scan 인자})]"""
    out = []
    for cid, rects, over, scan_kw in cards:
        make_scan(tmp_path, cid, rects, **scan_kw)
        c = {"card_id": cid, "title": cid, "zone_id": "Z1", "location_id": f"LOC-{cid}", "procedure_id": P1,
             "criteria_id": ADL, "criteria_rev": "A", "material": "CFRP",
             "scan_file": f"{cid}_amplitude_db.csv", "meta_file": f"{cid}_meta.json"}
        c.update(over)
        out.append({k: v for k, v in c.items() if v is not None})
    (tmp_path / "package.json").write_text(json.dumps(
        {"package_id": "T", "aircraft": aircraft, "check_type": "C-check", "cards": out}), encoding="utf-8")
    return tmp_path


def run_fixed(folder, text="처리해줘"):
    s = Session(folder, log=False)
    r = Runner(s, use_llm=False)
    r.run_turn(text)
    return s, r


def tools(s):
    return [(c["tool"], c["ok"]) for c in s.calls]


# ------------------------------------------------------------------ 정상 흐름 (실데이터 샘플)
@pytest.fixture()
def sample(tmp_path):
    dst = tmp_path / "pkg"
    shutil.copytree(SAMPLE, dst)
    return dst


def test_sample_asks_revision_and_stops(sample):
    s, r = run_fixed(sample)
    assert tools(s) == [("declare_plan", True), ("list_package", True), ("validate_scan", True), ("select_criteria", True)]
    q = s.pending_questions()
    assert [x["card_id"] for x in q] == ["CARD-05"] and q[0]["options"] == ["A", "B"]
    assert s.package_report is None
    assert s.next_required()[0] == "WAIT"


def test_sample_full_flow_dispositions(sample):
    s, r = run_fixed(sample)
    r.run_turn("CARD-05의 기준 개정번호는 Rev B입니다.")
    disp = {c.id: c.report["disposition"] for c in s.cards.values()}
    assert disp == {"CARD-01": "ALLOW", "CARD-02": "REPAIR", "CARD-03": "EXCEED", "CARD-04": "REPAIR",
                    "CARD-05": "ALLOW", "CARD-06": "NOT_EVALUATED"}
    assert [f["rule_id"] for f in s.cards["CARD-03"].eval["findings"]] == ["Z1-D2", "Z1-S1"]
    assert "절차 부적합" in s.cards["CARD-06"].blocked_reason and s.cards["CARD-06"].eval is None
    assert s.cards["CARD-04"].history["grew"] is True and s.cards["CARD-01"].history["grew"] is False
    assert s.cards["CARD-02"].history["found"] is False
    rep = s.package_report
    assert rep["status"] == "DRAFT" and rep["counts"] == {"ALLOW": 2, "REPAIR": 2, "EXCEED": 1, "NOT_EVALUATED": 1}
    assert rep["actions"]["oem_inquiry"] == ["CARD-03"] and rep["actions"]["growth"] == ["CARD-04"]
    assert rep["opinion_source"] == "template"
    html = rpt.render_html(rep)
    assert "CARD-03" in html and "EXAMPLE_ONLY" in html and "26.95" in html


def test_revision_changes_disposition(sample):
    s, r = run_fixed(sample)
    r.run_turn("CARD-05는 Rev A")
    assert s.cards["CARD-05"].report["disposition"] == "REPAIR"  # Rev B였다면 ALLOW


def test_answer_without_card_name_when_single_question(sample):
    s, r = run_fixed(sample)
    r.run_turn("Rev B야")
    assert s.cards["CARD-05"].rev == "B" and s.cards["CARD-05"].rev_source == "user"
    assert s.package_report is not None


# ------------------------------------------------------------------ 가드레일: 순서
def test_order_guard(sample):
    s = Session(sample, log=False)
    assert "list_package" in s.call("validate_scan", {})["error"]
    s.call("list_package", {})
    assert "validate_scan" in s.call("select_criteria", {})["error"]
    s.call("validate_scan", {})
    assert "select_criteria" in s.call("inspect_package", {})["error"]
    assert "error" in s.call("search_history", {})
    assert "search_history" in s.call("draft_item_report", {})["error"]
    assert "draft_item_report" in s.call("compile_package_report", {})["error"]
    assert s.package_report is None


def test_report_blocked_while_question_pending(sample):
    s = Session(sample, log=False)
    for t in ("list_package", "validate_scan", "select_criteria", "inspect_package", "search_history", "draft_item_report"):
        assert "error" not in s.call(t, {}), t
    res = s.call("compile_package_report", {})
    assert "답을 받지 못한 질문" in res["error"] and s.package_report is None


# ------------------------------------------------------------------ 가드레일: 개정번호 추측 금지
def test_revision_guess_rejected(sample):
    s = Session(sample, log=False)
    s.hear("패키지 처리해줘")
    for t in ("list_package", "validate_scan"):
        s.call(t, {})
    res = s.call("select_criteria", {"card_id": "CARD-05", "rev": "A"})  # 사용자가 말하지 않은 값
    assert "말한 적이 없다" in res["error"] and s.cards["CARD-05"].rev is None
    s.hear("CARD-01은 Rev B로 해")  # 다른 카드에 대한 말은 근거가 아니다
    assert "error" in s.call("select_criteria", {"card_id": "CARD-05", "rev": "B"})
    s.call("select_criteria", {})
    s.hear("CARD-05는 Rev B")
    assert s.call("select_criteria", {"card_id": "CARD-05", "rev": "B"})["cards"][0]["status"] == "selected"


def test_package_revision_cannot_be_overridden_by_tool(sample):
    s = Session(sample, log=False)
    s.hear("CARD-01은 Rev B")
    for t in ("list_package", "validate_scan"):
        s.call(t, {})
    assert "패키지에 Rev A로 지정" in s.call("select_criteria", {"card_id": "CARD-01", "rev": "B"})["error"]


# ------------------------------------------------------------------ 가드레일: 서명
@pytest.fixture()
def drafted(sample):
    s, r = run_fixed(sample)
    r.run_turn("CARD-05는 Rev B")
    assert s.package_report is not None
    return s, r


def sign(s, text, **args):
    s.hear(text)
    return s.call("record_signoff", args)


def test_signoff_rejects_ai_and_unnamed(drafted):
    s, _ = drafted
    assert "error" in sign(s, "AI가 CARD-01 승인", card_id="CARD-01", user="AI", decision="approve")
    assert "error" in sign(s, "CARD-01 승인해줘", card_id="CARD-01", user="김검사", decision="approve")  # 이름이 발화에 없음
    assert "error" in sign(s, "김검사입니다. CARD-01 확인 부탁", card_id="CARD-01", user="김검사", decision="approve")  # 의사 없음
    assert "error" in sign(s, "김검사입니다. CARD-02 승인", card_id="CARD-01", user="김검사", decision="approve")  # 다른 카드
    assert "error" in sign(s, "검사원입니다 CARD-01 승인", card_id="CARD-01", user="검사원", decision="approve")  # 이름 아님
    assert all(not c.signoffs for c in s.cards.values())


def test_signoff_once_per_utterance(drafted):
    s, _ = drafted
    assert sign(s, "김검사입니다. CARD-01 승인합니다", card_id="CARD-01", user="김검사", decision="approve")["recorded"]
    res = s.call("record_signoff", {"card_id": "CARD-01", "user": "김검사", "decision": "approve"})
    assert "이미 기록" in res["error"] and len(s.cards["CARD-01"].signoffs) == 1


def test_signoff_before_report_rejected(sample):
    s, _ = run_fixed(sample)  # 질문 대기 상태, 보고서 없음
    assert "보고서 초안이 아직 없다" in sign(s, "김검사 CARD-01 승인", card_id="CARD-01", user="김검사", decision="approve")["error"]


def test_exclusion_must_be_said_and_only_on_reject(drafted):
    s, _ = drafted
    res = sign(s, "김검사입니다. CARD-03 반려합니다", card_id="CARD-03", user="김검사", decision="reject",
               exclude_indications=["IND-02"])
    assert "이번 발화에 없다" in res["error"]
    res = sign(s, "김검사입니다. CARD-03 승인. IND-02 제외", card_id="CARD-03", user="김검사", decision="approve",
               exclude_indications=["IND-02"])
    assert "반려할 때만" in res["error"]
    res = sign(s, "김검사입니다. CARD-03 반려. IND-09 제외", card_id="CARD-03", user="김검사", decision="reject",
               exclude_indications=["IND-09"])
    assert "없는 지시" in res["error"]
    assert not s.cards["CARD-03"].excluded


def test_reject_makes_stale_blocks_report_then_reevaluates(drafted):
    s, r = drafted
    res = sign(s, "김검사입니다. CARD-03 반려합니다. IND-02는 표면 신호라 제외", card_id="CARD-03", user="김검사",
               decision="reject", exclude_indications=["IND-02"], reason="표면 신호")
    assert res["recorded"] and s.cards["CARD-03"].stale and s.report_stale
    assert "error" in s.call("draft_item_report", {})  # 재평가 전 보고서 차단
    assert "error" in s.call("compile_package_report", {})
    s.hear("김검사입니다. CARD-03 승인합니다")
    assert "재평가" in s.call("record_signoff", {"card_id": "CARD-03", "user": "김검사", "decision": "approve"})["error"]
    r.finish()
    c = s.cards["CARD-03"]
    assert not c.stale and not s.report_stale
    assert [f["rule_id"] for f in c.eval["findings"]] == ["Z1-D2"]  # 간격 위반(S1)은 사라지고 크기 초과는 남는다
    assert c.report["disposition"] == "EXCEED" and c.report["excluded"] == ["IND-02"]
    assert not c.approved


def test_reject_with_procedure_correction_evaluates_card(drafted):
    s, r = drafted
    r.run_turn("검사원 김검사 CARD-06 반려. 절차를 GNU-NTM-EX-51-02로 정정")
    c = s.cards["CARD-06"]
    assert c.procedure_id == P2 and c.proc_check["ok"] and c.report["disposition"] == "REPAIR"
    assert c.eval["findings"][0]["rule_id"] == "Z2-D1"


def test_approve_all_then_approved_report(drafted):
    s, r = drafted
    r.run_turn("검사원 김검사 전체 승인합니다")
    assert s.package_report["status"] == "APPROVED" and len(s.package_report["approved_cards"]) == 6
    assert all(c.approved for c in s.cards.values())


def test_fixed_parser_requires_explicit_name():
    class S:
        cards = {"CARD-01": None}
    assert parse_signoff("CARD-01 승인", S) is None
    assert parse_signoff("검사원 김검사 CARD-01 승인", S)["user"] == "김검사"
    assert parse_signoff("검사원 김검사 승인", S) is None  # 카드 미지정


# ------------------------------------------------------------------ 측정·판정 (합성)
def test_no_indication_is_allow(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [], {}, {})]))
    assert s.cards["C1"].indications == [] and s.cards["C1"].report["disposition"] == "ALLOW"


@pytest.mark.parametrize("size,expect,rule", [(8, "ALLOW", None), (12, "REPAIR", "Z1-D1"), (24, "EXCEED", "Z1-D2")])
def test_tiers(tmp_path, size, expect, rule):
    # 정사각형 한 변 size mm의 모멘트 기반 장축은 size * 2/sqrt(3) ≈ 1.155 * size
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(40, 20, 40 + size, 20 + size)], {}, {})]))
    c = s.cards["C1"]
    assert c.report["disposition"] == expect
    assert [f["rule_id"] for f in c.eval["findings"]] == ([rule] if rule else [])


def test_near_limit_warning(tmp_path):
    # 가로 8.5 x 세로 2 mm 띠: 장축 = 4*sqrt(8.5^2/12 + ...) ≈ 9.8 mm → 허용 한도 10 mm의 5% 이내
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(40, 20, 48.5, 22)], {}, {"pitch": 0.5, "rows": 120, "cols": 240})]))
    c = s.cards["C1"]
    major = c.indications[0]["major_mm"]
    assert 9.5 <= major <= 10.0, major
    assert c.report["disposition"] == "ALLOW"
    assert [w["kind"] for w in c.eval["warnings"]] == ["near_limit"]
    assert s.package_report["actions"]["recheck"] == ["C1"]


def test_scan_edge_warning(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(0, 20, 6, 26)], {}, {})]))
    c = s.cards["C1"]
    assert c.indications[0]["touches_scan_edge"] and "scan_edge" in [w["kind"] for w in c.eval["warnings"]]


def test_spacing_rule(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(20, 20, 25, 25), (35, 20, 40, 25)], {}, {})]))
    c = s.cards["C1"]
    f = [x for x in c.eval["findings"] if x["rule_id"] == "Z1-S1"]
    assert len(f) == 1 and f[0]["measured"] == 10.0 and c.report["disposition"] == "REPAIR"


def test_small_blobs_below_min_area_ignored(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(20, 20, 21, 22)], {}, {})]))  # 2 mm² < 3 mm²
    assert s.cards["C1"].indications == []


def test_procedure_thickness_out_of_range_not_measured(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [(40, 20, 60, 40)], {}, {"thickness": 5.0})]))
    c = s.cards["C1"]
    assert c.eval is None and c.indications == [] and c.report["disposition"] == "NOT_EVALUATED"
    assert "1.0~3.0" in c.report["not_evaluated_reason"]


def test_growth_flag(tmp_path, monkeypatch):
    from core import history
    hd = tmp_path / "hist"
    hd.mkdir()
    (hd / "HL-TEST.json").write_text(json.dumps({"aircraft": "HL-TEST", "source": "EXAMPLE_ONLY", "records": [
        {"location_id": "LOC-C1", "date": "2024-01-01", "major_mm": 5.0},
        {"location_id": "LOC-C1", "date": "2025-01-01", "major_mm": 9.0},
        {"location_id": "LOC-C2", "date": "2025-01-01", "major_mm": 9.0}]}), encoding="utf-8")
    monkeypatch.setattr(history, "HISTORY_DIR", hd)
    (tmp_path / "p").mkdir()
    s, _ = run_fixed(make_pkg(tmp_path / "p", [
        ("C1", [(40, 20, 52, 32)], {}, {}), ("C2", [(40, 20, 48, 28)], {}, {}), ("C3", [(40, 20, 48, 28)], {}, {})]))
    h1, h2, h3 = (s.cards[k].history for k in ("C1", "C2", "C3"))
    assert h1["previous"]["date"] == "2025-01-01" and h1["grew"] is True  # 가장 최근 기록과 비교
    assert h2["grew"] is False and h3["found"] is False


# ------------------------------------------------------------------ 입력 오류
def test_corrupt_csv_and_missing_meta_blocked_not_guessed(tmp_path):
    folder = make_pkg(tmp_path, [("C1", [(40, 20, 52, 32)], {}, {}), ("C2", [], {}, {}), ("C3", [], {}, {}),
                                 ("C4", [(40, 20, 52, 32)], {}, {})])
    p = folder / "C1_amplitude_db.csv"
    p.write_text(p.read_text().replace("-20.0", "x.x", 3), encoding="utf-8")
    m = json.loads((folder / "C2_meta.json").read_text())
    del m["reference_db"], m["thickness_mm"]
    (folder / "C2_meta.json").write_text(json.dumps(m))
    m = json.loads((folder / "C3_meta.json").read_text())
    m["grid"]["rows"] = 99
    (folder / "C3_meta.json").write_text(json.dumps(m))
    s, _ = run_fixed(folder)
    for cid, word in (("C1", "숫자가 아닌 셀"), ("C2", "reference_db"), ("C3", "다름")):
        c = s.cards[cid]
        assert c.eval is None and c.report["disposition"] == "NOT_EVALUATED" and word in c.blocked_reason, cid
    assert s.cards["C4"].report["disposition"] == "REPAIR"  # 나머지 카드는 정상 처리
    assert s.package_report["counts"]["NOT_EVALUATED"] == 3


def test_missing_card_info_blocks_that_card(tmp_path):
    s, _ = run_fixed(make_pkg(tmp_path, [("C1", [], {"zone_id": None}, {}), ("C2", [], {"procedure_id": "NOPE"}, {}),
                                         ("C3", [], {"zone_id": "Z9"}, {}), ("C4", [], {"criteria_rev": "Q"}, {})]))
    assert "부위 구역" in s.cards["C1"].blocked_reason
    assert "NOPE" in s.cards["C2"].blocked_reason
    assert "Z9" in s.cards["C3"].blocked_reason
    assert "Rev Q" in s.cards["C4"].blocked_reason
    assert all(c.report["disposition"] == "NOT_EVALUATED" for c in s.cards.values())


def test_hold_card(sample):
    s, r = run_fixed(sample)
    s.hear("CARD-05는 보류")
    s.hold_card("CARD-05", "확인 불가")
    r.finish()
    assert s.package_report and s.cards["CARD-05"].report["status"] == "HELD"
    assert s.cards["CARD-05"].report["disposition"] == "NOT_EVALUATED"


@pytest.mark.parametrize("doc,word", [
    (None, "package.json이 없음"), ("{", "형식 오류"), ('{"aircraft":"A","check_type":"C","cards":[]}', "cards"),
    ('{"check_type":"C","cards":[{"card_id":"C1"}]}', "aircraft"),
    ('{"aircraft":"A","check_type":"C","cards":[{"card_id":"C1"},{"card_id":"c1"}]}', "중복"),
    ('{"aircraft":"A","check_type":"C","cards":[{"card_id":"../x"}]}', "형식 오류")])
def test_package_errors(tmp_path, doc, word):
    if doc is not None:
        (tmp_path / "package.json").write_text(doc, encoding="utf-8")
    with pytest.raises(pkg.PackageError, match=word):
        pkg.load_package(tmp_path)


def test_zip_names_are_flattened_and_checked(tmp_path):
    import zipfile
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../evil.txt", "x")
        f.writestr("sub/package.json", "{}")
    out = tmp_path / "out"
    out.mkdir()
    pkg.safe_extract(z, out)
    assert sorted(p.name for p in out.iterdir()) == ["evil.txt", "package.json"]
    assert not (tmp_path.parent / "evil.txt").exists()
    with pytest.raises(pkg.PackageError):
        pkg.safe_name("a<b>.csv")


# ------------------------------------------------------------------ 서술문 검증
FACTS = "CARD-03: 지시 2건, 최대 IND-01 장축 26.95 mm. 한도 20.0 mm 초과. 허용 2건, 수리 가능 2건."


@pytest.mark.parametrize("text,ok", [
    ("CARD-03은 장축 26.95 mm로 한도 20.0 mm를 넘어 제작사 문의가 필요합니다. 최종 판단은 검사원이 합니다.", True),
    ("CARD-03은 장축 27.5 mm로 한도를 넘었습니다. 최종 판단은 검사원이 합니다.", False),  # 근거 없는 숫자
    ("장축 26.95 mm 손상이 있습니다. 최종 판단은 검사원이 합니다.", False),  # 필수 ID 누락
    ("CARD-03 외에는 문제 없으며 안전합니다. 최종 판단은 검사원이 합니다.", False),  # 금지 표현
    ("CARD-03과 CARD-04는 제작사와 협의해야 합니다. 최종 판단은 검사원이 합니다.", False),  # 카드와 조치 연결 오류
    ("CARD-03은 박리(delamination)로 보입니다. 최종 판단은 검사원이 합니다.", False)])
def test_verify_narrative(text, ok):
    got, detail = rpt.verify_narrative(text, FACTS, ["CARD-03"], {"제작사": ["CARD-03"]})
    assert got is ok, detail


def test_opinion_falls_back_to_template_when_llm_invents_number(sample):
    s = Session(sample, log=False, llm=lambda prompt: "CARD-03은 장축 99.9 mm입니다. 최종 판단과 서명은 자격 검사원이 한다.")
    r = Runner(s, use_llm=False)
    r.run_turn("처리")
    r.run_turn("CARD-05는 Rev B")
    assert s.package_report["opinion_source"] == "template"
    assert s.package_report["opinion"] == s.package_report["summary"]


def test_measure_matches_known_rectangle():
    amp = np.zeros((50, 80))
    amp[10:20, 30:50] = -12.0  # 20 x 10 mm, pitch 1
    ind = measure.extract_indications(amp, 1.0)
    assert len(ind) == 1
    i = ind[0]
    assert i["area_mm2"] == 200.0 and i["bbox_mm"] == [30.0, 10.0, 50.0, 20.0]
    assert abs(i["major_mm"] - 20 * 2 / 3 ** 0.5) < 0.05 and abs(i["minor_mm"] - 10 * 2 / 3 ** 0.5) < 0.05
    assert i["peak_drop_db"] == 12.0 and not i["touches_scan_edge"]
    assert measure.extract_indications(amp, 1.0, drop_db=13.0) == []


def test_unapproved_rules_refused(tmp_path):
    (tmp_path / "X_RevA.json").write_text(json.dumps({"criteria_id": "X", "revision": "A", "approved": False, "zones": {}}))
    with pytest.raises(cr.CriteriaError, match="승인하지 않은"):
        cr.load_limits("X", "A", tmp_path)
