"""작업 패키지(작업카드 묶음) 읽기. 폴더 또는 zip에서 package.json과 카드별 CSV·메타를 찾는다."""
import json
import re
import zipfile
from pathlib import Path

from . import domain as dm

CARD_FIELDS = ["zone_id", "location_id", "procedure_id", "criteria_id", "criteria_rev", "material"]
CARD_FIELDS_MFG = ["zone_id", "part_number", "procedure_id", "criteria_id", "criteria_rev", "material"]
FIELD_KO = {"zone_id": "부위 구역", "location_id": "부위 식별자", "procedure_id": "적용 절차",
            "criteria_id": "허용 손상 기준", "criteria_rev": "기준 개정번호", "material": "재질",
            "thickness_mm": "두께", "scan_file": "스캔 파일", "meta_file": "스캔 메타데이터",
            "part_number": "부품번호"}
FIELD_KO_MFG = {**FIELD_KO, "zone_id": "검사 구역", "criteria_id": "고객사양", "criteria_rev": "고객사양 개정번호"}
MAX_UNZIPPED = 200 * 1024 * 1024


class PackageError(Exception):
    pass


def safe_name(name):
    """업로드 파일 이름에서 폴더 부분을 버리고 허용 문자만 통과시킨다."""
    name = Path(str(name).replace("\\", "/")).name
    if not re.fullmatch(r"[\w.\-가-힣 ()]+", name) or name.startswith("."):
        raise PackageError(f"허용하지 않는 파일 이름: {name}")
    return name


def safe_extract(zip_path, dest):
    """zip을 dest에 푼다. 폴더 구조는 버리고, 지나치게 큰 묶음은 거부한다."""
    dest = Path(dest)
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise PackageError("zip 파일을 열 수 없음")
    with z:
        total = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            total += info.file_size
            if total > MAX_UNZIPPED:
                raise PackageError("압축을 푼 크기가 200 MB를 넘음. 변환된 격자 CSV만 넣을 것")
            (dest / safe_name(info.filename)).write_bytes(z.read(info))


def load_package(folder):
    """package.json을 읽고 카드별로 빠진 정보를 표시한다. 값을 추정해 채우지 않는다."""
    folder = Path(folder)
    pj = folder / "package.json"
    if not pj.exists():
        raise PackageError("package.json이 없음. 기체, 점검 종류, 작업카드 목록이 든 package.json이 필요함")
    try:
        doc = json.loads(pj.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise PackageError(f"package.json 형식 오류: {e}")
    if not isinstance(doc, dict):
        raise PackageError("package.json 최상위는 객체여야 함")
    domain = doc.get("domain") or dm.MAINT
    if domain not in dm.PROFILES:
        raise PackageError(f"package.json의 domain 값 오류: {domain!r} (maintenance 또는 manufacturing)")
    doc["domain"] = domain
    if domain == dm.MFG:
        # 제조 검사 묶음은 생산 로트 단위다. 내부에서는 로트 번호를 기체 자리(aircraft)에 둔다.
        if not doc.get("lot_id"):
            raise PackageError("package.json에 lot_id(생산 로트 번호)가 없음")
        doc["aircraft"] = str(doc["lot_id"])
    for k in ("aircraft", "check_type"):
        if not doc.get(k):
            raise PackageError(f"package.json에 {k}가 없음")
    cards = doc.get("cards")
    if not isinstance(cards, list) or not cards:
        raise PackageError("package.json에 cards 목록이 없음")
    seen = set()
    for c in cards:
        if not isinstance(c, dict):
            raise PackageError("cards의 각 항목은 객체여야 함")
        cid = str(c.get("card_id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_]{0,30}", cid):
            raise PackageError(f"card_id 형식 오류: {c.get('card_id')!r} (영문 대문자, 숫자, -, _ 만 허용)")
        if cid in seen:
            raise PackageError(f"card_id 중복: {cid}")
        seen.add(cid)
        c["card_id"] = cid
        missing = [k for k in (CARD_FIELDS_MFG if domain == dm.MFG else CARD_FIELDS) if c.get(k) in (None, "")]
        if domain == dm.MFG:
            c["location_id"] = c.get("part_number")
        for k in ("scan_file", "meta_file"):
            if not c.get(k) or not (folder / Path(str(c[k])).name).is_file():
                missing.append(k)
            else:
                c[k] = Path(str(c[k])).name
        c["missing"] = missing
    doc.setdefault("package_id", folder.name)
    doc["folder"] = str(folder)
    return doc


def field_ko(domain):
    return FIELD_KO_MFG if domain == dm.MFG else FIELD_KO
