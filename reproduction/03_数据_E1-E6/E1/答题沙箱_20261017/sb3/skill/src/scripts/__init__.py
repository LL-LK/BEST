"""src.scripts — Agent 调用入口 (CLI 脚本与共享 IO/checkpoint/config/context)。

职责: 脚本入口层的聚合门面。用 PEP 562 的模块级 ``__getattr__`` 把 CLI 脚本
(cone_search / crossmatch / multiband 导出) 与共享设施 (checkpoint / config /
context / guards) 汇成一个可 ``from src.scripts import X`` 的命名空间, 而
不引入 eager import 链。

所属子系统: 位于 src/ 的最外层, 是 Agent 侧唯一的脚本入口。向上被 Agent /
CLI 调用, 向下分发到 src/tap (查询)、src/core (后处理)、src/scripts 各叶子
模块。中间不再经过别的聚合层 —— 它就是边界本身。

对外接口 (12 个符号, 全部是外部可依赖的 seam):
- ``cone_search``: 单次锥形检索, 返回归一化源行。
- ``crossmatch_coords`` / ``crossmatch_with_gaia`` / ``crossmatch_with_ps1``:
  坐标与指定星表 (Gaia/PS1) 的交叉匹配。
- ``batch_export_multiband_photometry`` / ``export_multiband_photometry``:
  单目标与批量多波段测光导出。**批量版无断点续跑**: best_multiband_export 的批量
  分支只是 for sid 逐个 try/except, 未接 ``DownloadCheckpoint``, 中断后只能整批重跑;
  要断点续跑请走单目标版 + ``DownloadCheckpoint``。
- ``DownloadCheckpoint``: 下载进度检查点 (崩溃后按行续跑)。
- ``BestConfig``: 脚本层配置载体 (端点/配额/路径)。
- ``QueryContext``: token 预算与查询审计载体。
- ``to_csv`` / ``to_json`` / ``validate_coordinate``: 输出格式化与入参校验。

依赖与数据流: 只依赖标准库 ``importlib`` (惰性导入) 与本仓叶子模块。数据流
全部在**进程内内存**: 调用方的查询参数进, 归一化源行与导出文件出; 落盘只
经叶子模块的 atomic_write_text, 不跨进程。

关键契约与不变量:
- ``_EXPORTS`` 是公开面的唯一白名单: ``__getattr__`` 只解析表内名字, 表外
  名字必须抛 AttributeError, 否则拼错的符号会变成"某次误 import 成功"。
- 惰性是**性能与解耦**双约束, 不是偷懒 (见下方注释), 不可改回 eager import。
- 属性名到 (模块, 符号) 的映射必须一一对应; 一个名字只能来自一个模块, 否则
  同名符号的替换会静默改变行为。

陷阱与边界: 新增能力时只改 ``_EXPORTS`` + 对应叶子的 ``__all__``, 不要在这里
写实现; 另外, 惰性导出意味着 "import 这个包" 不再等于 "这些模块已加载",
需要在 import 期就触发副作用的模块绝不能挂进本门面。
"""

# 为什么惰性导出 (PEP 562):
#   旧版 eager import 链 ``best_cone_search -> src.client -> src.scripts.guards``
#   把整个 CLI 层拖进 client 的模块加载期, 逼得 ``src/client.py`` 只能把
#   校验器塞进函数体内延迟导入 (自我声明式的绕环补丁)。改用模块级
#   ``__getattr__`` 惰性导出后, ``from src.scripts.guards import ...`` 不再牵出
#   叶子模块, client 层可以在模块顶层正常 import 它们。
#   ``__getattr__`` 首次访问时才 importlib.import_module (模块有 sys.modules
#   缓存, 不会重复加载), 之后属性访问零额外开销。

__all__ = [  # 必须与下方 _EXPORTS 严格同步: 少列会让 import * 静默丢能力
    "cone_search",
    "crossmatch_coords",
    "crossmatch_with_gaia",
    "crossmatch_with_ps1",
    "batch_export_multiband_photometry",
    "export_multiband_photometry",
    "DownloadCheckpoint",
    "BestConfig",
    "QueryContext",
    "to_csv",
    "to_json",
    "validate_coordinate",
]

# 属性名 -> (模块, 符号): 公开面白名单, __getattr__ 只解析表内的名字
_EXPORTS = {  # 一个名字只能来自一个模块, 否则同名符号替换会静默改变行为
    "cone_search": ("src.scripts.best_cone_search", "cone_search"),
    "crossmatch_coords": ("src.scripts.best_crossmatch_pipeline", "crossmatch_coords"),
    "crossmatch_with_gaia": ("src.scripts.best_crossmatch_pipeline", "crossmatch_with_gaia"),
    "crossmatch_with_ps1": ("src.scripts.best_crossmatch_pipeline", "crossmatch_with_ps1"),
    "batch_export_multiband_photometry": ("src.scripts.best_multiband_export", "batch_export_multiband_photometry"),
    "export_multiband_photometry": ("src.scripts.best_multiband_export", "export_multiband_photometry"),
    "DownloadCheckpoint": ("src.scripts.checkpoint", "DownloadCheckpoint"),
    "BestConfig": ("src.scripts.config", "BestConfig"),
    "QueryContext": ("src.scripts.context", "QueryContext"),
    "to_csv": ("src.scripts.guards", "to_csv"),
    "to_json": ("src.scripts.guards", "to_json"),
    "validate_coordinate": ("src.scripts.guards", "validate_coordinate"),
}


def __getattr__(name: str):  # PEP 562 钩子: 首次访问属性时才触发, import 期不执行
    """首次访问属性时才导入并返回符号 (importlib 有模块缓存, 不重复加载)。"""
    target = _EXPORTS.get(name)  # 表外名字取到 None, 下一行走 fail-closed 分支
    if target is None:                                                                       # 取不到目标即不委派: 静默跳过会被读成"跑了但没结果"
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")  # 报错即契约: 不静默回落
    # 惰性导入: 只在首次访问该符号时才真正加载目标模块 (缩短 import 时延)
    import importlib

    module = importlib.import_module(target[0])  # 模块路径由 _EXPORTS 白名单决定, 不可外部注入
    return getattr(module, target[1])  # 从目标模块取符号本体, 本层不加任何包装


def __dir__() -> list[str]:  # 让 dir(本包) 列出惰性门面暴露的全部名字
    """Tab 补全面 (惰性导出名 + 本模块已有全局名)。"""
    return sorted(set(__all__) | set(globals()))  # 两侧取并集: 补全不缺表内名也不漏全局名
