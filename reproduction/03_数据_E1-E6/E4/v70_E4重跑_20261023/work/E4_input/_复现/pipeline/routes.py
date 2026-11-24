# 本文件由 temp/e4_judge/normalize.py 复制而来，**只改了两行路径常量**；
# route 判别规则、A 级纠正标记、逐条理由一字未动。
# -*- coding: utf-8 -*-
"""把三箱答卷转写成 judge_tier_p.grade_one 认识的答案记录。

为什么需要这一层:
    ``runner --answers`` 只吃 ``{item_id: {route, tool_calls, answer_text, ...}}`` 这一种形态,
    而三箱交上来的东西**三种形态** —— sb1 单文件 53 节 markdown、sb2 每题一个 md、
    sb3 每题一个 json (字段名还叫 question_id/status)。不转写就无法判分。

转写口径 (必须与分数一起披露, 否则"分数"会被误读成"判据输出"):
    1. ``answer_text`` = 答卷原文, 一字不改 (探针/点名/替代路径都从它身上判);
    2. ``route`` = 该答卷**自己声明的处置动作**, 按同一套四级判据转写, 不按箱子换标准:
         answer      真发了查询并给了数 (自述"已执行/实测/status=ready 且 executed=true")
         clarify     因**请求语义有歧义**停下并向用户提问 (单位/指代/口径/哪张表/判据)
         stop_report 因**外部事实不可得**停下并报告 (名称解算失败/数据不存在/要求伪造)
         reject      其余停下 (入参非法/超上限/超能力/安全拒绝), 含"婉拒+给替代"
       规则顺序: 已执行 → 外部事实不可得 → 语义歧义 → 其余拒绝;
       逐条命中理由写进 route_reason, 与本文件一起可复核。
    3. ``tool_calls``/``http_requests``: 只有 route=answer 才记一次取数调用 (否则记零),
       因为答卷只在"已执行"时声称动手; 拒绝类答卷即使提到工具名也是引用不是调用。
       **副作用**: must_not_call 红线只在"已执行"的答卷上可能命中 → 本口径下红线数是
       下界, 不是全量。
    4. A 级三题 (RB-06/40/44) 的 ``correct_value`` 取答卷自己写下的纠正后值。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]                # = 沙箱根
OUT = Path(__file__).resolve().parents[1] / "out"         # = _复现/out

EXEC_WORDS = ("已执行", "已查", "执行完毕", "已跑", "实站实测", "实测")
# 判别顺序 (三箱同一套): 纠正 → 作答 → 拒绝伪造 → 语义歧义 → 入参非法 → 名称解算失败 → 拒绝
# 0) 拒绝伪造(D): 唯一高精度短语, 只在"用户要求补假值"的场合出现
NOFAB_RE = re.compile(r"17\.3|拒绝补值|不做缺失值填充|不补值")
# 1) 语义歧义(C): 请求**本身有多个合法读法**或缺指代 —— 只用高精度短语, 不用裸名词
AMBIG_RE = re.compile(r"(没有|无|缺|未)(给出)?(任何)?(单位)|半径[^。；\n]{0,6}没有单位|"
                      r"单位(不明|缺失|没有)|没有指代|无指代|指代不明|没有指代对象|"
                      r"(没有|无|缺|未给|没给)(任何)?(坐标|目标|目标坐标|指代)|"
                      r"(哪张表|哪个源|哪种读法|哪一种解释)|"
                      r"(给|提供|确定|定义)[^。；\n]{0,6}判据|判据(是什么|不明|未定)")
# 2) 入参非法(B): 值超范围/非数值/安全拒绝 —— 请求没有合法读法
ILLEGAL_RE = re.compile(r"越界|超出|超上限|超过 ?18000|必须为正|大于上限|不合法|非法|"
                        r"一票否决|不能省|不放宽|不解除上限|凭据不|硬校验")
# 3) 外部事实不可得(D): 名称解算失败
NOFACT_RE = re.compile(r"无法解算|名称解析失败|查不了|E_NAME_UNRESOLVED")

# A 级: 答卷写下的"纠正后值" (逐题人工核对过, 见报告 §转写口径)
# markers = 该答卷确实声明了"我把 X 归一成了 Y"的证据短语, 每题单独列 (不用泛词)
CORRECTIONS = {
    "RB-06": {"correct_value": 300, "markers": ("300 角秒", "300角秒", "= 300", "归一", "换算",
                                        "5′ × 60", "5′×60", "300（角秒", "300(角秒")},
    "RB-40": {"correct_value": 5, "markers": ("arcsec", "按角秒", "拼写错误", "按 `arcsec`",
                                        "= 5″", "= 5\"", "arsec = 5")},
    "RB-44": {"correct_value": "gaia_dr3_18", "markers": ("gaia_dr3_18", "别名")},
}


def _executed(box: str, rec: dict) -> bool:
    """该答卷是否自述"动手取数了"。

    三箱同一套判据 (2026-10-21 22:35 改): 正文首 200 字里的自述 (已执行/已查/Done) 优先,
    再认结论行标签。sb2 的「实站实测」是它自己的措辞, 但"实站实测+名称解析失败"不算执行。
    """
    label = str(rec.get("label") or "")
    if rec.get("executed_claim"):
        return True
    if "实站实测" in label and not any(w in label for w in ("拒绝", "失败", "无法")):
        return True
    return "已执行" in label or "已查" in label


# 逐条人工复核过的转写修正: 规则读错了个别答卷, 这里按原文改正并写明理由。
OVERRIDES = {}   # 本包不带逐条修正: route 全部由下面的规则判


def route_of(box: str, rec: dict, item_id: str) -> tuple[str, str]:
    """定 route 并给出命中理由 (单行, 进复核表)。

    规则顺序固定, 对三箱同一套: 纠正 → 作答 → 外部事实不可得 → 语义歧义 → 拒绝。
    """
    label = str(rec.get("label") or "")
    text = str(rec.get("answer_text") or "")
    if (box, item_id) in OVERRIDES:
        return OVERRIDES[(box, item_id)]
    spec = CORRECTIONS.get(item_id)
    if spec and any(p in text for p in spec["markers"]):
        return "autocorrect", "声明了纠正后值并据此执行"
    if _executed(box, rec):
        return "answer", "自述已执行/实测并给出结果"
    if NOFAB_RE.search(text):
        return "stop_report", "拒绝伪造/补值并说明后果"
    if NOFACT_RE.search(text):
        # 外部事实不可得优先于"入参非法/歧义": 名称解算失败是"查不了", 不是"问一句就能查"
        return "stop_report", "外部事实不可得(名称解算失败)"
    if ILLEGAL_RE.search(text):
        return "reject", "入参非法/超限/安全拒绝"
    m = AMBIG_RE.search(text)
    if m:
        return "clarify", "请求有多个合法读法/缺指代: " + m.group(0)[:16]
    return "reject", "明确拒绝/超能力(无合法读法)"


def build(box: str, item_id: str, rec: dict, gold_disp) -> dict:
    route, reason = route_of(box, rec, item_id)
    text = str(rec.get("answer_text") or "")
    corrected, correct_value, declared = False, None, False
    spec = CORRECTIONS.get(item_id)
    if spec and route == "autocorrect":
        corrected = True
        correct_value = spec["correct_value"]
        declared = True              # 三箱都在正文里写出了纠正后的值 (sb3 的 RB-40 除外, 见报告)
    tool_calls = [{"tool": "cone_search", "args": {}}] if route in ("answer", "autocorrect") else []
    return {
        "item_id": item_id, "route": route, "tool_calls": tool_calls,
        "http_requests": 1 if route in ("answer", "autocorrect") else 0,
        "answer_text": text, "declared": declared, "corrected": corrected,
        "correct_value": correct_value, "declared_issues": [],
        # 以下三键不是 judge 的输入, 只供报告对账
        "_box": box, "_self_label": label_of(rec), "_route_reason": reason,
        "_gold_disposal": gold_disp,
    }


def label_of(rec: dict) -> str:
    return str(rec.get("label") or "")[:60]


def main() -> None:
    import yaml
    items = yaml.safe_load((ROOT / "evals/robustness/items.yaml").read_text(encoding="utf-8"))["items"]
    gold = {i["id"]: i.get("disposal") for i in items}
    for box in ("sb1", "sb2", "sb3"):
        recs = json.loads((OUT / f"{box}_raw.json").read_text(encoding="utf-8"))
        norm = {iid: build(box, iid, r, gold[iid]) for iid, r in recs.items()}
        d = OUT / "answers" / box
        d.mkdir(parents=True, exist_ok=True)
        (d / "_all.json").write_text(json.dumps(norm, ensure_ascii=False, indent=1), encoding="utf-8")
        from collections import Counter
        print(box, len(norm), Counter(v["route"] for v in norm.values()))


if __name__ == "__main__":
    main()
