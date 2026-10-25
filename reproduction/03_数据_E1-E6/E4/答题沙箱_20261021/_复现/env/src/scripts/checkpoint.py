"""src.scripts.checkpoint — Checkpoint/resume for long-running downloads.

能力边界: DownloadCheckpoint: 断点续传状态持久化。边界: 状态目录 .checkpoints/ (gitignored); job_id 必须是无目录成分的文件名 (resolve_within 统一校验, 拒绝对路径/盘符/斜杠/..)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (checkpoint 锚点)。
"""

from __future__ import annotations

# 标准库: JSON 序列化/日志/路径/类型标注
import json
import logging
from pathlib import Path
from typing import Any, Optional

# 本地: I/O 协议层两个单点实现 — 原子落盘 + 目录锚定 (防路径逃逸)
from src.scripts.guards import atomic_write_text, resolve_within

logger = logging.getLogger(__name__)  # 模块级 logger: 坏检查点告警不混进别的模块


class DownloadCheckpoint:
    """断点续传检查点管理器 (job 级状态持久化)。

    状态落在 ``.checkpoints/`` 目录 (gitignored); 每个 job 一个 JSON 文件,
    写走原子替换, 读容忍损坏 (坏文件视为无检查点, 调用方重下而不是崩)。
    """

    def __init__(self, checkpoint_dir: str = ".checkpoints") -> None:
        """构造管理器并确保状态目录存在。

        Args:
            checkpoint_dir: 检查点目录 (默认 ``.checkpoints``, 已在 git 忽略)。
        """
        self.checkpoint_dir = Path(checkpoint_dir)  # 规整成路径对象: 三个方法都拿它做锚定与拼接
        # IO 点: 建状态目录 (批量任务开始前的一次性准备)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)  # 构造期建目录: 省掉每个作业方法里的存在性判断

    def _path(self, job_id: str) -> Path:
        """把 ``job_id`` 锚定成检查点目录内的 ``<job_id>.json`` 路径。

        Windows 逃逸教训: 旧防线只查路径parts里有没有 ``..``; 在 Windows 上
        绝对路径 ``C:/evil.json`` 会整体替换根, 静默逃出目录而不被察觉。
        ``resolve_within`` 对绝对路径/盘符/分隔符/``..`` 一律拒绝, 只放行
        裸文件名。
        """
        raw = str(job_id)  # 先字符串化: 非字符串标识也走同一套锚定检查
        if not raw or set(raw) <= {"."}:  # 拒绝空串与 ".."/"." 这类纯点串
            raise ValueError(f"invalid checkpoint job id: {job_id!r}")
        if not raw.endswith(".json"):  # 统一补扩展名: 列作业时才能按主干名反向还原出标识
            raw = f"{raw}.json"  # 扩展名在此统一补齐, list_jobs 的反向还原才成立
        return resolve_within(self.checkpoint_dir, raw)  # 锚定后仍含目录成分即拒, 绝不写出状态目录

    def save(self, job_id: str, state: dict[str, Any]) -> str:
        """保存检查点 (原子写 + 路径锚定, 不会写出检查点目录)。

        Args:
            job_id: 任务标识 (必须是裸文件名, 不能带路径成分)。
            state: 检查点状态 (任意可 JSON 序列化的 dict)。

        Returns:
            检查点文件路径 (字符串)。
        """
        path = self._path(job_id)  # 先锚定再落盘: 非法标识在此就抛, 绝不写到状态目录外
        # IO 点: 原子落盘 (tmp + os.replace); 读者不会看到半写状态
        atomic_write_text(path, json.dumps(state, indent=2), encoding="utf-8")  # 缩进两格: 检查点要给人看, 崩溃后能手工排查
        return str(path)

    def load(self, job_id: str) -> Optional[dict[str, Any]]:
        """读取检查点 (Rule 12 防线三 BOM 兼容)。

        检查点损坏或不可读时返回 ``None`` — 调用方据此重下, 而不是让整个
        任务崩在 ``JSONDecodeError`` 上。job_id 非法同样返回 None (非法 id
        本就不存在检查点, 不该让调用方崩)。

        Args:
            job_id: 任务标识。

        Returns:
            检查点状态 dict; 缺失/损坏/非法 id 时 None。
        """
        try:
            path = self._path(job_id)  # 锚定可能抛值错误: 由下面的 except 收成无检查点
        except ValueError:
            # 不可用 id 本就没有检查点; 这里返回 None 而不是抛错, 让调用方按
            # "无断点, 从头下载"处理 (打错 id 不该让整个批次崩掉)
            return None
        if not path.exists():  # 先判存在: 直接 open 会让缺失走成异常路径
            return None  # 缺失即"无检查点", 与损坏同义: 调用方一律重下
        try:
            # IO 点: utf-8-sig 读取, 兼容带 BOM 的 Windows 编辑器产物
            with open(path, "r", encoding="utf-8-sig") as f:  # 用带 BOM 兼容的编码: Windows 编辑器写出的检查点也能读
                return json.load(f)  # 解析失败不入此路径, 由下面的 except 收口
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable checkpoint %s: %s", path, exc)  # 只记路径与异常, 不记 state 内容
            return None

    def delete(self, job_id: str) -> bool:
        """删除检查点 (任务完成后的清理; 文件不存在时返回 False)。

        Args:
            job_id: 任务标识。

        Returns:
            True 表示确实删除了文件, False 表示本来就没有。
        """
        path = self._path(job_id)  # 同样先锚定: 删除同样不许写出状态目录
        if path.exists():  # 存在才删: 不存在不是错误, 只表示无可清理
            # IO 点: 删除检查点文件
            path.unlink()  # 删的是检查点文件本身: 状态目录留给其它作业
            return True  # 真删掉了才报 True
        return False  # 本来就没有: 不是错误, 只表示"无可清理"

    def list_jobs(self) -> list[str]:
        """列出检查点目录下所有可恢复的 job_id (去掉 .json 后缀, 排序)。

        还原自 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) (扁平化时丢失)。用途是**人工复核面**: 长跑
        批任务中断后, 运维需要一眼看到"有哪些任务可以接着跑", 而不是去翻
        ``.checkpoints/`` 目录里的文件名。只返回文件名, 不读取内容 — 目录
        里可能有写坏的文件, 列举不应因此失败。
        """
        if not self.checkpoint_dir.is_dir():  # 目录不在就当没有作业: 列举不该因目录缺失而失败
            return []  # 目录不存在即"无可恢复任务"
        return sorted(
            path.stem for path in self.checkpoint_dir.glob("*.json") if path.is_file()  # 只取文件名主干: 不读内容, 写坏的文件不该让列举失败
        )  # stem 去 .json; 只列名不读内容, 写坏的文件不该让列举失败
