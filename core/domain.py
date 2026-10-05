"""검사 영역(도메인) 프로필. 같은 엔진이 기준 묶음과 용어만 바꿔 정비 점검과 제조 검사를 처리한다.

패키지의 package.json에 "domain"이 없으면 정비 점검(maintenance)이다.
여기에는 용어와 문장 틀만 둔다. 수치는 rules/의 기준 파일에서만 나온다.
"""
MAINT, MFG = "maintenance", "manufacturing"
ALLOW, REPAIR, EXCEED, NOT_EVALUATED = "ALLOW", "REPAIR", "EXCEED", "NOT_EVALUATED"

SYSTEM_MAINT = """너는 항공기 정기점검에서 나온 복합재 초음파 C-scan 작업카드 묶음(패키지)을 처리하는 검사 보조 에이전트다.
규칙:
1. 작업을 시작하면 가장 먼저 declare_plan으로 계획을 기록한다.
2. 기본 순서: list_package → validate_scan → select_criteria → inspect_package → search_history → draft_item_report → compile_package_report.
3. 카드에 기준 개정번호가 없으면 추측하지 않는다. list_package에서 빠진 정보를 발견해도 직접 묻거나 멈추지 말고 validate_scan과 select_criteria(인자 없이)까지 호출한다. 질문은 select_criteria가 등록해 화면에 표시한다. select_criteria가 질문을 돌려주면 그때 도구 호출을 멈추고 사용자 답을 기다린다. 사용자가 답하면 select_criteria에 card_id와 rev를 넣어 호출한 뒤 나머지 순서를 이어 간다.
4. 모든 수치와 ID는 도구 결과에서만 가져온다. 새 숫자를 만들지 않는다.
5. 처분은 초안이다. 최종 판단과 서명은 자격 검사원이 한다.
6. record_signoff는 검사원이 이름을 밝히고 직접 승인 또는 반려를 말했을 때만 호출한다. 스스로 호출하거나 이름과 사유를 지어내지 않는다.
7. 검사원이 반려하면 record_signoff(필요하면 제외할 지시, 정정할 절차나 개정번호 포함) → inspect_package(해당 카드) → search_history → draft_item_report → compile_package_report 순서로 재평가한다.
8. 도구가 오류를 돌려주면 오류 내용에 따라 선행 단계를 먼저 실행하거나 사용자에게 묻는다. 같은 호출을 반복하지 않는다.
9. 모든 도구가 끝나면 한 줄로만 마무리한다. 판정 요약은 시스템이 코드로 표시하므로 직접 쓰지 않는다.
"""

SYSTEM_MFG = """너는 항공 복합재 부품 제조 공정의 출하 전 초음파 C-scan 검사 묶음(생산 로트 패키지)을 처리하는 검사 보조 에이전트다.
규칙:
1. 작업을 시작하면 가장 먼저 declare_plan으로 계획을 기록한다.
2. 기본 순서: list_package → validate_scan → select_criteria → inspect_package → search_history → draft_item_report → compile_package_report.
3. 부품에 고객사양 개정번호가 없으면 추측하지 않는다. list_package에서 빠진 정보를 발견해도 직접 묻거나 멈추지 말고 validate_scan과 select_criteria(인자 없이)까지 호출한다. 질문은 select_criteria가 등록해 화면에 표시한다. select_criteria가 질문을 돌려주면 그때 도구 호출을 멈추고 사용자 답을 기다린다. 사용자가 답하면 select_criteria에 card_id와 rev를 넣어 호출한 뒤 나머지 순서를 이어 간다.
4. 모든 수치와 ID는 도구 결과에서만 가져온다. 새 숫자를 만들지 않는다.
5. 처분은 초안이다. 부적합보고서(NCR)도 초안이며 최종 판단과 서명은 자격 검사원이 한다.
6. record_signoff는 검사원이 이름을 밝히고 직접 승인 또는 반려를 말했을 때만 호출한다. 스스로 호출하거나 이름과 사유를 지어내지 않는다.
7. 검사원이 반려하면 record_signoff(필요하면 제외할 지시, 정정할 절차나 개정번호 포함) → inspect_package(해당 부품) → search_history → draft_item_report → compile_package_report 순서로 재평가한다.
8. 도구가 오류를 돌려주면 오류 내용에 따라 선행 단계를 먼저 실행하거나 사용자에게 묻는다. 같은 호출을 반복하지 않는다.
9. 모든 도구가 끝나면 한 줄로만 마무리한다. 판정 요약은 시스템이 코드로 표시하므로 직접 쓰지 않는다.
"""

PROFILES = {
    MAINT: {
        "name": "정비 점검", "subject": "기체", "unit": "카드", "unit_long": "작업카드",
        "criteria_word": "허용 손상 기준",
        "ko": {ALLOW: "허용(기록)", REPAIR: "수리 가능", EXCEED: "한도 초과(제작사 문의)", NOT_EVALUATED: "미평가"},
        "plan": ["패키지 항목 확인", "스캔 검증", "카드별 기준 선택 (빠진 정보는 되묻기)", "측정과 한도 대조",
                 "이전 점검 기록 비교", "카드별 평가 초안", "기체 단위 보고서 초안", "검사원 승인 대기"],
        "system": SYSTEM_MAINT,
        "report_title": "복합재 NDT 점검 보고서", "report_prefix": "NDT-RPT",
        "history_label": "이전 점검 기록 (가상)",
        "history_source": "EXAMPLE_ONLY (가상 이전 점검 기록)",
        "actions": [("제작사 문의 대상", "oem_inquiry"), ("수리 대상", "repair"), ("미평가 (재작업 필요)", "not_evaluated"),
                    ("재검사 권고", "recheck"), ("손상 확대 의심", "growth")],
        "opinion_intro": "항공기 복합재 초음파 정기점검 보고서의 '종합 의견' 문단을 한국어 3~5문장으로 써라.",
        "opinion_must": "제작사 문의 대상 카드가 있으면 그 카드 ID를 반드시 쓴다.",
        "opinion_groups": {"제작사": "oem_inquiry", "수리": "repair", "확대": "growth", "미평가": "not_evaluated",
                           "재검사": "recheck"},
        "limitations": [
            "허용 손상 기준, 절차, 기체, 작업카드, 이전 점검 기록은 모두 가상(EXAMPLE_ONLY)이며 실제 제작사 문서와 무관하다.",
            "크기는 바닥면 에코 진폭의 6 dB drop 기준 평면 치수다. 손상 깊이는 측정하지 않았다.",
            "Cranfield 변환본의 격자 간격(0.6 mm)은 설명서에 없어 처리 영상 축에서 읽은 추정값이다. mm 단위 수치는 이 추정에 의존한다.",
            "처분은 초안이다. 최종 판단과 서명은 자격 검사원이 한다.",
        ],
    },
    MFG: {
        "name": "제조 검사", "subject": "생산 로트", "unit": "부품", "unit_long": "검사 부품",
        "criteria_word": "고객사양",
        "ko": {ALLOW: "적합(기록)", REPAIR: "보류(재검사 권고)", EXCEED: "부적합(NCR 대상)", NOT_EVALUATED: "미평가"},
        "plan": ["로트 패키지 항목 확인", "스캔 검증", "부품별 고객사양 선택 (빠진 정보는 되묻기)", "측정과 사양 한도 대조",
                 "과거 NCR 이력 조회", "부품별 평가 초안", "로트 검사 보고서와 NCR 초안", "검사원 승인 대기"],
        "system": SYSTEM_MFG,
        "report_title": "복합재 초음파 검사 보고서 · NCR 초안", "report_prefix": "UT-RPT",
        "history_label": "과거 NCR 이력",
        "history_source": "data/history/ncr_history.json (과거 NCR 이력)",
        "actions": [("NCR 발행 대상", "oem_inquiry"), ("보류 (재검사 후 재판정)", "repair"),
                    ("미평가 (재작업 필요)", "not_evaluated"), ("재검사 권고", "recheck"),
                    ("같은 부품번호 과거 NCR 있음", "growth")],
        "opinion_intro": "항공 복합재 부품 출하 전 초음파 검사 보고서의 '종합 의견' 문단을 한국어 3~5문장으로 써라.",
        "opinion_must": "NCR 대상 부품이 있으면 그 부품 ID를 반드시 쓴다.",
        "opinion_groups": {"NCR": "oem_inquiry", "미평가": "not_evaluated", "재검사": "recheck"},
        "limitations": [
            "고객사양과 절차는 가상(EXAMPLE_ONLY)이며 실제 고객 문서와 무관하다.",
            "크기는 6 dB drop 기준 평면 치수다. 결함 깊이와 종류(박리, 기공 등)는 구분하지 않았다.",
            "mm 단위 수치는 올린 메타데이터의 격자 간격을 그대로 쓴 값이다. 누적 면적 비율의 분모는 스캔 영역 전체다.",
            "처분과 부적합보고서(NCR)는 초안이다. 최종 판단과 서명은 자격 검사원이 한다.",
        ],
    },
}


def profile(domain):
    return PROFILES[domain if domain in PROFILES else MAINT]
