# -*- coding: utf-8 -*-
"""E5 稿件数字重算：从原始归档 scores.json 复算通过率、开销与精确符号翻转检验。

用法： python recompute_e5.py
只读 <WORKSPACE> 下原始归档，不写任何 01-10 目录，不修改既有结果。
"""
import json, sys, itertools
from collections import defaultdict

ROOT = r"<WORKSPACE>"
SCORES = ROOT + r"\04_实验数据\E5_消融\正式结果_2026-10-12\scores.json"
PAPER = {
    "B0": (17.26, 0.00, 1372.9), "B1": (26.19, 0.00, 1560.9),
    "B2a": (48.81, 14.07, 5569.5), "B2b": (49.40, 7.23, 4036.8),
    "B3": (56.55, 4.85, 3534.8), "A1": (52.98, None, None),
    "A2": (54.17, None, None), "A3": (53.57, None, None),
    "A4": (55.36, None, None), "A5": (58.33, None, None),
    "A6": (52.98, None, None),
}


def load():
    with open(SCORES, encoding="utf-8") as f:
        return json.load(f)


def arm_stats(recs):
    n = len(recs)
    passed = sum(1 for r in recs if r.get("e2e_success"))
    calls = sum(r.get("tool_calls") or 0 for r in recs) / n
    toks = []
    for r in recs:
        mu = r.get("model_usage") or []
        s = 0
        if isinstance(mu, list):
            for m in mu:
                if isinstance(m, dict):
                    s += m.get("outputTokens", 0) or 0
        elif isinstance(mu, dict):
            s = mu.get("outputTokens", 0) or 0
        toks.append(s)
    return dict(n=n, passed=passed, rate=passed / n, calls=calls, tok=sum(toks) / n)


def task_series(recs):
    by = defaultdict(list)
    for r in recs:
        by[r["task"]].append(1 if r.get("e2e_success") else 0)
    tasks = sorted(by)
    return tasks, [sum(by[t]) / len(by[t]) for t in tasks]


def sign_flip(a, b):
    """精确配对符号翻转检验（同题同配置内三次重复先取均值，题号为配对单位）。"""
    ta, sa = task_series(a)
    tb, sb = task_series(b)
    assert ta == tb, "题集不一致"
    diff = [x - y for x, y in zip(sa, sb)]
    nz = [x for x in diff if x != 0]
    obs = abs(sum(diff))
    cnt = tot = 0
    for bits in range(1 << len(nz)):
        val = 0
        for i, x in enumerate(nz):
            val += x if (bits >> i) & 1 else -x
        tot += 1
        if abs(val) >= obs - 1e-12:
            cnt += 1
    return dict(k=len(nz), p=cnt / tot)


def main():
    recs = load()
    arms = defaultdict(list)
    for r in recs:
        arms[r["arm"]].append(r)
    st = {a: arm_stats(v) for a, v in arms.items()}

    print("== 原始归档 ==", SCORES)
    print("记录数 %d  臂数 %d" % (len(recs), len(arms)))
    print()
    print("%-5s %5s %6s %10s %10s %11s %s" % ("arm", "n", "pass", "rate%", "calls", "out_tok", "论文呈现值"))
    for a in ["B0", "B1", "B2a", "B2b", "B3", "A1", "A2", "A3", "A4", "A5", "A6", "sham"]:
        s = st[a]
        pv = PAPER.get(a, ("未在稿件呈现",))[0]
        print("%-5s %5d %6d %10.4f %10.4f %11.2f %s" % (a, s["n"], s["passed"], s["rate"] * 100, s["calls"], s["tok"], pv))

    b2b, b3 = st["B2b"], st["B3"]
    print()
    print("B3-B2b 通过率差 = %.4f pp (论文 7.14)" % ((b3["rate"] - b2b["rate"]) * 100))
    print("工具调用减少 = %.4f%% (论文 32.95)  [%.4f -> %.4f]" % ((b2b["calls"] - b3["calls"]) / b2b["calls"] * 100, b2b["calls"], b3["calls"]))
    print("输出 token 减少 = %.4f%% (论文 12.44)  [%.2f -> %.2f]" % ((b2b["tok"] - b3["tok"]) / b2b["tok"] * 100, b2b["tok"], b3["tok"]))
    for a in ["B0", "B1", "B2a"]:
        print("B3-%s 差 = %.4f pp" % (a, (b3["rate"] - st[a]["rate"]) * 100))

    print()
    ps = {}
    for a in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        r = sign_flip(arms["B3"], arms[a])
        ps[a] = r["p"]
        print("B3 vs %s: 精确双侧符号翻转 p = %.9f (k=%d 非零差)" % (a, r["p"], r["k"]))
    order = sorted(ps, key=lambda x: ps[x])
    m, run, holm = len(order), 0.0, {}
    for i, a in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[a]))
        holm[a] = run
    print("Holm 校正（族=六项消融）:", {k: round(v, 6) for k, v in holm.items()})
    r = sign_flip(arms["B3"], arms["B2b"])
    print("主比较 B3 vs B2b: 精确双侧符号翻转 p = %.9f (k=%d)" % (r["p"], r["k"]))
    print("A5 平均调用 = %.4f  平均输出 token = %.2f" % (st["A5"]["calls"], st["A5"]["tok"]))
    print("未在稿件呈现的 sham 臂: %d/%d = %.2f%%" % (st["sham"]["passed"], st["sham"]["n"], st["sham"]["rate"] * 100))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
