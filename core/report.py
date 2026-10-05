"""카드별 손상 평가 초안과 기체 단위 점검 보고서 초안 (결정론적).

숫자·표·요약 문장은 전부 여기서 코드로 만든다. LLM이 쓴 서술문은 verify_narrative()를 통과할 때만 쓴다.
"""
import html
import re
import time

from . import criteria as cr
from . import domain as dm

LIMITATIONS = dm.PROFILES[dm.MAINT]["limitations"]


def _numbers(text):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


BANNED = ("합격", "불합격", "안전합니다", "안전하", "문제없", "문제 없", "문제가 없", "이상 없", "이상없", "인증",
          "승인되었", "승인 완료")


def verify_narrative(text, facts_text, required_ids=(), card_groups=None, card_ids=None):
    """LLM 서술문 검증: 근거에 없는 숫자, 빠진 ID, 금지 표현, 카드와 조치의 잘못된 연결이 있으면 실패.

    card_groups: {"제작사": [카드...], "수리": [...], "확대": [...]}. 어떤 문장에 그 낱말이 있으면
    그 문장에 나온 카드 ID는 모두 해당 목록에 있어야 한다. 뜻까지 검증하지는 못한다(한계).
    card_ids: 패키지의 카드 ID 전체. 주지 않으면 CARD로 시작하는 ID만 카드로 본다.
    """
    allowed = _numbers(facts_text)
    bad = [n for n in _numbers(text) if not any(abs(n - a) < 0.011 for a in allowed)]
    missing = [i for i in required_ids if i not in text]
    banned = [w for w in BANNED if w in text]
    stray = re.findall(r"\([A-Za-z][A-Za-z -]{3,}\)", text)
    mislinked = []
    for sent in re.split(r"(?<=[.!?。])\s+|\n", text):
        ids = set(re.findall(r"[A-Z][A-Z0-9]*-\d+", sent))
        for word, allowed_cards in (card_groups or {}).items():
            wrong = sorted(i for i in ids if (i in card_ids if card_ids is not None else i.startswith("CARD"))
                           and i not in allowed_cards)
            if word in sent and wrong:
                mislinked.append({"word": word, "cards": wrong})
    ok = not bad and not missing and not banned and not stray and not mislinked and 10 <= len(text) <= 600
    return ok, {"unsupported_numbers": bad, "missing_ids": missing, "banned": banned, "stray_english": stray,
                "mislinked": mislinked}


def item_summary_sentence(r):
    """카드 한 건의 요약 문장 (코드가 만든 문장)."""
    cid = r["card_id"]
    if r["status"] == "HELD":
        return f"{cid}: 검사원 보류로 평가하지 않음 ({r['not_evaluated_reason']})."
    if r["disposition"] == cr.NOT_EVALUATED:
        return f"{cid}: 평가하지 않음. {r['not_evaluated_reason']}"
    ev = r["evaluation"]
    n = len(r["indications"])
    if n == 0:
        s = f"{cid}: 스캔에서 6 dB drop으로 잡힌 지시가 하나도 없음. 처분 초안 {ev['disposition_ko']}."
    else:
        big = r["indications"][0]
        s = (f"{cid}: 지시 {n}건, 최대 {big['id']} 장축 {big['major_mm']} mm. "
             f"{ev['rule_set']} {ev['zone_id']} 구역 기준 처분 초안 {ev['disposition_ko']}.")
    if ev["findings"]:
        s += " 근거: " + "; ".join(f"{f['rule_id']} {f['text']}" for f in ev["findings"]) + "."
    if r.get("excluded"):
        s += f" 검사원 제외 지시: {', '.join(r['excluded'])}."
    return s


def build_item_report(card, generated=None, domain=dm.MAINT):
    """card: agent.session.Card. 측정·판정 결과를 보고서용 dict로 정리한다."""
    info, meta = card.info, card.meta or {}
    r = {
        "domain": domain, "part_number": info.get("part_number"), "serial_number": info.get("serial_number"),
        "card_id": card.id, "title": info.get("title", ""), "zone_id": info.get("zone_id"),
        "location_id": info.get("location_id"), "procedure_id": card.procedure_id,
        "criteria_id": info.get("criteria_id"), "criteria_rev": card.rev, "material": info.get("material"),
        "thickness_mm": meta.get("thickness_mm"), "scan_date": meta.get("scan_date"),
        "equipment_id": meta.get("equipment_id"),
        "data_source": ("공개 실측 데이터 (변환본)" if meta.get("real_public_data")
                        else "합성 데이터" if meta.get("synthetic") else "업로드 데이터 (출처 미기재)"),
        "source_citation": meta.get("source_citation", ""),
        "grid": meta.get("grid"), "procedure_check": card.proc_check,
        "indications": [], "excluded": sorted(card.excluded), "evaluation": None, "history": card.history,
        "disposition": cr.NOT_EVALUATED, "disposition_ko": dm.profile(domain)["ko"][cr.NOT_EVALUATED],
        "not_evaluated_reason": card.blocked_reason or "", "status": "HELD" if card.held else "DRAFT",
        "signoffs": list(card.signoffs), "generated": generated or time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if card.eval:
        r["indications"] = [i for i in card.indications if i["id"] not in card.excluded]
        r["all_indications"] = card.indications
        r["evaluation"] = card.eval
        r["disposition"] = card.eval["disposition"]
        r["disposition_ko"] = card.eval["disposition_ko"]
        r["not_evaluated_reason"] = ""
    r["summary"] = item_summary_sentence(r)
    r["narrative"], r["narrative_source"] = r["summary"], "template"
    return r


def build_package_report(package, items, signoffs, mode_info, stale=False):
    counts = {k: 0 for k in (cr.ALLOW, cr.REPAIR, cr.EXCEED, cr.NOT_EVALUATED)}
    for r in items:
        counts[r["disposition"]] += 1
    approved = {r["card_id"] for r in items if r["signoffs"] and r["signoffs"][-1]["decision"] == "approve"}
    all_signed = len(approved) == len(items) and not stale
    actions = {
        "oem_inquiry": [r["card_id"] for r in items if r["disposition"] == cr.EXCEED],
        "repair": [r["card_id"] for r in items if r["disposition"] == cr.REPAIR],
        "not_evaluated": [r["card_id"] for r in items if r["disposition"] == cr.NOT_EVALUATED],
        "recheck": [r["card_id"] for r in items if r["evaluation"] and r["evaluation"]["warnings"]],
        "growth": [r["card_id"] for r in items if r["history"] and r["history"].get("grew")],
    }
    n = len(items)
    domain = package.get("domain", dm.MAINT)
    prof = dm.profile(domain)
    if domain == dm.MFG:
        # 제조: 같은 부품번호의 과거 NCR이 있는 부품, 부적합 부품의 NCR 초안 번호
        actions["growth"] = [r["card_id"] for r in items if r["history"] and r["history"].get("found")]
        for r in items:
            r["ncr_draft_id"] = (f"NCR-DRAFT-{package['aircraft']}-{r['card_id']}"
                                 if r["disposition"] == cr.EXCEED else None)
            r["ncr_draft"] = ncr_fields(r, package, time.strftime("%Y-%m-%d")) if r["ncr_draft_id"] else None
        ko = prof["ko"]
        summary = (f"생산 로트 {package['aircraft']} {package['check_type']} 부품 {n}건 처리 결과: "
                   f"{ko[cr.ALLOW]} {counts[cr.ALLOW]}건, {ko[cr.REPAIR]} {counts[cr.REPAIR]}건, "
                   f"{ko[cr.EXCEED]} {counts[cr.EXCEED]}건, 미평가 {counts[cr.NOT_EVALUATED]}건.")
        if actions["growth"]:
            summary += f" 같은 부품번호의 과거 NCR 있음: {', '.join(actions['growth'])}."
    else:
        summary = (f"기체 {package['aircraft']} {package['check_type']} 작업카드 {n}건 처리 결과: "
                   f"허용(기록) {counts[cr.ALLOW]}건, 수리 가능 {counts[cr.REPAIR]}건, "
                   f"한도 초과(제작사 문의) {counts[cr.EXCEED]}건, 미평가 {counts[cr.NOT_EVALUATED]}건.")
        if actions["growth"]:
            summary += f" 이전 기록 대비 손상 확대 의심: {', '.join(actions['growth'])}."
    if actions["recheck"]:
        summary += f" 재검사 권고: {', '.join(actions['recheck'])}."
    summary += (f" 검사원 승인 {len(approved)}/{n}건." if not all_signed
                else f" 전 {prof['unit']} 검사원 승인 완료({n}건).")
    return {
        "report_id": f"{prof['report_prefix']}-{package['aircraft']}-{time.strftime('%Y%m%d-%H%M%S')}",
        "domain": domain,
        "package_id": package.get("package_id"), "aircraft": package["aircraft"],
        "aircraft_note": package.get("aircraft_note", ""), "check_type": package["check_type"],
        "operator": package.get("operator") or package.get("customer", ""), "data_note": package.get("data_note", ""),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "counts": counts, "actions": actions,
        "summary": summary, "opinion": summary, "opinion_source": "template",
        "items": items, "signoffs": signoffs, "approved_cards": sorted(approved),
        "status": "APPROVED" if all_signed else "DRAFT",
        "status_ko": "검사원 승인 완료" if all_signed else "초안 - 검사원 승인 전",
        "mode": mode_info, "limitations": prof["limitations"],
    }


# ---------------------------------------------------------------- HTML
def _e(x):
    return html.escape("" if x is None else str(x))


DISP_COLOR = {cr.ALLOW: "#0B6E4F", cr.REPAIR: "#B26A00", cr.EXCEED: "#B3261E", cr.NOT_EVALUATED: "#5F6368"}

CSS = """
body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;color:#1b1c1e;margin:0;background:#f3f4f6}
.sheet{max-width:900px;margin:16px auto;background:#fff;padding:36px 44px;box-shadow:0 1px 6px rgba(0,0,0,.15)}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;border-bottom:2px solid #12343b;padding-bottom:4px}
h3{font-size:14px;margin:18px 0 6px}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}
th,td{border:1px solid #c9ced6;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#eef1f4;font-weight:600}
.banner{background:#fff4d6;border:1px solid #e0b84a;padding:8px 10px;font-size:12.5px;margin:10px 0}
.tag{display:inline-block;padding:2px 8px;border-radius:10px;color:#fff;font-size:12px;font-weight:600}
.muted{color:#5f6368;font-size:12px}.item{page-break-inside:avoid;margin-top:14px}
img.scan{max-width:100%;border:1px solid #c9ced6;margin:6px 0}
.sign{display:flex;gap:16px;margin-top:10px}.sign div{flex:1;border:1px solid #c9ced6;padding:8px;min-height:54px;font-size:12.5px}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none;padding:12mm}.noprint{display:none}}
"""


def limits_text(ev):
    """적용 한도를 한 줄로 쓴다 (보고서, 챗봇 공통)."""
    lim = ev["limits"]
    if "max_dimension_mm" in lim:
        t = f"최대 치수 {lim['max_dimension_mm']} mm"
        if lim.get("min_gap_mm"):
            t += f", 최소 간격 {lim['min_gap_mm']} mm"
        if lim.get("max_area_pct") is not None:
            t += f", 누적 면적 {lim['max_area_pct']}%"
            if ev.get("area_pct") is not None:
                t += f" (측정 {ev['area_pct']}%)"
        return t
    return (f"허용 {lim['allowable_mm']} mm, 수리 가능 {lim['repairable_mm']} mm, "
            f"최소 간격 {lim['min_gap_mm']} mm")


def _head_table(rep, mfg):
    a, b, c = ("생산 로트", "검사", "고객") if mfg else ("기체", "점검", "운영사")
    return ("<table><tr><th>{}</th><td>{}</td><th>{}</th><td>{}</td></tr>"
            "<tr><th>{}</th><td>{}</td><th>패키지</th><td>{}</td></tr>"
            "<tr><th>실행 방식</th><td colspan='3'>{}</td></tr></table>".format(
                a, _e(f"{rep['aircraft']} {rep['aircraft_note']}"), b, _e(rep["check_type"]), c, _e(rep["operator"]),
                _e(rep["package_id"]), _e(rep["mode"])))


NCR_AUTO, NCR_INSPECTOR, NCR_MRB = "system", "inspector", "mrb"


def ncr_fields(r, package, issued):
    """제조: 부적합 부품의 NCR 초안 12칸. 값은 모두 패키지·메타데이터·측정·대조·이력 결과에서 그대로 가져온다.

    filled_by: system(시스템이 기록에서 옮겨 적음) / inspector(검사원 승인 기록에서만 채움) / mrb(사람이 정함, 비워 둠).
    원본에 값이 없으면 '미기재'로 두고 채운 칸으로 세지 않는다.
    """
    ev = r["evaluation"]
    act = {i["id"]: i for i in r["indications"]}
    involved = [act[k] for f in ev["findings"] for k in str(f["indication"]).split("/") if k in act]
    involved = list({i["id"]: i for i in (involved or r["indications"])}.values())
    so = next((s for s in reversed(r["signoffs"]) if s["decision"] == "approve"), None)
    h = r.get("history") or {}

    def join(*xs):
        return " / ".join(str(x) for x in xs if x not in (None, "")) or None

    rows = [
        ("NCR 번호 (초안)", r["ncr_draft_id"], NCR_AUTO),
        ("발행일 (초안 작성일)", issued, NCR_AUTO),
        ("생산 로트 / 고객", join(package.get("lot_id") or package.get("aircraft"), package.get("customer")), NCR_AUTO),
        ("부품번호 / S/N", join(r.get("part_number"), r.get("serial_number")), NCR_AUTO),
        ("적용 고객사양 / 구역", join(ev["rule_set"], f"{ev['zone_id']} {ev['zone_name']}"), NCR_AUTO),
        ("검사 절차 / 장비", join(r.get("procedure_id"), r.get("equipment_id")), NCR_AUTO),
        ("스캔 일자 / 데이터 출처", join(r.get("scan_date"), r.get("data_source")), NCR_AUTO),
        ("부적합 내용 (규칙, 측정값, 한도)",
         "; ".join(f"{f['rule_id']} {f['indication']}: {f['text']}" for f in ev["findings"]) or None, NCR_AUTO),
        ("지시 위치·크기", "; ".join(f"{i['id']} 중심 ({i['centroid_x_mm']}, {i['centroid_y_mm']}) mm, 장축 {i['major_mm']} mm, "
                                f"면적 {i['area_mm2']} mm²" for i in involved) or None, NCR_AUTO),
        ("같은 부품번호의 과거 NCR", h.get("text"), NCR_AUTO),
        ("검사원 확인", f"{so['user']} 승인 {so['ts']}" if so else None, NCR_INSPECTOR),
        ("처분", None, NCR_MRB),
    ]
    fields = [{"label": k, "value": v, "filled_by": by} for k, v, by in rows]
    return {"id": r["ncr_draft_id"], "fields": fields, "total": len(fields),
            "system_filled": sum(f["value"] is not None for f in fields if f["filled_by"] == NCR_AUTO),
            "system_fields": sum(f["filled_by"] == NCR_AUTO for f in fields),
            "inspector_filled": bool(so)}


def _ncr_block(r):
    """제조: 부적합 부품의 부적합보고서(NCR) 초안 12칸."""
    n = r.get("ncr_draft")
    empty = {NCR_INSPECTOR: "검사원 승인 전 (승인 기록에서만 채움)",
             NCR_MRB: "미정 - 검사원 확인 뒤 자재심의(MRB)에서 결정. 이 시스템은 처분을 정하지 않음",
             NCR_AUTO: "미기재 (원본 자료에 없음)"}
    who = {NCR_AUTO: "시스템", NCR_INSPECTOR: "검사원", NCR_MRB: "MRB"}
    rows = "".join(f"<tr><th style='width:28%'>{j}. {_e(f['label'])}</th><td>{_e(f['value'] or empty[f['filled_by']])}</td>"
                   f"<td class='muted' style='width:9%'>{who[f['filled_by']]}</td></tr>"
                   for j, f in enumerate(n["fields"], 1))
    return ("<table><tr><th colspan='3'>부적합보고서(NCR) 초안 · {} · 시스템 기입 {}/{}칸, 검사원 {}칸, MRB 1칸</th></tr>{}"
            "</table>").format(_e(n["id"]), n["system_filled"], n["system_fields"],
                               "1/1" if n["inspector_filled"] else "0/1", rows)


def _tag(disp, ko):
    return f'<span class="tag" style="background:{DISP_COLOR[disp]}">{_e(ko)}</span>'


def render_html(rep, heatmap_url=None):
    """heatmap_url: card_id -> 이미지 URL(또는 data URI)을 돌려주는 함수."""
    o = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><link rel='icon' href='data:,'><title>{_e(rep['report_id'])}</title>"
         f"<style>{CSS}</style></head><body><div class='sheet'>"]
    mfg = rep.get("domain") == dm.MFG
    prof = dm.profile(rep.get("domain"))
    o.append(f"<h1>{_e(prof['report_title'])} ({_e(rep['status_ko'])})</h1>")
    o.append(f"<div class='muted'>문서번호 {_e(rep['report_id'])} · 생성 {_e(rep['generated'])}</div>")
    o.append("<div class='banner'>예시 기준(EXAMPLE_ONLY)으로 만든 문서입니다. 처분은 초안이며 "
             "최종 판단과 서명은 자격 검사원이 합니다.</div>")
    o.append(_head_table(rep, mfg))
    o.append(f"<h2>1. 종합</h2><p>{_e(rep['summary'])}</p>")
    if rep["opinion_source"] == "llm":
        o.append(f"<p><b>에이전트 종합 의견</b> <span class='muted'>(LLM 작성, 숫자·ID 검증 통과)</span><br>{_e(rep['opinion'])}</p>")
    o.append("<table><tr><th>{}</th><th>{}</th><th>절차</th><th>{}</th><th>지시</th><th>최대 장축(mm)</th>"
             "<th>{}</th><th>처분 초안</th><th>검사원</th></tr>".format(
                 *(("부품", "부품번호 / S/N", "고객사양", "과거 NCR") if mfg else ("카드", "부위", "기준", "이전 기록 대비"))))
    for r in rep["items"]:
        big = r["indications"][0]["major_mm"] if r["indications"] else "-"
        h = r["history"] or {}
        if mfg:
            hist = "-" if not h else (f"{h['records']}건" if h.get("found") else "없음")
        else:
            hist = "-" if not h else ("기록 없음" if not h.get("found") else
                                      ("측정 없음" if h.get("change_mm") is None else f"{h['change_mm']:+} mm" + (" (확대 의심)" if h.get("grew") else "")))
        so = r["signoffs"][-1] if r["signoffs"] else None
        sign = f"{so['user']} {'승인' if so['decision'] == 'approve' else '반려'}" if so else "대기"
        o.append("<tr><td>{}</td><td>{}<br><span class='muted'>{}</span></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
                 "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
                     _e(r["card_id"]), _e(r["location_id"]),
                     _e(f"S/N {r.get('serial_number') or '-'} · 구역 {r['zone_id']}" if mfg else r["zone_id"]),
                     _e(r["procedure_id"]),
                     _e(f"{r['criteria_id']} Rev {r['criteria_rev'] or '미지정'}"),
                     len(r["indications"]) if r["evaluation"] else "-", big, _e(hist),
                     _tag(r["disposition"], r["disposition_ko"]), _e(sign)))
    o.append("</table>")
    a = rep["actions"]
    o.append("<h2>2. 후속 조치 목록</h2><table>")
    for label, key in prof["actions"]:
        o.append(f"<tr><th style='width:30%'>{label}</th><td>{_e(', '.join(a[key]) or '없음')}</td></tr>")
    o.append("</table><h2>3. {}</h2>".format("부품별 평가와 NCR 초안" if mfg else "작업카드별 손상 평가"))
    for r in rep["items"]:
        o.append(f"<div class='item'><h3>{_e(r['card_id'])} · {_e(r['title'])} {_tag(r['disposition'], r['disposition_ko'])}</h3>")
        o.append(f"<p>{_e(r['narrative'])}</p>")
        pc = r["procedure_check"]
        o.append("<table><tr><th>데이터</th><td>{}</td><th>스캔 일자</th><td>{}</td></tr>"
                 "<tr><th>재질 / 두께</th><td>{} / {} mm</td><th>절차 적합성</th><td>{}</td></tr></table>".format(
                     _e(r["data_source"]), _e(r["scan_date"]), _e(r["material"]), _e(r["thickness_mm"]),
                     _e("확인 전" if not pc else ("적합 " + f"({pc['range_mm'][0]}~{pc['range_mm'][1]} mm)" if pc["ok"] else "부적합: " + "; ".join(pc["reasons"])))))
        if r["evaluation"]:
            if heatmap_url:
                o.append(f"<img class='scan' src='{_e(heatmap_url(r['card_id']))}' alt='C-scan {_e(r['card_id'])}'>")
            ev = r["evaluation"]
            o.append(f"<div class='muted'>적용 한도 ({_e(ev['rule_set'])}, {_e(ev['zone_id'])} {_e(ev['zone_name'])}): "
                     f"{_e(limits_text(ev))}</div>")
            if r["indications"]:
                o.append("<table><tr><th>지시</th><th>중심 (x, y) mm</th><th>장축 mm</th><th>단축 mm</th><th>면적 mm²</th><th>최대 감쇠 dB</th><th>스캔 가장자리</th></tr>")
                for i in r["indications"]:
                    o.append(f"<tr><td>{i['id']}</td><td>({i['centroid_x_mm']}, {i['centroid_y_mm']})</td><td>{i['major_mm']}</td>"
                             f"<td>{i['minor_mm']}</td><td>{i['area_mm2']}</td><td>{i['peak_drop_db']}</td>"
                             f"<td>{'닿음' if i['touches_scan_edge'] else '-'}</td></tr>")
                o.append("</table>")
            for w in ev["warnings"]:
                o.append(f"<div class='muted'>주의: {_e(w['text'])}</div>")
            if r["excluded"]:
                o.append(f"<div class='muted'>검사원이 제외한 지시: {_e(', '.join(r['excluded']))}</div>")
        if r["history"]:
            o.append(f"<div class='muted'>{_e(prof['history_label'])}: {_e(r['history']['text'])}</div>")
        if r.get("ncr_draft_id"):
            o.append(_ncr_block(r))
        for so in r["signoffs"]:
            o.append(f"<div class='muted'>검사원 기록 {_e(so['ts'])}: {_e(so['user'])} "
                     f"{'승인' if so['decision'] == 'approve' else '반려'}{(' - ' + _e(so['reason'])) if so.get('reason') else ''}</div>")
        if r["source_citation"]:
            o.append(f"<div class='muted'>출처: {_e(r['source_citation'])}</div>")
        o.append("</div>")
    o.append("<h2>4. 한계</h2><ul>" + "".join(f"<li>{_e(x)}</li>" for x in rep["limitations"]) + "</ul>")
    o.append("<h2>5. 서명</h2><div class='sign'><div><b>NDT 검사원</b><br>" +
             (_e(", ".join(sorted({s['user'] for s in rep['signoffs'] if s['decision'] == 'approve'}))) + " (카드별 승인 기록 기준)"
              if rep["status"] == "APPROVED" else "승인 전") +
             "</div><div><b>품질 책임자</b><br>(자필 서명)</div></div>")
    o.append("</div></body></html>")
    return "".join(o)
