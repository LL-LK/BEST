#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_pages.py — syn_huge 快照的 3700 行确定性页面生成器 (可重跑, 幂等)。

能力边界: 只生成 ``pages/page_000N.csv`` 与 ``rows_full.csv`` (E2 §5 场景 8
超大查询的回包原文); count.json / phase1.html / snapshot.yaml / manifest.json
由快照构建流程另行写入, 本脚本不碰。

确定性规则 (同样输入永远得到同样字节, 供 E6 可复现性与回放对账):
  - 行号 ``i`` 从 0 到 3699 (共 3700 行, page_size=1000 → 4 页:
    page_0001..page_0003 各 1000 行, page_0004 700 行);
  - ``ps1_source_id`` = ``BEST_SYN_%04d`` (零填充 4 位, 行序即主键序);
  - ``ps1_ra`` = 180.0 + i * 1e-4 (格式 ``%.6f``, 9 位有效数字, 满足
    E2 GT 的 precision_map: ra/dec ≥ 9 位);
  - ``ps1_dec`` 恒为 30.0;
  - ``ps1_rpsf`` = 18.0 + (i % 100) / 100.0 (格式 ``%.2f``, 18.00–18.99 循环);
  - ``ps1_snr`` 恒为 25.0;
  - **哨兵插入规则**: 每第 500 行 (``i % 500 == 499``, 即第 500/1000/…/3500 行)
    的 ``ps1_rpsf`` 改写为 ``-999.0`` (真实哨兵形态) — 共 7 个哨兵行,
    用于验证被测不会把哨兵当极暗星等纳入统计 (E2 M5 / E3 语义轴 D)。

形态保真 (照抄真实站点回包, 见 evals/groundtruth/snapshots/std_scr_galah_live):
  - UTF-8 BOM (``\\ufeff``);
  - ps1_ 前缀表头;
  - LF 行尾, 末行带换行。

用法 (在 skill 根目录):
    python evals/groundtruth/snapshots/syn_huge/gen_pages.py
"""
from __future__ import annotations

# 标准库: pathlib 定位快照目录 (以本文件位置为锚, 不依赖 cwd)
from pathlib import Path

# 快照目录 = 本文件所在目录 (pages/ 与 rows_full.csv 都落在这一层)
SNAP_DIR = Path(__file__).resolve().parent   # 以脚本自身位置为锚, 换机或换 cwd 都写到同一处
# 页容量与总行数 (E2 §5 场景 8: 3700 行 > 3 页, 用于测分页并集无重无漏)
PAGE_SIZE = 1000                  # 照抄站点真实分页容量, 改小会让 M4 结构判据的页数前提失效
TOTAL_ROWS = 3700                 # 故意不整除页容量, 逼出末页 700 行的残页分支
# 哨兵插入周期 (每 500 行 1 个 -999.0) 与哨兵取值 (真实形态)
SENTINEL_PERIOD = 500             # 7 个哨兵各自落在已知页内行位, 便于逐页人工核对
SENTINEL_VALUE = "-999.0"         # 用字面量而非算式: 哨兵必须是站点回包的原始字节形态
# 表头 (ps1_ 前缀, 与站点投影一致)
COLUMNS = ["ps1_source_id", "ps1_ra", "ps1_dec", "ps1_rpsf", "ps1_snr"]   # 列序即表头序, 与 ps1_ 投影一一对应


def gen_row(i: int) -> list[str]:
    """生成第 ``i`` 行 (0 起) 的字符串值; 纯函数, 无随机无时钟。

    Args:
        i: 行号 (0 <= i < TOTAL_ROWS)。

    Returns:
        与 ``COLUMNS`` 等宽的字符串列表; 哨兵行的 rpsf 为 ``-999.0``。
    """
    is_sentinel = (i % SENTINEL_PERIOD) == (SENTINEL_PERIOD - 1)   # 行号 0 起算, 故哨兵落在每段最后一行
    rpsf = SENTINEL_VALUE if is_sentinel else f"{18.0 + (i % 100) / 100.0:.2f}"   # 哨兵走字面量分支, 正常行走 %.2f 循环
    return [f"BEST_SYN_{i:04d}", f"{180.0 + i * 1e-4:.6f}", "30.0", rpsf, "25.0"]   # 五列与 COLUMNS 同序; ra 的 %.6f 保住 M2 要求的高有效位


def render_csv(rows: list[list[str]]) -> bytes:
    """把行集渲染成站点形态的 CSV 字节 (BOM + 表头 + LF 行尾 + 末行换行)。

    Args:
        rows: 数据行 (不含表头)。

    Returns:
        UTF-8 (带 BOM) 编码的 CSV 字节。
    """
    lines = ["\ufeff" + ",".join(COLUMNS)]   # BOM 挂在表头行首: 照抄站点回包, 解析端必须能吃下
    lines.extend(",".join(row) for row in rows)   # 自行拼行而非 csv 模块: 字段无逗号无引号, 少一层转义就少一处形变
    return ("\n".join(lines) + "\n").encode("utf-8")   # 末行补换行: 站点导出的收尾习惯, E6 字节级对账依赖它


def main() -> None:
    """生成 4 个分页文件与 rows_full.csv (幂等: 重跑覆盖写, 字节不变)。"""
    pages_dir = SNAP_DIR / "pages"              # 与 rows_full.csv 同层, 快照清单按固定相对路径取
    pages_dir.mkdir(parents=True, exist_ok=True)   # exist_ok: 重跑本脚本是正常操作, 不该因目录已存在报错
    all_rows = [gen_row(i) for i in range(TOTAL_ROWS)]   # 一次算全量再切页, 4 页与 rows_full.csv 才同源同序
    for page_index in range(0, (TOTAL_ROWS + PAGE_SIZE - 1) // PAGE_SIZE):   # 向上取整: 3700/1000 → 4 页
        chunk = all_rows[page_index * PAGE_SIZE:(page_index + 1) * PAGE_SIZE]   # 切片而非流式: 全量在内存, 重跑代价可忽略
        target = pages_dir / f"page_{page_index + 1:04d}.csv"   # 四位零填充页号, 与站点回包命名一致
        target.write_bytes(render_csv(chunk))   # 覆盖写: 幂等的前提, 同输入必得同字节
        print(f"wrote {target.relative_to(SNAP_DIR)}: {len(chunk)} rows")   # 自证输出: 行数对不上先看这里
    full = SNAP_DIR / "rows_full.csv"
    full.write_bytes(render_csv(all_rows))   # 单文件全量供行级判据一次读完, 不必在调用方拼页
    print(f"wrote {full.relative_to(SNAP_DIR)}: {len(all_rows)} rows")


if __name__ == "__main__":
    main()   # 无参数: 全部决策由上面的常量决定, 保证重跑结果可复现
