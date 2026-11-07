# 내 목소리 맞춤 인식

대본 낭독으로 개인의 반복 인식 오류를 찾아 이후 인식 결과를 보정하는 Streamlit 앱입니다. 토요심화코딩반 과제입니다.

Secrets 또는 환경 변수에 `SCHOOL_GEMINI_API_KEY`를 넣으면 녹음 인식이 켜집니다. 키가 없으면 안내와 예시 데이터 체험만 동작합니다. `ANTHROPIC_API_KEY`를 넣으면 Claude로 글자 보정을 할 수 있습니다. 녹음 인식은 Gemini 키가 있어야 합니다. 로컬에서는 `~/.all-tomorrow/key-pool.env`도 읽습니다.

선택 값: `AI_PROVIDER`(`claude` 또는 `gemini`, 없으면 학교 Gemini 다음 Claude), `GEMINI_MODEL`, `CLAUDE_MODEL`(기본 `claude-sonnet-5-5`), `VOICEFIT_DAILY_CALLS`(기본 300).

```powershell
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q tests
```
