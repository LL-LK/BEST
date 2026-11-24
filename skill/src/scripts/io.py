"""src.scripts.io — [deprecated shim] 已迁移到 src.scripts.guards (P0 命名整改)。

职责: 纯转发层, 把旧名 ``src.scripts.io`` 下的 9 个守卫符号原样再导出到
``src.scripts.guards``。本文件不含任何实现, 登记二期删除 —— 存在的唯一理由
是让已经写了 ``from src.scripts.io import to_csv`` 的外部调用方不必同步改。

所属子系统: 位于 src/ 的脚本入口层最末端, 是已废弃的命名别名。上游是
Agent 侧旧导入路径与 test/unit 下的历史测试; 下游是 :mod:`src.scripts.guards`
里那份权威实现, 本模块不复制逻辑, 因此行为永远与权威实现一致。

对外接口: 9 个 re-export 符号 —— ``validate_coordinate`` / ``validate_search_radius`` /
``validate_adql_query`` (入参校验)、``to_csv`` / ``to_json`` (输出格式化)、
``resolve_within`` / ``resolve_data_path`` (路径锚定)、``atomic_write_text``
(落盘原子性)、``validate_external_url`` (下载 URL 主机白名单)。全部是外部可
依赖的 seam: 名字虽然转发, 但对外承诺的语义 (尤其白名单与原子写) 与
:mod:`src.scripts.guards` 完全等同。

依赖与数据流: 唯一依赖是 ``from src.scripts.guards import ...`` 这一条
import, 内存内直连, 不跨进程。**本模块自己不发 IO** —— 真正的读写都发生在
被转发的 guards 实现里。

关键契约与不变量:
- 再导出必须保持 ``__all__`` 与实际导入的符号一一对应, 否则 ``from ... import *``
  与静态类型检查会在调用方侧失配。
- 转发层不得添加任何包装逻辑 (不 try/except、不改签名): 包装会让
  ``src.scripts.io`` 与 ``src.scripts.guards`` 的行为出现分叉, 而分叉的
  报错现场只会指向本文件, 极难定位到真正的权威实现。

陷阱与边界: 更名原因是职责名不符 —— "io" 空泛, 实际职责是入参校验 + 输出格式化
+ 路径锚定 + 下载 URL 白名单, 即"守卫"层。新增能力一律加到
:mod:`src.scripts.guards`, 不要在这里加, 否则等于复活了这个废弃 shim。
"""
# 本地: 新模块的 9 符号再导出 (P0 兼容 Shim; 新代码直接用 src.scripts.guards)
from src.scripts.guards import (  # noqa: F401
    atomic_write_text,  # 原子写: 同目录临时文件 + replace, 防半写残卷
    resolve_data_path,  # 数据文件路径锚定: 越出 skill 根即拒绝
    resolve_within,  # 相对路径解析 + 根内校验 (resolve_data_path 的底座)
    to_csv,  # 行记录 -> CSV 文本 (含公式注入消毒)
    to_json,  # 行记录 -> JSON 文本 (ensure_ascii=False)
    validate_adql_query,  # ADQL 语法与白名单校验, 拦在发请求之前
    validate_coordinate,  # 坐标值域校验 (ra/dec 越界即 ValueError)
    validate_external_url,  # 下载 URL 主机白名单 (防 SSRF 打到非 BEST 站点)
    validate_search_radius,  # 检索半径校验 (必须为正且不超上限)
)

__all__ = [                                                                 # 公开面清单: 列在此处的符号都是对外契约, 表外名字必须抛 AttributeError
    # __all__ 必须与上面那条 import 的符号严格一一对应: 少列会让 `import *`
    # 静默丢掉能力, 多列会在静态检查侧报不存在的属性
    "atomic_write_text",
    "resolve_data_path",
    "resolve_within",
    "to_csv",
    "to_json",
    "validate_adql_query",
    "validate_coordinate",
    "validate_external_url",
    "validate_search_radius",
]
