import base64
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import core
import data
import stt

st.set_page_config(page_title="내 목소리 맞춤 인식", page_icon="🎙️", layout="centered")
recorder_ui = components.declare_component("recorder", path=str(Path(__file__).parent / "components" / "recorder"))
s = st.session_state
LIVE_URL = "https://bull-give-broker-warned.trycloudflare.com/"  # 터널을 다시 켜면 바꾼다
EXAMPLE = "내일 외의는 하교에서 합니다."
model =stt.stt_model()
s.setdefault("profile", core.new_profile(model))
s.setdefault("eval_pairs", [])
s.setdefault("eval_ai", [])     # 효과 확인 문장마다 AI가 고친 문장
if "cal_left" not in s:
    s.cal_left, s.eval_left = data.draw()
s.setdefault("acks", {})         # 녹음기에 받았다고 답한 마지막 번호
s.setdefault("jobs", [])        # 뒤에서 받아 적는 중인 녹음
s.setdefault("free_rows", [])
s.setdefault("cal_log", [])     # 학습에 쓴 (대본, 인식)
s.setdefault("seen", set())
has_key = stt.can_record()
st.markdown(f"<style>{(Path(__file__).parent / 'style.css').read_text(encoding='utf8')}</style>",
            unsafe_allow_html=True)


def label(text):
    st.markdown(f'<p class="eyebrow">{text}</p>', unsafe_allow_html=True)


def reset_profile():
    s.profile, s.eval_pairs, s.eval_ai = core.new_profile(model), [], []
    s.cal_left, s.eval_left = data.draw()
    s.jobs, s.free_rows, s.cal_log = [], [], []
    s.demo = False


@st.cache_resource
def workers():
    return ThreadPoolExecutor(4)


def recorder(kind, left=None):
    """녹음은 브라우저에서 이어지고, 받은 녹음은 뒤에서 받아 적는다. 파일로 저장하지 않는다."""
    total = len(data.EVALUATION if kind == "eval" else data.CALIBRATION)
    got = recorder_ui(left=left, ack=s.acks.get(kind), total=total, next_tab=1 if kind == "cal" else None,
                      key=f"rec_{kind}", default=None)
    if not got or got["id"] == s.acks.get(kind):
        return
    s.acks[kind] = got["id"]
    audio = base64.b64decode(got["audio"]), got["mime"] or "audio/webm"
    if kind == "free":
        job = workers().submit(free_job, *audio, copy.deepcopy(profile))
    else:
        left.remove(got["ref"])
        fn = eval_job if kind == "eval" else stt.transcribe
        job = workers().submit(fn, *audio, *([copy.deepcopy(profile)] if kind == "eval" else []))
    s.jobs.append({"kind": kind, "ref": got["ref"], "future": job})
    st.rerun()


def eval_job(audio, mime, snapshot):
    """받아 적은 문장과, 그때의 규칙으로 AI가 고친 문장을 함께 돌려준다."""
    raw = stt.transcribe(audio, mime)
    fixed, _ = core.correct(snapshot, raw)
    ai = None
    if stt.provider():
        try:
            ai = core.guard(fixed, stt.polish(fixed, core.rules(snapshot), core.habits(snapshot)))
        except stt.Unavailable:
            pass
    return raw, ai


def free_job(audio, mime, snapshot):
    raw = stt.transcribe(audio, mime)
    fixed, _ = core.correct(snapshot, raw)
    row = {"일반 인식": raw, "내 프로필로 보정": fixed}
    if stt.provider():
        try:
            row["AI 문맥 보정"] = core.guard(fixed, stt.polish(fixed, core.rules(snapshot), core.habits(snapshot)))
        except stt.Unavailable:
            row["AI 문맥 보정"] = fixed
    return row


def drain():
    """끝난 받아 적기를 반영한다. 실패한 문장은 다시 읽도록 뒤로 돌린다."""
    for job in [j for j in s.jobs if j["future"].done()]:
        s.jobs.remove(job)
        kind, ref = job["kind"], job["ref"]
        try:
            result = job["future"].result()
        except stt.Unavailable as e:
            s.job_error = str(e)
            if kind in ("cal", "eval"):
                s[f"{kind}_left"].append(ref)
                st.rerun()
            continue
        s.job_error = None
        if kind == "cal":
            if s.profile.get("model") != model:  # 예시 데이터와 섞지 않는다
                s.profile, s.demo = core.new_profile(model), False
            core.learn(s.profile, ref, result)
            s.cal_log.append((ref, result))
        elif kind == "eval":
            s.eval_pairs.append((ref, result[0]))
            s.eval_ai.append(result[1])
        else:
            s.free_rows.insert(0, result)


def drop_learned(i):
    """잘못 읽은 문장을 학습에서 빼고 다시 읽을 차례로 돌린다."""
    ref, _ = s.cal_log.pop(i)
    s.profile = core.new_profile(model)
    for r, h in s.cal_log:
        core.learn(s.profile, r, h)
    s.cal_left.insert(0, ref)


def status():
    if s.get("job_error"):
        st.error(s.job_error)
    if s.jobs:
        st.caption(f"받아 적는 중 {len(s.jobs)}개. 기다리지 말고 다음 녹음을 하셔도 됩니다.")


def current():
    return s.profile if core.fits(s.profile, model) else core.new_profile(model)


live = st.fragment(run_every="1s" if s.jobs else None)


def ai_fix(text, rules):
    """같은 입력으로 다시 호출하지 않는다. 화면이 다시 그려져도 사용량이 늘지 않는다."""
    key = (text, tuple(sorted(rules.items())))
    if s.get("ai_key") != key:
        try:
            s.ai_text = core.guard(text, stt.polish(text, rules, core.habits(current())))
        except stt.Unavailable as e:
            st.error(str(e))
            return text
        s.ai_key = key
    return s.ai_text


def load_demo():
    p = core.new_profile(core.DEMO_MODEL)
    for ref, hyp in data.DEMO_CALIBRATION:
        core.learn(p, ref, hyp)
    s.profile, s.eval_pairs = p, list(data.DEMO_EVALUATION)
    s.eval_ai = [None] * len(s.eval_pairs)
    s.demo = True


title, menu = st.columns([12, 1], vertical_alignment="top")
title.markdown('<h1 class="hero">내 목소리 맞춤 인식</h1>'
               '<p class="lead">편하게 말씀하세요. 당신의 말투에 꼭 맞는 음성인식을 만들어 드립니다.</p>',
               unsafe_allow_html=True)
st.markdown(f'<p class="tuned">튜닝 대상 모델 <b>{model or "없음"}</b><br>'
            '튜닝은 이 모델이 내 말투를 잘못 듣는 습관을 배우는 일이라, '
            '이 모델에서만 효과가 있습니다. 모델이 바뀌면 다시 학습해야 합니다.</p>',
            unsafe_allow_html=True)

usable = core.fits(s.profile, model)
if not usable:
    st.error(f"이 프로필은 **{s.profile.get('model') or '알 수 없는 모델'}**용이라 "
             f"지금 모델({model or '없음'})에서는 쓰지 않습니다.")
    st.button("지금 모델로 새로 학습", on_click=reset_profile)
profile = s.profile if usable else core.new_profile(model)

with menu.popover("⋮"):
    label("내 프로필")
    st.caption(f"학습 모델: {s.profile.get('model') or model or '없음'}")
    st.metric("학습한 문장", s.profile["sentences"])
    st.metric("쓰는 보정 규칙", len(core.rules(profile)))
    st.button("예시 데이터로 체험", key="demo_btn", on_click=load_demo, use_container_width=True)
    st.download_button("프로필 내려받기", json.dumps(s.profile, ensure_ascii=False),
                       "voice-profile.json", "application/json", use_container_width=True)
    up = st.file_uploader("프로필 불러오기", type="json")
    if up is not None and up.file_id not in s.seen:
        s.seen.add(up.file_id)
        try:
            loaded = json.loads(up.getvalue())
            s.profile = {k: loaded[k] for k in ("errors", "kept", "sentences")}
            s.profile["model"] = loaded.get("model")
            st.rerun()
        except (ValueError, KeyError, TypeError):
            st.error("프로필 파일이 아닙니다.")
    st.caption("녹음 파일은 저장하지 않습니다. 프로필은 이 브라우저 화면에만 있고, 창을 닫으면 사라집니다. 다른 모델에서는 쓸 수 없습니다.")

if s.get("demo"):
    st.info("지금은 지어낸 예시 데이터입니다. 실제 측정값이 아닙니다.")
if not has_key:
    st.link_button("녹음과 AI가 켜진 주소로 가기", LIVE_URL, type="primary")
    st.warning("이 주소에는 AI 키가 없어 녹음 인식이 꺼져 있습니다. "
               "오른쪽 위 ⋮ 메뉴의 **예시 데이터로 체험**을 누르면 학습, 효과 확인, 보정을 그대로 볼 수 있습니다.")

agreed = has_key and st.checkbox("녹음한 음성을 인식을 위해 외부 AI 서비스로 보내는 데 동의합니다.", key="agree")
learn_tab, eval_tab, use_tab = st.tabs(["1. 내 발음 학습", "2. 효과 확인", "3. 써 보기"])

with learn_tab:
    if has_key:
        if not s.cal_left and not s.jobs:
            st.success("준비한 문장을 모두 읽었습니다. 효과 확인으로 넘어가 주세요.")
        elif agreed and usable:
            recorder("cal", s.cal_left)

    @live
    def learn_result():
        drain()
        status()
        p = current()
        rules = core.rules(p)
        label("찾아낸 내 오류")
        if rules:
            st.table([{"이렇게 인식되면": w, "이렇게 고칩니다": r} for w, r in rules.items()])
        else:
            seen = sum(sum(v.values()) for v in p["errors"].values())
            st.write("아직 없습니다. 같은 단어가 같은 글자로 두 번 넘게 틀려야 규칙이 됩니다.")
            if p["sentences"]:
                st.caption(f"지금까지 단어가 다른 단어로 인식된 곳 {seen}곳, 같은 오류가 반복된 곳 "
                           f"{sum(max(v.values()) >= core.MIN_COUNT for v in p['errors'].values())}곳")
        found = core.habits(p)
        label("찾아낸 발음 습관")
        if found:
            st.table([{"자리": part, "원래 소리": x, "이렇게 들림": y, "나온 단어 수": n} for part, x, y, n in found])
            st.caption("서로 다른 단어에서 같은 소리가 같은 식으로 바뀐 것입니다. AI 보정이 이 습관을 참고합니다.")
        else:
            st.write("두 단어 이상에서 같은 소리가 같은 식으로 바뀌면 여기에 나타납니다.")
        if s.cal_log:
            label(f"학습한 문장 {len(s.cal_log)}개")
            for i in range(len(s.cal_log) - 1, max(-1, len(s.cal_log) - 6), -1):
                ref, hyp = s.cal_log[i]
                text, ng = st.columns([12, 1], vertical_alignment="center")
                same = "" if core.cer(ref, hyp) == 0 else "  \n:red[" + hyp + "]"
                text.markdown(f"{ref}{same}")
                if ng.button("✕", key=f"ng{i}_{len(s.cal_log)}", help="이 문장을 학습에서 빼고 다시 읽기"):
                    drop_learned(i)
                    st.rerun()
            if len(s.cal_log) > 5:
                st.caption("최근 5개만 보입니다. 빨간 줄은 대본과 다르게 인식된 문장입니다.")

    learn_result()

with eval_tab:
    st.write("학습에 쓰지 않은 문장으로 비교합니다. 멀쩡한 문장을 망친 경우도 함께 셉니다.")
    if has_key and s.eval_left:
        if agreed:
            recorder("eval", s.eval_left)

    @live
    def eval_result():
        drain()
        status()
        if s.eval_pairs:
            r = core.evaluate(current(), s.eval_pairs)
            ai = [(ref, x) for (ref, _), x in zip(s.eval_pairs, s.eval_ai) if x is not None]
            a, b, e = st.columns(3)
            a.metric("일반 오류율", f"{r['before']:.1%}")
            b.metric("규칙 보정 후", f"{r['after']:.1%}")
            if ai:
                e.metric("AI 보정 후", f"{sum(core.cer(ref, x) for ref, x in ai) / len(ai):.1%}",
                         help=f"AI 결과가 있는 {len(ai)}문장 기준")
            else:
                e.metric("AI 보정 후", "없음")
            c, d = st.columns(2)
            c.metric("규칙으로 좋아진 문장", r["improved"])
            d.metric("규칙으로 나빠진 문장", r["harmed"])
            rows = [{k: x[k] for k in ("대본", "일반 인식", "보정 결과")} for x in r["rows"]]
            for row, x in zip(rows, s.eval_ai):
                row["AI 보정"] = x or ""
            pick = st.dataframe(rows, use_container_width=True, hide_index=True,
                                on_select="rerun", selection_mode="multi-row", key=f"evt{len(rows)}")
            chosen = sorted(pick.selection.rows, reverse=True)
            if chosen and st.button(f"✕ 잘못 읽은 {len(chosen)}문장 빼기", help="빼고 다시 읽을 차례로 돌립니다"):
                for i in chosen:
                    ref, _ = s.eval_pairs.pop(i)
                    s.eval_ai.pop(i)
                    s.eval_left.insert(0, ref)
                st.rerun()
            st.caption("대본과 다르게 읽은 줄은 눌러 고른 뒤 빼면 수치에서 빠집니다.")

    eval_result()

with use_tab:
    if has_key:
        st.write("아무 말이나 녹음해 보세요. 처리되는 동안 계속 녹음할 수 있습니다.")
        if agreed:
            recorder("free")
        else:
            st.caption("위의 동의에 체크하면 녹음할 수 있습니다.")

        @live
        def free_result():
            drain()
            status()
            if s.free_rows:
                st.dataframe(s.free_rows, use_container_width=True, hide_index=True)

        free_result()
    text = st.text_input("문장으로 시험해 보기", "" if has_key else EXAMPLE)
    if text:
        fixed, changes = core.correct(profile, text)
        one, two = st.columns(2)
        with one:
            label("일반 인식")
        one.write(text)
        with two:
            label("내 프로필로 보정")
        two.write(fixed)
        if changes:
            st.caption("고친 곳: " + ", ".join(f"{w} → {r}" for w, r in changes))
        if stt.provider() and text != EXAMPLE:
            label("AI 문맥 보정")
            st.write(ai_fix(fixed, core.rules(profile)))
