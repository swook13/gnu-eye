"""샘플 패키지 생성: Cranfield WP2 변환본(이전 버전이 만든 것)을 가상의 작업카드에 배치한다.

실데이터: C-scan 격자(CSV)와 장비·격자 메타데이터.
가상(EXAMPLE_ONLY): 기체, 점검, 작업카드, 부위, 절차, 기준, 이전 점검 기록.
카드 배치는 측정값을 본 뒤 정했다. 가상 한도(rules/)는 시연에서 세 처분이 모두 나오도록 정한 값이다.

    python tools/build_sample_package.py
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "projects" / "gnu-eye" / "data" / "real_adapted"
AIRCRAFT = "HL-EX01"
PKG = ROOT / "data" / "packages" / f"{AIRCRAFT}_C-check_2026-10"

# 두께는 Cranfield 설명서(Information_On_Impact_Damages_Specimen_List.docx)의 평균 경화 두께다.
# 파일 이름의 1.6 / 3.2 mm 표기와 다르다(얇은 쿠폰 1.65 mm, 두꺼운 쿠폰 3.8 mm).
THICK = {"C16": 1.65, "C32": 3.8}
P1, P2, ADL = "GNU-NTM-EX-51-01", "GNU-NTM-EX-51-02", "GNU-ADL-EX-001"

CARDS = [
    # card, cranfield case, zone, location, procedure, rev, title
    ("CARD-01", "CRF-C16-2P5J-2008", "Z1", "LOC-FUS-L-012", P1, "A", "동체 좌측 외피 패널 12, 지정 SDI 작업"),
    ("CARD-02", "CRF-C16-12J-2042", "Z1", "LOC-FUS-L-027", P1, "A", "동체 좌측 외피 패널 27, 공구 낙하 의심 부위 범위 평가"),
    ("CARD-03", "CRF-C32-12J-2216", "Z1", "LOC-WNG-R-004", P2, "A", "우측 날개 하면 외피 4, 육안 점검 발견 손상 범위 평가"),
    ("CARD-04", "CRF-C32-8JA-2139", "Z2", "LOC-WNG-R-019", P2, "A", "우측 날개 하면 외피 19, 이전 점검 기록 손상 추적"),
    ("CARD-05", "CRF-C16-4J-2024", "Z1", "LOC-FUS-R-008", P1, None, "동체 우측 외피 패널 8, 지정 SDI 작업 (개정번호 미기재)"),
    ("CARD-06", "CRF-C32-8JB-2151", "Z2", "LOC-EMP-L-003", P1, "A", "수평 꼬리날개 좌측 외피 3, 지정 SDI 작업"),
]

HISTORY = [
    {"location_id": "LOC-FUS-L-012", "date": "2024-10-11", "check": "C-check", "major_mm": 9.0,
     "disposition": "ALLOW", "note": "가상 기록"},
    {"location_id": "LOC-WNG-R-019", "date": "2024-10-12", "check": "C-check", "major_mm": 16.0,
     "disposition": "REPAIR", "note": "가상 기록. 수리 보류 후 추적 관찰로 가정"},
]


def main():
    PKG.mkdir(parents=True, exist_ok=True)
    for f in PKG.iterdir():
        if f.is_file():
            f.unlink()
    cards = []
    for cid, case, zone, loc, proc, rev, title in CARDS:
        src = SRC / case
        meta = json.loads((src / f"{case}_meta.json").read_text(encoding="utf-8"))
        new_meta = {
            "synthetic": False, "real_public_data": True, "source_case": case,
            "equipment_id": meta["equipment_id"], "probe": meta["probe"],
            "reference_db": meta["reference_db"], "reference_note": meta["reference_standard_id"],
            "gate": meta["gate"],
            "grid": {k: meta["grid"][k] for k in ("pitch_mm", "width_mm", "height_mm", "rows", "cols")},
            "pitch_note": meta["pitch_note"], "amplitude_unit": meta["amplitude_unit"],
            "thickness_mm": THICK[case.split("-")[1]],
            "thickness_note": "Cranfield 설명서의 평균 경화 두께 (측정 계산에는 쓰지 않고 절차 적합성 확인에만 씀)",
            "scan_date": meta["scan_date"], "source_citation": meta["source_citation"],
        }
        shutil.copyfile(src / f"{case}_amplitude_db.csv", PKG / f"{cid}_amplitude_db.csv")
        (PKG / f"{cid}_meta.json").write_text(json.dumps(new_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        card = {"card_id": cid, "title": title, "zone_id": zone, "location_id": loc, "procedure_id": proc,
                "criteria_id": ADL, "criteria_rev": rev, "material": "CFRP",
                "scan_file": f"{cid}_amplitude_db.csv", "meta_file": f"{cid}_meta.json"}
        cards.append({k: v for k, v in card.items() if v is not None})
    pkg = {
        "package_id": PKG.name, "aircraft": AIRCRAFT, "aircraft_note": "가상 등록부호 (EXAMPLE_ONLY)",
        "check_type": "C-check (정기점검, 가상)", "operator": "가상 운영사 (EXAMPLE_ONLY)",
        "created": "2026-10-04",
        "data_note": "C-scan 격자는 Cranfield CompInnova WP2 공개 데이터(CC BY 4.0)의 변환본이다. "
                     "기체, 작업카드, 부위, 절차, 기준, 이전 점검 기록은 모두 가상이다.",
        "cards": cards,
    }
    (PKG / "package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    hist = {"aircraft": AIRCRAFT, "source": "EXAMPLE_ONLY",
            "disclaimer": "가상 이전 점검 기록. Cranfield 데이터에는 같은 시편을 시간 간격을 두고 다시 찍은 스캔이 없다.",
            "records": HISTORY}
    hdir = ROOT / "data" / "history"
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / f"{AIRCRAFT}.json").write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    zp = PKG.parent / f"{PKG.name}.zip"
    if zp.exists():
        zp.unlink()
    shutil.make_archive(str(PKG.parent / PKG.name), "zip", PKG)
    print("패키지:", PKG.name, "카드", len(cards), "건, zip:", zp.name)


if __name__ == "__main__":
    main()
