# -*- coding: utf-8 -*-
"""drawio_io.py — .drawio 落盘的共用出口 (剥离构建库写入的外来工具元数据)。

为什么需要这一层: ``drawio_builder`` 的 ``DrawioFile.save()`` 会在 ``<mxfile>``
根元素上写死 ``host="app.diagrams.net"`` / ``agent="Antigravity/DrawioAuthor"``
/ ``version="24.0.0"`` / ``type="device"`` 四个属性 (构建库 ``to_xml()`` 的
硬编码)。这些是**构建库自带的工具元数据**, 不是本项目的发布版本号, 但留在
受跟踪产物里有两个坏处:

1. ``version="24.0.0"`` 是一段三段式版本号字面量, 与仓库铁律 3 (全仓不得
   出现发布版本号) 口径冲突, 版本号清扫脚本会反复误报它;
2. ``agent`` 写明另一个工具的名字, 读者会误以为本套图由那个工具维护。
3. 构建库在 Windows 上写出 CRLF 行尾, 而 ``.gitattributes`` 对 ``*.drawio``
   规定 ``eol=lf`` — 不归一会让工作树文件与克隆机不一致, git 每次 touch
   都会报 "CRLF will be replaced by LF"。

``save_clean()`` 落盘后做两件事: 把 ``<mxfile>`` 根标签的属性全部剥掉, 只留
标签本身 — draw.io 桌面端打开根图不需要任何属性; 再把行尾统一成 LF — 构建库
在 Windows 上写出 CRLF, 而 ``.gitattributes`` 对 ``*.drawio`` 规定 ``eol=lf``
(提交时 CRLF 会被规范化成 LF, 克隆机拿到的是 LF), 不归一会让工作树文件与
克隆机不一致, 并让 git 每次 touch 都报 "CRLF will be replaced by LF"。

两步都是确定性的 (每次都剥成同一形态), 因此「生成器重产出 == 受跟踪产物」
的逐字节比对门禁不受影响; 反过来, 若有人改用构建库的裸 ``save()``, 那道
门禁会立刻因根标签多出属性 (或行尾不一致) 而报红。
"""
from __future__ import annotations

# 标准库组:
#   re        — 匹配并剥离 <mxfile> 根开标签上的属性段
#   pathlib   — 落盘目标定位与类型标注
import re
from pathlib import Path

# <mxfile ...> 开标签 (只替换第一处, 即根元素; <diagram> 子标签不含 mxfile)
_MXFILE_OPEN_RE = re.compile(r"<mxfile\b[^>]*>")                                       # 匹配 mxfile 开标签: 判"是不是 draw.io 文件"用


def save_clean(doc, filepath: str | Path) -> Path:
    """落盘 .drawio, 剥离根标签外来元数据并归一行尾为 LF, 返回落盘路径。

    Args:
        doc: 构建库的 ``DrawioFile`` 文档对象 (未落盘)。
        filepath: 目标 .drawio 路径。

    Returns:
        实际落盘路径的 Path (与 ``doc.save()`` 同口径)。

    Note:
        先让构建库正常落盘、再回读改写文本, 而不是绕过 ``save()`` 自己拼
        XML — ``save()`` 负责建目录与 XML 序列化 (含字符转义), 那部分必须
        复用; 本函数只做"落盘后的属性剥离 + 行尾归一", 不碰任何图内容
        (坐标/样式/文案一律不动, 几何审计与逐字节门禁照旧有效)。
    """
    target = doc.save(filepath)                                                                     # 保存到目标路径: 写盘前先确保目录已存在
    text = target.read_text(encoding="utf-8")
    cleaned = _MXFILE_OPEN_RE.sub("<mxfile>", text, count=1)
    # 行尾归一: 与 .gitattributes 的 eol=lf 对齐, 消除克隆机行尾差与
    # git 的 CRLF->LF 替换警告
    cleaned = cleaned.replace("\r\n", "\n")
    if cleaned != text:                                                                          # 文本被改过就重新落盘: 不然文件与内存会不一致
        # 写点: 唯一的文件输出。必须走 write_bytes 而不是 write_text —
        # Windows 上文本模式写盘会把 \n 按 os.linesep 转回 \r\n, 行尾归一
        # 等于没做 (这个坑本模块第一次实现时踩过, 特此留注)。
        # 原子性不需要 tmp+replace: 读者只在生成期存在, 不是运行时热文件。
        target.write_bytes(cleaned.encode("utf-8"))
    return target
