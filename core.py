"""대본과 인식 결과를 비교해 개인 오류 규칙을 만들고 적용한다. AI를 쓰지 않는다."""
import re
from difflib import SequenceMatcher

MIN_COUNT = 2      # 같은 오류가 이만큼 반복돼야 규칙이 된다
MIN_SHARE = 0.8    # 그 표기가 나왔을 때 이 비율 이상 틀려야 고친다
DEMO_MODEL = "예시 데이터"
PUNCT = ".,!?~\"'…"


def tokens(text):
    return re.sub(f"[{PUNCT}]", " ", text).split()


def cer(ref, hyp):
    """글자 오류율. 공백과 문장부호는 세지 않는다."""
    a, b = "".join(tokens(ref)), "".join(tokens(hyp))
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


def _core(wrong, right):
    """조사처럼 뒤가 같은 부분을 떼어 낸다. 외의를/회의를 → 외의/회의."""
    n = 0
    while n < min(len(wrong), len(right)) - 2 and wrong[-1 - n] == right[-1 - n]:
        n += 1
    return (wrong[:-n], right[:-n]) if n else (wrong, right)


def new_profile(model=None):
    """프로필은 학습에 쓴 인식 모델 하나에만 맞는다."""
    return {"errors": {}, "kept": {}, "sentences": 0, "model": model}


def fits(profile, model):
    """비어 있거나 같은 모델로 학습한 프로필만 쓸 수 있다."""
    return profile["sentences"] == 0 or profile.get("model") in (model, DEMO_MODEL)


def learn(profile, ref, hyp):
    r, h = tokens(ref), tokens(hyp)
    for op, i1, i2, j1, j2 in SequenceMatcher(None, r, h, autojunk=False).get_opcodes():
        if op == "equal":
            for t in h[j1:j2]:
                profile["kept"][t] = profile["kept"].get(t, 0) + 1
        elif op == "replace" and i2 - i1 == j2 - j1:
            for right, wrong in zip(r[i1:i2], h[j1:j2]):
                w, c = _core(wrong, right)
                targets = profile["errors"].setdefault(w, {})
                targets[c] = targets.get(c, 0) + 1
    profile["sentences"] += 1
    return profile


def rules(profile):
    """반복되고 모호하지 않은 오류만 규칙으로 쓴다."""
    out = {}
    for wrong, targets in profile["errors"].items():
        right, count = max(targets.items(), key=lambda x: x[1])
        kept = sum(n for t, n in profile["kept"].items() if t.startswith(wrong))
        total = sum(targets.values()) + kept
        if count >= MIN_COUNT and count / total >= MIN_SHARE:
            out[wrong] = right
    return out


def correct(profile, text):
    """고친 문장과 고친 내역을 돌려준다."""
    active = rules(profile)
    changes = []

    def fix(m):
        token = m.group(0)
        for wrong in sorted(active, key=len, reverse=True):
            if token.startswith(wrong):
                changes.append((wrong, active[wrong]))
                return active[wrong] + token[len(wrong):]
        return token

    return re.sub(rf"[^\s{PUNCT}]+", fix, text), changes


def evaluate(profile, pairs):
    """학습에 안 쓴 문장으로 전후를 비교한다. 과잉 교정도 센다."""
    rows = []
    for ref, hyp in pairs:
        fixed, _ = correct(profile, hyp)
        rows.append({"대본": ref, "일반 인식": hyp, "보정 결과": fixed,
                     "before": cer(ref, hyp), "after": cer(ref, fixed)})
    n = len(rows) or 1
    return {
        "before": sum(x["before"] for x in rows) / n,
        "after": sum(x["after"] for x in rows) / n,
        "improved": sum(x["after"] < x["before"] for x in rows),
        "harmed": sum(x["after"] > x["before"] for x in rows),
        "rows": rows,
    }


# 소리 단위 습관. 단어 규칙은 같은 단어가 반복돼야 생기지만,
# 습관은 서로 다른 단어에서 같은 소리가 같은 소리로 바뀐 것을 모은다.
ONSET = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
VOWEL = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
CODA = ["없음"] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")
PART = ("첫소리", "가운데소리", "받침")


def jamo(ch):
    n = ord(ch) - 0xAC00
    if not 0 <= n < 11172:
        return None
    return ONSET[n // 588], VOWEL[n % 588 // 28], CODA[n % 28]


def habits(profile, min_words=2):
    """여러 단어에서 되풀이된 소리 바뀜. [(자리, 원래, 들린 것, 단어 수)]"""
    found = {}
    for wrong, targets in profile["errors"].items():
        for right in targets:
            if len(wrong) != len(right):
                continue
            for a, b in zip(right, wrong):
                ja, jb = jamo(a), jamo(b)
                if not ja or not jb or ja == jb:
                    continue
                for part, x, y in zip(PART, ja, jb):
                    if x != y:
                        found.setdefault((part, x, y), set()).add(right)
    out = [(p, x, y, len(w)) for (p, x, y), w in found.items() if len(w) >= min_words]
    return sorted(out, key=lambda h: -h[3])
