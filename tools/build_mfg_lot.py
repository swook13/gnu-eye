"""제조 검사 시연용 생산 로트 패키지(하이브리드)를 만든다.

    python tools/build_mfg_lot.py      →  demo_files/4_mfg_lot_GNU-LOT-2610-07_hybrid.zip
                                          data/packages/GNU-LOT-2610-07_hybrid/ (+ .zip, 내장 샘플)

제조 공정의 실제 C-scan을 확보하지 못해 두 종류를 섞는다. 시연을 위해 내장 샘플로도 넣는다(2026-10-06 팀 결정).
- 실측 2건: Cranfield WP2 충격 시편 변환본(정비 샘플과 같은 스캔). 제조·이송 중 공구 낙하 같은 취급 충격 손상으로
  보고, 결함 이름을 바꾸지 않는다. 부품번호와 S/N은 가상이다.
- 합성 5건: GNU-Eye v1의 generator.py(2026-10-04)에서 결함 모델을 옮겼다. 미세 격자(1/4)에서 타원 결함의
  감쇠를 계산하고(경계는 시그모이드, 공칭 경계에서 정확히 -6 dB), 4x4 블록 평균(빔 평균 효과)과 백색·상관 노이즈를
  더한다. 결함 크기, 감쇠량, 노이즈는 사람이 정한 가정값이다. 결함 종류는 NASA/TM-2020-220568 Vol. I의
  CFRP 결함 분류(기공, 층간 분리, 이물질)를 따랐고, 표면 신호 허상은 검사원 반려 시연용이다.
- 합성 부품에는 정답 파일(*_truth.json)을 같이 넣는다: 노이즈 없는 미세 격자에서 잰 -6 dB 장축과 공칭 장축(2a).
  측정기와 같은 6 dB 정의를 쓰므로 정확도 검증이 아니라 노이즈·격자 영향의 확인이다.

부품번호는 가상 과거 NCR 이력(data/history/ncr_history.json)의 GNU-P-1001~1005를 쓴다.
"""
import json
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import measure  # noqa: E402

REAL = ROOT / "data" / "packages" / "HL-EX01_C-check_2026-10"
OUT = ROOT / "demo_files" / "4_mfg_lot_GNU-LOT-2610-07_hybrid.zip"
LOT = "GNU-LOT-2610-07"
SAMPLE = ROOT / "data" / "packages" / f"{LOT}_hybrid"  # 내장 샘플 (검사 요청 화면의 목록)
PROC, SPEC = "GNU-UT-EX-MFG-01", "GNU-SPEC-UT-001"
WIDTH, HEIGHT, THICKNESS, PITCH, FINE = 300.0, 200.0, 4.0, 1.0, 4


@dataclass
class Defect:
    kind: str          # delamination | porosity | foreign_object | surface_signal_artifact
    cx: float
    cy: float
    a: float           # 반장축 mm (공칭 -6 dB 경계)
    b: float           # 반단축 mm
    theta_deg: float = 0.0
    loss_db: float = 16.0
    edge_w: float = 0.8
    harmonics: list = field(default_factory=list)
    texture: bool = False


def _texture(shape, rng, sigma_px):
    t = ndimage.gaussian_filter(rng.standard_normal(shape), sigma_px)
    return (t - t.mean()) / t.std()


def defect_field(X, Y, d, tex=None):
    ang = np.radians(d.theta_deg)
    xr = (X - d.cx) * np.cos(ang) + (Y - d.cy) * np.sin(ang)
    yr = -(X - d.cx) * np.sin(ang) + (Y - d.cy) * np.cos(ang)
    u, v = xr / d.a, yr / d.b
    rho = np.hypot(u, v) + 1e-9
    th = np.arctan2(v, u)
    m = np.ones_like(rho)
    for k, eps, phi in d.harmonics:
        m += eps * np.cos(k * th + phi)
    gnorm = np.hypot(xr / d.a ** 2, yr / d.b ** 2) / rho
    dist = (rho - m) / np.maximum(gnorm, 1e-6)
    d0 = -d.edge_w * np.log(d.loss_db / 6.0 - 1.0)
    s = 1.0 / (1.0 + np.exp(np.clip((dist - d0) / d.edge_w, -50, 50)))
    D = d.loss_db if tex is None else np.clip(d.loss_db * (1 + 0.22 * tex), 6.6, 14.0)
    return D * s


def synth_scan(defects, seed):
    """돌려주는 값: (입력용 거친 격자 dB, 노이즈 없는 미세 격자 감쇠, 미세 격자 간격)."""
    rng = np.random.default_rng(seed)
    fp = PITCH / FINE
    nx, ny = int(round(WIDTH / fp)), int(round(HEIGHT / fp))
    X, Y = np.meshgrid((np.arange(nx) + 0.5) * fp, (np.arange(ny) + 0.5) * fp)
    loss = np.zeros((ny, nx))
    for d in defects:
        tex = _texture(loss.shape, rng, 3.0 / fp) if d.texture else None
        loss = np.maximum(loss, defect_field(X, Y, d, tex))
    coarse = -loss.reshape(ny // FINE, FINE, nx // FINE, FINE).mean(axis=(1, 3))
    corr = ndimage.gaussian_filter(rng.standard_normal(coarse.shape), 2.0)
    noise = rng.standard_normal(coarse.shape) * 0.30 + corr / corr.std() * 0.30
    return coarse + noise, loss, fp


def _delam(cx, cy, a, b, theta=0.0):
    return Defect("delamination", cx, cy, a, b, theta, 16.0, 0.8, [(2, 0.04, 0.3), (3, 0.03, 1.1)])


def _foreign(cx, cy, r):
    return Defect("foreign_object", cx, cy, r, r, 0, 15.0, 0.7)


def _porosity(cx, cy, a, b, theta=0.0):
    return Defect("porosity", cx, cy, a, b, theta, 9.0, 3.0, [(2, 0.08, 1.0)], texture=True)


KO = {"delamination": "층간 분리", "porosity": "기공 군집", "foreign_object": "이물질",
      "surface_signal_artifact": "표면 신호 허상"}

# (부품 ID, 부품번호, 구역, 개정, 제목, 종류, 내용, 시드)
PARTS = [
    ("PART-01", "GNU-P-1001", "B", "A", "윙 리브 브래킷, 일반 구역", "synthetic", [], 2601),
    ("PART-02", "GNU-P-1002", "A", "A", "외피 패널 체결부, 중요 구역", "synthetic",
     [_delam(150, 100, 3.0, 2.1, 15)], 2602),
    ("PART-03", "GNU-P-1003", "A", "A", "외피 패널, 중요 구역 (이송 중 공구 낙하 의심)", "real", "CARD-04", None),
    ("PART-04", "GNU-P-1004", "A", None, "스트링거 플랜지, 중요 구역 (고객사양 개정번호 미기재)", "synthetic",
     [_delam(140, 80, 3.75, 2.6, 40)], 2604),
    ("PART-05", "GNU-P-1005", "B", "A", "액세스 도어, 일반 구역 (취급 충격 의심)", "real", "CARD-01", None),
    ("PART-06", "GNU-P-1001", "B", "A", "윙 리브 브래킷, 일반 구역 (스캔 시작부 표면 신호)", "synthetic",
     [Defect("surface_signal_artifact", 150, 3, 20.0, 1.0, 0, 10.0, 0.6), _foreign(170, 110, 2.5)], 2606),
    ("PART-07", "GNU-P-1002", "B", "A", "외피 패널 체결부, 일반 구역", "synthetic",
     [_porosity(160, 100, 9.0, 6.0, 30)], 2607),
]


def write_synthetic(folder, pid, defects, seed):
    amp, loss_fine, fp = synth_scan(defects, seed)
    np.savetxt(folder / f"{pid}_amplitude_db.csv", amp, delimiter=",", fmt="%.2f")
    ny, nx = amp.shape
    meta = {"synthetic": True, "equipment_id": "UT-SIM-01 (합성)", "probe": {"frequency_mhz": 5.0, "type": "simulated"},
            "reference_db": 0.0, "grid": {"pitch_mm": PITCH, "rows": ny, "cols": nx, "width_mm": WIDTH, "height_mm": HEIGHT},
            "thickness_mm": THICKNESS, "scan_date": "2026-10-05",
            "amplitude_unit": "dB relative to healthy-area reference",
            "source_citation": "합성 데이터 (GNU-Eye 결함 모델, 결함 크기·감쇠·노이즈는 가정값). 결함 분류는 "
                               "NASA/TM-2020-220568 Vol. I를 따름."}
    (folder / f"{pid}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    truth = measure.extract_indications(-loss_fine, fp, 6.0, 0.0, 3.0)
    doc = {"part": pid, "seed": seed, "note": "노이즈 없는 미세 격자(0.25 mm)에서 같은 6 dB 정의로 잰 값과 공칭 장축(2a)",
           "defects": [{**asdict(d), "kind_ko": KO[d.kind], "nominal_major_mm": round(2 * d.a, 2)} for d in defects],
           "truth_indications": [{k: i[k] for k in ("id", "major_mm", "minor_mm", "area_mm2", "centroid_x_mm",
                                                    "centroid_y_mm")} for i in truth]}
    (folder / f"{pid}_truth.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return " + ".join(f"{KO[d.kind]} 공칭 장축 {2 * d.a:g} mm" for d in defects) or "결함 없음 (노이즈만)"


def write_real(folder, pid, card):
    shutil.copyfile(REAL / f"{card}_amplitude_db.csv", folder / f"{pid}_amplitude_db.csv")
    meta = json.loads((REAL / f"{card}_meta.json").read_text(encoding="utf-8"))
    meta["mfg_note"] = (f"Cranfield 충격 시편 {meta.get('source_case', card)}의 실측 스캔을 가상 부품번호에 대응시킴. "
                        "제조·이송 중 취급 충격 손상 시나리오이며 결함 종류는 충격 손상 그대로다.")
    (folder / f"{pid}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"실측 충격 손상 ({meta.get('source_case', card)})"


def build(folder):
    folder = Path(folder)
    cards, notes = [], {}
    for pid, pn, zone, rev, title, kind, content, seed in PARTS:
        notes[pid] = (write_synthetic(folder, pid, content, seed) if kind == "synthetic"
                      else write_real(folder, pid, content))
        c = {"card_id": pid, "title": f"{title} [{'실측' if kind == 'real' else '합성'}]", "zone_id": zone,
             "part_number": pn, "serial_number": f"SN-2610-{pid[-2:]}", "procedure_id": PROC, "criteria_id": SPEC,
             "criteria_rev": rev, "material": "CFRP",
             "scan_file": f"{pid}_amplitude_db.csv", "meta_file": f"{pid}_meta.json"}
        cards.append({k: v for k, v in c.items() if v is not None})
    doc = {"domain": "manufacturing", "package_id": f"{LOT}_hybrid", "lot_id": LOT,
           "check_type": "출하 전 초음파 C-scan 검사 (가상)", "customer": "가상 고객 A (EXAMPLE_ONLY)",
           "created": "2026-10-05",
           "data_note": "실측 2건(PART-03, PART-05)은 Cranfield WP2 충격 시편 변환본(CC BY 4.0)을 가상 부품번호에 대응시킨 것이고, "
                        "합성 5건은 결함 크기·감쇠·노이즈를 가정한 합성 데이터다. 로트, 부품, 고객사양, 절차, 과거 NCR 이력은 모두 가상이다.",
           "cards": cards}
    (folder / "package.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return notes


def main():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / LOT
        folder.mkdir()
        notes = build(folder)
        OUT.parent.mkdir(exist_ok=True)
        for z in (OUT, SAMPLE.with_suffix(".zip")):
            if z.exists():
                z.unlink()
            shutil.make_archive(str(z.with_suffix("")), "zip", folder)
        # 내장 샘플 폴더: OneDrive가 폴더 삭제를 막으므로 폴더는 두고 파일만 바꾼다
        SAMPLE.mkdir(parents=True, exist_ok=True)
        for f in SAMPLE.iterdir():
            if f.is_file():
                f.unlink()
        for f in folder.iterdir():
            shutil.copyfile(f, SAMPLE / f.name)
    for pid, n in notes.items():
        print(pid, n)
    print("저장:", OUT.relative_to(ROOT), "/ 내장 샘플:", SAMPLE.relative_to(ROOT))


if __name__ == "__main__":
    main()
