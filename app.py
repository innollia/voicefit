import json

import streamlit as st

import core
import data
import stt

st.set_page_config(page_title="내 목소리 맞춤 인식", page_icon="🎙️", layout="centered")
s = st.session_state
s.setdefault("profile", core.new_profile())
s.setdefault("eval_pairs", [])
s.setdefault("cal_i", 0)
s.setdefault("eval_i", 0)
s.setdefault("seen", set())
has_key = stt.can_record()


def new_audio(widget_key):
    """녹음이 새로 들어왔을 때만 바이트를 돌려준다. 파일로 저장하지 않는다."""
    clip = st.audio_input("녹음", key=widget_key, label_visibility="collapsed")
    if clip is None or widget_key in s.seen:
        return None
    s.seen.add(widget_key)
    return clip.getvalue(), clip.type or "audio/wav"


def recognise(clip):
    try:
        return stt.transcribe(*clip)
    except stt.Unavailable as e:
        st.error(str(e))


def load_demo():
    p = core.new_profile()
    for ref, hyp in data.DEMO_CALIBRATION:
        core.learn(p, ref, hyp)
    s.profile, s.eval_pairs = p, list(data.DEMO_EVALUATION)
    s.demo = True


st.title("내 목소리 맞춤 인식")
st.write("대본을 읽으면 내 발음에서 반복되는 인식 오류를 찾아, 다음 인식부터 고쳐 줍니다.")

with st.sidebar:
    st.subheader("내 프로필")
    st.metric("학습한 문장", s.profile["sentences"])
    st.metric("쓰는 보정 규칙", len(core.rules(s.profile)))
    st.button("예시 데이터로 체험", on_click=load_demo, use_container_width=True)
    st.download_button("프로필 내려받기", json.dumps(s.profile, ensure_ascii=False),
                       "voice-profile.json", "application/json", use_container_width=True)
    up = st.file_uploader("프로필 불러오기", type="json")
    if up is not None and up.file_id not in s.seen:
        s.seen.add(up.file_id)
        try:
            loaded = json.loads(up.getvalue())
            s.profile = {k: loaded[k] for k in ("errors", "kept", "sentences")}
            st.rerun()
        except (ValueError, KeyError, TypeError):
            st.error("프로필 파일이 아닙니다.")
    st.caption("녹음 파일은 저장하지 않습니다. 프로필은 이 브라우저 화면에만 있고, 창을 닫으면 사라집니다.")

if s.get("demo"):
    st.info("지금은 지어낸 예시 데이터입니다. 실제 측정값이 아닙니다.")
if not has_key:
    st.warning("AI 키가 아직 설정되지 않아 녹음 인식은 꺼져 있습니다. "
               "왼쪽의 **예시 데이터로 체험**을 누르면 학습, 효과 확인, 보정을 그대로 볼 수 있습니다.")

learn_tab, eval_tab, use_tab = st.tabs(["1. 내 발음 학습", "2. 효과 확인", "3. 써 보기"])

with learn_tab:
    active = core.rules(s.profile)
    if has_key:
        agreed = st.checkbox("녹음한 음성을 인식을 위해 외부 AI 서비스로 보내는 데 동의합니다.")
        i = s.cal_i
        if i >= len(data.CALIBRATION):
            st.success("준비한 문장을 모두 읽었습니다. 효과 확인으로 넘어가 주세요.")
        elif agreed:
            st.progress(i / len(data.CALIBRATION), f"{i + 1} / {len(data.CALIBRATION)}")
            st.subheader(data.CALIBRATION[i])
            clip = new_audio(f"cal{i}")
            if clip and (hyp := recognise(clip)):
                core.learn(s.profile, data.CALIBRATION[i], hyp)
                s.cal_i += 1
                s.last = hyp
                st.rerun()
            if s.get("last"):
                st.caption(f"방금 인식: {s.last}")
    st.subheader("찾아낸 내 오류")
    if active:
        st.table([{"이렇게 인식되면": w, "이렇게 고칩니다": r} for w, r in active.items()])
    else:
        st.write("같은 오류가 두 번 넘게 반복되면 여기에 나타납니다.")

with eval_tab:
    st.write("학습에 쓰지 않은 문장으로 비교합니다. 멀쩡한 문장을 망친 경우도 함께 셉니다.")
    i = s.eval_i
    if has_key and i < len(data.EVALUATION):
        st.subheader(data.EVALUATION[i])
        if st.checkbox("녹음을 외부 AI 서비스로 보내는 데 동의합니다.", key="eval_ok"):
            clip = new_audio(f"eval{i}")
            if clip and (hyp := recognise(clip)):
                s.eval_pairs.append((data.EVALUATION[i], hyp))
                s.eval_i += 1
                st.rerun()
    if s.eval_pairs:
        r = core.evaluate(s.profile, s.eval_pairs)
        a, b, c, d = st.columns(4)
        a.metric("일반 오류율", f"{r['before']:.1%}")
        b.metric("보정 후", f"{r['after']:.1%}")
        c.metric("좋아진 문장", r["improved"])
        d.metric("나빠진 문장", r["harmed"])
        st.dataframe([{k: x[k] for k in ("대본", "일반 인식", "보정 결과")} for x in r["rows"]],
                     use_container_width=True, hide_index=True)

with use_tab:
    text = ""
    if has_key:
        st.write("아무 말이나 녹음해 보세요.")
        clip = st.audio_input("녹음", key="free")
        if clip is not None and s.get("free_id") != clip.file_id:
            s.free_id = clip.file_id
            s.free_text = recognise((clip.getvalue(), clip.type or "audio/wav")) or ""
        text = st.text_input("인식 결과 (직접 고쳐 넣어도 됩니다)", s.get("free_text", "내일 외의는 하교에서 합니다."))
    else:
        text = st.text_input("인식된 문장을 넣어 보세요", "내일 외의는 하교에서 합니다.")
    if text:
        fixed, changes = core.correct(s.profile, text)
        left, right = st.columns(2)
        left.markdown("**일반 인식**")
        left.write(text)
        right.markdown("**내 프로필로 보정**")
        right.write(fixed)
        if changes:
            st.caption("고친 곳: " + ", ".join(f"{w} → {r}" for w, r in changes))
        elif core.rules(s.profile):
            st.caption("확실한 오류가 없어 그대로 두었습니다.")
        else:
            st.caption("아직 프로필이 비어 있습니다.")
        if stt.provider() and core.rules(s.profile) and st.button("AI로 문맥까지 확인"):
            try:
                st.write(stt.polish(fixed, core.rules(s.profile)))
            except stt.Unavailable as e:
                st.error(str(e))
