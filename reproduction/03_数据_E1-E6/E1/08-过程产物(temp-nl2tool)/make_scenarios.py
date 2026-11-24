# -*- coding: utf-8 -*-
"""改分情景推演: 构造"修好之后"的轨迹, 交真判分器打分。

只用于回答"改哪里才有机会通过", 不是模型成绩。
情景定义:
  base   —— 原样 (对照组)
  fix16  —— NL2T-16 补 columns 参数 + 去掉多余的 describe_catalog
  clar0720 —— NL2T-07 / NL2T-20 的澄清措辞对齐 probes (点明缺失维度并给出选项)
  over6  —— 6 道过度澄清题改成按标注正确调用
  over4  —— 只改其中 4 道 (toolset 刚好过 0.90 的下限组合)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = ROOT / "evals" / "nl2tool" / "tasks.yaml"
PRIMERS_PATH = ROOT / "evals" / "nl2tool" / "context_primers.yaml"
SRC = ROOT / "temp" / "nl2tool" / "traces-live-2026-10-06"

RESOLVED = {  # 标注占位符 + 上下文前缀台账都没有的运行时值: 给一组合理具化值
    "<1000 个 {ra, dec, id?} 对象的数组>": [[180.0, 30.0, f"obj{i}"] for i in range(1000)],
    "<resolved_ra>": 10.6847,
    "<resolved_dec>": 41.2690,
    "<用户给定的天体名>": "M31",
    "<上一步返回的 sqlid, 形如 s3898 或 3898>": "s3898",
    "<上一次查询返回的 sqlid>": "ps1_20261004_ab12cd34",
}

FIXED_ANSWERS = {
    "NL2T-07": (
        "BEST 的 12 张可查表里没有 ZTF 星表; ZTF 只作为测光系统出现在标准星交叉表里。"
        "要哪一种? 选项一: scr_galah / scr_lamost 的实测交叉列 gztf/rztf/iztf;"
        "选项二: xpsp 的 ztf_g_g_xpsp/ztf_r_r_xpsp/ztf_i_i_xpsp (Gaia XP 光谱拟合的"
        "合成测光, 不是 ZTF 实测星等)。另外工具面没有按 Gaia DR3 source_id 直接取源"
        "的能力, 需先经 CDS Sesame 把名字解算成坐标再按坐标检索, 是否接受?"
    ),
    "NL2T-20": (
        "这个字段指代不明: 请指明是哪个星表的哪一列, 具体是 stripe82_gnobs、"
        "stripe82_gmmed 还是 ps1_gpsf? 在确认之前我不能判断它代表逐历元星等。"
    ),
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    tasks = {t["id"]: t for t in yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]}
    primers = yaml.safe_load(PRIMERS_PATH.read_text(encoding="utf-8"))["primers"]
    base = {}
    for p in sorted(SRC.glob("*.json")):
        tr = load_json(p)
        base[tr["task_id"]] = tr

    def golden_calls(tid: str) -> list[dict]:
        """按 expect_tools 造出正确调用序列 (占位符按台账/具化表落地)。"""
        binds = (primers.get(tid) or {}).get("bindings") or {}
        calls = []
        for item in tasks[tid].get("expect_tools") or ():
            args = {}
            for key, val in (item.get("args") or {}).items():
                if isinstance(val, str) and val.startswith("<"):
                    if isinstance(binds.get(key), (int, float, str)):
                        args[key] = binds[key]
                    else:
                        args[key] = RESOLVED.get(val, val)
                else:
                    args[key] = val
            calls.append({"tool": item["tool"], "args": args})
        return calls

    OVER = ["NL2T-05", "NL2T-06", "NL2T-08", "NL2T-09", "NL2T-14", "NL2T-21"]
    over_answer = {
        "NL2T-05": "1000 个坐标一次性提交服务端 proximity 匹配: crossmatch_batch(coords=..., catalog=ps1, radius_arcsec=3.0, nearest_only=true, max_rows=50000)。coords 内联, 不需要先上传建 job。",
        "NL2T-06": "先 cone_search 建查询会话拿 sqlid, 再 count 取服务端真实总数, 据此决定是否续拉。天区沿用上文的 RA=180.0、Dec=30.0、半径 60 角秒, 表按 ps1。",
        "NL2T-08": "用上文会话 sqlid=ps1_20261004_ab12cd34 走幂等分页 GET: fetch_page(sqlid=..., page=2, page_size=1000, catalog=ps1, max_rows=1000)。",
        "NL2T-09": "先 resolve_name(name=\"M31\") 把名字解算成坐标, 再 cone_search 查 std 组成员表 scr_galah (radius_arcsec=3.0, nearest_only=true)。失败哨兵 -1000 不当坐标用。",
        "NL2T-14": "12h30m00s = 12.5h × 15 = 187.5 度, +20°00′00″ = 20.0 度: cone_search(ra=187.5, dec=20.0, radius_arcsec=60, catalog=ps1, max_rows=1000)。半径按 60 角秒兜底。",
        "NL2T-21": "星等越小越亮: cone_search(sort=ps1_rpsf, order=asc, nearest_only=true) 取首席即最亮源。避免因 sort 用 desc 而把 -1000 哨兵排到最前。",
    }

    def build(name: str, **flags) -> Path:
        out = ROOT / "temp" / "nl2tool" / f"scenario-{name}"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for tid, tr in base.items():
            t = json.loads(json.dumps(tr))  # 深拷贝: 不动原轨迹
            if flags.get("fix16") and tid == "NL2T-16":
                t["tool_calls"] = golden_calls(tid)
                t["answer_text"] = (
                    "S-PLUS 对应可查表是 splus_dr4; r 波段的权威列是全限定名 "
                    "splus_dr4_r_pstotal (与 ps1 的 ps1_rpsf、uss_dr1 的 r 都不同), "
                    "已写进调用参数。按 RA=180.0、Dec=30.0、半径 60 角秒检索。"
                )
            if flags.get("clar") and tid in FIXED_ANSWERS:
                t["answer_text"] = FIXED_ANSWERS[tid]
            pick = None
            if flags.get("over6"):
                pick = OVER
            elif flags.get("over4"):
                pick = ["NL2T-05", "NL2T-06", "NL2T-14", "NL2T-21"]
            if pick and tid in pick:
                t["tool_calls"] = golden_calls(tid)
                t["answer_text"] = over_answer[tid]
                t["route"] = "answer"
            (out / f"{tid}.{name}.json").write_text(
                json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    scenarios = [
        ("base", {}),
        ("fix16", {"fix16": True}),
        ("clar", {"clar": True}),
        ("fix16_clar", {"fix16": True, "clar": True}),
        ("fix16_clar_over4", {"fix16": True, "clar": True, "over4": True}),
        ("all", {"fix16": True, "clar": True, "over6": True}),
    ]
    for name, flags in scenarios:
        path = build(name, **flags)
        print(f"{path}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
