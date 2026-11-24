"""src.crossmatch — Coordinate cross-match against BEST catalogs.

能力边界: BestCrossMatch: 坐标交叉匹配 (含 Gaia/PS1) 与 _angular_separation_arcsec (haversine 大圆距离 + cos(dec) 投影)。边界: manifest 声明单点失败隔离 (Q-17); 匹配结果形态见 BestCrossMatchResult。
白盒锚点: references/ALGORITHM-SPEC.md §2 (crossmatch 锚点); 数学见行内注释。

【权威学术来源锚定】
  - NADC China-VO BEST REST API 规范 (2023): 约束式锥形检索 (cone search) 口径, 规范引用（无 DOI）。
  - 球面角距与锥形交叉匹配: 标准球面几何公式（规范引用; haversine/angular separation）; 开源实现参照 astropy.coordinates SkyCoord 语义 (astropy, BSD-3)。
  - 开源依赖: requests (Apache-2.0)。
Rule 9 状态: [VERIFIED_ALGO]（标准基准算法; 物理可解释输出, 无伪概率打分）。

核心原则: 上传自有坐标, 只取回匹配的 BEST 源; 通过约束式 API 的逐点锥形
检索, 避免下载全量 20 亿+ 星表。

匹配策略:
  A. 逐点锥形检索 (默认, ≤100 个坐标, 实现简单)
  B. 服务端 proximity 批量匹配 (P0-1): 一次 ``pos.type=proximity`` POST,
     请求体为 ``ra,dec,radius`` 多行 textarea, 由服务端一次匹配全部坐标;
     响应带 ``inputobjs_*`` 列回显输入行号与角距。以 1 次批量提交替代 N 次
     锥形检索 (实机测量: 8 坐标 = 16 请求/25.9s -> 2 请求/7.0s)。策略 A 保留
     为回归基线, 并在批量提交失败时自动降级回退。
  C. 本地批量任务队列: submit_upload_job 解析 CSV 内容, 将任务持久化到磁盘,
     并按策略 A 逐点执行 (BEST 服务未开放公开上传/任务 API, 故匹配在客户端
     完成)。
"""
from __future__ import annotations

# 标准库: csv 解析上传的 CSV 内容, json 负责任务文件序列化 (落盘走共享
# atomic_write_text, 本模块不再自带 tmp/replace 副本), math 提供球面角距计算,
# ThreadPoolExecutor 并发执行逐点锥形检索。
# (策略 C 的 uuid/datetime/io 任务 id 与时间戳已随其迁至 src.crossmatch_jobs。)
import csv
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional, Union

# 本地: BestClient 提供 HTTP 会话与锥形检索 (跨网络能力边界);
# models 侧为查询结果/匹配记录/任务的数据模型; proximity_radec_text 是
# proximity 线格式的权威实现, 线格式归属协议层, 本模块只做薄别名
from src.client import BestClient
from src.models import (
    BestCrossMatchJob,  # 作业句柄模型: 任务队列的返回契约
    BestQueryResult,  # 查询结果信封: 与逐点路径共用同一返回面
    BestSource,  # 源对象: 匹配行在结果里的载体
)
from src.protocol import E_BACKEND, proximity_radec_text  # 兜底码取协议层真源 (见 _QUERY_FAILED)
from src.scripts.guards import atomic_write_text  # 全仓唯一原子写实现: 本模块的 input.csv/manifest/results 一律走它

logger = logging.getLogger(__name__)  # 匹配器自持 logger: 批量降级与单点失败告警走调用方的 handler

MAX_WORKERS = 4  # 逐点锥形检索的并发线程数 (对服务端限流保守的值)
JOBS_DIRNAME = "best_crossmatch_jobs"  # 本地磁盘任务队列的根目录名
# 逐点查询失败但客户端没给出分类码时的兜底码: 复用协议层的 E_BACKEND 真源
# (与 src/client_paging.py 对网络故障的取码同源), 不自造新码也不另抄一份
# 字面量 —— 错码就够分, 再多一套同名不同义的值只会让调用方按错码分支。
# 2026-10-05 (T1): 字面量改为从 src.protocol 取, 此前这里是第二份定义。
_QUERY_FAILED = E_BACKEND  # 兜底码: 异常路径拿不到客户端分类码时用它


def _proximity_radec_text(
    ra_list: list[float], dec_list: list[float], radius_arcsec: float                            # 三入参同取: 半径是每个输入位置共用的匹配半径
) -> str:
    """构造 proximity 批量匹配用的 ``ra,dec,radius`` 多行 textarea。

    仅是 :func:`src.protocol.proximity_radec_text` 的薄别名 — 线格式归属
    协议层, 两个客户端共享同一实现。

    P3-1: 本文件里不得再出现第二份同名定义 (重写 zip 逻辑) — 两份定义里
    后定义的那份会在运行时生效, "线格式归属协议层"的单一事实源随之被打破,
    且 zip 无 strict 会静默截断坐标列表。此处只留本薄别名。
    """
    return proximity_radec_text(ra_list, dec_list, radius_arcsec)  # 薄别名转发: 线格式只在协议层有一份, 本模块不再重写 zip


def _echo_line_value(raw: Any) -> Optional[int]:
    """把响应里的回显行号原样解成 int; 不做任何基准假设。

    与 ``_input_line_index`` 分开是因为基准探测需要**未经换算**的原值:
    "出现 0" 与 "出现 n_inputs" 这两条决定性信号都只在原值域里成立。
    """
    try:
        return int(float(str(raw).strip()))  # 先转 float 再转 int: 服务端偶尔回 1.0 形态的行号
    except (TypeError, ValueError):
        return None


def _input_line_index(raw: Any, n_inputs: int, zero_based: Optional[bool] = None) -> Optional[int]:
    """把 proximity 响应中的输入行号值映射为 0 基索引。

    ``zero_based`` 显式指定回显基准: ``True`` 纯 0 基, ``False`` 纯 1 基,
    ``None`` (缺省) 走"1 基优先"的兼容探测。线上服务端按 1 基回行号, 旧会话/
    mock 快照按 0 基, 两者都要接受; 无法映射时返回 None。

    Args:
        raw: 响应里的回显值 (``None``/非数字一律无法映射)。
        n_inputs: 本批输入坐标数, 越界即判无法映射。
        zero_based: 回显基准; ``None`` 表示未定, 由调用方探测后传入。
    """
    line = _echo_line_value(raw)
    if line is None:
        return None
    if zero_based is True:                  # 基准已定为 0 基: 只认 [0, n_inputs)
        return line if 0 <= line < n_inputs else None
    if zero_based is False:                 # 基准已定为 1 基: 只认 [1, n_inputs]
        return (line - 1) if 1 <= line <= n_inputs else None
    # 基准未定: 1 基优先 (记录在案的偏好, 见 test_crossmatch.py 的回归锚点)。
    # 两条分支在 1 <= line < n_inputs 上重叠是**有意的** —— 那一刻两种基准都能
    # 自圆其说, 只能取其一; 调用方应先探测基准再传进来, 别依赖这里的兜底。
    if 1 <= line <= n_inputs:  # 1 基优先: 服务端实际回显的就是 1 基, 先行解释可避免 0 基误判
        return line - 1
    if 0 <= line < n_inputs:  # 仅在 1 基分支落空时兜底: 0 基的 line 0 只有这里接得住
        return line
    # 越界即视为"无法关联": 宁可让该行没有 id 前缀, 也不要错挂到
    # 别的输入位置上 — 错挂的污染比缺失更难被发现。
    return None


def _angular_separation_arcsec(
    ra1: Optional[float], dec1: Optional[float], ra2: Optional[float], dec2: Optional[float]  # 两对坐标: 大角距按球面算, 不做平面近似
) -> Optional[float]:
    """两个天球位置之间的大圆角距 (单位: 角秒)。

    采用 haversine 公式, 高赤纬处的角距依然精确 (不做平面天球近似)。
    数学推导见下方行内注释; 消费方为 submit_upload_job 的逐点匹配记录。

    任一坐标缺失即返回 ``None``: 星表行可以只有 ra 没有 dec (结构半行在
    ``models.malformed_coordinate_reason`` 已单独判, 但防御层不能假设下游
    一定先过那一关)。``math.radians(None)`` 会抛 TypeError, 而调用点那圈
    ``except Exception`` 会把整条记录退化成 errors 里的异常文本 —— 那样
    ``matched`` 已置位的记录会带着空 separation 混进结果集。
    """
    # 逐个显式判 None (不用 any(...)): any() 不是类型守卫, mypy 不会据此收窄,
    # 下面 float(ra1) 就会报 float | None。
    if ra1 is None or dec1 is None or ra2 is None or dec2 is None:
        return None  # 缺坐标就算不出角距: 不拿 0.0 冒充天球原点
    r1, d1, r2, d2 = map(math.radians, (float(ra1), float(dec1), float(ra2), float(dec2)))  # 四个角一次性转弧度: 漏转一个就会差出约 57.3 倍
    # 先转弧度: haversine 的三角函数按弧度定义, 直接喂度会让结果差
    # 一个约 57.3 的因子 (度的数量级)。
    # haversine 公式: a = sin²(Δdec/2) + cos(dec1)·cos(dec2)·sin²(Δra/2)
    # 分离角 = 2·asin(√a); 相比平面近似多出 cos(dec) 因子 — dec=30° 面上 1°RA
    # 只跨 3600·cos(30°)≈3117.7″ 而非 3600″ (M5 突变由 3 条 dedup 用例守护)。
    a = (                                                                                         # haversine 形式: 小角距下数值稳定
        math.sin((d2 - d1) / 2.0) ** 2                                                              # 赤纬项: 半角正弦平方
        + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2                             # 赤纬余弦修正加赤经项: 缺一就不是球面距离
    )
    # min(1.0, ...) 防浮点误差使 asin 定义域越界; deg*3600 = deg -> arcsec
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0  # 先度后角秒一次换算: 中间值不再拿去与阈值比较


class BestCrossMatch:
    """把用户坐标交叉匹配到 BEST 星表。

    每个输入坐标触发一次针对 BEST 的锥形检索; 只返回匹配到的源,
    不下载全量星表。

    三条策略 (见模块头): 逐点并发 (:meth:`crossmatch_coords`)、
    服务端 proximity 批量 (:meth:`crossmatch_batch`)、本地磁盘任务队列
    (:meth:`submit_upload_job`)。前两条在内存内返回结果, 第三条把
    任务持久化供审计; 三者最终都收敛到同一个执行单元
    :meth:`_cone_search_single`, 保证匹配口径不会各走各的。
    """

    def __init__(self, client: BestClient) -> None:
        """持有 BestClient 实例 (HTTP 会话与锥形检索能力由 client 提供)。

        Args:
            client: 已配置好 base_url/限流/重试的客户端。

        本类不自己开 HTTP 会话也不缓存凭据: 构造**不做网络 IO**,
        因此可以安全地在纯离线测试里用替身对象构造。
        """
        self.client = client  # 只存引用: 匹配器不拥有会话生命周期, 关闭由 client 负责

    def crossmatch_coords(
        self,                                                                                       # 实例: 逐点路径的最小执行单元
        ra_list: list[float],                                                                       # 赤经列表: 与赤纬列表逐位配对
        dec_list: list[float],                                                                      # 赤纬列表: 长度不等即拒, 不静默截断
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                       # 逐点匹配半径(角秒): 缺省三角秒, 与交叉匹配常规口径一致
        id_list: Optional[list[str]] = None,                                                        # 输入标识可空: 给了就给匹配行加来源前缀
        max_workers: int = MAX_WORKERS,                                                       # 并发度: 所有 worker 共享客户端那把限流时钟
    ) -> BestQueryResult:
        """把坐标列表逐点交叉匹配到 BEST 星表 (策略 A, 回归基线)。

        对每个输入坐标发起一次小半径锥形检索, 结果合并为单个
        BestQueryResult。逐点路径同时是 proximity 批量路径
        (:meth:`crossmatch_batch`) 的回归基线与失败降级目标。

        Args:
            ra_list: RA 坐标 (单位: 度)
            dec_list: Dec 坐标 (单位: 度)
            catalog: 目标星表 (ps1, std, stripe82, gaia_dr3 等)
            radius_arcsec: 匹配半径 (单位: 角秒)
            id_list: 可选的输入 ID, 用于在 source_id 前缀中追踪来源
            max_workers: 并发检索数 (默认 4)

        Returns:
            仅含匹配源的 BestQueryResult。行按输入坐标排序 (线程池完成顺序
            不定), 保证多次运行结果可复现。

            **失败与无匹配严格可分** (``n_errors`` 即失败坐标数): 任一坐标的
            锥形检索失败时, ``query_params["n_errors"] > 0`` 且
            ``error_code`` 取首个失败码 (``E_NO_SQLID`` / ``E_SOFT_404`` 等
            客户端分类码, 异常路径回落 ``E_BACKEND``); 全部坐标失败时信封
            ``success=False``。查询成功但 0 命中才是合法的"无匹配"
            (``success=True, error_code=None, n_errors=0``) —— 站点没建出会话
            与天区真的没有源, 绝不返回同一种结果 (铁律 5)。部分失败时
            ``success=True`` 只表示"取回的行可用", 调用方须一并看 ``error_code``。
        """
        if not ra_list or not dec_list:  # 空表判失败而非返回零行: 两种结果对调用方意义完全不同
            return BestQueryResult(success=False, error="Empty coordinate list")
        # 长度不等即无法配对: 此处返回失败结果而非抛错, 与空列表同形,
        # 让调用方一处判 success 即可 (两个批量/逐点入口口径一致)。
        if len(ra_list) != len(dec_list):  # 长度不齐在入口拒: 进了线程池就再也对不回原坐标
            return BestQueryResult(success=False, error="RA/Dec list length mismatch")
        for index, (ra, dec) in enumerate(zip(ra_list, dec_list)):  # 校验单独跑一趟: 值域问题要在任何 HTTP 之前全部暴露
            # ra/dec 缺失时不得默认填 (0, 0) —— 那是一个真实天球位置 ——
            # 那样畸形输入会静默去查询天球原点而不是报错; 必须显式抛错。
            try:
                ra_value = float(ra)  # 先转 float: 值域比较要求数值, 字符串坐标会在这里直接抛
                dec_value = float(dec)                                                        # 先转浮点: 值域比较要求数值, 字符串坐标在这里就抛
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"coordinate {index} is not numeric: ra={ra!r} dec={dec!r}"
                ) from exc
            # 值域校验必须在任何 HTTP 之前: 越界坐标会被服务端静默
            # 归一成别的天区, 拿回来的匹配无法察觉是错的。
            if not 0.0 <= ra_value < 360.0 or not -90.0 <= dec_value <= 90.0:  # 半开 RA 闭 Dec: 与协议层量纲校验同口径, 两处不许分叉
                raise ValueError(
                    f"coordinate {index} out of range: ra={ra_value} dec={dec_value}"
                )

        total = len(ra_list)  # 以输入计数为准: 匹配数通常远小于它, 两者语义不可混
        all_matches: list[BestSource] = []                                                          # 匹配集容器: 只收真匹配上的源
        # errors 与 matches 并行收集: 单点失败要能报出是哪一行配错,
        # 所以不能只丢异常对象。
        errors: list[str] = []                                                                      # 错误清单: 单点失败要能报出是哪一行配错

        # 线程池并发发起逐点锥形检索; matched_by_index 以输入下标为键收集
        # 结果, 使完成顺序不影响最终输出顺序 (见下方按序回放)
        matched_by_index: dict[int, tuple[Optional[BestSource], Optional[str], Optional[str]]] = {}        # 按输入下标收集: 完成顺序不影响最终输出顺序 (源, 失败码, 失败原因)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:  # 退出 with 即 join: 未完成的 future 会被等完, 不丢结果
            futures = {}                                                                     # 任务表: 提交时就要记下标, 回收时才知道属于哪个输入
            for i, (ra, dec) in enumerate(zip(ra_list, dec_list)):  # 提交时就把下标绑上: 回收时才知道这一条属于哪个输入
                future = executor.submit(                                                           # 提交单点检索: 线程池内只跑最小执行单元
                    self._cone_search_single, ra, dec, catalog, radius_arcsec                      # 四个位置参数: 顺序与执行单元签名逐位对齐
                )
                # future → 输入下标的反查表: 提交时记, 回收时才能把
                # 乱序完成的结果还原回原坐标。
                futures[future] = i                                                           # 任务到下标的反查表: 提交时记, 回收时才能还原顺序

            for future in as_completed(futures):  # 谁先完成谁先收: 慢点不拖住已就绪的结果
                i = futures[future]                                                                # 取回下标: 完成顺序是乱的, 靠这张表还原
                try:
                    matched_by_index[i] = future.result()                                          # 结果按输入下标归档: 键就是输出顺序的依据
                except Exception as e:
                    # 兜底: _cone_search_single 内部已吞过一次, 走到
                    # 这里说明还有未预期的异常类型, 仍只记不抛 (Q-17)。
                    # 归成"查询失败"而非"无匹配": 未预期异常同样不是
                    # "这个天区没有源", 折叠过去就是又一次静默归零。
                    matched_by_index[i] = (None, _QUERY_FAILED, str(e))  # 未预期异常也归失败形状: 回放循环不必再分支

        # 输出必须确定: 按输入序号回放 (线程池完成顺序不固定), 且每个失败坐标的
        # 错误文本都要保留 (丢掉的话用户看不到是哪一行配错了)。
        first_code: Optional[str] = None                                                            # 首个失败码: 信封 error_code 取它 (按输入序, 可复现)
        for i in sorted(matched_by_index):  # 按输入序回放: 这是输出可复现的唯一保证
            src, code, err = matched_by_index[i]                                                   # 拆出源/失败码/原因: 形状固定, 三者都可能为空
            if src:  # 真值判据即可: 无源即 None, BestSource 不会自造出真值
                # id 前缀只在 id_list 够长时加: 短了就退化成无前缀,
                # 不截断 id_list 去凑 — 凑出来的前缀会挂错来源。
                if id_list and i < len(id_list):                        # 两条件缺一不可: 越界就不加前缀, 不截断 id_list 去凑数
                    src.source_id = f"{id_list[i]} -> {src.source_id}"  # 前缀而非替换: 匹配源自身的 id 是复核依据, 不能被输入 id 盖掉
                all_matches.append(src)                                                             # 追加匹配行: 只收真值判据下的源
            if err:                                                                                 # 有错误才记: 无匹配不是错误, 不进清单
                errors.append(f"Coord {i}: {err}")                                                 # 原因自带码前缀 (见 _cone_search_single): 清单文本即可排障
                first_code = first_code or code                                                    # 首个失败码定信封: 多个码并存时按输入序取, 结果可复现

        n_failed = len(errors)  # 失败坐标计数: "真空区"(0 匹配) 与"查询失败" 从此可分, 两者不再同形
        if n_failed:  # 失败必留痕: 日志是事后唯一的取证线索, 信封会被下游改写 (铁律 5)
            logger.warning("Cross-match: %d/%d coordinates failed to query (matched %d); first: %s",  # 一次一条: 逐坐标全文在 query_params 侧与 errors 清单里
                           n_failed, total, len(all_matches), errors[0])
        return BestQueryResult(  # 整批信封: 失败与空结果的可分性全部落在这几个字段上
            # success 只在"没有坐标查询失败"时才为真。三种情形:
            #   n_failed == 0            → 整批查询完成; 0 匹配是真·真空区, 合法结果;
            #   0 < n_failed < total     → **部分失败**: 已取回的行是真的, 如实交出,
            #     但 error_code 必置位 —— success=True 在此只表示"取回的行可用",
            #     不表示"这批坐标都查到了", 调用方必须一并看 error_code / n_errors;
            #   n_failed == total         → **整批失败**: 0 行 + success=True 等于把
            #     "站点压根没建出会话"说成"这批坐标没有对应源" (铁律 5 禁 fail-open)。
            success=n_failed < total,                                                              # 全灭即整体失败: 交 0 行还报成功 = 把故障说成"天区为空"
            error_code=first_code,                                                                 # 首个失败码 (输入序): 部分失败时也非空, 供调用方按码分支
            error=(f"{n_failed}/{total} coordinates failed to query, {len(all_matches)} matched: {errors[0]}" if n_failed else None),
            total_count=total,                                                                    # 总数取输入计数: 与匹配数语义不同, 不可混
            returned_count=len(all_matches),
            sources=all_matches,                                                                    # 源列表即匹配集: 未匹配的坐标不产生源
            query_params={                                                                       # 溯源整份重建: 逐点路径的语义字段集与别处不同
                "n_coords": total,
                "catalog": catalog,
                "radius_arcsec": radius_arcsec,
                "n_matched": len(all_matches),
                "n_errors": n_failed,                                                             # 失败坐标数: 查询失败才算, 无匹配不算
            },
        )

    def crossmatch_batch(
        self,                                                                                       # 实例: 批量路径与逐点路径同一入口
        ra_list: list[float],                                                                       # 赤经列表: 一次 POST 携带全部坐标
        dec_list: list[float],                                                                      # 赤纬列表: 与赤经严格等长
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                                 # 逐坐标半径(角秒): 服务端按行套用
        id_list: Optional[list[str]] = None,                                                        # 输入标识可空: 给了才加来源前缀
        columns: Optional[list[str]] = None,                                                        # 列投影可空: 不给则按该表完整列
        nearest_only: bool = True,                                                                  # 最近邻默认开: 批量匹配的常规诉求
        max_rows: int = 50000,                                                                      # 取回上限: 覆盖全部输入的期望返回量
        page_size: int = 1000,                                                                      # 页大小: 决定总往返次数
    ) -> BestQueryResult:
        """服务端 proximity 批量交叉匹配 (``pos.type=proximity``, P0-1)。

        一次 POST 以 ``ra,dec,radius`` 多行 textarea 提交全部坐标, 由服务端
        一次匹配; 响应携带 ``inputobjs_*`` 列, 把每行结果重新关联回其输入
        位置。以 1 次批量提交替代 N 次两阶段锥形检索 (实机测量: 8 坐标 =
        16 请求/25.9s -> 2 请求/7.0s), 1000 坐标只需数次请求而非约 2000 次。

        Args:
            ra_list: RA 坐标 (单位: 度)
            dec_list: Dec 坐标 (单位: 度)
            catalog: 目标星表 (ps1, stripe82, gaia_dr3_18 等)
            radius_arcsec: 逐坐标匹配半径 (单位: 角秒)
            id_list: 可选的输入 ID; 匹配行的 ``source_id`` 加
                ``"{input_id} -> {matched_id}"`` 前缀, 与逐点路径一致
            columns: 可选的 ``showcol`` 投影 (P1-8)
            nearest_only: 每个输入位置只保留最近匹配
                (``proximity_nearestonly``, 默认 True)
            max_rows: 分页取回的最大匹配行数
            page_size: 每次 API 页的行数

        Returns:
            含匹配源的 BestQueryResult (每行 ``raw_data`` 保留
            ``inputobjs_*`` 匹配元数据); ``query_params`` 记录
            ``mode="proximity"``; 失败时记录自动逐点降级信息。

        批量提交本身失败 (网络/soft-404) 时降级到 :meth:`crossmatch_coords`,
        使站点侧问题回退到慢路径, 而不是整体丢失匹配。
        """
        if not ra_list or not dec_list:  # 批量路径同形拒空: 提交一张空坐标表只会换回一次空回包
            return BestQueryResult(success=False, error="Empty coordinate list")
        if len(ra_list) != len(dec_list):                                                          # 两序列长度不等即拒: 静默截断会让配对错位
            return BestQueryResult(success=False, error="RA/Dec list length mismatch")

        total = len(ra_list)                                                                        # 总数取输入计数: 溯源里的坐标数就是它
        # HTTP 调用点 (经 client 公开 seam): 提交服务端 proximity 批量匹配 —
        # 批量表单一律走公开接口: 直连 ``client._build_form`` 私有方法会
        # 破坏封装, 私有方法签名一变这条路径就无声失效。
        batch = self.client.crossmatch_batch(  # 一次 POST 换全部匹配: N 次两阶段锥搜降为 1 次请求
            ra_list, dec_list, catalog=catalog, radius_arcsec=radius_arcsec,                     # 坐标与星表整份传: 一次 POST 换全部匹配
            columns=columns, nearest_only=nearest_only, max_rows=max_rows,                         # 投影与最近邻同传: 少一项就静默少一项能力
            page_size=page_size,                                                                    # 上限与页大小: 与逐点路径同口径
        )
        if not batch.success:  # 只有批量失败才降级: 成功路径绝不回落, 否则慢路径会掩盖批量故障
            # 显式降级: 批量路径失败 (网络/soft-404)。逐点锥形检索保留为
            # 回归基线, 此处作为兜底继续完成匹配, 失败原因记入 query_params
            logger.warning(                                                                       # 降级必须告警: 批量路径的故障不能被降级掩盖
                "proximity batch failed (%s); falling back to per-coordinate "
                "cone searches", batch.error,
            )
            fallback = self.crossmatch_coords(  # 回退到逐点: 站点侧问题不该让整批匹配直接消失
                ra_list, dec_list, catalog, radius_arcsec, id_list                               # 回退到逐点: 站点侧问题不该让整批匹配直接消失
            )
            fallback.query_params["mode"] = "per_coordinate_fallback"
            fallback.query_params["batch_error"] = batch.error  # 失败原因随结果一起走: 降级后原始故障就查不到了
            return fallback

        matched = list(batch.sources)                                                               # 匹配集拷贝: 下面要就地改写来源标识
        # 先把回显行号收齐 (两条回显列名都试: 不同 BEST 星表的响应列前缀不一致,
        # 写死一个会在另一些星表上丢掉全部来源标注; 未提交 showcol 时压根没有
        # 回显列, 这时留 None, 下面按无法映射处理)。
        echo_raw: list[Any] = [
            (s.raw_data or {}).get("inputobjs_input_line", (s.raw_data or {}).get("input_line"))
            for s in matched
        ]
        # 回显基准探测 (两条互斥的**决定性**信号, 必须在**原值域**里判):
        #   line 0      只可能出自 0 基批次 —— 1 基回显最小是 1;
        #   line n_in   只可能出自 1 基批次 —— 0 基回显最大是 n_inputs-1。
        # 两条都没出现时基准不可判 (例如 0 基批次里恰好第一个坐标没命中), 此时
        # 按记录在案的 1 基偏好兜底, 并把 line_convention 记成 ambiguous 让
        # 歧义**可观测** —— 静默猜错会整批错挂, 比缺前缀更难发现。
        echo_lines = [
            value for value in (_echo_line_value(v) for v in echo_raw)
            if value is not None
        ]
        zero_based: Optional[bool] = None                                         # None = 基准未定
        if 0 in echo_lines:
            zero_based = True                                                    # 出现 0 基的地板值: 基准只能是 0 基
            convention = "0-based"
        elif total in echo_lines:
            zero_based = False                                                   # 出现 1 基的天花板值: 基准只能是 1 基
            convention = "1-based"
        else:
            convention = "ambiguous"                                             # 两条决定性信号都没出现: 基准不可判, 本批一律不挂前缀
        n_labelled = 0                                                                              # 标注计数: 多少行成功挂上了输入标识
        for src, line_raw in zip(matched, echo_raw):                                                # 逐行标注: 靠回显行号把结果接回输入
            idx = _input_line_index(line_raw, total, zero_based=zero_based)    # 映射到 0 基: 基准已在上面统一定过, 同一批不得逐行各猜
            # 基准不可判时**不挂前缀** (宁缺勿错): 该函数带 "1 基优先" 兼容兜底,
            # 但把那个猜测用在本行的 id 归属上就会错挂 —— 0 基批次里只有第 2 个
            # 坐标命中时回显 "1", 兜底映射成 0, 于是 B 的匹配行挂上 A 的 id
            # ("ID_A -> ps1_99", 真值 ID_B)。缺前缀只是信息少, 错挂是**假信息**
            # 且更难发现 (行仍在、坐标也对, 只有 id 是错的)。歧义本身仍由
            # line_convention="ambiguous" 与 n_labelled=0 外带, 可事后复核。
            if zero_based is not None and idx is not None and id_list and idx < len(id_list):  # 四条件并判: 基准不可判/映射失败/无 id/越界都退化为无前缀
                src.source_id = f"{id_list[idx]} -> {src.source_id}"           # 按回显下标取 id: 批量返回顺序不保证与输入一致
                n_labelled += 1                                                                     # 标注计数累加: 溯源里的标注率靠它算

        # query_params 整份覆盖而非逐键合并: 批量路径的语义字段集与
        # 逐点路径不同, 合并会残留逐点路径的 n_errors 造成误读。
        batch.query_params = {  # 整份替换: 客户端带回的是查询面字段, 不含本路径的标注率等语义
            "mode": "proximity",
            "n_coords": total,
            "n_inputs": total,
            "catalog": catalog,
            "radius_arcsec": radius_arcsec,
            "nearest_only": nearest_only,
            "n_matched": len(matched),
            "n_labelled": n_labelled,
            "line_convention": convention,                                                          # 本批回显基准: 歧义时落 "ambiguous" 供事后复核
            "truncated": batch.truncated,
        }
        return batch

    def _cone_search_single(
        self,                                                                                       # 实例: 线程池内调用的最小单元
        ra: float,                                                                                  # 单点赤经: 与赤纬共同定位天区
        dec: float,                                                                                 # 单点赤纬: 值域在提交前已校验
        catalog: str,                                                                               # 目标星表: 三条策略最终都收敛到这一处
        radius_arcsec: float,                                                                  # 单点半径(角秒): 只取最近邻, 半径控制每点流量
    ) -> tuple[Optional[BestSource], Optional[str], Optional[str]]:
        """单坐标锥形检索 (逐点路径的最小执行单元, 在线程池内调用)。

        Returns:
            ``(源, 失败码, 失败原因)`` 三元组, 三种结局互不同形:
            匹配成功 → ``(BestSource, None, None)``;
            **查询成功但无匹配** → ``(None, None, None)`` (0 命中不是错误);
            **查询失败** → ``(None, error_code, "码: 原因")``, 失败码取客户端
            分类码 (``E_NO_SQLID`` / ``E_SOFT_404`` 等), 异常路径回落
            ``E_BACKEND``; 检索异常同样走这一支 (码为 ``E_BACKEND``)。
        """
        try:
            # HTTP 调用点: 经 BestClient 向 BEST 发起约束式锥形检索;
            # max_records=1 只取最近邻, 小半径控制每点流量
            result = self.client.cone_search(  # 三条策略最终都收敛到这一处, 匹配口径才不会各走各的
                ra=ra, dec=dec,                                                                   # 几何参数按名传: 位置传参易把中心与半径对调
                radius_arcsec=radius_arcsec,                                                       # 半径独立一行: 与赤经赤纬同口径但不同单位
                catalog=catalog,                                                                    # 星表随行传: 与上面几项同为请求面参数
                max_records=1,  # 只取 1 条: 交叉匹配要的是一个对应, 不是锥内全部
            )
            if result.success and result.sources:  # 两条件都要: 失败信封里的 sources 不可信
                return result.sources[0], None, None
            if not result.success:
                # 失败必须自带码与原因: 早先这里对"失败"与"无匹配"一律返回
                # (None, None), 于是站点一次软错误 (实跑: 故意错 base_url
                # 前缀 → 底层 E_NO_SQLID) 被上层读成"这批坐标没有对应源",
                # 整批匹配静默归零 (G1-01 实跑证据)。
                code = result.error_code or _QUERY_FAILED                                          # 优先信客户端的码: 消息措辞会随站点改版漂移, 码不会
                return None, code, f"{code}: {result.error or 'cone search failed'}"                 # 码前缀写进原因: 清单文本单独拿出来也能排障
            return None, None, None  # 真·无匹配: 0 命中不是错误, 交回给调用方按"该坐标无对应源"处理
        except Exception as e:
            # 异常转字符串而非上抛: 调用方在 as_completed 循环里逐条
            # 收集, 上抛会打断整批匹配 (Q-17 单点失败隔离)。
            return None, _QUERY_FAILED, f"{_QUERY_FAILED}: {e}"  # 异常转字符串: 在线程池里上抛会打断整批匹配

    def crossmatch_source_list(
        self,                                                                                       # 源字典列表: 每个字典至少含坐标键
        sources: list[dict[str, Any]],                                                    # 每个字典至少含坐标: 缺键落到零坐标会把真实天球位置当数据查
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                                 # 匹配半径(角秒): 与逐点路径同缺省
    ) -> BestQueryResult:
        """交叉匹配一组源 dict (每个 dict 至少含 "ra"/"dec" 键)。

        可选的 "id" 或 "source_id" 键用于追踪来源。

        Args:
            sources: 含 ra/dec 的 dict 列表
            catalog: 目标星表
            radius_arcsec: 匹配半径 (单位: 角秒)

        Returns:
            BestQueryResult

        Raises:
            ValueError: 某个源 dict 没有可用的 ``ra``/``dec`` (缺省落到
                (0, 0) 会把一个真实天球位置当作数据来检索, 属静默错误)
        """
        ra_list: list[float] = []                                                                   # 赤经收集: 逐源取值, 顺序即输入序
        dec_list: list[float] = []                                                                 # 赤纬收集: 与赤经同步追加, 下标严格对齐
        id_list: list[str] = []                                                                     # 标识收集: 三级兜底保证每行可追踪
        n_fallback = 0                                                                              # 走下标兜底的行数: 脏输入必须留痕, 不静默换名
        for index, source in enumerate(sources):                                               # 逐源遍历: 下标要带进错误消息, 才能定位是哪一行
            # None 判据而非真值: ra=0.0 是合法坐标, 用 `if not ra`
            # 会把赤道原点的源误报成"缺 ra/dec"。
            if source.get("ra") is None or source.get("dec") is None:
                raise ValueError(
                    f"source {index} has no ra/dec: {sorted(source)[:6]}"
                )
            ra_list.append(float(source["ra"]))
            dec_list.append(float(source["dec"]))
            # id 回退到 source_id 再回退到下标: 三级兜底保证每行都有
            # 可追踪标识, 否则匹配结果无法反查输入。
            # 逐级 `is None` 判定而非 `.get` 默认值 —— `.get("id", …)` 只在
            # **键缺失**时回落, 值是 None 时原样返回, `str(None)` 于是把
            # Python 关键字 None 变成字面串 "None" 混进 source_id 前缀
            # ("None -> ps1_123"): 真实 id 被吞, 且该前缀与合法 id 无法区分,
            # 比缺前缀更难发现的错挂 (G1-07 同形缺陷, 口径与
            # src/ai_tools.py 的 id_list 收集点一致)。
            raw_id = source.get("id") if source.get("id") is not None else source.get("source_id")  # 两级取值: 键存在但值为 None 也算缺失
            if raw_id is None or not str(raw_id).strip():  # 空串/纯空白同样视作缺失: 拼出的是无主前缀
                raw_id = index  # 最后落到输入下标: 至少还能指回"是哪个输入"
                n_fallback += 1  # 计数而非静默: 事后能从日志看出有多少行是兜底名
            id_list.append(str(raw_id))  # 三级兜底: id 到 source_id 到输入序号, 保证每行可追踪
        if n_fallback:
            # 告警而非抛错: id 脏不该让整批匹配消失 (坐标本身有效), 但绝不
            # 静默把 None 变成 "None" 前缀混进结果行 (铁律 5)。一批一条:
            # 逐行 warn 会把千行坐标的日志刷爆。
            logger.warning("crossmatch_source_list: %d/%d sources had no usable id; "
                           "labelled by input index instead", n_fallback, len(sources))
        return self.crossmatch_coords(
            ra_list, dec_list, catalog, radius_arcsec, id_list                                    # 整份下传: 逐点路径负责真正的并发与失败隔离
        )

    def crossmatch_from_csv(
        self,                                                                                       # 实例: 文件入口走同一条逐点路径
        csv_path: str,                                                                             # CSV 路径: 坐标来源是文件而非内存列表
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                                 # 匹配半径(角秒): 与其它入口同缺省
        ra_col: str = "ra",
        dec_col: str = "dec",
        id_col: Optional[str] = None,                                                               # 标识列名可空: 缺列时退化为无前缀路径
    ) -> BestQueryResult:
        """从 CSV 文件读取坐标并交叉匹配。

        Args:
            csv_path: 含 ra/dec 列的 CSV 路径
            catalog: 目标星表
            radius_arcsec: 匹配半径
            ra_col: RA 列名
            dec_col: Dec 列名
            id_col: 可选的 ID 列名

        Returns:
            BestQueryResult
        """
        ra_list: list[float] = []                                                                   # 赤经收集: 与内存路径同构
        dec_list: list[float] = []                                                                  # 赤纬收集: 同上
        id_list: list[str] = []                                                                     # 标识收集: 缺列时保持空列表

        # 文件读取点: utf-8-sig 兼容 Excel 导出 CSV 的 BOM 头; 列缺失/数值
        # 畸形会直接抛异常 (不吞错), 由调用方决定如何处理坏输入
        with open(csv_path, "r", encoding="utf-8-sig") as f:  # utf-8-sig 吃掉 Excel 导出的 BOM: 否则第一个表头名多一个不可见字符
            reader = csv.DictReader(f)                                                             # 按表头读行: 列名写错会在取值时当场炸出来
            for row in reader:                                                                      # 逐行取值: 不静默跳过坏行
                # 直接 float(...) 不包 try: 列名写错/单元格畸形属调用方
                # 的输入错误, 必须当场炸出来而不是静默跳过整行。
                ra_list.append(float(row[ra_col]))                                           # 赤经直接转浮点: 畸形值属调用方输入错误, 必须炸出来
                dec_list.append(float(row[dec_col]))                                                # 赤纬同样直接转浮点: 同上
                # 列存在才收 id: 缺 id 列时保持空列表, 由下方
                # `id_list or None` 决定是否退化为无前缀路径。
                if id_col and id_col in row:                                                       # 列存在才收标识: 缺列时下方按无前缀路径走
                    id_list.append(str(row[id_col]))  # 值统一转字符串: 数字 id 也要与下标兜底走同一形态

        return self.crossmatch_coords(
            ra_list, dec_list, catalog, radius_arcsec,                                              # 坐标与星表整份传: 与内存入口同一签名
            id_list=id_list or None,                                                                # 空列表归一成空值: 免得下游再判一次长度
        )

    def submit_upload_job(
        self,                                                                                       # 实例: 任务队列的编排器
        file_content: str,                                                                        # CSV 文本内容: 内存形态输入, 不经文件
        catalog: str = "ps1",
        radius_arcsec: float = 3.0,                                                                 # 匹配半径(角秒): 逐坐标共用
        output_dir: Union[str, Path] = ".",
        max_workers: int = MAX_WORKERS,                                                         # 并发度: 与逐点入口同缺省, 同样受限流时钟约束
    ) -> BestCrossMatchJob:
        """本地批量交叉匹配任务并持久化到磁盘 (策略 C; 实现已抽至 crossmatch_jobs)。

        委派壳: 同名同签名保留 —— 这是仓内**公开**的作业提交面
        (references/client-api-reference.md 登记在册), 调用方按名字调它。
        解析/落盘/并发/终态 manifest 的编排与「失败返回句柄而非上抛」的契约
        由 crossmatch_jobs 承担, 本壳只做转发。
        """
        # 延迟导入: 策略 C 抽离件 (预算 §3.13; 别名避与壳同名)
        from src.crossmatch_jobs import submit_upload_job as _submit_upload_job_impl

        return _submit_upload_job_impl(
            self, file_content, catalog, radius_arcsec, output_dir, max_workers,  # 位置直传: 六个位置参数, 无错位余地
        )

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        """本地任务队列用的 JSON 落盘 (薄壳, 原子性由共享实现承担)。

        此前本方法自带一份 tmp + os.replace 副本, 与 ``src.scripts.guards``
        的 ``atomic_write_text`` 重叠 —— 那份副本正是"全仓单一实现"要防的
        漂移面。现整段委派出去: 原子语义、失败时的临时文件清理、newline
        口径三件事只有一处定义。
        """
        # 文件写入点: ensure_ascii=False 保留中文可读
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
