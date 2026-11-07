"""Gemini 호출. 키는 서버의 SCHOOL_GEMINI_API_KEY에서만 읽고 일일 한도를 둔다."""
import base64
import datetime
import json
import os
import tempfile
from pathlib import Path

import requests

COUNTER = Path(tempfile.gettempdir()) / "voicefit_calls.json"
PROMPT = ("이 한국어 음성을 들리는 그대로 받아 적어라. 맞춤법이나 문맥으로 고치지 말고, "
          "들린 발음에 가장 가까운 표기로 적어라. 받아 적은 문장만 출력하라.")


class Unavailable(Exception):
    """사용자에게 그대로 보여 줄 수 있는 실패."""


def _setting(name, default=None):
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default


def api_key():
    return _setting("SCHOOL_GEMINI_API_KEY")


def daily_limit():
    return int(_setting("VOICEFIT_DAILY_CALLS", 300))


def _count_call():
    today = datetime.date.today().isoformat()
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


def transcribe(audio, mime="audio/wav"):
    data = base64.b64encode(audio).decode()
    return _generate([{"text": PROMPT}, {"inline_data": {"mime_type": mime, "data": data}}])


def polish(text, active_rules):
    """규칙을 근거로 문맥이 분명한 곳만 고친다. 모호하면 그대로 둔다."""
    listing = "\n".join(f"{w} → {r}" for w, r in active_rules.items())
    return _generate([{"text": (
        "다음은 한 사람의 음성 인식 결과와, 그 사람에게 반복되는 오류 목록이다. "
        "목록에 있는 오류이고 문맥상 확실할 때만 고쳐라. 조금이라도 모호하면 그대로 둬라. "
        "새 내용을 더하거나 다듬지 마라. 문장만 출력하라.\n\n"
        f"오류 목록:\n{listing}\n\n문장: {text}")}])
