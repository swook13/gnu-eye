"""Ollama 호출 (외부 API 미사용). 주소와 모델은 환경변수로 바꾼다.

    OLLAMA_HOST   기본 http://localhost:11434   (H200은 SSH 포트 연결 후 http://localhost:11525)
    GNUEYE_MODEL  기본 qwen2.5:7b
    GNUEYE_CTX    기본 8192
"""
import json
import os
import time
import urllib.error
import urllib.request


def host():
    h = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    return h if h.startswith("http") else "http://" + h


def model():
    return os.environ.get("GNUEYE_MODEL", "qwen2.5:7b")


def num_ctx():
    return int(os.environ.get("GNUEYE_CTX", "8192"))


def status(timeout=3):
    """LLM 서버 연결과 모델 설치 여부. 실패해도 예외를 던지지 않는다."""
    try:
        with urllib.request.urlopen(f"{host()}/api/tags", timeout=timeout) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
    except Exception as e:
        return {"ok": False, "host": host(), "model": model(), "error": f"{type(e).__name__}: {e}"}
    has = model() in names or f"{model()}:latest" in names
    return {"ok": has, "host": host(), "model": model(), "models": names,
            "error": None if has else f"모델 {model()}이 서버에 없음"}


def max_tokens():
    return int(os.environ.get("GNUEYE_MAX_TOKENS", "640"))


def chat(messages, tools=None, timeout=120):
    """Ollama /api/chat. 서버 오류(5xx)와 연결 오류는 두 번까지 재시도한다.

    답 길이 상한(num_predict)을 둔다. 2026-10-06 새벽, 모델이 답을 끝내지 않고 계속 생성해 한 호출이 5분을 넘긴
    일이 있었다(서버 기록의 500, 4m59s). 학교 서버는 한 번에 요청 하나만 처리해 그동안 다른 요청이 모두 줄을 섰다.
    시간 초과는 같은 요청을 다시 보내도 같은 일이 되풀이되므로 재시도하지 않는다.
    """
    body = {"model": model(), "messages": messages, "stream": False, "keep_alive": "60m",
            "options": {"temperature": 0, "num_ctx": num_ctx(), "num_predict": max_tokens()}}
    if tools:
        body["tools"] = tools
    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        req = urllib.request.Request(f"{host()}/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                raise
            last = e
    raise last


def plain(prompt, system=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return chat(msgs)["message"]["content"]
