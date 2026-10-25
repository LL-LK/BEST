# -*- coding: utf-8 -*-
"""src.crossmatch_jobs — 交叉匹配的策略 C: 本地磁盘任务队列 (抽离件, budget §3.13)。

能力边界: ``BestCrossMatch.submit_upload_job`` 的实现 —— 从内存 CSV 文本解析
坐标、落盘 ``input.csv`` 与 running 态 manifest、线程池逐点锥形检索、落盘
``results.json``、再把 manifest 推到 completed / failed 终态, 全程返回
``BestCrossMatchJob`` 句柄。抽离缘由: ``src/crossmatch.py`` 抽离前实测 400 净行,
**零余量**, 故必须先抽函数 (budget §3「次接近上限」名单); 本轮
`ops/audit/count_code_lines.py` 实测已回到 285 净行, 零余量已不成立。

**为什么按策略 C 切**: 交叉匹配有三条策略 (A 逐点并发 / B 服务端 proximity
批量 / C 本地磁盘任务队列), 前两条**只在内存里返回结果**, 唯独策略 C 碰磁盘
—— 它自带 job 目录、manifest 状态机与「进程被杀也要在磁盘上留证据」这套
持久化纪律。这条边界是模块头自己声明的, 按它切最内聚, 且切完 crossmatch.py
里剩下的两条策略与四个模块级几何/回显助手构成一个纯粹的「内存匹配」单元。

**留在 crossmatch.py 的东西与理由**:
  - ``_angular_separation_arcsec`` —— 被策略 C 消费, 但归属「球面几何」这一
    独立关注点, 且有仓外引用 (``evals/probes.py`` / ``test_fixes.py`` /
    ``references/client-api-reference.md``), 搬走会断那些引用;
  - ``_cone_search_single`` —— 三条策略最终收敛到的公共执行单元, 抽走会让
    策略 A 与策略 C 的调用点跨文件; 本模块经 ``matcher`` 形参回调它。

契约:
  - 原地委派壳: ``BestCrossMatch.submit_upload_job`` 保留同名同签名, 壳只
    转发; ``_write_json`` 保留同名同签名的 staticmethod 委派壳, 且实现体经
    ``matcher._write_json(...)`` 回调它 —— 壳因此不是死代码, 对它的 patch
    仍然生效;
  - 失败语义不变: 任务队列的契约是「提交即返回 job 句柄」, 因此失败态
    **返回** ``status="failed"`` 的句柄而不上抛 (抛异常会让调用方拿不到
    job_id 而无法回查 manifest); 全表无可解析行才抛 ``ValueError`` (空任务
    不该占掉一个 job 目录);
  - 单点失败隔离 (Q-17) 不变: 逐坐标异常只进 ``errors`` 清单, 不中断整批;
  - 半提交记录的坑不变: ``matched`` 置位必须等角距算完, 否则源坐标缺失时
    会留下一条「已匹配但 separation 为空」且照样计入 n_matched 的记录。

白盒锚点: src/crossmatch.py (三条策略与公共执行单元) / src/models/__init__.py
(BestCrossMatchJob / BestCrossMatchResult) / src/scripts/guards.py
(atomic_write_text —— 全仓唯一原子写实现)。
"""
from __future__ import annotations

# 标准库: csv/io 解析上传的 CSV 内容, json 负责任务文件序列化 (落盘走共享
# atomic_write_text), uuid/datetime 生成任务 id 与时间戳, ThreadPoolExecutor
# 并发执行逐点锥形检索
import csv
import io
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

# 本地: 作业句柄与逐坐标结果模型 (任务队列的返回契约)
from src.models import BestCrossMatchJob, BestCrossMatchResult  # 缺一个就把句柄或结果列表的形态定错

# 本地: 全仓唯一原子写实现: 本模块的 input.csv/manifest/results 一律走它
from src.scripts.guards import atomic_write_text

# 任务队列的磁盘根目录名: 随策略 C 一起搬来, 且**只有本模块定义它** ——
# crossmatch.py 侧的同名常量已随之删除, 两处各留一份就又是「两份定义」漂移面。
JOBS_DIRNAME = "best_crossmatch_jobs"

logger = logging.getLogger(__name__)  # 任务队列自持 logger: 后台跑时日志是唯一的即时线索



def submit_upload_job(
    matcher,                                                                                        # 匹配器: 经它读 client 与公共执行单元 _cone_search_single
    file_content: str,                                                                              # CSV 文本内容: 内存形态输入, 不经文件
    catalog: str,                                                                                   # 目标星表 (ps1, std, stripe82, gaia_dr3 等)
    radius_arcsec: float,                                                                            # 匹配半径(角秒): 逐坐标共用
    output_dir: Union[str, Path],                                                                   # 磁盘任务队列的基目录
    max_workers: int,                                                                                # 并发度: 委派壳必传 —— 缺省值是 crossmatch.MAX_WORKERS 这个具名常量, 在此写死 4 就是复制第二份
) -> BestCrossMatchJob:
    """对 CSV 内容执行本地批量交叉匹配任务并持久化到磁盘 (策略 C)。

    BEST 服务未开放公开上传/任务 API, 故批量在客户端执行: 从
    ``file_content`` 解析坐标, 逐个走逐点锥形检索管线
    (:meth:`_cone_search_single`)。任务 manifest、输入 CSV 与逐坐标
    ``BestCrossMatchResult`` 列表落盘到
    ``<output_dir>/best_crossmatch_jobs/<job_id>/`` 供审计。

    Args:
        file_content: CSV 文本, 表头至少含 ``ra``/``dec`` 列
            (可选的 ``id`` 列被追踪)。
        catalog: 目标星表 (ps1, std, stripe82, gaia_dr3 等)
        radius_arcsec: 匹配半径 (单位: 角秒)
        output_dir: 磁盘任务队列的基目录
        max_workers: 并发锥形检索数

    Returns:
        BestCrossMatchJob, 含真实 job_id、最终状态 (``"completed"`` 或
        ``"failed"``) 与 ``output_url`` 中的结果文件路径。

    Raises:
        ValueError: ``file_content`` 中没有任何可解析的 ra/dec 行。
    """
    # 延迟导入: 球面角距助手留在 crossmatch.py (归属几何关注点, 且有仓外
    # 引用: evals/probes.py / test_fixes.py / references 文档), 搬来会断那些
    # 引用; 按 §3.9 原则 2 不反向 import, 故在调用点惰性取。
    from src.crossmatch import _angular_separation_arcsec  # 函数内导入: 破 import 环, 代价是每次作业查一次模块缓存

    created = datetime.now(timezone.utc).isoformat()                                            # 创建时间: 统一 UTC, 跨机器可比
    ra_list: list[float] = []                                                                   # 赤经收集: 坏行跳过时仍保持三表同下标
    dec_list: list[float] = []                                                                  # 赤纬收集: 同上
    id_list: list[str] = []                                                                     # 标识收集: 同上

    # 手工剥 BOM: DictReader 会把 \ufeff 吃进第一个表头名, 令
    # row.get("ra") 恒为 None, 整份 CSV 解析成零行。
    if file_content.startswith("\ufeff"):
        file_content = file_content[1:]                                                     # 手工剥 BOM: 解析器会把标记吃进第一个表头名

    reader = csv.DictReader(io.StringIO(file_content))                                          # 按表头读行: 内存文本走同一个解析器
    for i, row in enumerate(reader):                                                            # 带下标遍历: 坏行日志要指明是哪一行
        try:
            ra = float((row.get("ra") or "").strip())
            dec = float((row.get("dec") or "").strip())
        except (TypeError, ValueError):
            # 与 crossmatch_from_csv 相反的口径: 任务队列面向批量,
            # 个别坏行跳过后仍能完成其余匹配, 故记 warning 而非抛。
            logger.warning("Job row %d skipped: invalid ra/dec %r", i, row)
            continue
        # 跳过行不进 id_list: 三个列表必须同下标对齐, 补占位会让
        # 后续 input_id 与坐标错位。
        ra_list.append(ra)                                                                 # 追加赤经: 跳过行不占位, 三个列表必须同下标对齐
        dec_list.append(dec)                                                                    # 追加赤纬: 同上
        # id 三级兜底 (id -> 输入序号), 逐级 `is None` 判定而非 `.get` 默认值:
        # `.get("id", i)` 只在**键缺失**时回落 i, 而 DictReader 对「表头有 id
        # 但该行字段不足」的情形填的是 None, 于是原写法 str(None) 把 Python
        # 关键字 None 变成字面串 "None" 混进 source_id 前缀 ("None -> ps1_123"):
        # 真实 id 被吞, 且该前缀与合法 id 无法区分, 比缺前缀更难发现的错挂。
        # 空串/纯空白同样视作缺失: 拼出的是无主前缀。口径与
        # crossmatch_source_list 与 src/ai_tools.py 的 id 收集点一致 (G1-07)。
        raw_id = row.get("id") if row.get("id") is not None else None  # 两级取值: 键存在但值为 None 也算缺失
        if raw_id is None or not str(raw_id).strip():  # 空串/纯空白同样视作缺失: 拼出的是无主前缀
            raw_id = i  # 最后落到输入下标: 至少还能指回"是哪个输入"
        id_list.append(str(raw_id))  # 三级兜底: id 到输入序号, 保证每行都有可追踪标识

    if not ra_list:  # 全表无可解析行即拒: 空任务不该占掉一个 job 目录
        raise ValueError(
            "submit_upload_job: no parseable ra/dec rows found in file_content "
            "(expected a CSV header with 'ra' and 'dec' columns)"
        )

    # job_id = UTC 时间戳 + 8 位随机十六进制: 时间戳给人排序,
    # 随机段防同秒并发提交撞名 (时间戳单独用会覆盖彼此的目录)。
    job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"  # 时间戳给人排序, 随机段防同秒并发提交互相覆盖目录
    job_dir = Path(output_dir) / JOBS_DIRNAME / job_id                                          # 三级路径: 基目录/队列根/任务 id, 便于整队列归档
    # 文件写入点: 建任务目录并原样留存输入 CSV, 保证事后可回溯复现匹配
    job_dir.mkdir(parents=True, exist_ok=True)                                                  # 任务目录建在提交时: 目录不存在则先建
    # 输入留痕必须原子写: 进程死在写一半时, 就地 write_text 会留下一份看着
    # 完整、实则截断的 input.csv —— 事后回溯复现会拿它当真输入。
    atomic_write_text(job_dir / "input.csv", file_content, encoding="utf-8")                  # 全包单一实现, 不在本模块私带副本
    manifest: dict[str, Any] = {                                                            # 清单容器: 先写运行态, 进程被杀时磁盘上有证据
        "job_id": job_id,
        "status": "running",  # 先写 running: 进程被杀时磁盘上留有未完成的证据
        "created": created,
        "catalog": catalog,
        "radius_arcsec": radius_arcsec,
        "input_sources": len(ra_list),
    }
    # 先落盘 running 态 manifest: 任务若中途被杀, 磁盘上留下"未完成"
    # 的证据, 而不是悄悄消失
    matcher._write_json(job_dir / "job.json", manifest)

    results: list[BestCrossMatchResult] = []                                              # 结果列表: 失败坐标也留一条, 输出行数才对得上输入
    errors: list[str] = []                                                                      # 错误清单: 逐坐标累计, 不中断整批
    try:
        # 逐点锥形检索并发执行; as_completed 到岗即记, 单点失败只进
        # errors 列表、不中断整批 (manifest 声明的单点失败隔离 Q-17)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:  # 并发度保守: 所有 worker 共享客户端那把限流时钟
            futures = {                                                                       # 任务到下标的映射: 提交时绑定, 回收时反查
                executor.submit(                                                           # 提交单点检索: 复用最小执行单元, 不另写一份逻辑
                    matcher._cone_search_single, ra, dec, catalog, radius_arcsec                   # 四个位置参数: 与执行单元签名逐位对齐
                ): i
                for i, (ra, dec) in enumerate(zip(ra_list, dec_list))                           # 提交时即按下标: 乱序完成才能还原回输入
            }
            for future in as_completed(futures):                                                # 谁先完成谁先收: 慢点不拖住已就绪的结果
                i = futures[future]                                                             # 取回输入下标: 靠提交时那张映射表
                # 先建记录再等结果: 失败坐标也必须留一条未匹配记录,
                # 否则输出行数与输入行数对不上, 无法判断是漏匹配还是漏输入。
                rec = BestCrossMatchResult(  # 先建记录再等结果: 失败坐标也留一行, 输出行数才能对上输入
                    input_id=id_list[i],                                                        # 输入标识: 来自解析阶段的标识列表
                    input_ra=ra_list[i],                                                        # 输入赤经: 记输入值, 与匹配源坐标分开
                    input_dec=dec_list[i],                                                      # 输入赤纬: 同上
                    match_radius_arcsec=radius_arcsec,  # 记的是检索条件: 实际偏差另存 separation_arcsec, 两者不可混
                    catalog=catalog,                                                            # 目标星表: 进每条结果, 便于事后分组
                )
                try:
                    src, _code, err = future.result()                                         # 取回单点结果: 形状固定为 (源, 失败码, 原因); 码已自带在原因文本里, 清单不必再拼一次
                    if src is not None:                                                       # 有源才标匹配: 无源即未匹配, 不靠异常判断
                        # 角距用**输入坐标**与**匹配源坐标**现算, 不用
                        # 检索半径: 后者是查询条件, 前者才是用户想看的
                        # 实际偏差。
                        # 顺序要紧: matched 必须等 separation 算完再置位。
                        # 先置位的话, 源坐标缺失导致角距算不出时, 记录会以
                        # 「已匹配」提交却带着空 separation/matched_source,
                        # 还照样计入 n_matched —— 半提交的记录比缺记录更难查。
                        separation = _angular_separation_arcsec(                            # 现算角距: 半径是查询条件, 这个才是用户想看的实际偏差
                            ra_list[i], dec_list[i], src.ra, src.dec                         # 用输入坐标与源坐标现算: 半径是查询条件不是实际偏差
                        )
                        rec.separation_arcsec = separation                                     # None 表示源坐标不全算不出角距: 如实留空, 不填 0.0
                        rec.matched_source = src                                              # 挂上匹配源: 结果文件因此自带源对象
                        rec.matched = True                                                    # 置匹配标志: 汇总计数靠它现算, 不另维护累加器
                    if err:                                                                     # 有错误才记: 无匹配不是错误
                        errors.append(f"Coord {i}: {err}")
                except Exception as e:  # noqa: BLE001 - 记入 errors 后继续
                    errors.append(f"Coord {i}: {e}")  # 未预期异常走同一归档: 任务队列不能因一行崩掉
                results.append(rec)                                                             # 记录入库: 无论成败每行都占一条

        # 文件写入点: 逐坐标结果 + 错误清单落盘 (原子写, 见 _write_json)
        results_path = job_dir / "results.json"
        # n_matched 现算而非累加: 累加要跨 except 分支维护, 漏一处
        # 就会和 results 里的实际 matched 字段不一致。
        matcher._write_json(results_path, {  # 结果先落盘再更新 manifest: 顺序反了会留下指向空结果的 completed
            "job_id": job_id,
            "catalog": catalog,
            "radius_arcsec": radius_arcsec,
            "created": created,
            "n_inputs": len(ra_list),
            "n_matched": sum(1 for r in results if r.matched),
            "n_errors": len(errors),
            "errors": errors,
            "results": [r.to_dict() for r in results],
        })

        manifest.update({                                                                # 终态整份更新: 顺序字段追加, 不覆盖已写的输入侧字段
            "status": "completed",
            "matched": sum(1 for r in results if r.matched),
            "finished": datetime.now(timezone.utc).isoformat(),
            "output_url": str(results_path),  # 指向结果文件而非目录: 调用方拿到就能直接读
        })
        # 收尾: manifest 更新为 completed 终态后再落盘
        matcher._write_json(job_dir / "job.json", manifest)  # completed 终态最后落: 它是审计的最终凭据
        logger.info(                                                                         # 完成也打日志: 后台跑的队列常没有别的即时线索
            "Batch cross-match job %s completed: %d/%d matched, %d errors",
            job_id, manifest["matched"], len(ra_list), len(errors),
        )
        return BestCrossMatchJob(
            job_id=job_id,                                                                      # 作业句柄: 提交即返回, 调用方拿它回查
            status="completed",
            created=created,                                                                    # 创建时间回传: 与清单里的值同源
            input_sources=len(ra_list),                                                         # 输入行数: 与清单字段一致
            matched=manifest["matched"],
            output_url=str(results_path),  # 完成态给结果路径, 失败态给 manifest 路径, 两种都可读
        )
    except Exception as e:  # noqa: BLE001 - 失败如实落进 manifest, 不静默吞
        manifest.update({                                                                       # 失败态整份更新: 状态与原因一次写全
            "status": "failed",
            "error": str(e),  # 错误全文进 manifest: 只写 failed 不写原因等于没留证据
            "finished": datetime.now(timezone.utc).isoformat(),
        })
        # 诚实持久化失败: manifest 落 failed 态与错误文本, 不假装完成
        matcher._write_json(job_dir / "job.json", manifest)
        logger.error("Batch cross-match job %s failed: %s", job_id, e)  # 失败也打日志: 任务队列常在后台跑, 日志是唯一的即时线索
        # 返回 failed 而非上抛: 任务队列的契约是"提交即返回 job
        # 句柄", 抛异常会让调用方拿不到 job_id 而无法回查 manifest。
        return BestCrossMatchJob(
            job_id=job_id,                                                                  # 失败也返回句柄: 抛异常会让调用方拿不到任务标识
            status="failed",
            created=created,                                                                   # 创建时间同源: 成功与失败两条路给同一口径
            input_sources=len(ra_list),                                                        # 输入行数: 失败态也如实报, 便于判断规模
            matched=0,                                                                        # 失败时匹配数为零: 没有结果就不许报一个假数
            output_url=str(job_dir / "job.json"),
        )
