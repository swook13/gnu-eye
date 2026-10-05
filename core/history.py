"""이전 점검 기록 조회와 크기 변화 비교 (결정론적). 기록은 모두 가상(EXAMPLE_ONLY)이다."""
import json
from collections import Counter
from pathlib import Path

HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "history"
DEFECT_KO = {"delamination": "박리", "porosity": "기공", "foreign_object": "이물질", "impact_damage": "충격 손상"}


def load_history(aircraft, history_dir=None):
    path = Path(history_dir or HISTORY_DIR) / f"{aircraft}.json"
    if not path.exists():
        return {"aircraft": aircraft, "source": "EXAMPLE_ONLY", "records": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compare(aircraft, location_id, current_major_mm, growth_flag_mm, history_dir=None):
    """같은 기체·같은 부위의 가장 최근 기록과 현재 최대 손상 장축을 비교한다."""
    doc = load_history(aircraft, history_dir)
    recs = sorted((r for r in doc["records"] if r["location_id"] == location_id), key=lambda r: r["date"])
    if not recs:
        return {"found": False, "location_id": location_id, "source": doc.get("source", "EXAMPLE_ONLY"),
                "text": "이전 점검 기록 없음 (신규 발견으로 기록)"}
    prev = recs[-1]
    res = {"found": True, "location_id": location_id, "source": doc.get("source", "EXAMPLE_ONLY"),
           "previous": prev, "records": len(recs), "growth_flag_mm": growth_flag_mm}
    if current_major_mm is None:
        res.update(change_mm=None, grew=False,
                   text=f"이전 기록({prev['date']}) 장축 {prev['major_mm']} mm. 이번 점검에서는 지시가 측정되지 않음")
        return res
    change = round(current_major_mm - prev["major_mm"], 2)
    grew = change > growth_flag_mm
    res.update(current_major_mm=current_major_mm, change_mm=change, grew=grew)
    if grew:
        res["text"] = (f"이전 기록({prev['date']}) 장축 {prev['major_mm']} mm → 현재 {current_major_mm} mm, "
                       f"{change:+} mm. 변화 기준 {growth_flag_mm} mm 초과 - 손상 확대 의심, 검사원 확인 필요")
    else:
        res["text"] = (f"이전 기록({prev['date']}) 장축 {prev['major_mm']} mm → 현재 {current_major_mm} mm, "
                       f"{change:+} mm. 변화 기준 {growth_flag_mm} mm 이내")
    return res


def ncr_lookup(part_number, history_dir=None):
    """제조 검사: 같은 부품번호의 과거 부적합보고서(NCR) 기록을 찾는다.

    기록 파일(data/history/ncr_history.json)은 {source, records: [{ncr_number, date, part_number, size_mm}]} 꼴이다.
    파일이 없으면 조회하지 못했다고 돌려준다. 값을 지어내지 않는다.
    """
    path = Path(history_dir or HISTORY_DIR) / "ncr_history.json"
    if not path.exists():
        return {"found": False, "grew": False, "location_id": part_number, "source": "이력 데이터 없음",
                "text": "과거 NCR 이력 데이터가 등록되지 않아 조회하지 못함"}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    records = doc["records"] if isinstance(doc, dict) else doc
    source = doc.get("source", "ncr_history.json") if isinstance(doc, dict) else "ncr_history.json"
    recs = sorted((r for r in records if r.get("part_number") == part_number), key=lambda r: r.get("date", ""))
    if not recs:
        return {"found": False, "grew": False, "location_id": part_number, "source": source,
                "text": "같은 부품번호의 과거 NCR 기록 없음"}
    last = recs[-1]
    size = f", 장축 {last['size_mm']} mm" if last.get("size_mm") is not None else ""
    text = f"같은 부품번호의 과거 NCR {len(recs)}건. 최근 {last.get('date', '-')} {last.get('ncr_number', '-')}{size}"
    kinds = Counter(DEFECT_KO.get(r["defect_type"], r["defect_type"]) for r in recs if r.get("defect_type"))
    causes = Counter(r["root_cause"] for r in recs if r.get("root_cause"))
    if last.get("disposition"):
        text += f", 처분 {last['disposition']}"
    if kinds:
        text += ". 결함 유형별: " + ", ".join(f"{k} {n}건" for k, n in kinds.most_common())
    if causes:
        # 과거 기록에 적힌 원인을 세기만 한다. 이번 지시의 원인을 추정하지 않는다.
        text += ". 과거 기록의 원인(참고): " + ", ".join(f"{k} {n}건" for k, n in causes.most_common(3))
    return {"found": True, "grew": False, "location_id": part_number, "source": source, "records": len(recs),
            "previous": last, "change_mm": None, "defect_types": dict(kinds), "root_causes": dict(causes),
            "text": text}
