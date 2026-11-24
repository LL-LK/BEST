"""src.downloader — Download BEST data to local files.

能力边界: BestDownloader: 流式下载 + 断点续传 (checkpoint) + 落盘 (原子写) + 校验和核对 (Q-54: 有期望值 verify_checksum, 无期望值记 unknown)。边界: 行构建收敛 _rows_from_result (Q-27); CSV/TSV 落盘 utf-8-sig, JSON/VOTable 纯 utf-8 (Q-60)。
白盒锚点: references/ALGORITHM-SPEC.md §2 (downloader 锚点) / §3 (超参)。

【权威学术来源锚定】
  - NADC China-VO BEST REST API 规范 (2023): 区域/约束下载与输出格式 (CSV/TXT/JSON/VOTable) 口径, 规范引用（无 DOI）; 开源依赖 requests (Apache-2.0)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。

核心原则: 绝不整表下拉 20 亿级全量星表 — 只按约束/天区取回真正需要的
文件片段 (区域锥搜, 约束过滤, 已有 sqlid 续传), 把带宽与磁盘压在最小。

分工: 区域编排在 ``src/download_region``, 落盘辅助在 ``src/download_artifacts``,
格式写出在 ``src/serialization``; 本模块只保留取数主链与这三者的接线。
"""
from __future__ import annotations

# 标准库: CSV 读写 (组合并/落盘共用) / SHA-256 与恒定时间比对 (校验和) /
# HTML 转义 (VOTable 值防 XML 注入) / 内存缓冲 (先拼内容再原子落盘);
# csv/io 仅 export_results 的合并产物导出用 (列序保持首次出现顺序, 与
# src.serialization.delimited_text 的排序口径刻意不同, 故不走共享实现)
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

# 本地 src.*: HTTP 协议客户端 (锥搜/分页/phase-1 提交都经它下发) /
# CSV 公式注入消毒 (Q-06) / 数据模型 (查询结果/源行/列约束) /
# 协议层权威键集 (星表组/近邻元列/星等列名) / 页级 checkpoint 与原子写 /
# 落盘辅助层 (路径解析/行构建/组合并/复核 sidecar/原始导出) /
# 输出序列化层 (csv/tsv/json/votable 的单一事实源 + 格式白名单校验)
from src.client import BestClient
from src.download_artifacts import (
    STATUS_OK,  # 行状态"有行"的字面量: sidecar 契约与空结果闸共用一份, 不各写字符串
    export_results,  # 合并产物的落盘点: 格式与消毒约定由该模块一处负责
    merge_region_files,  # 导航组成员文件合并: 合并策略与成员清理只此一处
    resolve_output_path,  # 输出路径锚定: 防路径穿越的那一刀在此
    verify_nonempty,  # 空结果共用闸: 四条落盘路径的最终出口都要过它 (0 行不许当成功交付)
    write_provenance,  # sidecar 血缘: 让人能核对文件确实来自这次查询
)
from src.download_artifacts import (
    compute_sha256 as artifacts_compute_sha256,  # 产物层哈希: 薄壳转发, 完整实现不在本模块
)
from src.download_artifacts import (
    digests_match as artifacts_digests_match,  # 恒定时间摘要比较: checksum_match 门禁的唯一判定实现
)
from src.download_artifacts import (
    text_sha256 as artifacts_text_sha256,  # 写前意图摘要: 与写后读回摘要配成两个独立来源
)
from src.download_artifacts import (
    verify_checksum as artifacts_verify_checksum,  # 恒定时间校验和: 防时序侧信道的实现细节在产物层
)
from src.download_region import download_region as region_download
from src.download_sqlid import (
    download_sqlid as sqlid_download,  # 按会话号分页: 断点状态机的完整语义在该模块
)
from src.download_sqlid import (
    resume_job,  # 原地续传: 找不到断点时抛错, 不静默新建作业
)
from src.models import BestQueryResult, ColumnConstraint
from src.protocol import (
    CATALOG_GROUPS,  # 导航组清单: 组名 (如 std) 不是可查询星表, 算区域键时不能送去归一
    PROXIMITY_META_COLUMNS_BARE,  # 无前缀近邻元数据列: 导出时据此把查询元数据剔掉
    resolve_catalog,  # 星表 id 归一: 断点指纹要按归一后的 id 计算
)
from src.scripts.checkpoint import DownloadCheckpoint
from src.scripts.guards import atomic_write_text
from src.serialization import (
    BASE_COLUMNS,  # 固定列清单: 0 行结果的表头与行投影同源, 不另写一份
    BOM_ENCODING,  # 带 BOM 编码: 仅表格类用, Excel 兼容约定
    PLAIN_ENCODING,  # 纯 utf-8 编码: JSON 与 VOTable 加 BOM 会破坏标准解析器
    delimited_text,  # 分隔文本写出: CSV 与 TSV 共用, 由分隔符参数区分
    empty_table_text,  # 只写表头: 0 行结果的产物形态, 与 3 字节空壳在字节层可区分
    json_document,  # JSON 文档写出: 载荷与总行数一起落
    normalize_output_format,  # 格式归一: 大小写与别名在此收口, 扩展名查表依赖它
    votable_document,  # VOTable 文档写出: 全仓唯一 VOTable 路径
    write_fits,  # FITS 写出: 纯本地转换, 服务端不提供该格式
)

logger = logging.getLogger(__name__)  # 下载器自持 logger: 落盘与校验告警走调用方的 handler 配置


def _fingerprint_body(payload: str) -> str:
    """JSON 规范化串 → SHA-256 前 16 位十六进制 (断点键的主体, 不含种类前缀)。

    前缀由调用方按作业种类加 (``constr_`` / ``region_``), 好让两类作业的键空间
    在人读检查点目录时仍可辨; 主体算法只有一份, 避免两处各自演化。
    """
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]  # 16 位短到能进文件名


def _constraint_tuples(constraints: list) -> list[list[str]]:
    """把约束对象展开成固定五元组 (对象字段序不固定, 靠显式取值归一)。"""
    return [
        [                                                                               # 单条约束: 五元组顺序固定, 换序会算出不同指纹
            str(getattr(c, "name", "")),  # 缺字段退空串: 约束对象允许只给一部分字段
            str(getattr(c, "constraint", "")),
            str(getattr(c, "min", "")),
            str(getattr(c, "max", "")),
            str(getattr(c, "value", "")),
        ]
        for c in constraints                                                          # 逐约束展开: 约束对象字段序不固定, 靠显式取值归一
    ]


def _constraint_fingerprint(catalog: str, constraints: list, output_format: str) -> str:
    """把 (catalog, constraints, output_format) 映射成稳定的 checkpoint 键。

    约束作业的断点键必须内容寻址: ``constr_{catalog}_{len(constraints)}_
    {output_format}`` 这类粗粒度键会让任何两个仅约束内容不同的下载撞同一键 —
    第二个任务静默读到第一个任务的 sqlid, 把自己的行写进新输出文件 (跨查询
    数据混洗, D1 级静默事故)。故对约束五元组做 JSON 规范化后取 SHA-256 前
    16 位十六进制, 约束集不同则键必不同。

    签名**不得增删必填参数**: ``test/unit/audit_round/test_audit_fixes.py``
    按 3 个位置参数调它 (AD2 §5 PINNED-01)。锥搜三元组要进键时走同族的
    :func:`constraint_checkpoint_key` (radec 形参), 区域作业走
    :func:`region_checkpoint_key` —— 都不是给本函数加参数。实现上本函数
    整段委托给 ``constraint_checkpoint_key(..., radec=None)``, 于是
    "radec 缺省时键不变" 这条向后兼容由同一段载荷构造代码保证, 不靠两份
    拷贝碰巧相同。
    """
    return constraint_checkpoint_key(catalog, constraints, output_format)  # 委托同族函数: radec=None 的键与旧实现逐位一致


def constraint_checkpoint_key(
    catalog: str,
    constraints: list,
    output_format: str,
    radec: Optional[tuple[float, float, float]] = None,
) -> str:
    """约束作业的断点键: ``radec`` 非空时锥几何必须进指纹 (YZ-10)。

    :meth:`BestDownloader.download_by_constraints` 的断点路径会把 ``radec``
    透传进 phase-1 表单 (服务端锥搜在会话里定型, 事后补不了), 而旧键只按
    (catalog, constraints, output_format) 寻址 —— 同一约束集换一组锥几何
    就撞同一断点键, 续传读到**别的锥区**的 sqlid, 把那片天区的行写进本作业
    的输出文件 (跨查询数据静默混洗, 与 P0-02 同族同后果)。故锥搜三元组
    非空时并入 JSON 规范化载荷; 浮点用 ``repr`` 而非定点格式化, 否则粗化
    本身就是撞键来源 (``60.4`` 与 ``60.0`` 在 ``.0f`` 下同键)。

    ``radec=None`` 时载荷与旧 :func:`_constraint_fingerprint` 逐字节一致
    (键空间不迁移, 既有断点继续有效); ``constr_`` 前缀与区域键的
    ``region_`` 前缀隔开, 两类作业的键空间在人读检查点目录时仍可辨。
    """
    segments = [                                                                                      # 外层三段: 星表、约束集、输出格式共同构成指纹输入
        str(resolve_catalog(catalog)),  # 先归一: 旧拼写与新 id 同义, 不归一会读不到自己的断点
        _constraint_tuples(constraints),                                                    # 约束段: 逐条展开成固定五元组
        str(output_format),                                                                   # 格式也进指纹: 同一约束集换格式是另一次下载
    ]
    if radec is not None:  # 锥几何只在给了才进键: None 时保持与旧键逐位一致, 既有断点不失效
        segments.append([repr(float(radec[0])), repr(float(radec[1])), repr(float(radec[2]))])  # repr 保全精度: .2f/.0f 粗化会把邻近锥区压成同键
    payload = json.dumps(  # 先规范化成 JSON 再哈希: 约束对象的字段序与形态都不固定
        segments,
        sort_keys=True,  # 键排序是稳定性的来源: 同一约束集的不同写法必须算出同一个指纹
    )
    return "constr_" + _fingerprint_body(payload)  # 前缀标明键的种类, 与 region_/sqlid 作业的键空间隔开


def _key_scope(catalog: str) -> str:
    """断点键的"星表段": 可查询星表按 id 归一, 导航组名原样保留。

    ``resolve_catalog`` 对导航组名 (如 ``std``) 会抛 ``ValueError`` —— 组不是
    可查询星表, 而组级断点键确实要按组名分键空间 (否则组键会与某个成员表的键
    混在一起)。按 ``CATALOG_GROUPS`` 显式判组, 而不是 try/except 吞掉归一失败:
    星表名写错时仍应照常抛错, 不该被降级成一个静默的自定义键空间。
    """
    if str(catalog) in CATALOG_GROUPS:
        return str(catalog)  # 导航组名: 原样作键空间段, 不归一
    return str(resolve_catalog(catalog))  # 真星表: 旧拼写与新 id 同义, 不归一会读不到自己的断点


def region_checkpoint_key(
    catalog: str,
    ra_center: float,
    dec_center: float,
    radius_arcsec: float,
    bands: Optional[list[str]],
    output_format: str,
    constraints: list,
    max_rows: int,
) -> str:
    """区域作业的断点键: **决定结果的每一维都进指纹** (P0-02)。

    旧写法是 ``f"region_{catalog}_ra{ra:.2f}_dec{dec:.2f}_r{radius:.0f}"`` ——
    只含**粗化后的几何**, 于是:

    - 同一区域只改 ``bands`` / ``output_format`` / ``constraints`` / ``max_rows``
      的多个作业**撞同一个键** (AD2 实测: 9 个不同作业 → 1 个键);
    - 几何侧 ``.2f`` / ``.0f`` 还把 ``ra=10.001`` 与 ``10.0``、``r=60.4`` 与
      ``60.0`` 压成同键。

    撞键的后果不是报错, 是续传时静默读到**别的作业**的断点, 把自己的行写进新
    输出文件 (跨查询数据混洗)。故全部维度按 JSON 规范化后取 SHA-256; 浮点用
    ``repr`` 而非定点格式化, 否则粗化本身就是撞键来源。
    """
    payload = json.dumps(
        [
            _key_scope(catalog),  # 星表按 id 归一 (旧拼写不另开键空间); 导航组名原样保留
            repr(float(ra_center)),   # repr 保全精度: .2f 会把 10.001 与 10.0 压成同键
            repr(float(dec_center)),
            repr(float(radius_arcsec)),
            [str(b) for b in (bands or [])],  # 波段进键: 换波段是另一次下载, 不是同一作业的续传
            str(output_format),
            _constraint_tuples(constraints),  # 约束进键: 与波段分开列, 二者并非总是同源
            int(max_rows),  # 上限进键 (P0-02 标题的"上限"): 换上限还续旧断点会取错行数
        ],
        sort_keys=True,  # 键排序是稳定性来源: 同一作业的等价写法必须算出同一个键
    )
    return "region_" + _fingerprint_body(payload)  # 前缀与 constr_ 分开: 两类作业键空间可辨


class BestDownloader:
    """把 BEST 数据库数据下载到本地文件。

    只发约束查询按需取数 (不整表下载); **线上**协议白名单是 CSV / TXT (TSV) / JSON /
    VOTable (见 :data:`protocol.SUPPORTED_OUTPUT_FORMATS`, 其余格式显式报错),
    **落盘层另加 fits** (serialization.LOCAL_EXPORT_FORMATS = 白名单 + ("fits",))
    —— fits 是被支持的导出格式, 不是未知格式。断点续传以"页"为粒度, 由
    :class:`DownloadCheckpoint` 原子落盘承载。
    """

    def __init__(
        self,                                                                                       # 实例: 会话与落盘能力都在本对象上
        client: BestClient,                                                                        # 协议层客户端: 阶段一与阶段二都经它发请求
        output_dir: str = "best_data",
        checkpoint_dir: str = ".checkpoints",
    ) -> None:
        """构造下载器。

        Args:
            client: 协议层客户端 (HTTP 会话 / 分页 / phase-1 提交都经它)
            output_dir: 输出根目录 (所有落盘文件名都被限制在该目录内)
            checkpoint_dir: 页级断点 checkpoint 目录
        """
        self.client = client                # 复用注入的会话: 下载器自己不另开 HTTP 连接
        self.output_dir = Path(output_dir)  # 转 Path 便于后续 with_suffix 改名, 此处不做存在性校验
        # 输出目录惰性创建 (外部 IO): 首次下载即建, 已存在则复用
        self.output_dir.mkdir(parents=True, exist_ok=True)                                     # 输出目录建在构造期: 首次下载即用, 已存在则复用
        # checkpoint 目录由 DownloadCheckpoint 内部自行 mkdir, 这里只传路径
        self.checkpoint = DownloadCheckpoint(checkpoint_dir)  # 只交路径: 目录建法归 checkpoint 模块, 两处各建一次会打架

    @staticmethod
    def compute_sha256(filepath: str | Path, chunk_size: int = 65536) -> str:
        """分块流式计算文件 SHA-256 (薄壳, 实现在 download_artifacts)。

        Rule 12 防线二/四 (防内存 OOM 与完整性校验) 的完整语义见
        :func:`src.download_artifacts.compute_sha256`。
        """
        return artifacts_compute_sha256(filepath, chunk_size)  # 薄壳转发: 分块大小原样透传, 由调用方按文件量定

    @staticmethod
    def verify_checksum(filepath: str | Path, expected_sha256: str) -> bool:
        """恒定时间哈希比对 (薄壳, 实现在 download_artifacts)。

        防时序侧信道的完整理由见 :func:`src.download_artifacts.verify_checksum`。
        """
        return artifacts_verify_checksum(filepath, expected_sha256)  # 恒定时间比对在下游: 本壳不再写第二个比较实现

    def download_region(
        self,                                                                                       # 实例: 区域编排要回调本类的查询与落盘
        ra_center: float,                                                                           # 天区中心赤经(度): 区域下载的定位依据
        dec_center: float,                                                                          # 天区中心赤纬(度): 与赤经共同界定天区
        radius_arcsec: float = 600.0,                                                               # 区域半径(角秒): 缺省面向小批量建库
        catalog: str = "ps1",
        bands: Optional[list[str]] = None,                                                      # 波段列表可空: 缺省不限波段, 整表测光一并返回
        output_format: str = "csv",
        output_file: Optional[str] = None,                                                      # 输出文件名可空: 缺省自动生成, 显式名原样尊重
        max_rows: int = 50000,                                                                      # 取回上限: 与页大小解耦, 便于分批
        page_size: int = 1000,                                                                      # 每页行数: 决定单次请求体积与中断粒度
        job_id: Optional[str] = None,                                                               # 作业标识可空: 给了才走断点路径
        resumable: bool = False,                                                                    # 断点标志: 与作业标识给任一即生效
        on_page_observer: Optional[Callable[[int, list], None]] = None,                          # 逐页回调: 进度落盘与取消检查都挂在这一个钩子
    ) -> str:
        """把一个天区下载为本地文件 (区域/批量下载编排入口, 薄壳)。

        std 组展开 / 断点路由 / 一次性锥搜三段决策树见
        :func:`src.download_region.download_region`。
        """
        return region_download(
            self,  # 传 self 作上下文: 区域编排要回调本类的查询与落盘能力
            ra_center=ra_center,                                                             # 实例作上下文传下去: 编排层要回调本类的查询与落盘能力
            dec_center=dec_center,                                                                  # 中心赤经透传: 区域几何不由本壳改动
            radius_arcsec=radius_arcsec,                                                            # 中心赤纬透传: 同上
            catalog=catalog,                                                                        # 半径透传: 同上
            bands=bands,                                                                            # 星表透传: std 组在上游已展开成成员
            output_format=output_format,                                                            # 格式透传: 缺省名与扩展名都按它推
            output_file=output_file,                                                                # 输出名透传: 显式名一律原样尊重
            max_rows=max_rows,                                                                      # 取回上限透传: 上限判定在下游分页器
            page_size=page_size,                                                                    # 页大小透传: 末页自然不足一页
            job_id=job_id,                                                                          # 作业标识透传: 断点键由编排层算好
            resumable=resumable,  # 断点标志原样透传: 编排层据此决定要不要走 checkpoint
            on_page_observer=on_page_observer,                                                      # 逐页回调透传: 不下传会同时丢进度与取消
        )

    def _query_by_catalog(
        self,                                                                                       # 实例: 三份并行分发的收敛点
        catalog: str,                                                                               # 星表 id: 决定走哪一个查询面
        constraints: list[ColumnConstraint],                                                        # 列约束列表: 原样下传, 本壳不改写约束
        output_format: str,                                                                         # 输出格式: 声明式格式只进溯源
        max_rows: int,                                                                              # 取回上限: 透传给三条查询路径
        page_size: int,                                                                             # 页大小: 三条查询路径共用同一页大小
        radec: Optional[tuple[float, float, float]] = None,                                         # 锥搜三元组可空: 给了就一律走服务端锥搜
    ) -> BestQueryResult:
        """经客户端公共缝做一次星表查询 (三处重复分发的收敛点)。

        星表分发只此一处: 拆成 ps1 / std / 其余多份并行分发时各自维护,
        极易漂移。空间选择一律以原生 cone 参数下发, 不手搓
        RA/Dec between 约束。
        """
        cone = radec  # 保留原三元组: 下面两个锥搜分支都按位取, 不就地解包
        # 带了 cone 参数就一律走服务端锥搜 (pos.type=cone), 与星表无关 —
        # 空间选择不再降级成列约束
        if catalog == "ps1":  # ps1 单独分支: 它既有专用查询面也有通用锥搜面, 别的星表只有后者
            # HTTP 调用点 (协议阶段一+二由 client 合做): ps1 带 cone 走锥搜,
            # 无 cone 走 Pan-STARRS 约束查询
            return self.client.cone_search(
                ra=cone[0], dec=cone[1], radius_arcsec=cone[2],  # 按位取三元组: 传反会静默把中心与半径对调而不报错
                catalog=catalog, max_records=max_rows, page_size=page_size,                      # 取回上限与页大小随行传: 两条查询面参数同口径
            ) if cone else self.client.query_panstarrs(  # 三元分派: 有 cone 走锥搜, 无 cone 回落专用约束面
                constraints=constraints, output_format=output_format,                           # 约束与格式走专用面: 没有空间约束时用列约束查询
                max_rows=max_rows, page_size=page_size,                                         # 上限与页大小同传: 少一项就与另一条路径口径不同
            )
        if cone:  # 通用星表的锥搜分支: 与 ps1 路径共用同一组参数
            # HTTP 调用点: 通用星表服务端锥搜
            return self.client.cone_search(
                ra=cone[0], dec=cone[1], radius_arcsec=cone[2],                                    # 三元组按位取: 传反会静默把中心与半径对调
                catalog=catalog, max_records=max_rows, page_size=page_size,                        # 星表与上限随行传: 通用锥搜与专用面同口径
            )
        if catalog == "std":  # std 只能约束查: 它是导航组, 没有单独的锥搜面
            # HTTP 调用点: Standard Stars 约束查询 (std 组已在 download_region
            # 上游展开, 能到这里只会是组成员星表)
            return self.client.query_standard_stars(  # 成员展开在 download_region 上游已完成, 这里只管发请求
                constraints=constraints, output_format=output_format,                           # 约束与格式: 标准星只能约束查, 没有单独锥搜面
                max_rows=max_rows, page_size=page_size,                                             # 上限与页大小: 与另两条路径同口径
            )
        # HTTP 调用点: Well-Calibrated 等其余星表的约束查询
        return self.client.query_calibrated(  # 兜底分支: Well-Calibrated 等巡天共用这一条查询面
            survey=catalog, constraints=constraints, output_format=output_format,                 # 巡天体名传同一形参: 兜底分支不再自造参数名
            max_rows=max_rows, page_size=page_size,                                                 # 上限与页大小: 兜底路径同样受上限约束
        )

    def _merge_region_files(
        self,                                                                                       # 实例: 合并要回调本类的落盘能力
        parts: list[str],                                                                           # 成员临时文件列表: 合并完成后按策略清理
        catalog: str,                                                                               # 星表: 决定合并产物的命名与元数据
        ra_center: float,                                                                           # 天区中心赤经(度): 写进合并产物的溯源
        dec_center: float,                                                                          # 天区中心赤纬(度): 同上
        radius_arcsec: float,                                                                       # 区域半径(角秒): 同上
        bands: Optional[list[str]],                                                                 # 波段列表可空: 进合并产物的溯源
        output_format: str,                                                                         # 输出格式: 决定合并产物的最终形态
        output_file: Optional[str],                                                                 # 输出文件名可空: 缺省由合并层生成
    ) -> str:
        """把导航组各成员星表的临时落盘文件合并为一份导出 (薄壳, 实现在 artifacts)。

        合并策略/缺失容忍/成员清理的完整语义见
        :func:`src.download_artifacts.merge_region_files`。
        """
        return merge_region_files(  # 薄壳转发: 合并策略与成员清理只在 artifacts 一处
            parts, catalog, ra_center, dec_center, radius_arcsec, bands,                           # 几何与波段整份下传: 合并层要靠它们写溯源
            output_format, output_file, output_dir=self.output_dir,  # 只交输出目录: 合并层自己走统一落盘出口 (格式白名单 + 原子写 + sidecar)
        )

    def download_by_constraints(
        self,                                                                                       # 实例: 约束下载主通道
        constraints: list[ColumnConstraint],                                                        # 列约束列表: 主通道的核心输入
        catalog: str = "ps1",
        output_format: str = "csv",
        output_file: Optional[str] = None,                                                        # 输出文件名可空: 缺省按星表与约束数自动生成
        max_rows: int = 50000,                                                                      # 取回上限: 与页大小解耦
        page_size: int = 1000,                                                                      # 每页行数: 决定每页请求体积
        job_id: Optional[str] = None,                                                               # 作业标识可空: 给了就带断点
        resumable: bool = False,                                                                    # 断点标志: 与作业标识给任一即生效
        on_page_observer: Optional[Callable[[int, list], None]] = None,                             # 逐页回调: 断点路径与非断点路径共用
        radec: Optional[tuple[float, float, float]] = None,                                         # 锥搜三元组可空: 给了就走服务端原生锥搜
    ) -> str:
        """按自定义列约束下载数据到本地文件 (约束下载 / 断点路径的主通道)。

        Args:
            constraints: ColumnConstraint 列表
            catalog: 目标星表
            output_format: csv, txt, json, votable
            output_file: 输出文件名
            max_rows: 最大行数
            page_size: 每页行数
            job_id: 可续传 checkpoint 的作业标识
            resumable: True 时保存页进度并支持续传
            on_page_observer: 每页回调 (page, sources)
            radec: 可选 (ra, dec, radius_arcsec) 原生锥搜选择

        Returns:
            落盘文件路径。

        Raises:
            RuntimeError: phase-1 未取得 sqlid, 或查询失败。
        """
        if not output_file:  # 仅在调用方没给名时自动生成: 显式名一律原样尊重
            # 缺省名只含星表与约束个数 — 唯一性由 constraint_checkpoint_key
            # 的 checkpoint 键保证, 文件名不承担寻址责任。
            # P3-3/P3-4: 自动名用规范扩展名 (txt→tsv / votable→xml, 与
            # 同层 ext_map 同口径)。直接拿 output_format 当扩展名
            # (txt→.txt / votable→.votable) 再靠 _save_result 里的纠后缀
            # 分支改写, 两处约定就分了家
            n_constraints = len(constraints)                          # 只进文件名供人工辨认, 唯一性由指纹保证而不是由名字
            ext_map = {"txt": "tsv", "votable": "xml", "csv": "csv",  # 扩展名别名与落盘层同口径: txt 走 tsv, votable 走 xml
                       "json": "json", "fits": "fits"}
            auto_ext = ext_map.get(normalize_output_format(output_format),  # 先归一格式再查表: 大小写差异不该落到未知键上
                                   output_format)                                               # 查不到别名时原样用: 不猜扩展名, 交给入口校验
            output_file = f"best_{catalog}_c{n_constraints}.{auto_ext}"  # 自动名不承担唯一性: 同名不同约束由 checkpoint 键区分

        if resumable or job_id:  # 给任一即走断点路径: 显式 job_id 也该能续, 不必同时给 resumable
            # 内容寻址 id: 两个不同约束集不再共享同一 checkpoint
            # (D1: 旧粗粒度键导致跨查询数据静默混洗; YZ-10: 锥几何同样进键,
            # 否则同约束集换 radec 会续到别的天区的断点上)
            effective_job_id = job_id or constraint_checkpoint_key(  # 缺省才用内容指纹: 显式 job_id 是调用方自己的寻址承诺
                catalog, constraints, output_format, radec=radec,  # radec 进键 (YZ-10): 锥搜在 phase-1 会话里定型, 换锥区必须换断点键
            )
            # 断点读取 (外部 IO): checkpoint 是 resume 的唯一事实源
            # (sqlid + next_page + 已累积 sources)
            ckpt = self.checkpoint.load(effective_job_id)  # 读断点是外部 IO: 缺失返回 None 而不是抛错
            if ckpt and ckpt.get("sqlid"):                 # 两个条件都要: 断点存在但无 sqlid 时无从续起, 只能重走阶段一
                # 有断点即从 sqlid 续传 — phase-1 POST 不重发, 服务端
                # 会话仍有效时直接从 next_page 继续拉。
                # observer 在续传路径上同样必须转发: 缺失它进度停止累加,
                # 取消标志也不再被检查 (取消静默失效)。
                return self.download_sqlid(  # 续传路径: 阶段一不重发, 直接从 checkpoint 的 next_page 接着拉
                    sqlid=ckpt["sqlid"],
                    catalog=catalog,                                                                # 星表透传: 阶段一按它选路由
                    output_format=output_format,                                                    # 格式透传: 声明式格式进溯源
                    output_file=output_file,                                                        # 输出名透传: 显式名原样尊重
                    max_rows=max_rows,                                                              # 取回上限透传: phase-2 本地封顶, 不改服务端会话 (A2-03)
                    page_size=page_size,                                                            # 页大小透传: 翻页粒度
                    job_id=effective_job_id,                                                  # 作业标识用算出的那一份: 断点键与写入时必须完全一致
                    resumable=True,                                                                 # 强制走断点: 走进这一段的目的就是留断点
                    on_page_observer=on_page_observer,  # observer 必须转发: 缺它进度停止累加且取消标志不再被检查
                )

            # 协议阶段一 (phase 1): POST 约束表单到 /q 换取 sqlid —
            # 经客户端公共缝下发 (不得再在本层私建 _build_form/
            # _submit_query_for_sqlid 一对, 那是 phase-1 协议的第二份拷贝)。
            # 失败语义: 拿不到 sqlid 就无法分页, 直接 raise。
            sqlid, err = self.client.submit_phase1(  # 只提交不取数: 拿到 sqlid 先落断点, 之后才开始翻页
                catalog,                                                                            # 星表传首位: 阶段一按位置参数接住
                constraints=constraints,                                                           # 约束原样下发; 上限只封 phase-2 取回量, 不下发进阶段 1 表单 (A2-03)
                max_rows=max_rows,                                                            # 上限与锥搜三元组同传: 三元组在会话里定型事后补不了, 上限只是 phase-2 封顶 (A2-03)
                radec=radec,                                                                        # 锥搜三元组透传: 有才下发位置键
            )
            if err or not sqlid:                                                   # 两条件并判: 只看 sqlid 会丢掉有 id 却带错误信息的组合
                raise RuntimeError(f"Download query failed: {err or 'no sqlid'}")  # 抛而不降级: 没有 sqlid 就无法分页, 返回空文件会被当成零行成功

            # 首检落盘 (外部 IO): 立即写下 sqlid + next_page=1, 此后每页
            # 更新 — 进程在任何时刻被杀都能从断点恢复 (原子写, 见 scripts.guards)
            self.checkpoint.save(effective_job_id, {  # 首检落盘: 此刻就记下 sqlid, 之后任何时刻被杀都能恢复
                "job_id": effective_job_id,
                "sqlid": sqlid,  # 会话号是续传的唯一凭据, 丢了就只能重走阶段一建新会话
                "catalog": catalog,
                "next_page": 1,  # 页码 1 起: 与 build_page_url 的页码约定保持一致
                "sources": [],
                "output_format": output_format,
                "output_file": output_file,
                "page_size": page_size,  # 步长入断点: phase-2 是偏移翻页, next_page 脱离 page_size 就没有意义
                "max_rows": max_rows,  # 上限同样入断点: 续传不靠缺省猜 phase-2 封顶值 (A2-03)
            })
            return self.download_sqlid(  # 新建路径同样强制 resumable: 走进这一段的目的就是留断点
                sqlid=sqlid,                                                                        # 会话号: 已落断点, 从这里开始只翻页
                catalog=catalog,                                                                    # 星表: 错误信封与溯源都要它
                output_format=output_format,                                                        # 格式: 声明式格式进溯源
                output_file=output_file,                                                            # 输出名: 显式名原样尊重
                max_rows=max_rows,                                                                  # 取回上限: 分页器的封顶值
                page_size=page_size,                                                                # 页大小: 每页行数
                job_id=effective_job_id,                                                            # 作业标识: 与断点键同一份
                resumable=True,                                                                     # 强制走断点: 每页都要更新断点
                on_page_observer=on_page_observer,                                                # 逐页回调必须转发: 缺它进度不累加且取消失效
            )

        # 非断点路径: 按星表分发一次性查询 (HTTP 调用点; 协议阶段一+二
        # 由 client 内部合起来做, 无 checkpoint — 失败只能整任务重来)
        if catalog == "ps1":  # 非断点路径同样按星表分发: 与 _query_by_catalog 保持同一口径
            result = self.client.query_panstarrs(                                                   # 非断点的 ps1 专用查询面
                constraints=constraints, output_format=output_format, max_rows=max_rows, page_size=page_size  # 约束与上限同口径: 与断点路径不共用参数名
            )
        elif catalog == "std":
            result = self.client.query_standard_stars(                                              # 非断点的标准星查询面
                constraints=constraints, output_format=output_format, max_rows=max_rows, page_size=page_size  # 约束与上限同口径: 同上
            )
        else:
            result = self.client.query_calibrated(                                                  # 非断点的巡天兜底查询面
                survey=catalog, constraints=constraints,                                  # 巡天体名形参: 兜底面用 survey 而非 catalog
                output_format=output_format, max_rows=max_rows, page_size=page_size                 # 约束与上限: 与前两条路径同口径
            )

        if not result.success:                                      # 失败信封不落盘: 半截文件比直接报错更难清理
            raise RuntimeError(f"Download failed: {result.error}")  # 把服务端错误原文带给调用方: 裸消息会丢掉软 404 与硬失败的区别

        return self._save_result(result, output_file, output_format)  # 此路不传期望校验和: 没有可信基准, 由 _save_result 记 unknown

    def _resolve_output_path(self, filename: str) -> Path:
        """规范化输出文件名: 去除目录成分并限制在 output_dir 之内 (防路径穿越)。

        实现委托 ``download_artifacts.resolve_output_path``; 本方法保留是为了
        不破坏 ``BestDownloader._resolve_output_path`` 这个既有调用点。
        """
        return resolve_output_path(self.output_dir, Path(filename).name)  # 取 name 丢掉目录成分: 这是防路径穿越的那一刀

    @staticmethod
    def _rows_from_result(result: BestQueryResult) -> list[dict]:
        """Q-27: 行构建单一实现 (csv/txt/votable 三处 22 行逐行重复已收敛)。

        近邻匹配元数据 (``inputobjs_*``) 刻意不作为列导出: 它描述的是查询
        而不是源本身, 且已包含在 JSON 导出的 ``raw_data`` 里; 导出它会让
        站点 proximity 模式返回的每个 CSV 多出四列重复数据。

        Note:
            与 ``download_artifacts.rows_from_result`` 是**两个不同职责**:
            本方法做"源对象 -> 扁平列"的科学投影 (星等展平成 ``{band}mag``),
            那个只做浅拷贝供合并/导出用。刻意不合并 — 合并会让"导出列形态"
            这条契约散到两处。
        """
        rows_data = []                                 # 先累积整表再返回: 导出层一次性拼内容, 不逐行落盘
        for src in result.sources:                     # 逐源投影: 列形态由本方法定, 数据侧不参与列序决策
            d = src.to_dict()                          # 先转字典: 下面的展平与直拷都按字典键走
            row: dict = {}                             # 空行起步: 星等列是动态的, 固定列先落再补动态列
            for col in BASE_COLUMNS:                   # 固定列一次成型: 与 0 行结果的表头同源, 两处不会各写一份而漂移
                row[col] = d.get(col, "")              # 缺列给空串而非 None: CSV 里 None 会被写成字面量
            for band, mag in d.get("magnitudes", {}).items():  # 星等展成 {band}mag: 下游表格工具按列名直接取值
                if mag is not None:                            # None 跳过而非填空: 空值格与 0.0 在科学含义上并不等价
                    row[f"{band}mag"] = mag
            for band, err in d.get("magnitude_errors", {}).items():  # 误差列同样按波段展开, 命名带 err 后缀以便成对识别
                if err is not None:                                  # 与星等同一判据: 半条误差信息不如没有
                    row[f"{band}err"] = err
            for k, v in d.items():                                                             # 其余列原样带出: 表结构随星表变化, 不在此处裁剪
                if k in ("magnitudes", "magnitude_errors") or k in row:  # 已展平的键不再直拷: 否则宽表会多出嵌套字典列
                    continue
                if k.startswith("inputobjs_") or k in PROXIMITY_META_COLUMNS_BARE:  # 近邻元数据刻意不导出: 它描述查询而非源, 且 raw_data 里已包含它
                    continue
                row[k] = v  # 其余列原样带出: 表结构随星表变化, 不在此处裁剪
            rows_data.append(row)                                                                   # 整表投影完再入库: 导出层一次性拼内容
        return rows_data

    def _save_result(
        self,                                                                                       # 实例: 所有下载路径的最终出口
        result: BestQueryResult,                                                                    # 查询结果: 落盘内容的唯一来源
        output_file: str,                                                                           # 输出文件名: 先过路径锚定再落盘
        output_format: str,                                                                       # 输出格式: 白名单外显式失败, 不静默改格式
        expected_sha256: Optional[str] = None,                                                  # 期望校验和可空: 无基准时显式记 unknown
    ) -> str:
        """把查询结果落盘为本地文件 (所有下载路径的最终出口)。

        Q-54: 落盘后强制校验和核对——有期望值即 verify_checksum, 失败 raise;
        无期望值也给出真实判定: checksum_match = (写前意图摘要 == 写后读回摘要),
        布尔值, 恒真或恒假的门禁都不算数 (A3-05: 此前恒写 "unknown", 使
        blocking 门禁 checksum_match==True 永不可满足)。
        Q-27/Q-28/Q-60: 行构建去重; VOTable 值 XML 转义; 文本落盘 utf-8-sig。

        Args:
            result: 查询结果 (含 sources)
            output_file: 输出文件名
            output_format: csv, txt, json, votable, fits (线上白名单见 protocol.SUPPORTED_OUTPUT_FORMATS;
                fits 仅落盘层可用, 见 serialization.LOCAL_EXPORT_FORMATS; 与下方 ext_map 含 fits 一致)
            expected_sha256: 可选的期望 SHA-256 (落盘后核对)

        Returns:
            落盘文件的绝对路径。

        Raises:
            ValueError: 输出格式不在白名单内 —— 绝不静默改格式 (``else``
                分支把 fits 等未知格式写成 JSON 并改扩展名的话, 调用方请求
                FITS 会拿到 JSON 文件且无任何提示)。
        """
        path = self._resolve_output_path(output_file)  # 先定路径: 后面每个格式分支都可能再改一次名
        # 格式白名单前置校验: 未注册格式在此就失败, 不会走到"已落错盘"那一步
        fmt = normalize_output_format(output_format)  # 格式先归一: 后续分支判定与扩展名校验共用这一份结果

        # P3-4: 文件名与格式必须自洽 (fail-closed) — fmt=txt 给 .csv 名会把
        # TSV 内容落进 .csv 文件; 别名口径与本层 ext_map 同一套
        # (.votable/.txt 是 live 实证的调用姿势, 容忍; 规范名 txt→.tsv 的
        # 归一在下方分支做)
        ext_aliases = {  # 别名表容忍 .txt 与 .votable 的既有调用姿势, 但不放行跨格式的名字
            "csv": {"csv"},
            "txt": {"tsv", "txt"},
            "json": {"json"},
            "votable": {"xml", "votable"},
            "fits": {"fits"},
        }
        given_ext = Path(output_file).suffix.lstrip(".").lower()  # 扩展名去点取小写: .CSV 与 .csv 应当等价
        if given_ext not in ext_aliases.get(fmt, {"json"}):       # 名实不符即拒: TSV 内容落进 .csv 的错只有下游才会发现
            raise ValueError(
                f"output_file {output_file!r} 的扩展名 .{given_ext or '(无)'} 与"
                f"格式 {output_format!r} 不相配 (可接受: "
                f"{sorted(ext_aliases.get(fmt, {'json'}))})"
            )

        # 空结果共用闸 (A3-03): region/sqlid/约束/精准四条路径的最终出口都是
        # 本方法, 闸装在这里一次覆盖四条。抛而不落盘 —— 有数据却写 0 行时产物
        # 本身就是错的证据, 落下去只会让人把它当"这片天区没源"。
        row_status = verify_nonempty(result, path)  # ok/empty: 终态要记进 sidecar, 0 行不许只留一个空文件

        if fmt == "json":
            content = json_document(                                                            # 载荷只取源对象: 不带信封字段, 那是另一层的事
                [s.to_dict() for s in result.sources], total=result.total_count                   # 总行数取服务端报告值: 与取回数不等即被截断
            )

        elif fmt in ("csv", "txt"):
            delimiter = "\t" if fmt == "txt" else ","  # 分隔符由格式决定: txt 走制表符, csv 走逗号
            if fmt == "txt" and given_ext == "txt":    # 只在这一组合改后缀: 已给 .tsv 的原样保留, 不再纠名
                # txt 形态的规范容器是 .tsv (内容为制表符分隔): 调用方给 .txt
                # 别名时归一到 .tsv (live 实证的既有行为); 给 .tsv 原样保留
                path = self._resolve_output_path(                                               # 改后缀后重新锚定: 归一后的文件名同样要过防穿越
                    f"{output_file.rsplit('.', 1)[0]}.tsv")
            rows_data = self._rows_from_result(result)                                          # 行构建走单点: csv 与 txt 共用同一投影
            # 0 行也要落表头: 空串在 CSV 路径上会变成只含 BOM 的 3 字节文件,
            # 字节上与"写坏的空文件"不可区分 (行状态另由 row_status 记进 sidecar)
            content = delimited_text(rows_data, delimiter) or empty_table_text(BASE_COLUMNS, delimiter)  # 表头与行投影同源

        elif fmt == "votable":
            # VOTable XML 输出 (IVOA 标准表格式, 供 TOPCAT/astropy 读);
            # 列类型按实际取值推断 + ra/dec/mag 补 unit — 落盘格式统一走
            # src.serialization 单点 (P1 删除 pybest 双副本后唯一写出路径),
            # 杜绝"两套写出逻辑各自漂移"。
            # P3-3: 不得无条件 with_suffix(".xml") — 显式 .votable 名会被
            # 暗改成 .xml, 调用方按自传路径 stat 即 FileNotFoundError (live
            # 实证); 别名经入口校验放行后原样保留, 不纠后缀
            content = votable_document(  # 写出统一走 serialization: 全仓只剩这一条 VOTable 路径
                self._rows_from_result(result),                                             # 同一份行投影: VOTable 与表格类共用, 不另投影
                catalog=str(result.query_params.get("catalog", "query")),  # 缺省 query: 无星表上下文时不该编一个名字进元数据
                nrows=result.returned_count,                                                       # 取回数写入表元数据: 截断时消费方能看出来
            )

        elif fmt == "fits":
            # FITS 是纯本地转换格式 (服务端不返回 FITS, 请求 fits 拿到结果页
            # HTML); astropy 缺失时 serialization.write_fits 抛带安装提示的
            # RuntimeError, 不静默降级成别的格式。
            # FITS 是二进制, 不走 atomic_write_text — 先写同目录 .tmp 再
            # os.replace, 与文本路径同样保证"不存在写一半的半成品"。
            if not output_file.endswith(".fits"):  # 显式 .fits 名原样保留: 无条件改后缀的话, 按自传路径 stat 就找不到
                path = path.with_suffix(".fits")
            fits_tmp = path.with_suffix(path.suffix + ".tmp")  # 临时名留在同目录: 跨文件系统的 os.replace 不是原子的
            try:
                write_fits(fits_tmp, self._rows_from_result(result),                                  # FITS 走临时文件: 二进制不进文本原子写
                           catalog=str(result.query_params.get("catalog", "")))
                written_sha256 = self.compute_sha256(fits_tmp)  # 切换前的意图摘要: 临时文件在盘上, 二进制一样能算哈希
                os.replace(fits_tmp, path)                                      # 原子切换: 读方永远看不到写了一半的 FITS
            finally:
                # YZ-47: 半成品清理与 atomic_write_text 同口径 —— write_fits 写一半
                # 抛错 (如 astropy 转换失败) 时 .tmp 会留在盘上, 没有 finally 的话
                # 下次运行会被当成"上次写好的产物"之外的孤儿垃圾; 替换成功后
                # tmp 已不存在, 这里只兜失败路径
                if fits_tmp.exists():  # 替换成功后临时文件已消失, 这里只兜失败路径
                    try:
                        fits_tmp.unlink()  # 尽力清理半成品: 不让半截 FITS 留在输出目录
                    except OSError:
                        logger.debug("fits temp cleanup failed for %s", fits_tmp)  # debug 而非 warning: 清理失败不该把原始异常盖掉
            # checksum_match = 写前意图 vs 切换后读回 (A3-05): 二进制同样可判定,
            # 此前硬编码 "unknown" 只是让阻断门禁恒假, 与"二进制不走文本原子写"无关。
            checksum_match = artifacts_digests_match(written_sha256, self.compute_sha256(path))
            self._write_provenance(path, result, output_format, checksum_match, row_status)  # sidecar 写在切换之后
            return str(path.resolve())

        else:  # pragma: no cover - normalize_output_format 已拦住其余取值
            raise ValueError(f"unreachable output format: {fmt}")

        # 原子写 (外部 IO): .tmp + os.replace (Rule 12 防线二) — 共享实现
        # 在 src.scripts.guards.atomic_write_text, 内部用 newline="" 写文本,
        # 防 Windows 文本模式把 \r\n 翻译成 \n 破坏行结构; replace 瞬间
        # 完成切换, 不存在"写一半的半成品文件"窗口。
        # Q-60: 仅 CSV/TSV 用 utf-8-sig (Excel 兼容约定, 同 io.to_csv);
        # JSON/VOTable 保持纯 utf-8 (BOM 会破坏标准解析器)。
        text_encoding = BOM_ENCODING if fmt in ("csv", "txt") else PLAIN_ENCODING  # 只有表格类加 BOM: Excel 兼容与标准解析器在此分道
        written_sha256 = artifacts_text_sha256(content, text_encoding)  # 写**前**按落盘编码算的意图摘要
        atomic_write_text(path, content, encoding=text_encoding)                   # 原子写单点: newline 口径由 guards 负责, 本模块不自己开文件

        # Q-54: 校验和接线。有调用方给的期望值就核对它 (不符即抛); 无论有没有
        # 期望值, checksum_match 都取"写前意图摘要 vs 写后读回摘要"的比对
        # 结果 (A3-05) —— 恒写 "unknown" 会让 blocking 门禁永不可满足。
        if expected_sha256 and not self.verify_checksum(path, expected_sha256):  # 有基准才核对, 不允许默认判通过
            raise ValueError(  # 现读现算: 拿刚落盘的文件比对, 免得拿旧文件当依据
                f"checksum mismatch for {path}: expected {expected_sha256}"
            )
        checksum_match = artifacts_digests_match(written_sha256, self.compute_sha256(path))  # 意图 vs 事实: 布尔, 供 sidecar 与日志
        logger.info("Saved %d records to %s (checksum_match=%s, row_status=%s)",  # 条数/校验/行状态同一条日志: 复核先看这一行
                    len(result.sources), path, checksum_match, row_status)

        # 人工复核产物: 落盘旁写 <name>.provenance.json (data_hash + lineage +
        # 查询参数), 让人能核对"这个文件确实来自这次查询" (Q-08 从"只写不读"
        # 的测试-only 接线变成真实产物)。
        self._write_provenance(path, result, output_format, checksum_match, row_status)  # sidecar 写在日志之后: 它是 best-effort, 失败不该影响产物可用性

        return str(path.resolve())  # 返回绝对路径: 相对路径会随调用方的 cwd 变化而失效

    def _write_provenance(
        self,                                                                                       # 实例: sidecar 走本类的哈希方法
        path: Path,                                                                                 # 产物路径: 哈希要读回落盘文件重算
        result: BestQueryResult,                                                                    # 查询结果: 血缘里的查询参数从它取
        output_format: str,                                                                         # 输出格式: 进溯源
        checksum_match: bool,                                                                 # 校验判定: 写前意图摘要与写后读回摘要是否一致 (布尔)
        row_status: str = STATUS_OK,                                                         # 行状态: ok/empty 由空结果闸判定, 缺省只在无闸调用点生效
    ) -> Optional[str]:
        """给下载产物写 provenance sidecar (薄壳, 实现在 artifacts)。

        best-effort 语义 (失败只 warn 不 raise)、``row_status`` 键的语义
        (与信封自身 ``status`` 不同名不同义)、``checksum_match`` 必须是
        真实布尔 (恒假的阻断门禁等于没有门禁) 与"哈希必须读回刚落盘文件
        重算"的完整理由见 :func:`src.download_artifacts.write_provenance`。
        """
        return write_provenance(  # 薄壳转发: 哈希读回落盘文件重算的完整语义在 artifacts
            path, result, output_format, checksum_match,
            row_status=row_status,  # 行状态原样透传: 0 行必须留在复核契约里
            sha256_of=self.compute_sha256,  # 注入本类方法: artifacts 因此不必反向依赖下载器
        )

    def download_sqlid(
        self,                                                                                       # 实例: 分页下载要回调本类能力
        sqlid: str,                                                                                 # 会话号: 续传的唯一凭据
        catalog: str = "ps1",
        output_format: str = "csv",
        output_file: Optional[str] = None,                                                          # 输出文件名可空: 缺省自动生成
        max_rows: int = 50000,                                                                      # 取回上限: 分页器的封顶值
        page_size: int = 1000,                                                                      # 页大小: 每页行数
        job_id: Optional[str] = None,                                                               # 作业标识可空: 给了才更新断点
        resumable: bool = False,                                                                    # 断点标志: 强制为真时每页都落断点
        on_page_observer: Optional[Callable[[int, list], None]] = None,                             # 逐页回调: 进度与取消的唯一钩子
    ) -> str:
        """按 sqlid 分页下载 (薄壳, 实现在 download_sqlid 模块)。

        断点状态机 (next_page 语义 / 历史源前缀回交 / 成功即删断点) 的完整
        语义见 :func:`src.download_sqlid.download_sqlid`。
        """
        return sqlid_download(  # 薄壳转发: 断点状态机只在 download_sqlid 一处
            self, sqlid, catalog=catalog, output_format=output_format,                              # 实例与星表随行传: 被委派方靠它回调落盘
            output_file=output_file, max_rows=max_rows, page_size=page_size,  # 分页参数原样透传: 改动会让既有断点的 next_page 失去意义
            job_id=job_id, resumable=resumable, on_page_observer=on_page_observer,               # 作业标识与回调透传: 断点与进度都挂在这两项上
        )

    def resume_job(
        self,
        job_id: str,
        on_page_observer: Optional[Callable[[int, list], None]] = None,
    ) -> str:
        """从 checkpoint 原地续传一个未完成的下载作业 (薄壳, 实现在 download_sqlid)。

        断点缺失/无 sqlid 时抛 FileNotFoundError 的完整理由见
        :func:`src.download_sqlid.resume_job`。

        ``on_page_observer`` 逐页透传给下游: 续传期的进度累加与取消检查
        都挂在它上面, 薄壳吞掉它等于让续传既不报进度也不可取消。
        """
        # 逐页回调透传: 缺它则续传期间进度冻结且取消静默失效 (与本文件
        # download_region 续传分支同一条纪律, 两侧都不得就地吞掉)
        return resume_job(self, job_id, on_page_observer=on_page_observer)  # 原地续传: 找不到断点时由下游抛错, 不静默新建一个作业

    def export_results(
        self,                                                                                       # 实例: 合并产物的落盘出口
        data: list[dict],                                                                          # 原始行数据: 扁平列, 与科学投影不同职责
        filename: str = "best_results.json",
    ) -> str:
        """把原始数据列表导出为文件 (CSV 或 JSON, 合并产物的落盘点)。

        实现委托 ``download_artifacts.export_results``; 本方法保留是为了
        不破坏 ``BestDownloader.export_results`` 这个既有调用点 (含
        ``_merge_region_files`` 的回调注入)。
        """
        return export_results(data, filename, self.output_dir)  # 限制在 output_dir 内落盘: 合并产物同样要过防路径穿越那一关
