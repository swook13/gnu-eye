"""C-scan 입출력·검증·6 dB drop 측정 (결정론적, LLM 없음).

진폭 규약: amplitude_db = 건전부 기준 레벨 대비 dB (건전부 ~0, 손상부 음수).
6 dB drop 지시 영역 = amplitude_db <= reference_db - 6.
이전 버전 cscan_tools.py에서 옮겼다. 바뀐 점: 가상 zone 마스크 제거(부위는 작업카드가 지정),
스캔 범위 가장자리 접촉 경고 추가.
"""
import json

import numpy as np
from scipy import ndimage

REQUIRED_META = ["grid", "reference_db", "thickness_mm", "probe", "equipment_id", "scan_date"]
REQUIRED_GRID = ["pitch_mm", "rows", "cols"]


class ScanFormatError(ValueError):
    pass


def load_meta(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_rows(csv_path):
    rows, bad = [], []
    with open(csv_path, encoding="utf-8-sig") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            vals = []
            for ci, c in enumerate(line.split(","), 1):
                try:
                    v = float(c)
                    if not np.isfinite(v):
                        raise ValueError
                    vals.append(v)
                except ValueError:
                    vals.append(np.nan)
                    bad.append({"line": ln, "col": ci, "value": c[:20]})
            rows.append(vals)
    return rows, bad


def validate_scan(csv_path, meta):
    """형식·크기·메타데이터 검증. 추정값으로 메우지 않고 문제 목록만 돌려준다."""
    problems, missing = [], []
    meta = meta or {}
    for k in REQUIRED_META:
        if meta.get(k) in (None, "", {}):
            missing.append(k)
    grid = meta.get("grid") or {}
    for k in REQUIRED_GRID:
        if grid and grid.get(k) in (None, ""):
            missing.append(f"grid.{k}")
    rows, bad = _read_rows(csv_path)
    if not rows:
        problems.append("CSV에 데이터 행이 없음")
    lens = {len(r) for r in rows}
    if len(lens) > 1:
        problems.append(f"행마다 열 수가 다름: {sorted(lens)[:5]}")
    if bad:
        problems.append(f"숫자가 아닌 셀 {len(bad)}개 (예: {bad[:3]})")
    if grid.get("rows") and grid.get("cols") and rows and len(lens) == 1:
        if (len(rows), next(iter(lens))) != (grid["rows"], grid["cols"]):
            problems.append(f"CSV 크기 {len(rows)}x{next(iter(lens))}가 메타데이터 grid "
                            f"{grid['rows']}x{grid['cols']}와 다름")
    return {"ok": not missing and not problems, "missing_fields": missing, "problems": problems}


def load_cscan(csv_path):
    rows, bad = _read_rows(csv_path)
    if not rows or bad or len({len(r) for r in rows}) != 1:
        raise ScanFormatError("CSV 손상: validate_scan을 먼저 실행할 것")
    return np.array(rows, dtype=float)


def extract_indications(amp_db, pitch_mm, drop_db=6.0, ref_db=0.0, min_area_mm2=3.0):
    """6 dB drop 임계 → 연결요소 → 크기·면적·위치.

    major/minor = 영역 2차 모멘트 타원의 장·단축 길이(mm).
    touches_scan_edge = 지시가 스캔 범위 가장자리 픽셀에 닿음. 실제 손상이 스캔 밖으로 이어질 수 있어
    크기가 작게 측정됐을 가능성이 있다.
    """
    ny, nx = amp_db.shape
    thr = ref_db - drop_db
    lab, _ = ndimage.label(amp_db <= thr, structure=np.ones((3, 3)))
    out = []
    for k, sl in enumerate(ndimage.find_objects(lab), 1):
        region = lab[sl] == k
        iy, ix = np.nonzero(region)
        iy = iy + sl[0].start
        ix = ix + sl[1].start
        area = len(ix) * pitch_mm ** 2
        if area < min_area_mm2:
            continue
        xs, ys = (ix + 0.5) * pitch_mm, (iy + 0.5) * pitch_mm
        cov = np.cov(np.vstack([xs, ys]), bias=True) if len(xs) > 1 else np.zeros((2, 2))
        cov = cov + np.eye(2) * pitch_mm ** 2 / 12.0
        ev, _ = np.linalg.eigh(cov)
        major, minor = 4 * np.sqrt(ev[1]), 4 * np.sqrt(ev[0])
        out.append({
            "centroid_x_mm": round(float(xs.mean()), 2),
            "centroid_y_mm": round(float(ys.mean()), 2),
            "major_mm": round(float(major), 2),
            "minor_mm": round(float(minor), 2),
            "area_mm2": round(float(area), 2),
            "peak_drop_db": round(float(-amp_db[iy, ix].min() + ref_db), 2),
            "bbox_mm": [round(float(xs.min() - pitch_mm / 2), 2), round(float(ys.min() - pitch_mm / 2), 2),
                        round(float(xs.max() + pitch_mm / 2), 2), round(float(ys.max() + pitch_mm / 2), 2)],
            "touches_scan_edge": bool(iy.min() == 0 or ix.min() == 0 or iy.max() == ny - 1 or ix.max() == nx - 1),
        })
    out.sort(key=lambda d: -d["area_mm2"])
    for i, d in enumerate(out, 1):
        d["id"] = f"IND-{i:02d}"
    return out


def bbox_gap_mm(a, b):
    """두 지시 경계 상자 사이의 최단 거리(mm). 겹치거나 맞닿으면 0."""
    ax0, ay0, ax1, ay1 = a["bbox_mm"]
    bx0, by0, bx1, by1 = b["bbox_mm"]
    dx = max(bx0 - ax1, ax0 - bx1, 0.0)
    dy = max(by0 - ay1, ay0 - by1, 0.0)
    return round(float(np.hypot(dx, dy)), 2)
