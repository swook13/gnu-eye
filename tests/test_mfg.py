"""제조 검사 모드 회귀 테스트 (LLM 없음).

    cd 지누아이 && python -m pytest tests -q

제조 실데이터가 없어서 합성 스캔(사각형 지시)을 테스트 안에서 만든다. 측정기와 같은 가정(6 dB 임계)을 쓰므로
이 테스트는 측정 정확도가 아니라 제조 기준 대조, 배선, 가드레일을 확인하는 것이다.
사각형 한 변이 w mm이면 장축은 2w/√3 mm로 측정된다.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.loop import Runner  # noqa: E402
from agent.session import Session  # noqa: E402
from core import criteria as cr  # noqa: E402
from core import history as hist  # noqa: E402
from core import package as pkg  # noqa: E402
from core import report as rpt  # noqa: E402
from tests.test_tools import make_scan, tools  # noqa: E402

PROC, SPEC = "GNU-UT-EX-MFG-01", "GNU-SPEC-UT-001"


def make_lot(tmp_path, parts, lot="LOT-T1", top=None):
    """parts: [(card_id, rects, {부품 덮어쓰기}, {make_scan 인자})]"""
    out = []
    for cid, rects, over, scan_kw in parts:
        make_scan(tmp_path, cid, rects, **scan_kw)
        c = {"card_id": cid, "title": cid, "zone_id": "A", "part_number": f"PN-{cid}", "serial_number": f"SN-{cid}",
             "procedure_id": PROC, "criteria_id": SPEC, "criteria_rev": "A", "material": "CFRP",
             "scan_file": f"{cid}_amplitude_db.csv", "meta_file": f"{cid}_meta.json"}
        c.update(over)
        out.append({k: v for k, v in c.items() if v is not None})
    doc = {"domain": "manufacturing", "package_id": "T", "lot_id": lot, "check_type": "출하 전 초음파 검사",
           "customer": "가상 고객 A", "cards": out}
    doc.update(top or {})
    (tmp_path / "package.json").write_text(json.dumps({k: v for k, v in doc.items() if v is not None}), encoding="utf-8")
    return tmp_path


def run_fixed(folder, text="처리해줘"):
    s = Session(folder, log=False)
    r = Runner(s, use_llm=False)
    r.run_turn(text)
    return s, r


FINE = dict(rows=120, cols=240, pitch=0.5)  # 60 x 120 mm, 0.5 mm 격자
LOT = [
    ("PART-01", [(10, 10, 14, 14)], {}, {}),                      # 4 mm → 장축 4.62: 적합
    ("PART-02", [(10, 10, 15.5, 15.5)], {}, FINE),                # 5.5 mm → 6.35: 한도 100% → 보류
    ("PART-03", [(10, 10, 30, 30)], {}, {}),                      # 20 mm → 23.09: 부적합
    ("PART-04", [(10, 10, 17, 17)], {"criteria_rev": None}, {}),  # 7 mm → 8.08: Rev A 부적합, Rev B 적합
]


def test_lot_asks_revision_then_dispositions(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, LOT))
    assert s.domain == "manufacturing"
    q = s.pending_questions()
    assert [x["card_id"] for x in q] == ["PART-04"] and q[0]["options"] == ["A", "B"] and "고객사양" in q[0]["text"]
    assert s.package_report is None
    r.run_turn("PART-04의 개정번호는 Rev B입니다.")
    disp = {c.id: c.report["disposition"] for c in s.cards.values()}
    assert disp == {"PART-01": "ALLOW", "PART-02": "REPAIR", "PART-03": "EXCEED", "PART-04": "ALLOW"}
    assert s.cards["PART-02"].eval["disposition_ko"] == "보류(재검사 권고)"
    assert [f["rule_id"] for f in s.cards["PART-03"].eval["findings"]] == ["A-1", "A-3"]
    rep = s.package_report
    assert rep["domain"] == "manufacturing" and rep["report_id"].startswith("UT-RPT-LOT-T1-")
    assert rep["counts"] == {"ALLOW": 2, "REPAIR": 1, "EXCEED": 1, "NOT_EVALUATED": 0}
    assert rep["actions"]["oem_inquiry"] == ["PART-03"] and rep["actions"]["recheck"] == ["PART-02"]
    assert "생산 로트 LOT-T1" in rep["summary"] and "부적합(NCR 대상) 1건" in rep["summary"]
    html = rpt.render_html(rep)
    assert "NCR-DRAFT-LOT-T1-PART-03" in html and "부품번호 / S/N" in html and "PN-PART-03" in html
    assert "기체" not in html and "제작사 문의" not in html and "EXAMPLE_ONLY" in html
    assert html.count("부적합보고서(NCR) 초안") == 1  # 부적합 부품에만 NCR 초안


def test_ncr_draft_has_12_fields_and_leaves_disposition_to_mrb(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, LOT))
    r.run_turn("PART-04의 개정번호는 Rev B입니다.")
    n = next(i for i in s.package_report["items"] if i["card_id"] == "PART-03")["ncr_draft"]
    assert n["total"] == 12 and n["system_fields"] == 10 and n["system_filled"] == 10 and not n["inspector_filled"]
    f = {x["label"]: x for x in n["fields"]}
    assert f["처분"]["value"] is None and f["처분"]["filled_by"] == "mrb"
    assert "A-1" in f["부적합 내용 (규칙, 측정값, 한도)"]["value"] and "IND-01" in f["지시 위치·크기"]["value"]
    assert f["부품번호 / S/N"]["value"] == "PN-PART-03 / SN-PART-03"
    assert all(i["ncr_draft"] is None for i in s.package_report["items"] if i["card_id"] != "PART-03")
    html = rpt.render_html(s.package_report)
    assert "시스템 기입 10/10칸, 검사원 0/1칸, MRB 1칸" in html and "자재심의(MRB)" in html
    s.hear("검사원 김검사: 전체 부품 승인합니다.")
    assert s.call("record_signoff", {"card_id": "ALL", "user": "김검사", "decision": "approve"}, by="user").get("recorded")
    n = next(i for i in s.package_report["items"] if i["card_id"] == "PART-03")["ncr_draft"]
    assert n["inspector_filled"] and {x["label"]: x for x in n["fields"]}["검사원 확인"]["value"].startswith("김검사 승인")
    assert {x["label"]: x for x in n["fields"]}["처분"]["value"] is None  # 승인 뒤에도 처분은 시스템이 채우지 않는다


def test_demo_lot_builds_with_designed_dispositions(tmp_path):
    from tools import build_mfg_lot as lot
    lot.build(tmp_path)
    s, r = run_fixed(tmp_path)
    assert [q["card_id"] for q in s.pending_questions()] == ["PART-04"]
    r.run_turn("PART-04의 고객사양 개정번호는 Rev B입니다.")
    disp = {c.id: c.report["disposition"] for c in s.cards.values()}
    assert disp == {"PART-01": "ALLOW", "PART-02": "REPAIR", "PART-03": "EXCEED", "PART-04": "ALLOW",
                    "PART-05": "EXCEED", "PART-06": "EXCEED", "PART-07": "EXCEED"}
    assert s.cards["PART-03"].report["data_source"].startswith("공개 실측") and s.cards["PART-01"].report["data_source"] == "합성 데이터"
    assert all(c.history["found"] for c in s.cards.values())  # 부품번호가 가상 이력의 GNU-P-1001~1005
    s.hear("검사원 김검사: PART-06 반려합니다. IND-01은 표면 신호라 제외.")
    assert s.call("record_signoff", {"card_id": "PART-06", "user": "김검사", "decision": "reject",
                                     "exclude_indications": ["IND-01"]}, by="user").get("recorded")
    r.finish()
    assert s.cards["PART-06"].report["disposition"] == "ALLOW"


def test_revision_changes_disposition(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, LOT))
    r.run_turn("PART-04는 Rev A")
    assert s.cards["PART-04"].report["disposition"] == "EXCEED"  # Rev B였다면 ALLOW


def test_revision_not_guessed(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, LOT))
    res = s.call("select_criteria", {"card_id": "PART-04", "rev": "B"}, by="llm")
    assert "말한 적이 없다" in res["error"] and s.cards["PART-04"].rev is None


def test_spacing_and_area_rules(tmp_path):
    parts = [("PART-01", [(10, 10, 14, 14), (24, 10, 28, 14)], {}, {}),   # 구역 A: 간격 10 mm < 25 mm
             ("PART-02", [(10, 10, 20, 20)], {"zone_id": "B"}, {})]       # 구역 B: 장축 11.55 < 12.7, 면적 1.39% > 1%
    s, r = run_fixed(make_lot(tmp_path, parts))
    assert [f["rule_id"] for f in s.cards["PART-01"].eval["findings"]] == ["A-2"]
    f = s.cards["PART-02"].eval["findings"]
    assert [x["rule_id"] for x in f] == ["B-3"] and f[0]["measured"] == 1.39 and f[0]["unit"] == "%"
    assert s.cards["PART-02"].eval["limits"] == {"max_dimension_mm": 12.7, "min_gap_mm": None, "max_area_pct": 1.0}


def test_reject_exclusion_then_approve_all(tmp_path):
    parts = [("PART-01", [(10, 10, 14, 14), (24, 10, 28, 14)], {}, {})]
    s, r = run_fixed(make_lot(tmp_path, parts))
    assert s.cards["PART-01"].report["disposition"] == "EXCEED"
    s.hear("검사원 김검사: PART-01 반려합니다. IND-02는 표면 신호라 제외.")
    res = s.call("record_signoff", {"card_id": "PART-01", "user": "김검사", "decision": "reject",
                                    "exclude_indications": ["IND-02"]}, by="user")
    assert res.get("recorded"), res
    r.finish()
    assert s.cards["PART-01"].report["disposition"] == "ALLOW" and s.package_report["status"] == "DRAFT"
    s.hear("검사원 김검사: 전체 부품 승인합니다.")
    res = s.call("record_signoff", {"card_id": "ALL", "user": "김검사", "decision": "approve"}, by="user")
    assert res.get("recorded"), res
    assert s.package_report["status"] == "APPROVED" and "전 부품 검사원 승인 완료" in s.package_report["summary"]


def test_signoff_refused_without_name(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, [("PART-01", [(10, 10, 14, 14)], {}, {})]))
    s.hear("PART-01 승인합니다.")
    res = s.call("record_signoff", {"card_id": "PART-01", "user": "AI", "decision": "approve"}, by="llm")
    assert "error" in res and not s.cards["PART-01"].signoffs


def test_maintenance_criteria_refused_in_lot(tmp_path):
    parts = [("PART-01", [(10, 10, 14, 14)], {"criteria_id": "GNU-ADL-EX-001", "zone_id": "Z1"}, {}),
             ("PART-02", [(10, 10, 14, 14)], {"procedure_id": "GNU-NTM-EX-51-01"}, {})]
    s, r = run_fixed(make_lot(tmp_path, parts))
    for cid in ("PART-01", "PART-02"):
        assert "정비 점검용" in s.cards[cid].blocked_reason and s.cards[cid].eval is None
    assert s.package_report["counts"]["NOT_EVALUATED"] == 2


def test_lot_criteria_refused_in_maintenance(tmp_path):
    from tests.test_tools import make_pkg
    s = Session(make_pkg(tmp_path, [("CARD-01", [(10, 10, 14, 14)], {"criteria_id": SPEC, "zone_id": "A"}, {})]), log=False)
    Runner(s, use_llm=False).run_turn("처리")
    assert "제조 검사용" in s.cards["CARD-01"].blocked_reason


def test_procedure_thickness_out_of_range(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, [("PART-01", [(10, 10, 14, 14)], {}, {"thickness": 12.0})]))
    assert "절차 부적합" in s.cards["PART-01"].blocked_reason and s.cards["PART-01"].eval is None


def test_package_requires_lot_and_part_number(tmp_path):
    make_lot(tmp_path, [("PART-01", [], {"part_number": None}, {})])
    p = pkg.load_package(tmp_path)
    assert p["domain"] == "manufacturing" and p["cards"][0]["missing"] == ["part_number"]
    s, r = run_fixed(tmp_path)
    assert "부품번호" in s.cards["PART-01"].blocked_reason
    make_lot(tmp_path, [("PART-01", [], {}, {})], top={"lot_id": None})
    with pytest.raises(pkg.PackageError, match="lot_id"):
        pkg.load_package(tmp_path)
    make_lot(tmp_path, [("PART-01", [], {}, {})], top={"domain": "other"})
    with pytest.raises(pkg.PackageError, match="domain"):
        pkg.load_package(tmp_path)


def test_ncr_history_lookup(tmp_path):
    assert hist.ncr_lookup("PN-1", tmp_path)["found"] is False  # 이력 파일 없음: 지어내지 않는다
    (tmp_path / "ncr_history.json").write_text(json.dumps({"source": "TEST", "records": [
        {"ncr_number": "NCR-1", "date": "2026-01-02", "part_number": "PN-1", "size_mm": 7.5},
        {"ncr_number": "NCR-2", "date": "2026-03-04", "part_number": "PN-1", "size_mm": 9.1},
        {"ncr_number": "NCR-3", "date": "2026-02-01", "part_number": "PN-2"}]}), encoding="utf-8")
    h = hist.ncr_lookup("PN-1", tmp_path)
    assert h["found"] and h["records"] == 2 and "NCR-2" in h["text"] and "9.1" in h["text"] and h["grew"] is False
    assert hist.ncr_lookup("PN-9", tmp_path)["found"] is False


def test_ncr_history_counts_types_and_recorded_causes(tmp_path):
    (tmp_path / "ncr_history.json").write_text(json.dumps({"source": "TEST", "records": [
        {"ncr_number": "NCR-1", "date": "2026-01-02", "part_number": "PN-1", "size_mm": 7.5,
         "defect_type": "porosity", "root_cause": "진공백 누설", "disposition": "수리"},
        {"ncr_number": "NCR-2", "date": "2026-03-04", "part_number": "PN-1", "size_mm": 9.1,
         "defect_type": "delamination", "root_cause": "진공백 누설", "disposition": "폐기"}]},
        ensure_ascii=False), encoding="utf-8")
    h = hist.ncr_lookup("PN-1", tmp_path)
    assert h["defect_types"] == {"기공": 1, "박리": 1} and h["root_causes"] == {"진공백 누설": 2}
    assert "처분 폐기" in h["text"] and "진공백 누설 2건" in h["text"] and "(참고)" in h["text"]


def test_bundled_ncr_history_is_marked_virtual():
    doc = json.loads((ROOT / "data" / "history" / "ncr_history.json").read_text(encoding="utf-8"))
    assert doc["source"].startswith("EXAMPLE_ONLY") and doc["records"]
    assert all(r.get("synthetic") is True for r in doc["records"])
    assert hist.ncr_lookup("GNU-P-1001")["found"] and not hist.ncr_lookup("PN-PART-01")["found"]


def test_tool_order_same_as_maintenance(tmp_path):
    s, r = run_fixed(make_lot(tmp_path, [("PART-01", [(10, 10, 14, 14)], {}, {})]))
    assert tools(s) == [(t, True) for t in ("declare_plan", "list_package", "validate_scan", "select_criteria",
                                             "inspect_package", "search_history", "draft_item_report",
                                             "compile_package_report")]
    assert s.plan[0] == "로트 패키지 항목 확인" and cr.procedure_ids("manufacturing") == [PROC]


def test_opinion_verified_against_part_ids(tmp_path):
    bad = "PART-01은 NCR 대상입니다. 최종 판단과 서명은 자격 검사원이 한다."  # NCR 대상은 PART-03이다
    s = Session(make_lot(tmp_path, LOT), log=False, llm=lambda prompt: bad)
    r = Runner(s, use_llm=False)
    r.run_turn("처리")
    r.run_turn("PART-04는 Rev B")
    assert s.package_report["opinion_source"] == "template"
