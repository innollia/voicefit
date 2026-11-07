"""Gemini 호출. 키는 서버의 SCHOOL_GEMINI_API_KEY에서만 읽고 일일 한도를 둔다."""
import base64
import datetime
import json
import os
import tempfile
import threading
from pathlib import Path

import requests

POOL = Path.home() / ".all-tomorrow" / "key-pool.env"
COUNTER = Path(tempfile.gettempdir()) / "voicefit_calls.json"
COUNTER_LOCK = threading.Lock()
PROMPT = ("이 한국어 음성을 들리는 그대로 받아 적어라. 맞춤법이나 문맥으로 고치지 말고, "
          "들린 발음에 가장 가까운 표기로 적어라. 받아 적은 문장만 출력하라.")


class Unavailable(Exception):
    """사용자에게 그대로 보여 줄 수 있는 실패."""


def _from_pool(name):
    """로컬 전용 키 파일. Cloud에는 없으므로 없으면 조용히 넘어간다."""
    try:
        lines = POOL.read_text(encoding="utf8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def _setting(name, default=None):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return value
    except Exception:
        pass
    return _from_pool(name) or default


def api_key():
    return _setting("SCHOOL_GEMINI_API_KEY")


def claude_key():
    return _setting("ANTHROPIC_API_KEY")


def provider():
    """글자 보정에 쓸 AI. AI_PROVIDER가 우선이고, 없으면 학교 Gemini, 그다음 Claude."""
    chosen = (_setting("AI_PROVIDER") or "").strip().lower()
    if chosen in ("claude", "gemini"):
        return chosen
    if api_key():
        return "gemini"
    return "claude" if claude_key() else None


def can_record():
    return bool(api_key() or groq_key())


def stt_model():
    """지금 녹음을 받아 적는 모델 이름. 없으면 None."""
    if api_key():
        return "Gemini " + _setting("GEMINI_MODEL", "gemini-2.5-flash")
    if groq_key():
        return "Groq " + _setting("GROQ_MODEL", "whisper-large-v3")
    return None


def groq_key():
    return _setting("GROQ_API_KEY") or _setting("GROQ__CHUNGHO208")


def daily_limit():
    return int(_setting("VOICEFIT_DAILY_CALLS", 300))


def _count_call():
    """녹음을 동시에 처리하므로 한 번에 하나씩 센다."""
    today = datetime.date.today().isoformat()
    with COUNTER_LOCK:
        try:
            data = json.loads(COUNTER.read_text())
        except (OSError, ValueError):
            data = {}
        used = data.get(today, 0)
        if used >= daily_limit():
            raise Unavailable("오늘 사용 한도를 다 썼습니다. 내일 다시 쓸 수 있고, 예시 데이터 체험은 계속됩니다.")
        COUNTER.write_text(json.dumps({today: used + 1}))


def _generate(parts):
    key = api_key()
    if not key:
        raise Unavailable("AI 키가 아직 설정되지 않았습니다.")
    _count_call()
    model = _setting("GEMINI_MODEL", "gemini-2.5-flash")
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0}},
            timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (requests.RequestException, KeyError, IndexError, ValueError):
        raise Unavailable("AI 호출에 실패했습니다. 잠시 뒤 다시 시도해 주세요.") from None


def _claude(prompt):
    key = claude_key()
    if not key:
        raise Unavailable("Claude 키가 아직 설정되지 않았습니다.")
    _count_call()
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": _setting("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"]).strip()
    except (requests.RequestException, KeyError, ValueError):
        raise Unavailable("AI 호출에 실패했습니다. 잠시 뒤 다시 시도해 주세요.") from None


def _groq(audio, mime):
    _count_call()
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {groq_key()}"},
            files={"file": ("speech." + mime.split("/")[-1], audio, mime)},
            data={"model": _setting("GROQ_MODEL", "whisper-large-v3"), "language": "ko",
                  "temperature": "0", "response_format": "json"},
            timeout=60)
        r.raise_for_status()
        return r.json()["text"].strip()
    except (requests.RequestException, KeyError, ValueError):
        raise Unavailable("음성 인식에 실패했습니다. 잠시 뒤 다시 시도해 주세요.") from None


def transcribe(audio, mime="audio/wav"):
    if not can_record():
        raise Unavailable("녹음 인식 키가 아직 설정되지 않았습니다.")
    if not api_key():
        return _groq(audio, mime)
    data = base64.b64encode(audio).decode()
    return _generate([{"text": PROMPT}, {"inline_data": {"mime_type": mime, "data": data}}])


def polish(text, active_rules):
    """잘못 들은 것이 문맥상 분명한 곳만 고친다. 규칙이 없어도 동작하고, 모호하면 그대로 둔다."""
    listing = "\n".join(f"{w} → {r}" for w, r in active_rules.items()) or "(아직 없음)"
    prompt = (
        "다음은 한 사람의 음성 인식 결과와, 그 사람에게 반복되는 오류 목록이다. "
        "목록의 오류와, 목록에 없어도 비슷한 발음을 잘못 받아 적은 것이 문맥상 확실한 곳만 고쳐라. "
        "조금이라도 모호하면 그대로 둬라. 말투, 어순, 띄어쓰기를 다듬거나 새 내용을 더하지 마라. "
        "문장만 출력하라.\n\n"
        f"오류 목록:\n{listing}\n\n문장: {text}")
    if provider() == "claude":
        return _claude(prompt)
    return _generate([{"text": prompt}])
