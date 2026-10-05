"""기준 두 단계 (결정론적). LLM은 이 파일의 수치를 만들지 않는다.

1단계 절차 적합성: 두께·재질이 절차 범위 안인가.
2단계 허용 손상 한도: 부위(zone)별 한도와 대조해 처분 초안을 낸다.
모든 기준은 가상(EXAMPLE_ONLY)이다.
"""
import json
from pathlib import Path

from . import domain as dm
from . import measure
from .domain import ALLOW, EXCEED, NOT_EVALUATED, REPAIR

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

TIER = {ALLOW: 0, REPAIR: 1, EXCEED: 2}
KO = dm.PROFILES[dm.MAINT]["ko"]
KO_MFG = dm.PROFILES[dm.MFG]["ko"]
DRAFT_STATUS = "초안 - 자격 검사원 승인 전"


class CriteriaError(Exception):
    pass


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_procedure(procedure_id, rules_dir=RULES_DIR):
    doc = _load(Path(rules_dir) / "procedures.json")
    if not doc.get("approved"):
        raise CriteriaError("procedures.json은 사람이 승인하지 않아 쓸 수 없음")
    for p in doc["procedures"]:
        if p["id"] == procedure_id:
            return {**p, "source": doc["source"]}
    raise CriteriaError(f"절차 {procedure_id} 없음. 등록된 절차: {[p['id'] for p in doc['procedures']]}")


def available_revisions(criteria_id, rules_dir=RULES_DIR):
    return sorted(p.stem.split("_Rev")[1] for p in Path(rules_dir).glob(f"{criteria_id}_Rev*.json"))


def load_limits(criteria_id, revision, rules_dir=RULES_DIR):
    path = Path(rules_dir) / f"{criteria_id}_Rev{revision}.json"
    if not path.exists():
        raise CriteriaError(f"기준 {criteria_id} Rev {revision} 없음. "
                            f"등록된 개정: {available_revisions(criteria_id, rules_dir)}")
    doc = _load(path)
    if not doc.get("approved"):
        raise CriteriaError(f"{path.name}은 사람이 승인하지 않은 기준이라 판정에 쓸 수 없음")
    return doc


def check_procedure(proc, thickness_mm, material):
    """절차 적합성. 범위 밖이면 그 카드는 측정·판정하지 않는다."""
    reasons = []
    if material not in proc["materials"]:
        reasons.append(f"재질 {material}은 절차 {proc['id']}의 적용 재질 {proc['materials']}에 없음")
    lo, hi = proc["thickness_min_mm"], proc["thickness_max_mm"]
    if not (lo <= thickness_mm <= hi):
        reasons.append(f"두께 {thickness_mm} mm가 절차 {proc['id']}의 적용 범위 {lo}~{hi} mm 밖")
    return {"ok": not reasons, "procedure_id": proc["id"], "thickness_mm": thickness_mm, "material": material,
            "range_mm": [lo, hi], "reasons": reasons}


def procedure_ids(domain=dm.MAINT, rules_dir=RULES_DIR):
    doc = _load(Path(rules_dir) / "procedures.json")
    return [p["id"] for p in doc["procedures"] if p.get("domain", dm.MAINT) == domain]


def evaluate(indications, limits, zone_id, scan_area_mm2=None):
    """indications: extract_indications 결과(검사원이 제외한 것은 뺀 뒤). 처분 '초안'을 돌려준다.

    기준 파일의 domain이 manufacturing이면 고객사양 방식(_evaluate_mfg)으로 대조한다.
    """
    if zone_id not in limits["zones"]:
        raise CriteriaError(f"기준 {limits['criteria_id']} Rev {limits['revision']}에 구역 {zone_id} 없음. "
                            f"등록된 구역: {sorted(limits['zones'])}")
    if limits.get("domain") == dm.MFG:
        return _evaluate_mfg(indications, limits, zone_id, scan_area_mm2)
    z = limits["zones"][zone_id]
    near = limits.get("near_limit_ratio", 0.05)
    findings, warnings = [], []
    for i in indications:
        m = i["major_mm"]
        if m > z["repairable_mm"]:
            findings.append({"rule_id": f"{zone_id}-D2", "indication": i["id"], "measured": m,
                             "limit": z["repairable_mm"], "unit": "mm", "tier": EXCEED,
                             "text": f"장축 {m} mm가 수리 가능 한도 {z['repairable_mm']} mm 초과"})
        elif m > z["allowable_mm"]:
            findings.append({"rule_id": f"{zone_id}-D1", "indication": i["id"], "measured": m,
                             "limit": z["allowable_mm"], "unit": "mm", "tier": REPAIR,
                             "text": f"장축 {m} mm가 허용 한도 {z['allowable_mm']} mm 초과 (수리 가능 한도 {z['repairable_mm']} mm 이내)"})
        for rule, lim in ((f"{zone_id}-D1", z["allowable_mm"]), (f"{zone_id}-D2", z["repairable_mm"])):
            if lim * (1 - near) <= m <= lim:
                warnings.append({"kind": "near_limit", "rule_id": rule, "indication": i["id"], "measured": m,
                                 "limit": lim, "unit": "mm", "ratio_to_limit_pct": round(m / lim * 100, 1),
                                 "text": f"{i['id']} 장축 {m} mm가 한도 {lim} mm의 {m / lim * 100:.1f}% 수준 - "
                                         "측정 불확실도를 고려해 재검사 권고"})
        if i.get("touches_scan_edge"):
            warnings.append({"kind": "scan_edge", "indication": i["id"],
                             "text": f"{i['id']}가 스캔 범위 가장자리에 닿음 - 손상이 스캔 밖으로 이어질 수 있어 "
                                     "크기가 작게 측정됐을 가능성. 범위를 넓혀 재스캔 권고"})
    for a in range(len(indications)):
        for b in range(a + 1, len(indications)):
            gap = measure.bbox_gap_mm(indications[a], indications[b])
            if gap < z["min_gap_mm"]:
                findings.append({"rule_id": f"{zone_id}-S1",
                                 "indication": f"{indications[a]['id']}/{indications[b]['id']}",
                                 "measured": gap, "limit": z["min_gap_mm"], "unit": "mm", "tier": REPAIR,
                                 "text": f"손상 간 거리 {gap} mm가 최소 간격 {z['min_gap_mm']} mm 미만 - "
                                         "하나의 손상으로 보고 검사원이 재평가"})
    disp = ALLOW
    for f in findings:
        if TIER[f["tier"]] > TIER[disp]:
            disp = f["tier"]
    return {"disposition": disp, "disposition_ko": KO[disp], "findings": findings, "warnings": warnings,
            "rule_set": f"{limits['criteria_id']} Rev {limits['revision']}", "zone_id": zone_id,
            "zone_name": z["name"], "limits": {k: z[k] for k in ("allowable_mm", "repairable_mm", "min_gap_mm")},
            "source": limits["source"], "status": DRAFT_STATUS}


def _evaluate_mfg(indications, limits, zone_id, scan_area_mm2):
    """제조 검사: 고객사양의 구역별 최대 치수, 지시 간 거리, 누적 면적 비율과 대조한다.

    최대 치수가 한도의 ±near 범위면 측정 불확실도 안이라 단정하지 않고 보류(재검사 권고)로 둔다.
    """
    z = limits["zones"][zone_id]
    near = limits.get("near_limit_ratio", 0.05)
    lim = z["max_dimension_mm"]
    findings, warnings = [], []
    for i in indications:
        m = i["major_mm"]
        if m > lim * (1 + near):
            findings.append({"rule_id": f"{zone_id}-1", "indication": i["id"], "measured": m, "limit": lim,
                             "unit": "mm", "tier": EXCEED, "text": f"최대 치수 {m} mm가 사양 한도 {lim} mm 초과"})
        elif m >= lim * (1 - near):
            pct = round(m / lim * 100, 1)
            findings.append({"rule_id": f"{zone_id}-1", "indication": i["id"], "measured": m, "limit": lim,
                             "unit": "mm", "tier": REPAIR,
                             "text": f"최대 치수 {m} mm가 사양 한도 {lim} mm의 {pct}% 수준 - "
                                     "측정 불확실도 범위라 단정하지 않음"})
            warnings.append({"kind": "near_limit", "rule_id": f"{zone_id}-1", "indication": i["id"], "measured": m,
                             "limit": lim, "unit": "mm", "ratio_to_limit_pct": pct,
                             "text": f"{i['id']} 최대 치수 {m} mm가 한도 {lim} mm의 {pct}% 수준 - 재검사 권고"})
        if i.get("touches_scan_edge"):
            warnings.append({"kind": "scan_edge", "indication": i["id"],
                             "text": f"{i['id']}가 스캔 범위 가장자리에 닿음 - 지시가 스캔 밖으로 이어질 수 있어 "
                                     "크기가 작게 측정됐을 가능성. 범위를 넓혀 재스캔 권고"})
    if z.get("min_gap_mm"):
        for a in range(len(indications)):
            for b in range(a + 1, len(indications)):
                gap = measure.bbox_gap_mm(indications[a], indications[b])
                if gap < z["min_gap_mm"]:
                    findings.append({"rule_id": f"{zone_id}-2",
                                     "indication": f"{indications[a]['id']}/{indications[b]['id']}",
                                     "measured": gap, "limit": z["min_gap_mm"], "unit": "mm", "tier": EXCEED,
                                     "text": f"지시 간 거리 {gap} mm가 사양의 최소 간격 {z['min_gap_mm']} mm 미만"})
    area_pct = None
    if scan_area_mm2:
        area_pct = round(sum(i["area_mm2"] for i in indications) / scan_area_mm2 * 100, 2)
        if z.get("max_area_pct") is not None and area_pct > z["max_area_pct"]:
            findings.append({"rule_id": f"{zone_id}-3", "indication": "전체", "measured": area_pct,
                             "limit": z["max_area_pct"], "unit": "%", "tier": EXCEED,
                             "text": f"누적 지시 면적 {area_pct}%가 사양 한도 {z['max_area_pct']}% 초과 (스캔 영역 대비)"})
    disp = ALLOW
    for f in findings:
        if TIER[f["tier"]] > TIER[disp]:
            disp = f["tier"]
    return {"disposition": disp, "disposition_ko": KO_MFG[disp], "findings": findings, "warnings": warnings,
            "rule_set": f"{limits['criteria_id']} Rev {limits['revision']}", "zone_id": zone_id,
            "zone_name": z["name"], "area_pct": area_pct, "near_limit_ratio": near,
            "limits": {k: z.get(k) for k in ("max_dimension_mm", "min_gap_mm", "max_area_pct")},
            "source": limits["source"], "status": DRAFT_STATUS}
