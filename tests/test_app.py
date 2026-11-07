import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
import core  # noqa: E402
import data  # noqa: E402
import stt  # noqa: E402


def trained():
    p = core.new_profile()
    for ref, hyp in data.DEMO_CALIBRATION:
        core.learn(p, ref, hyp)
    return p


def test_rule_keeps_particles():
    assert core.correct(trained(), "외의를 하교에서 했다.")[0] == "회의를 학교에서 했다."


def test_single_error_is_not_a_rule():
    p = core.new_profile()
    core.learn(p, "회의가 있다", "외의가 있다")
    assert core.rules(p) == {}


def test_ambiguous_form_is_left_alone():
    p = core.new_profile()
    for _ in range(2):
        core.learn(p, "의사를 만났다", "이사를 만났다")
        core.learn(p, "이사를 했다", "이사를 했다")
    assert core.correct(p, "이사를 했다")[0] == "이사를 했다"


def test_demo_improves_without_harm():
    r = core.evaluate(trained(), data.DEMO_EVALUATION)
    assert r["after"] < r["before"] and r["harmed"] == 0


def test_overcorrection_is_counted():
    p = core.new_profile()
    for _ in range(2):
        core.learn(p, "의사를 만났다", "이사를 만났다")
    assert core.evaluate(p, [("이사를 했다", "이사를 했다")])["harmed"] == 1


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    for k in ("SCHOOL_GEMINI_API_KEY", "ANTHROPIC_API_KEY", "AI_PROVIDER", "GROQ_API_KEY", "GROQ__CHUNGHO208"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(stt, "POOL", tmp_path / "none.env")
    monkeypatch.setattr(stt, "COUNTER", tmp_path / "calls.json")


def test_provider_order(monkeypatch):
    assert stt.provider() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert stt.provider() == "claude" and not stt.can_record()
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert stt.can_record()
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.setenv("SCHOOL_GEMINI_API_KEY", "x")
    assert stt.provider() == "gemini" and stt.can_record()
    monkeypatch.setenv("AI_PROVIDER", "claude")
    assert stt.provider() == "claude" and stt.can_record()


def test_pool_file_is_read(monkeypatch, tmp_path):
    f = tmp_path / "k.env"
    f.write_text("ANTHROPIC_API_KEY=abc\n", encoding="utf8")
    monkeypatch.setattr(stt, "POOL", f)
    assert stt.claude_key() == "abc"


def test_claude_polish_uses_messages_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("CLAUDE_MODEL", "m")
    seen = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "text", "text": "회의"}]}

    def post(url, headers, json, timeout):
        seen.update(url=url, model=json["model"])
        return R()

    monkeypatch.setattr(stt.requests, "post", post)
    assert stt.polish("외의", {"외의": "회의"}) == "회의"
    assert seen == {"url": "https://api.anthropic.com/v1/messages", "model": "m"}


def test_profile_is_bound_to_its_model():
    p = core.new_profile("A")
    assert core.fits(p, "B")
    core.learn(p, "회의가 있다", "외의가 있다")
    assert core.fits(p, "A") and not core.fits(p, "B")
    p["model"] = core.DEMO_MODEL
    assert core.fits(p, "B")


def test_no_key_refuses(monkeypatch):
    with pytest.raises(stt.Unavailable):
        stt.transcribe(b"x")


def test_daily_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "COUNTER", tmp_path / "c.json")
    monkeypatch.setenv("VOICEFIT_DAILY_CALLS", "1")
    stt._count_call()
    with pytest.raises(stt.Unavailable):
        stt._count_call()


def test_app_without_key_shows_guide_and_demo(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("SCHOOL_GEMINI_API_KEY", raising=False)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception and "AI 키" in at.warning[0].value
    at.button(key="demo_btn").click().run()
    assert not at.exception
    assert any(m.label == "규칙으로 좋아진 문장" and m.value != "0" for m in at.metric)


def test_habit_needs_two_different_words():
    p = core.new_profile("A")
    core.learn(p, "회의가 있다", "외의가 있다")
    assert core.habits(p) == []
    core.learn(p, "학교 간다", "악교 간다")
    assert core.habits(p) == [("첫소리", "ㅎ", "ㅇ", 2)]


def test_scripts_vary_endings():
    ends = {s.rstrip(".?!")[-1] for s in data.CALIBRATION}
    assert len(ends) >= 8 and sum(s.endswith("?") for s in data.CALIBRATION) >= 4
