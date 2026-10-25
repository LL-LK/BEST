# -*- coding: utf-8 -*-
"""evals._data — 跨实验共享数据字典加载件 (纯数据区的唯一代码入口)。

职责: 加载并校验仓库里仅有的两份跨实验共享数据字典 (哨兵值表 + 容差表),
让 E2/E3/E4/E5 的判定代码读同一个数, 而不是各自硬编码一个副本。

所属实验: 服务 E2 金标准一致性 (docs/eval-E2-groundtruth.md §4.4 把本目录
列为唯一允许被跨实验共享的文件), 并被 E3/E4/E5 间接消费; 本文件自身
不对应任何独立实验编号, 它是这些实验的公共底座而非第六个实验。

对外接口: ``load_null_sentinel()`` 读哨兵值字典并校验三个必需键;
``load_tolerances()`` 读容差表并校验两个必需键; ``DATA_DIR`` 暴露字典
所在目录, 供等价性测试拼夹具路径。

依赖与数据流: 输入是仓内 ``null_sentinel.yaml`` / ``tolerances.yaml``
两份随版本入库的纯数据文件, 由 ``evals.equivalence`` 的守卫比对同值;
产物只进内存 (经 lru_cache 缓存), 不落盘任何报告, 因为它的下游
指标件各自负责写 JSON/MD。

关键契约与不变量: fail-closed — 文件缺失或缺必需键一律抛异常, 绝不
回退默认值 (默认值会悄悄变成第二份真值, 之后所有阈值争议都无从查证);
纯数据区不含判定逻辑, 因此不涉及离线回放与 rate_limit, 也不允许
import 任何实验目录 — 零跨实验 import 铁律的例外只有本目录的纯数据字典,
其等价性由 ``evals/equivalence/`` 的断言守护。

陷阱与边界: 缓存只对同一进程有效, 改了 YAML 必须重启进程才生效, 测试
里若要读改后的值需先清 lru_cache; 字典用 safe_load 而非全量加载, 是因为
这些文件只该含标量与列表, 出现自定义标签说明数据文件被人手工改坏了。
"""
from __future__ import annotations

# 标准库: YAML 加载 + 路径锚定 + 简单缓存 (字典在进程内只读一次)
from functools import lru_cache
from pathlib import Path

import yaml

# 目录锚点取 resolve 后的父级: 走软链或相对路径启动时, __file__ 可能不含
# 完整前缀, 直接拼相对路径会在 pytest 的 rootdir 漂移下找不到字典文件
DATA_DIR = Path(__file__).resolve().parent  # 数据目录锚点: 两个 yaml 都挂它下面, 换机不用改路径


# 缓存而非每次重读: 字典在一次评测跑批内必须是同一个对象, 否则下游拿到的
# 副本可能被中途改写, 同一份报告会前后不一致 (maxsize=1 覆盖两套字典各一次)
@lru_cache(maxsize=1)
def load_null_sentinel() -> dict:  # lru_cache(maxsize=1): 全仓只读一次, 跑批里反复取不能每次重解析
    """读哨兵值字典 (evals/_data/null_sentinel.yaml); 缺失/损坏即抛。"""
    path = DATA_DIR / "null_sentinel.yaml"
    # 先判存在再读: 让人拿到的是"文件缺了"这种可定位的错, 而不是解析空串
    if not path.is_file():  # 缺文件即抛: 空哨兵表会让所有哨兵判据静默失效
        raise FileNotFoundError(f"哨兵字典缺失: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # 三个必需键是哨兵语义的最小契约: 阈值决定何时算"值没解析出来",
    # 失败哨兵是唯一允许的替身值, 豁免列是这些列不参与哨兵比较的名单
    for key in ("threshold", "name_resolve_fail_sentinel", "exempt_columns"):
        if key not in data:  # 逐键校验: 少一个键就抛, 不给"部分可用"的半截表
            raise ValueError(f"哨兵字典缺必需键: {key}")
    return data


@lru_cache(maxsize=1)
def load_tolerances() -> dict:  # 同上, 容差表也只加载一次: 判定侧与报告侧必须读到同一份
    """读容差表 (evals/_data/tolerances.yaml); 缺失/损坏即抛。"""
    path = DATA_DIR / "tolerances.yaml"
    if not path.is_file():  # 缺文件即抛: 容差表没了就只能退回严格相等, 那不是我们要的口径
        raise FileNotFoundError(f"容差表缺失: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # 字段表与单位表缺一不可: 数值容差按字段给, 量纲换算按单位给,
    # 只补一半会让剩下的比较悄悄退回严格相等
    for key in ("fields", "units"):
        if key not in data:
            raise ValueError(f"容差表缺必需键: {key}")
    return data
