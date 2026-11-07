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


def test_no_key_refuses(monkeypatch):
    monkeypatch.delenv("SCHOOL_GEMINI_API_KEY", raising=False)
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
    at = AppTest.from_file(str(ROOT / "app.py")).run()
    assert not at.exception and "AI 키" in at.warning[0].value
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert any(m.label == "좋아진 문장" and m.value != "0" for m in at.metric)
