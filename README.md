# 지누아이 (GNU-Eye)

**항공 복합재 초음파(C-scan) 검사결과의 기준 대조 및 검사 보고서 작성 보조 AI 에이전트**

제4회 경남 AI·SW 경진대회 대학부 · ③ 제조·피지컬 AI Agent / 3-1 우주항공 제조 · 경상국립대학교 지누아이 팀

검사원이 복합재 초음파 C-scan 검사 묶음을 올리면, AI 에이전트가 계획을 세우고 도구를 호출해 손상·결함 크기를 재고, 기준과 이력에 대조해 보고서 초안을 만듭니다. 빠진 정보는 추측하지 않고 되묻고, 검사원이 반려하면 반영해 다시 평가합니다. **측정과 처분 수치는 Python 코드가 계산하고, 최종 판단과 서명은 검사원이 합니다.**

같은 엔진이 기준 묶음만 바꿔 두 모드로 동작합니다.

| 모드 | 입력 | 결과물 |
|---|---|---|
| 정비 점검 | 정기점검 작업카드 묶음 | 기체 단위 NDT 점검 보고서 초안 |
| 제조 검사 | 생산 로트의 부품 묶음 | 로트 검사 보고서 + 부적합 부품별 NCR 초안(12칸) |

> 기준, 절차, 기체·작업카드, 고객사양, 이전 점검 기록, 과거 NCR 이력은 모두 **시연용 가상 값(EXAMPLE_ONLY)** 입니다. 실제 제작사·고객 문서와 무관합니다.

## 구조

```
브라우저 (web/: 시작 화면 + 화면 7장)  ──REST/SSE──  FastAPI (api/main.py)
                                                         │
        agent/  세션·도구 9종·가드레일(session.py), LLM 루프·진행 확인·고정 순서 모드(loop.py), 도우미(chat.py)
           │                                             │
        core/  측정(measure.py)·기준(criteria.py)·이력(history.py)·보고서·NCR(report.py)    Ollama (qwen2.5)
           │
        rules/ 기준 묶음, data/packages/ 내장 샘플, data/history/ 가상 이력
```

| 결정론 코드 | LLM (내부 실행) | 검사원 |
|---|---|---|
| 측정(6 dB drop), 절차 적합성, 한도 대조, 처분 초안, 이력 비교, 보고서·NCR의 모든 숫자 | 처리 계획과 도구 호출 순서, 반려 뒤 재평가 순서, 검사원 문장 해석, 종합 의견(숫자·ID 검증 통과 시), 도우미 답변 | 빠진 정보에 답하기, 건별 승인·반려, 최종 판단과 서명 |

도구 9종: `declare_plan`, `list_package`, `validate_scan`, `select_criteria`, `inspect_package`, `search_history`, `draft_item_report`, `compile_package_report`, `record_signoff`

## 실행

### 1. 준비
- Python 3.13, Chrome(브라우저 테스트용)
- [Ollama](https://ollama.com)와 모델: `ollama pull qwen2.5:7b` (노트북) 또는 `qwen2.5:14b` (GPU 서버)
- 패키지: `pip install -r requirements.txt`

### 2. 서버 띄우기
```bat
run_local.bat        :: 이 PC의 Ollama(http://localhost:11434), qwen2.5:7b
```
또는 직접:
```bash
set OLLAMA_HOST=http://localhost:11434
set GNUEYE_MODEL=qwen2.5:7b
python -m uvicorn api.main:app --port 8000
```
브라우저에서 http://localhost:8000 → 시작 화면 → 시작하기 → 홈.

`run_h200.bat`는 학교 GPU 서버에 SSH 터널을 열어 `qwen2.5:14b`를 씁니다(접속 설정은 각자의 `~/.ssh/config`에 두며 저장소에는 포함하지 않습니다). 다른 환경에서는 `OLLAMA_HOST`만 바꾸면 됩니다.

LLM이 없으면 화면의 실행 방식에서 **고정 순서(LLM 없음)** 를 고르면 같은 도구를 정해진 순서로 실행합니다. 결과 수치는 같습니다.

### 3. 시연 순서
1. 홈의 **정비점검 시작하기** → 내장 샘플 `HL-EX01_C-check_2026-10` → LLM 에이전트 → 검사 요청 생성 → 에이전트 실행
2. CARD-05의 개정번호 질문에 **Rev B 적용**
3. 판정 결과 → 보고서에서 검사원 이름을 적고 승인·반려 → 이메일(.eml 저장) → 검토 이력
4. 상단 **제조 검사** → **제조검사 시작하기** → 내장 로트 `GNU-LOT-2610-07_hybrid`

### 환경변수
| 이름 | 기본값 | 뜻 |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 주소 |
| `GNUEYE_MODEL` | `qwen2.5:7b` | 모델 |
| `GNUEYE_CTX` | `8192` | 문맥 길이 |
| `GNUEYE_MAX_TOKENS` | `640` | LLM 답 길이 상한 |
| `GNUEYE_LLM_OPINION` | `1` | `0`이면 보고서 종합 의견을 코드 문장만 씀 |

## 테스트

```bash
python -m pytest tests -q                       # 도구 계층 회귀 테스트 62건 (LLM 없음)
python tests/e2e_browser.py                     # 실제 Chrome으로 업로드 → 승인 → .eml → 이력 (서버를 먼저 띄움)
python tools/run_test_cases.py 3 <꼬리표>       # 정비 대표 Test Case 8건 (고정 순서 1회 + LLM 3회)
python tools/run_test_cases_mfg.py 3 <꼬리표>   # 제조 대표 Test Case 8건
```
실행 기록은 `outputs/test_cases_*.md`에 있습니다. 횟수가 적어 성공률로 쓰지 않습니다.

## 데이터

- **정비**: Cranfield CompInnova WP2 초음파 C-scan 공개 데이터의 변환본 6건(`data/packages/HL-EX01_C-check_2026-10/`). Padiyar, J. et al., "Dataset of the WP2 Cranfield", Zenodo, DOI [10.5281/zenodo.4405277](https://doi.org/10.5281/zenodo.4405277), **CC BY 4.0**. 실험실 CFRP 충격 시편이며 격자 간격(0.6 mm)은 처리 영상 축에서 읽은 추정값입니다.
- **제조**: 시연 로트 7건(`data/packages/GNU-LOT-2610-07_hybrid/`) = 위 실측 충격 시편 2건(가상 부품번호) + 합성 5건. 합성은 `tools/build_mfg_lot.py`가 만들며 결함 크기·감쇠·노이즈는 가정값입니다.
- **가상 기준·이력**: `rules/`, `data/history/` (EXAMPLE_ONLY).

## 한계

- 실제 정비·제조 현장 데이터로 검증하지 않았습니다. 손상 깊이는 재지 않고 평면 크기·간격·면적만 봅니다.
- 문장으로 반려하면 LLM이 제외할 지시를 빠뜨릴 수 있습니다. 화면의 반려 버튼은 LLM을 거치지 않습니다.
- LLM 종합 의견은 숫자와 ID만 검증하고 뜻은 검증하지 못합니다.

## 출처와 라이선스

- 모델: Qwen2.5-14B/7B-Instruct (Apache 2.0), Ollama로 실행
- 화면 라이브러리: `web/vendor/README.md` (GSAP, three.js, html2canvas, liquid-glass-js, thinking-orbs)
- 글꼴: Pretendard, Space Grotesk (SIL OFL 1.1), Noto Sans, JetBrains Mono, Material Symbols
- 화면 틀 일부는 Stitch로 만들었고, 코드 작성과 테스트에 Claude Code를 썼습니다.

설계와 결정 기록은 [DESIGN.md](DESIGN.md)에 있습니다.
