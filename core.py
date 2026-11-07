"""대본과 인식 결과를 비교해 개인 오류 규칙을 만들고 적용한다. AI를 쓰지 않는다."""
import re
from difflib import SequenceMatcher

MIN_COUNT = 2      # 같은 오류가 이만큼 반복돼야 규칙이 된다
MIN_SHARE = 0.8    # 그 표기가 나왔을 때 이 비율 이상 틀려야 고친다
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


def new_profile():
    return {"errors": {}, "kept": {}, "sentences": 0}


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
