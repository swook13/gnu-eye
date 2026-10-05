"""LLM 모드로 샘플 패키지를 한 번 끝까지 돌려 본다 (개발 확인용, 성능 수치로 쓰지 않는다).

    python tools/run_llm_once.py            # OLLAMA_HOST, GNUEYE_MODEL 환경변수 사용
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import llm  # noqa: E402
from agent.loop import Runner  # noqa: E402
from agent.session import Session  # noqa: E402


def main():
    print("LLM:", llm.status())
    s = Session("data/packages/HL-EX01_C-check_2026-10", llm=llm.plain, log=False, mode_info=f"LLM {llm.model()}")

    def emit(kind, d):
        if kind == "tool":
            print(f"  [{d['by']}] {d['name']} {d['args']} -> {'ok' if d['ok'] else 'ERR ' + d['result']['error'][:90]}")
        elif kind == "llm":
            print(f"  (llm {d['sec']}s, calls={d['tool_calls']})")
        elif kind == "fallback":
            print("  !! 대체 경로:", d["reason"])

    r = Runner(s, use_llm=True, emit=emit)
    turns = [
        "패키지 HL-EX01_C-check_2026-10의 정기점검 작업카드 6건을 처리하고 기체 단위 점검 보고서 초안을 만들어 줘.",
        "CARD-05의 기준 개정번호는 Rev B입니다.",
        "김검사입니다. CARD-03의 IND-02는 표면 신호로 보여 제외하고 반려합니다.",
        "김검사입니다. 전체 카드 승인합니다.",
    ]
    for t in turns:
        t0 = time.time()
        print("\n>>", t)
        print(r.run_turn(t))
        print(f"   ({time.time() - t0:.1f}s)")
    print("\n가드레일:", r.guard_metrics())
    print("보고서 상태:", s.package_report and s.package_report["status"], "| 의견 출처:",
          s.package_report and s.package_report["opinion_source"])
    if s.package_report:
        print("의견:", s.package_report["opinion"])


if __name__ == "__main__":
    main()
