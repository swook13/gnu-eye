"""브라우저 끝까지 시험: 실제 Chrome으로 업로드 → 에이전트 → 되묻기 답 → 결과 → 반려·재평가 → 전체 승인 → .eml 저장 → 이력.
정비 점검 모드(내장 샘플 zip)를 먼저 돌리고, 이어서 제조 검사 모드(시험 안에서 만든 합성 로트 zip)를 돌린다.

서버가 떠 있어야 한다 (기본 http://localhost:8000, 환경변수 GNUEYE_BASE로 바꿀 수 있다).

    python tests/e2e_browser.py            # 고정 순서 모드
    python tests/e2e_browser.py llm        # LLM 모드 (느림)

화면 캡처는 outputs/shots/e2e_*.png 에 남는다. 통과 여부는 마지막 줄(E2E OK / 예외)로 본다.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BASE = os.environ.get("GNUEYE_BASE", "http://localhost:8000").rstrip("/")
MODE = "llm" if len(sys.argv) > 1 and sys.argv[1] == "llm" else "fixed"
ZIP = ROOT / "data" / "packages" / "HL-EX01_C-check_2026-10.zip"
SHOTS = ROOT / "outputs" / "shots"
T = 600_000 if MODE == "llm" else 30_000


def make_lot_zip(tmp):
    """제조 실데이터가 없어 합성 로트 패키지를 만든다 (tests/test_mfg.py와 같은 부품 4건)."""
    from tests.test_mfg import LOT, make_lot
    folder = Path(tmp) / "LOT-E2E"
    folder.mkdir()
    make_lot(folder, LOT, lot="LOT-E2E")
    return shutil.make_archive(str(Path(tmp) / "LOT-E2E_synthetic"), "zip", folder)


def mfg_flow(page, shot, lot_zip, errors):
    # 홈: 제조 검사 모드로 전환. 예시 화면 표시는 없어야 한다
    page.goto(f"{BASE}/mfg/index.html")
    page.wait_for_url("**/index.html?mode=mfg")
    expect(page.locator("#app")).to_contain_text("제조 검사 모드 · 생산 로트")
    expect(page.locator("#mode-toggle a[aria-current]")).to_have_text("제조 검사")
    assert "예시 화면" not in page.locator("body").inner_text()
    assert page.evaluate("document.body.classList.contains('mode-mfg')")  # 제조 테마 (2026-10-06 흰 바탕 리퀴드 글래스)
    shot("m0_home")

    # ① 검사 요청: 내장 샘플은 하이브리드 시연 로트뿐(정비 샘플은 보이지 않음) → 업로드. 정비 패키지를 올리면 거부한다
    page.goto(f"{BASE}/request.html")
    expect(page.locator("#sample-list")).to_contain_text("GNU-LOT-2610-07_hybrid", timeout=T)
    assert "HL-EX01" not in page.locator("#sample-list").inner_text()
    page.click("#tab-upload")
    expect(page.locator("#pane-upload")).to_be_visible()
    page.check("input[name=mode][value=fixed]")
    page.set_input_files("#file-input", str(ZIP))
    page.click("#btn-create")
    expect(page.locator("#req-msg")).to_contain_text("정비 점검용", timeout=T)
    errors[:] = [e for e in errors if "status of 400" not in e]  # 방금 거부는 의도한 것이다
    page.set_input_files("#file-input", lot_zip)
    page.check(f"input[name=mode][value={MODE}]")
    page.click("#btn-create")
    expect(page.locator("#preview")).to_contain_text("PART-04", timeout=T)
    expect(page.locator("#preview")).to_contain_text("고객사양 개정번호")  # PART-04의 빠진 정보
    expect(page.locator("#preview")).to_contain_text("생산 로트 LOT-E2E")
    shot("m1_request")
    page.click("#preview a")

    # ② 에이전트: 개정번호 질문 → Rev B
    page.wait_for_url("**/agent.html")
    q = page.locator("#questions")
    expect(q).to_contain_text("PART-04", timeout=T)
    expect(q).to_contain_text("고객사양")
    shot("m2_agent_question")
    page.click(".q-rev[data-rev=B]")
    expect(page.locator("#final")).to_contain_text("보고서 초안을 만들었습니다", timeout=T)
    expect(page.locator("#log")).to_contain_text("과거 NCR 이력 조회")
    shot("m3_agent_done")
    page.click("#next a")

    # ③ 판정 결과
    page.wait_for_url("**/results.html")
    expect(page.locator("#rows tr[data-card=PART-01]")).to_contain_text("적합(기록)")
    expect(page.locator("#rows tr[data-card=PART-02]")).to_contain_text("보류(재검사 권고)")
    expect(page.locator("#rows tr[data-card=PART-03]")).to_contain_text("부적합(NCR 대상)")
    page.click("#rows tr[data-card=PART-03]")
    expect(page.locator("#detail")).to_contain_text("23.09")
    expect(page.locator("#detail")).to_contain_text("사양 한도 6.35 mm")
    page.wait_for_function("document.querySelector('#detail img') && document.querySelector('#detail img').naturalWidth > 0")
    shot("m4_results")

    # ④ 보고서: NCR 초안, 반려(Rev 정정) → 재평가, 전체 승인
    page.goto(f"{BASE}/report.html")
    frame = page.frame_locator("#frame")
    expect(frame.locator("h1")).to_contain_text("NCR 초안", timeout=T)
    expect(frame.locator("body")).to_contain_text("NCR-DRAFT-LOT-E2E-PART-03")
    page.fill("#insp", "")
    page.click("[data-card=PART-01] .b-approve")
    expect(page.locator("#final")).to_contain_text("기록하지 않았습니다", timeout=T)
    page.fill("#insp", "김검사")
    page.click("[data-card=PART-04] .b-toggle")
    page.fill("[data-card=PART-04] .r-reason", "개정번호 오기")
    page.select_option("[data-card=PART-04] .r-rev", "A")
    page.click("[data-card=PART-04] .b-reject")
    expect(page.locator("[data-card=PART-04]")).to_contain_text("부적합(NCR 대상)", timeout=T)
    expect(frame.locator("body")).to_contain_text("NCR-DRAFT-LOT-E2E-PART-04", timeout=T)
    shot("m5_report_review")
    page.goto(f"{BASE}/email.html")
    expect(page.locator("#btn-send")).to_be_disabled()
    page.goto(f"{BASE}/report.html")
    page.fill("#insp", "김검사")
    page.click("#btn-all")
    expect(page.locator("#rep-status")).to_contain_text("검사원 승인 완료", timeout=T)
    shot("m6_report_approved")

    # ⑤ 이메일(.eml 저장), ⑥ 이력
    page.click("#next a")
    page.wait_for_url("**/email.html")
    expect(page.locator("#subj")).to_have_value("[초음파 검사 보고서] 로트 LOT-E2E 출하 전 초음파 검사")
    page.click("#btn-send")
    expect(page.locator("#sent")).to_contain_text("outputs/outbox/", timeout=T)
    shot("m7_email")
    page.goto(f"{BASE}/history.html")
    expect(page.locator("#rows")).to_contain_text("발송(.eml 저장)", timeout=T)
    expect(page.locator("#rows")).to_contain_text("제조 검사 · 부품 4건")

    # 모드를 되돌리면 정비 점검 세션이 그대로 보인다
    page.goto(f"{BASE}/results.html?mode=maint")
    expect(page.locator("#mode-toggle a[aria-current]")).to_have_text("정비 점검")
    expect(page.locator("#rows")).to_contain_text("CARD-01", timeout=T)
    assert "PART-01" not in page.locator("#rows").inner_text()


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def shot(name):
            page.screenshot(path=str(SHOTS / f"e2e_{MODE}_{name}.png"), full_page=True)

        # ① 검사 요청: zip 업로드
        page.goto(f"{BASE}/request.html?mode=maint")
        page.click("#tab-upload")
        page.set_input_files("#file-input", str(ZIP))
        page.check(f"input[name=mode][value={MODE}]")
        page.click("#btn-create")
        expect(page.locator("#preview")).to_contain_text("CARD-06", timeout=T)
        expect(page.locator("#preview")).to_contain_text("기준 개정번호")  # CARD-05의 빠진 정보
        shot("1_request")
        page.click("#preview a")

        # ② 에이전트: 자동 시작 → 개정번호 질문
        page.wait_for_url("**/agent.html")
        q = page.locator("#questions")
        expect(q).to_contain_text("CARD-05", timeout=T)
        expect(q).to_contain_text("추측하지 않습니다")
        shot("2_agent_question")
        page.click(".q-rev[data-rev=B]")
        expect(page.locator("#final")).to_contain_text("보고서 초안을 만들었습니다", timeout=T)
        expect(page.locator("#log")).to_contain_text("compile_package_report")
        shot("3_agent_done")
        page.click("#next a")

        # ③ 판정 결과
        page.wait_for_url("**/results.html")
        expect(page.locator("#rows")).to_contain_text("한도 초과(제작사 문의)")
        expect(page.locator("#rows tr[data-card=CARD-04]")).to_contain_text("확대 의심")
        expect(page.locator("#rows tr[data-card=CARD-06]")).to_contain_text("미평가")
        page.click("#rows tr[data-card=CARD-03]")
        expect(page.locator("#detail")).to_contain_text("26.95")
        page.wait_for_function("document.querySelector('#detail img') && document.querySelector('#detail img').naturalWidth > 0")
        shot("4_results")

        # ④ 보고서: 이름 없이 승인 → 거부
        page.goto(f"{BASE}/report.html")
        expect(page.frame_locator("#frame").locator("h1")).to_contain_text("복합재 NDT 점검 보고서", timeout=T)
        page.fill("#insp", "")
        page.click("[data-card=CARD-01] .b-approve")
        expect(page.locator("#final")).to_contain_text("기록하지 않았습니다", timeout=T)
        page.fill("#insp", "AI")
        page.click("[data-card=CARD-01] .b-approve")
        expect(page.locator("#final")).to_contain_text("기록하지 않았습니다", timeout=T)
        # 반려: CARD-06 절차 정정 → 재평가
        page.fill("#insp", "김검사")
        page.click("[data-card=CARD-06] .b-toggle")
        page.fill("[data-card=CARD-06] .r-reason", "절차 번호 오기")
        page.select_option("[data-card=CARD-06] .r-proc", "GNU-NTM-EX-51-02")
        page.click("[data-card=CARD-06] .b-reject")
        expect(page.locator("[data-card=CARD-06]")).to_contain_text("수리 가능", timeout=T)
        # 반려: CARD-03 IND-02 제외 → 재평가
        page.click("[data-card=CARD-03] .b-toggle")
        page.fill("[data-card=CARD-03] .r-reason", "표면 신호")
        page.check("[data-card=CARD-03] .r-ind[value=IND-02]")
        page.click("[data-card=CARD-03] .b-reject")
        expect(page.locator("[data-card=CARD-03]")).to_contain_text("검사원 제외 지시: IND-02", timeout=T)
        shot("5_report_review")
        # 발송은 승인 전에는 막힌다
        page.goto(f"{BASE}/email.html")
        expect(page.locator("#btn-send")).to_be_disabled()
        expect(page.locator("#app")).to_contain_text("승인이 끝나지 않아")
        # 전체 승인
        page.goto(f"{BASE}/report.html")
        page.fill("#insp", "김검사")
        page.click("#btn-all")
        expect(page.locator("#rep-status")).to_contain_text("검사원 승인 완료", timeout=T)
        expect(page.frame_locator("#frame").locator("body")).to_contain_text("검사원 승인 완료", timeout=T)
        shot("6_report_approved")

        # ⑤ 이메일(.eml 저장)
        page.click("#next a")
        page.wait_for_url("**/email.html")
        page.click("#btn-send")
        expect(page.locator("#sent")).to_contain_text("outputs/outbox/", timeout=T)
        expect(page.locator("#sent")).to_contain_text("SHA-256")
        shot("7_email")

        # ⑥ 이력
        page.goto(f"{BASE}/history.html")
        expect(page.locator("#rows")).to_contain_text("발송(.eml 저장)", timeout=T)
        expect(page.locator("#rows")).to_contain_text("검사원 서명")
        shot("8_history")

        # 챗봇
        expect(page.locator("#chat")).to_be_hidden()  # 도우미는 기본으로 닫혀 있다
        page.click("#chat-toggle")
        page.fill("#chat-input", "6 dB drop이 뭐야?")
        page.press("#chat-input", "Enter")
        expect(page.locator("#chat-thread")).to_contain_text("근거:", timeout=120_000)

        # 홈
        page.goto(f"{BASE}/index.html")
        expect(page.locator("#app")).to_contain_text("이어서 보기")
        assert not page.evaluate("document.body.classList.contains('mode-mfg')")  # 정비 테마

        # 제조 검사 모드
        with tempfile.TemporaryDirectory() as tmp:
            mfg_flow(page, shot, make_lot_zip(tmp), errors)
        b.close()
    errors = [e for e in errors if "favicon" not in e and "cdn.tailwindcss.com should not be used" not in e]
    if errors:
        print("브라우저 오류:", errors)
        sys.exit(1)
    print("E2E OK", MODE)


if __name__ == "__main__":
    main()
