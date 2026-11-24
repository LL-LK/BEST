"""src.core.source_postprocess — BEST 源记录的领域级后处理 (去重/亮度筛选/波段统计)。

能力边界: BestProcessor: 对已取回的源记录做纯函数式后处理。边界: 只做
行级变换与统计, 不发任何网络请求、不落盘 (落盘归 downloader/best_export); 坐标
运算与 crossmatch._angular_separation_arcsec 同一套 haversine 口径, 不引入
第二套球面距离实现。

还原记录: 迁移自 pybest 打包产物 (git 6f00efeb^〔本仓历史已无此对象〕〔本仓历史已无此对象〕) 的 ``pybest/core/processor.py`` (该树在 best
分支 "Phase 8 扁平化" 时整体删除)。三项能力在当前 src/ 均无等价实现:
``deduplicate`` (真球面去重)、``bright_sources`` (亮度筛选)、
``band_summary`` (波段计数)。

白盒锚点: references/ALGORITHM-SPEC.md §2 (processor 锚点)。
"""
from __future__ import annotations

# 标准库: math 提供 haversine 球面距离与有限性/哨兵判断; typing 供标注
import math
from typing import Any

# 本地: 星等列判据单点 (由 protocol.CATALOG_MAG_COLUMNS 现场推导后缀集)。
# 自建 `endswith("mag")` 清单是本模块此前的做法, 它漏掉站点实际发布的大多数列名。
from src.serialization import is_magnitude_column


class BestProcessor:
    """BEST 源记录的领域后处理工具集 (全部为静态方法, 无状态)。"""

    @staticmethod
    def bright_sources(
        sources: list[dict],
        mag_limit: float = 16.0,
        band: str | None = None,
    ) -> list[dict]:
        """筛选亮于 ``mag_limit`` 的源 (严格小于)。

        ``band`` (2026-10-07 新增, D4): **指定用哪个波段的星等判亮度**。缺省 ``None``
        时按下面的"代表列"兜底口径走, 而那个口径是**猜出来的** —— 所以它只该在
        确实不关心波段时用。

        兼容两种行形态: 归一化行 (``best_mag`` 由 from_row 写入) 与原始行
        (``{catalog}_{band}mag`` 投影)。缺测 (None/空/哨兵) 一律剔除 —
        "没有测光" 不等于 "暗", 不能靠默认值放行。

        **为什么不带 band 就错 (实测)**: 旧实现把"按键名排序的第一个可解析星等列"
        当代表值。gaia 的列是 ``phot_b_mean_mag`` / ``phot_g_mean_mag`` / …, 按字母序
        ``b`` 永远排在最前, 于是**恒定拿蓝带来判所有源的亮度**。实测真实 gaia
        1000 行过 ``mag_limit=16`` 只剩 **13** 行 —— 不是因为那 987 颗暗, 而是因为
        它们在蓝带缺测, 于是被当"没有测光"整行剔除。结构性默认值(字典序第一个)
        恰好挑中了信息最少的那一列, 而结果被读成"这批星就是暗"。
        """
        representative = None  # 代表列只在 band 缺省时才需要; 显式给了 band 就不用猜
        if band is None and sources:  # 空输入不必选列 (见下方 early-return 的 kept)
            representative = BestProcessor.representative_magnitude_column(sources)
        kept: list[dict] = []  # 只收亮于门限的行: 缺测行在下面被滤掉, 不进结果
        for source in sources:  # 逐行判定: 筛选是纯行级变换, 不改写入参
            # mag is None = 该行"没有测光"而非"暗": 缺测行一律剔除, 不能靠
            # 默认值放行, 否则亮度筛选会把无测光行当成最亮的行收进来
            mag = BestProcessor._best_magnitude(source, band=band,  # 取代表星等: 显式 band 优先, 否则用兜底代表列
                                                 representative=representative)
            if mag is not None and mag < mag_limit:  # 严格小于: 等于极限星的算不算亮, 口径必须钉死
                kept.append(source)  # 存原行引用: 后处理不改内容, 下游拿到的仍是取回时那一条
        return kept

    @staticmethod
    def representative_magnitude_column(sources: list[dict]) -> str | None:
        """在 ``band`` 缺省时挑一个"代表星等列" —— **按数据完整度, 不按字典序**。

        口径: 逐个候选星等列数一遍"这批行里有多少行在该列有可解析值", 取**覆盖数
        最多**的那列; 并列时按列名排序取第一个 (确定性: 同输入必得同结果)。

        为什么改成数据驱动: 旧口径取"按键名排序的第一个可解析星等列" ——
        这是个**结构性默认值**, 它挑中的往往是信息最少的那一列 (见
        :func:`bright_sources` 的实测)。改后的口径仍然是个兜底 (不是"对"的口径,
        是"最不坏"的口径), 所以它必须**可检视**: 本函数是 public, 调用方可以在
        筛选前问一句"你将拿哪一列判亮度", 也能在结果可疑时自己复算。
        """
        candidates: dict[str, int] = {}  # 列名 -> 覆盖行数 (含该列的行里有多少行值可用)
        for source in sources:  # 逐行统计: 代表列必须对**整批**负责, 不是只看第一行
            for key in sorted(source):  # 排序遍历: 候选列的收集顺序可复现
                # 列名判据复用 serialization.is_magnitude_column —— 它由
                # protocol.CATALOG_MAG_COLUMNS 现场推导后缀集, 是星等列的唯一真源。
                # 原判据 `key.endswith("mag")` 漏掉站点**实际发布**的绝大多数列名:
                # ps1 发 ``ps1_gpsf``/``ps1_rpsf``, splus_dr4 发 ``*_pstotal``,
                # landolt 发 ``vmag`` 而 gaia 发 ``phot_g_mean_mag`` —— 于是
                # 一行真实 ps1 源 (ps1_gpsf=15.0) 走进 bright_sources 会被判成
                # 「无测光」而整行剔除, 即亮度筛选对绝大多数星表是**空操作**。
                # 误差列以 err/rms 结尾, 不在真源后缀集里, 不会被误当星等。
                if not is_magnitude_column(key):  # 星等列判据只认一份真源, 不自建 endswith 清单
                    continue
                if BestProcessor._as_float(source.get(key)) is not None:  # 只数真值: 哨兵/空串/非数值都不算覆盖
                    candidates[key] = candidates.get(key, 0) + 1
        if not candidates:  # 整批没有任何可用星等: 无代表列可言, 调用方据此判缺测
            return None
        # 并列按列名定序: 覆盖数相同时必须有个确定性裁决, 否则同输入可能得不同列
        return min(candidates.items(), key=lambda pair: (-pair[1], pair[0]))[0]

    @staticmethod
    def _best_magnitude(
        source: dict,
        band: str | None = None,
        representative: str | None = None,
    ) -> float | None:
        """取行的代表星等。

        优先级: ``best_mag`` → 显式 ``band`` 对应的列 → 兜底代表列 → 任意可解析星等列。

        ``band`` 的列名形态: ``{band}mag`` / ``{band}_mag`` / 去掉表前缀后的同名列,
        以及**列名本身就以 band 结尾**的形态 (ps1 的 ``ps1_gpsf`` 带 ``g`` 即是)。
        认不出来时回落兜底 —— 因为"猜错一条列名"不该让整批亮度筛选失效。
        """
        for key in ("best_mag", "best_magnitude"):  # 两个同义键都认: 不同归一版本写出的键名不一样
            value = BestProcessor._as_float(source.get(key))  # 经统一转换: 字符串数值与哨兵值在这一步就分掉
            if value is not None:  # 第一个可用值即代表值: 后面的同义键不再看
                return value
        if band is not None:  # 显式指定波段: 只认这一波段的列, 绝不混用别的带
            value = BestProcessor._band_magnitude(source, band)
            if value is not None:
                return value
            # 显式 band 在本行没有可用值 → 该行就此判缺测, 不再退到别的带:
            # 退到别的带等于"用 g 带判 r 带的亮度", 那不是调用方要的语义。
            return None
        if representative is not None and representative in source:  # 兜底代表列 (由整批统计得出)
            value = BestProcessor._as_float(source.get(representative))
            if value is not None:  # 本行该列可用即采用
                return value
        # 末位回退: 按 key 排序取第一个可解析的**星等列**, 保证同输入同输出 (可复现)
        for key in sorted(source):  # 排序而非 dict 迭代序: 输入列序一变结果就会漂
            # 列名判据复用 serialization.is_magnitude_column —— 它由
            # protocol.CATALOG_MAG_COLUMNS 现场推导后缀集, 是星等列的唯一真源。
            # 原判据 `key.endswith("mag")` 漏掉站点**实际发布**的绝大多数列名:
            # ps1 发 ``ps1_gpsf``/``ps1_rpsf``, splus_dr4 发 ``*_pstotal``,
            # landolt 发 ``vmag`` 而 gaia 发 ``phot_g_mean_mag`` —— 于是
            # 一行真实 ps1 源 (ps1_gpsf=15.0) 走进 bright_sources 会被判成
            # 「无测光」而整行剔除, 即亮度筛选对绝大多数星表是**空操作**。
            # 误差列以 err/rms 结尾, 不在真源后缀集里, 不会被误当星等。
            if not is_magnitude_column(key):  # 星等列判据只认一份真源, 不自建 endswith 清单
                continue
            value = BestProcessor._as_float(source.get(key))  # 同上走统一转换: 不可解析的列自动被跳过
            if value is not None:  # 排序后第一个可用值: 保证同输入同输出
                return value
        return None  # 走到这里说明整行没有任何可用星等: 调用方据此判缺测

    @staticmethod
    def _band_magnitude(source: dict, band: str) -> float | None:
        """取"某个波段"的星等; 本行该波段缺测即返回 None (不跨带兜底)。

        **按 ``_`` 切词元**认列名, 而不是去"剥掉表前缀" —— 剥前缀只能处理
        ``ps1_gpsf`` 这种两段名, 一遇到 ``phot_g_mean_mag`` 就把真正的 band
        (``g``) 一起剥掉了, 于是显式 band 反而认不出列。切词元后三种真实形态都覆盖:
        ``gmag`` / ``ps1_gpsf`` / ``phot_g_mean_mag`` / ``splus_dr4_u_pstotal``。

        匹配分两档并**优先精确档**: 词元恰等于 band (phot_g_mean_mag 的 "g") 优先于
        "以 band 起头" (ps1_gpsf 的 "gpsf"), 否则 band="g" 会先撞上同前缀的别的列。
        同档内按列名排序取第一个 ⇒ 可复现。
        """
        want = str(band).strip().lower()  # 归一书写形态: 大小写差异不该改变判定的波段
        if not want:
            return None  # 空 band 不当"任意带": 那会退化成与不传 band 同一个坑
        best_rank, best_key = None, None  # 先在整行里挑出最优匹配列, 再取值 (避免撞上第一个非空列就返回)
        for key in sorted(source):  # 排序: 多形态同时命中时结果可复现
            if not is_magnitude_column(key):  # 非星等列直接排除: 误差列名也以星等列名结尾
                continue
            tokens = key.lower().split("_")  # 切词元: 不假设表前缀占几段
            if want in tokens:  # 精确档: 有词元恰好等于 band
                rank = 0
            elif any(t.startswith(want) for t in tokens):  # 起头档: gpsf 对 band=g
                rank = 1
            else:
                continue
            if best_rank is None or rank < best_rank:  # 只在不劣时替换: 同档保留先到的 (已排序 ⇒ 确定)
                best_rank, best_key = rank, key
        if best_key is None:  # 本行没有任何列属于这一波段
            return None
        return BestProcessor._as_float(source.get(best_key))  # 命中即取值 (可能 None = 该格缺测)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        """把单元格转 float; 空值/非数值/≈-1000 哨兵一律返回 None。"""
        if value is None:  # 空值不能当 0: 否则无测光行会被当成最亮行收进来
            return None
        try:
            number = float(str(value).strip())  # 经 str 再转: 列里存的是 "18.2" 这类字符串
        except (TypeError, ValueError):
            return None  # 非数值列不静默当 0: 假 0 会被亮度筛选当成最亮的行
        if not math.isfinite(number):  # 非有限值一律剔除: 与它们的比较结果不可预期
            return None  # NaN/inf 一律剔除: 比较运算与它们的结果不可预期
        # 与 BestSource.NULL_MAGNITUDE_SENTINEL (-999.0) **不是**同一阈值: 这里取 -900
            # 以吸收哨兵噪声, 故 -950 一类取值在 models.from_row 判为有效星等、
            # 在本文件被剔成 None。真正共用同一常量的是 src/tap/formats.py
        if number <= -900.0:  # 阈值取 -900 而非 -1000: 哨兵带噪声, 要取一个仍不可能是真实星等的界
            return None  # 阈值 -900 而非 -1000: 哨兵带噪声, 取一个仍不可能是真实星等的界
        return number

    @staticmethod
    def deduplicate(sources: list[dict], tolerance_arcsec: float = 0.5) -> list[dict]:
        """按天球位置去重 (haversine 大圆距离, 非平面近似)。

        语义要点 (迁移自上游并保留其修正):
          - 坐标缺失/非有限/越界 (ra∉[0,360), dec∉[-90,90]) 的行**保留**。
            把它们当作 (0,0) 会静默丢掉不相关记录 — 去重是清洗, 不是裁剪。
          - 输入顺序即输出顺序, 保留首次出现的那一条 (稳定, 可复现)。
          - ``tolerance_arcsec`` 必须有限且非负, 否则 ValueError (防止
            "容差写成 -1 导致全删" 这类静默事故)。

        复杂度为 O(n²) — 单次锥检索/交叉匹配的量级 (数百到数千行) 下可接受;
        真要做全星表去重应走服务端 GROUP BY, 不在这里。
        """
        tolerance = float(tolerance_arcsec)  # 先转 float: 传进来的可能是字符串容差
        # 容差必须显式校验: 容差写成 -1 (或 NaN) 会让"距离 <= 容差"恒不成立,
        # 结果是全部行被当作重复项静默删除 —— 清洗变裁剪且无任何报错
        if not math.isfinite(tolerance) or tolerance < 0:  # 容差必须有限非负: 负容差让判定恒不成立, 全表会被当重复删光
            raise ValueError("tolerance_arcsec must be a finite non-negative value")  # 抛而不降级: 静默全删是数据损坏
        if not sources:  # 空输入早退: 省掉后面两层闭包的定义开销
            return []  # 空输入早退: 省掉后面两层闭包的定义开销

        def coordinates(source: dict) -> tuple[float, float] | None:
            """解析行的 (ra, dec); 不可用时返回 None (该行免于去重)。"""
            ra = BestProcessor._as_float(source.get("ra"))  # 走统一转换: 缺测与哨兵坐标在这一步就分出来
            dec = BestProcessor._as_float(source.get("dec"))  # 同上: 赤纬缺测的行走免于去重分支
            if ra is None or dec is None:  # 缺坐标不是错误: 该行免于去重, 但仍原样保留
                return None  # 缺坐标不是错误: 该行免于去重, 但仍原样保留
            if not 0.0 <= ra < 360.0 or not -90.0 <= dec <= 90.0:  # 越界同缺测处理: 哨兵坐标绝不能参与球面距离
                return None  # 越界同缺测处理: 哨兵坐标绝不能参与球面距离
            return ra, dec

        def separation_arcsec(
            left: tuple[float, float],  # 左侧坐标: 必来自上面的解析, 不会是哨兵值
            right: tuple[float, float],  # 右侧同理: 两个入参都已归一到 0-360 区间
        ) -> float:
            """两点的大角距 (角秒); ra 环绕 0/360 已归一, 无跨圈跳变。"""
            ra1, dec1 = map(math.radians, left)  # 先转弧度: haversine 的三角函数要弧度, 直接用度会静默算错
            ra2, dec2 = map(math.radians, right)  # 同上转弧度: 两点必须同一单位制才能相减
            delta_ra = (ra1 - ra2 + math.pi) % (2.0 * math.pi) - math.pi  # 归一到 ±pi: ra 跨 0/360 时不算成整圈
            delta_dec = dec1 - dec2  # 赤纬差无需归一: 区间本身不环绕
            haversine = (  # 选 haversine: 小角距下数值稳定, 不像余弦公式在 0 附近丢精度
                math.sin(delta_dec / 2.0) ** 2  # 半角正弦平方: haversine 定义式的第一项
                + math.cos(dec1) * math.cos(dec2) * math.sin(delta_ra / 2.0) ** 2  # 赤纬余弦修正加赤经项: 缺一算出来的就不是球面距离
            )
            angle = 2.0 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))  # min/max 夹住舍入毛刺: 超过 1 会让 asin 抛域错
            return math.degrees(angle) * 3600.0  # 弧度 -> 度 -> 角秒, 与 tolerance_arcsec 同单位

        unique: list[dict] = []  # 保留集合: 输入顺序即输出顺序, 保证可复现
        # unique_coordinates 与 unique 严格同序同长: 第 i 项就是第 i 行的位置,
        # None 表示该行坐标不可用、免于去重判定 (不是 (0,0)!)
        unique_coordinates: list[tuple[float, float] | None] = []  # 与 unique 并行推: 下标即行号, 错位会把 A 跟 B 比
        for source in sources:  # 逐行与已收行比对: 单趟插入式去重, 无需先排序
            position = coordinates(source)  # 先解析坐标: 不可用的行直接走免判定分支
            # 只与"坐标可用"的已收行比较; 不可用行自身永不被当成重复,
            # 保证"去重是清洗, 不裁剪"这条语义在实现层也成立
            duplicate = position is not None and any(  # 先短路: position 为 None 时不碰闭包, 省掉整轮 any
                other is not None and separation_arcsec(position, other) <= tolerance  # 只与坐标可用的已收行比: 免判定的行不能当零坐标参与
                for other in unique_coordinates  # 并行数组: 下标即行号, 与保留集合严格同序
            )
            if not duplicate:  # 命中重复就跳过: 保留首次出现的那条, 后出现的丢弃
                # 保留**首次**出现的那条 (输入顺序即输出顺序), 使同输入同输出
                unique.append(source)  # 追加原行: 去重是清洗, 不改写也不裁剪内容
                unique_coordinates.append(position)  # 坐标同步追加: 两者错位就会拿 A 的位置去比 B
        return unique

    @staticmethod
    def band_summary(sources: list[dict]) -> dict[str, int]:
        """按波段计数 (``band`` 字段; 缺失计为 ``unknown``), 结果按波段名排序。"""
        counts: dict[str, int] = {}  # 计数从空起: 首个出现的波段不必预置
        for source in sources:  # 逐行累加: 缺波段的行也要计入, 否则覆盖度看起来比实际更好
            # 缺 band 的行归入 unknown 而不是跳过: 统计要覆盖全部输入,
            # 少计会让波段覆盖度看起来比实际更好
            band = str(source.get("band") or "unknown")  # 归一成 str: 列里可能是 None 或非字符串波段码
            counts[band] = counts.get(band, 0) + 1  # get 兜 0: 首个出现的波段不必预置
        # 按波段名排序返回, 保证同输入同输出 (下游回归比对依赖这一点)
        return dict(sorted(counts.items()))  # sorted 而非 insertion 序: 统计结果要可逐行 diff
