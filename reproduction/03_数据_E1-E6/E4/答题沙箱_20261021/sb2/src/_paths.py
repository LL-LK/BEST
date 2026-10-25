"""src._paths — skill 根目录解析的**唯一实现** (全仓路径解析真源)。

能力边界: 只做一件事 —— 从调用点自己的 ``__file__`` 定位 skill 根。不读
manifest 内容, 不拼输出路径, 不做校验 (那些是协议层/落盘层的职责)。

为什么值得单独成件 (R4-03): 定位 skill 根 (逐级上溯找 ``manifest.yaml``) 这段
逻辑曾在三处各抄一份 —— ``src/kb/__init__.py`` / ``src/models/output.py`` /
``src/knowledge_slots.py``。三份的**兜底层数并不相同** (前两处
``parents[2]``, 第三处 ``parents[1]``), 因为它们各自的文件深度不同, 于是
"同一个根"在每处都被写成一个与其**所在层数耦合**的魔数。

耦合层数正是这份债的实质: 副本与真源一旦分叉 (将来根目录多一层, 或某个件被
挪进子目录), 会有**一份**解析到错误目录, 而且**静默** —— 错根不会抛错, 只会
让该调用面读到空清单 (``list_references() == []`` 这类形态历史上真的发生过,
见 ``docs/CODE-QUALITY-FIX-LIST.md`` Q-55)。三处各自使用时也没有任何交叉
校验能发现分叉。

收敛口径: skill 根 = **含 ``src/`` 的那一级的父目录**。于是兜底不再需要逐调用
点写死层数 —— 一条基于目录名的规则同时覆盖任意深度的调用点, 且与三处各自原
来的兜底值**逐一致** (本轮收敛为纯移动, 不改任何解析结果)。

为什么真源放在这里而不是 ``src/serialization.py``: 序列化层与路径解析无关,
把无关关注点塞进去等于换一个耦合; 也不放 ``src/models/output.py`` —— 那会让
``src.kb`` 反向依赖模型层。
"""
from __future__ import annotations

# 标准库: pathlib 做跨平台路径上溯与存在性判定
from pathlib import Path

# skill 根标志文件: 逐级上溯时首个含它的目录即 skill 根 (不靠写死层数, Q-39)
SKILL_MARKER = "manifest.yaml"

# 兜底锚点目录名: 含它的目录之**父**即 skill 根 (比层数耐漂移)
SOURCE_DIR_NAME = "src"


def skill_root(source_file: Path | str) -> Path:
    """从 ``source_file`` 逐级上溯定位 skill 根目录。

    Args:
        source_file: 调用点自己的 ``__file__`` (它决定上溯起点, 故本函数
            不需要知道调用方在第几层)。

    Returns:
        skill 根的绝对路径。标志文件缺失时先退回"含 ``src/`` 的那一级的父
        目录", 再不济按上跳一级 —— **任何形态都返回确定路径**: 既不返回
        ``None`` (免得每个调用点各自发明一套"取不到怎么办"), 也不抛异常。

    Raises:
        不抛。文件直接位于盘符根时 (``C:/manifest.yaml``, 它的 ``parents``
        只有一项) 没有"上一级"可取, 此时返回能取到的最高一层 (该根本身),
        而不是让 ``parents[1]`` 越界抛 IndexError。

    Note:
        ``resolve()`` 先消符号链接: 软链部署时否则会从错误位置起算。
        两段上溯都逐级走 ``parents``, 故深链、软链、盘符大小写都按解析后的
        绝对路径判定, 不依赖调用方写法。
    """
    resolved = Path(source_file).resolve()  # 先消符号链接: 软链部署下否则从错误位置起算
    for parent in resolved.parents:  # 主路径: 逐级上溯找标志文件, 命中即停
        if (parent / SKILL_MARKER).is_file():
            return parent  # 首个命中即停: 再往上没有意义
    for parent in resolved.parents:  # 兜底一: 按目录名定位而非层数, 一条规则覆盖所有深度的调用点
        if parent.name == SOURCE_DIR_NAME:
            return parent.parent  # src/ 所在目录的父即 skill 根
    # 兜底二: 源码不在任何 src/ 下 (裁剪克隆), 上跳一级给出确定值而非 None。
    # 两段上溯都没命中时**不能**无条件取 parents[1]: 文件直接位于盘符根
    # (parents 长度为 1) 会越界抛 IndexError, 与上面"任何形态都返回确定
    # 路径、不抛"的承诺相反。故逐层退到"能取到的最高一级"。
    if len(resolved.parents) > 1:
        return resolved.parents[1]  # 常规形态: 上跳一级 (与三处调用点原兜底值逐一致)
    return resolved.parents[0] if resolved.parents else resolved  # 文件在盘符根: 上面没有层可上跳, 返回该根本身
