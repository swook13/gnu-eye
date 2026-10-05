"""직접 올려 볼 수 있는 시연용 패키지 zip을 demo_files/에 만든다. 스캔은 모두 Cranfield WP2 변환본이다.

    python tools/make_demo_files.py
"""
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "projects" / "gnu-eye" / "data" / "real_adapted"
OUT = ROOT / "demo_files"
THICK = {"C16": 1.65, "C32": 3.8, "L": 1.65}  # Cranfield 설명서의 평균 경화 두께
P1, P2, ADL = "GNU-NTM-EX-51-01", "GNU-NTM-EX-51-02", "GNU-ADL-EX-001"


def add_card(folder, cid, case, zone, loc, proc, rev, title, break_csv=False, drop_meta=()):
    meta = json.loads((SRC / case / f"{case}_meta.json").read_text(encoding="utf-8"))
    new = {"synthetic": False, "real_public_data": True, "source_case": case,
           "equipment_id": meta["equipment_id"], "probe": meta["probe"], "reference_db": meta["reference_db"],
           "gate": meta["gate"],
           "grid": {k: meta["grid"][k] for k in ("pitch_mm", "width_mm", "height_mm", "rows", "cols")},
           "pitch_note": meta["pitch_note"], "thickness_mm": THICK[case.split("-")[1]],
           "scan_date": meta["scan_date"], "source_citation": meta["source_citation"]}
    for k in drop_meta:
        new.pop(k, None)
    text = (SRC / case / f"{case}_amplitude_db.csv").read_text(encoding="utf-8")
    if break_csv:  # 일부러 깨뜨린 파일: 셋째 줄의 값 몇 개를 글자로 바꾼다
        lines = text.split("\n")
        cells = lines[2].split(",")
        cells[5:8] = ["ERR", "", "n/a"]
        lines[2] = ",".join(cells)
        text = "\n".join(lines)
    (folder / f"{cid}_amplitude_db.csv").write_text(text, encoding="utf-8")
    (folder / f"{cid}_meta.json").write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    card = {"card_id": cid, "title": title, "zone_id": zone, "location_id": loc, "procedure_id": proc,
            "criteria_id": ADL, "criteria_rev": rev, "material": "CFRP",
            "scan_file": f"{cid}_amplitude_db.csv", "meta_file": f"{cid}_meta.json"}
    return {k: v for k, v in card.items() if v is not None}


def build(name, aircraft, check, specs):
    with tempfile.TemporaryDirectory() as t:
        folder = Path(t)
        cards = [add_card(folder, *s[:7], **(s[7] if len(s) > 7 else {})) for s in specs]
        (folder / "package.json").write_text(json.dumps({
            "package_id": name, "aircraft": aircraft, "aircraft_note": "가상 등록부호 (EXAMPLE_ONLY)",
            "check_type": check, "operator": "가상 운영사 (EXAMPLE_ONLY)",
            "data_note": "C-scan 격자는 Cranfield CompInnova WP2 공개 데이터(CC BY 4.0)의 변환본이다. 나머지는 가상이다.",
            "cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")
        z = OUT / f"{name}.zip"
        if z.exists():
            z.unlink()
        shutil.make_archive(str(OUT / name), "zip", folder)
        print(z.name, len(cards), "건")


def main():
    OUT.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "data" / "packages" / "HL-EX01_C-check_2026-10.zip", OUT / "1_basic_HL-EX01_C-check.zip")
    print("1_basic_HL-EX01_C-check.zip 6 건")
    build("2_other_scans_HL-EX02_A-check", "HL-EX02", "A-check (정기점검, 가상)", [
        ("CARD-11", "CRF-L-W3-1524", "Z2", "LOC-WNG-L-031", P1, "A", "좌측 날개 상면 외피 31 (라미네이트 W3)"),
        ("CARD-12", "CRF-L-W4-1446", "Z2", "LOC-WNG-L-032", P1, "A", "좌측 날개 상면 외피 32 (라미네이트 W4)"),
        ("CARD-13", "CRF-C32-20J-2221", "Z1", "LOC-FUS-R-040", P2, "B", "동체 우측 외피 패널 40 (3.2 mm 20 J)"),
        ("CARD-14", "CRF-C16-8JA-2011", "Z1", "LOC-FUS-R-041", P1, None, "동체 우측 외피 패널 41 (개정번호 미기재)"),
    ])
    build("3_input_errors_HL-EX03", "HL-EX03", "A-check (정기점검, 가상)", [
        ("CARD-21", "CRF-C16-8JB-2055", "Z1", "LOC-FUS-L-050", P1, "A", "정상 카드"),
        ("CARD-22", "CRF-C16-12J-2123", "Z1", "LOC-FUS-L-051", P1, "A", "CSV 일부 셀이 깨진 카드", {"break_csv": True}),
        ("CARD-23", "CRF-C32-8JB-2151", "Z2", "LOC-FUS-L-052", P2, "A", "메타데이터에 두께와 기준 dB가 없는 카드",
         {"drop_meta": ("thickness_mm", "reference_db")}),
    ])


if __name__ == "__main__":
    main()
