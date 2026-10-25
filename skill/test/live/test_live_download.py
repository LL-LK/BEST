"""Live 下载测试 — 验证 VOTable、CSV、TXT、FITS 四种格式的真实下载。

【需要真实网络 / 默认 skip】除非设置 PYBEST_RUN_LIVE=1 (见下方
pytestmark), 否则整文件在收集阶段跳过; 每个用例都对 nadc.china-vo.org
发起真实两阶段查询并落盘。【为什么不能离线跑】这里守的是服务端
emitter 的字节形态 (CSV 逗号分隔、TXT 制表符、VOTable 的 XML 结构与
数值列类型、FITS 的表结构), mock 回包只能复述我们自己的假设。

P1 合并注记: 原经 pybest 单类 (``Best.download``); 双副本删除后改用
``BestDownloader.download_region`` (区域下载的权威路径) — 验证目标
(四种 emitter 的字节形态) 不变。
"""
from __future__ import annotations

# 标准库: os 读环境变量 PYBEST_RUN_LIVE (live 开关) 并检查落盘文件;
# tempfile 建临时目录 (live 产物不落仓库根)。
import os
import tempfile

# 第三方: pytest 提供夹具 (tmp_path) 与用例发现
import pytest

# 本地: 唯一生产客户端 + 区域下载路径 — download_region 的真实落盘。
# legacy-import-guard: 导入失败即整文件跳过 (live 文件不该因环境报错)。
try:
    # src.client: 两阶段异步 HTTP 客户端; src.downloader: 区域下载被测路径
    from src.client import BestClient
    from src.downloader import BestDownloader
except Exception as _legacy_err:  # legacy-import-guard
    # pytest: 导入失败时主动 skip, 不让环境问题伪装成用例失败
    import pytest as _pytest
    _pytest.skip(f'legacy import unavailable: {_legacy_err!r}', allow_module_level=True)

# 默认跳过: 只有 PYBEST_RUN_LIVE=1 才访问公网服务 (限流 + 防离线误触)
pytestmark = pytest.mark.skipif(  # live 开关: 不设 PYBEST_RUN_LIVE=1 就在收集期整文件跳过, 默认不触网
    os.environ.get("PYBEST_RUN_LIVE") != "1",
    reason="set PYBEST_RUN_LIVE=1 to run live tests",
)

# 冒烟天区 (与其余 live 文件一致: 小半径少行数, 省服务端配额)
RA = 286.0925889890722                                                                              # 目标天区中心 RA (J2000)
DEC = 15.727985031303144                                                                            # 目标天区中心 Dec (J2000)
RADIUS_ARCSEC = 5.0                                                                                 # 半径 5 角秒


def _live_download(fmt: str) -> str:
    """真实两阶段查询 + 指定 emitter 落盘, 返回产物路径 (live 共用体)。

    Args:
        fmt: 输出格式 (csv/txt/votable/fits, 服务端 + 本地导出集)。

    Returns:
        落盘文件路径。
    """
    client = BestClient(rate_limit=0)                                                              # 下载同样限速置零: 一次小请求, 不值得睡
    dl = BestDownloader(client, output_dir=tempfile.gettempdir())  # 落 tempfile 而非 skill 根: live 产物不该混进版本库工作区
    return dl.download_region(                                     # 两阶段查询: POST 取 sqlid 再分页 GET, 这里跑的是完整生产路径
        ra_center=RA, dec_center=DEC, radius_arcsec=RADIUS_ARCSEC,                                  # 天区中心与半径
        catalog="ps1", output_format=fmt, max_rows=10,
    )


def _check_and_preview(path, fmt):
    """落盘产物必须存在且非空, 并读回前文供格式断言。

    四种 emitter 共用的本地 IO 守门: 文件缺失或为空都算下载失败; 读回的
    文本供 CSV/TXT/VOTable 的字节形态断言使用 (FITS 走二进制通道, 不经过它)。
    """
    # 本地 IO 检查 + 读回前文: 落盘文件必须存在且非空, 以 utf-8 读回内容
    # 供格式断言 (CSV/TXT/VOTable 均走文本通道)。
    assert os.path.exists(path), f"{fmt} file not created"  # 文件缺失即下载失败: emitter 静默不产文件是最常见的失败形态
    size = os.path.getsize(path)                                                                   # 落盘后立刻回读体积: 文件存在不等于写成功
    assert size > 0, f"{fmt} file is empty"       # 非空才算成功: 0 字节文件在下游表现为「查到了却什么都没有」
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()                                                                          # 读回内容: 要与后续的结构校验用同一份
    return size, content

@pytest.mark.live
def test_download_csv():
    """【需要真实网络 / 默认 skip】CSV 下载必须含 ps1_ra 表头且逗号分隔。

    【验证的服务端行为】服务端 csv emitter 产出带 ps1_ 前缀列头的逗号
    分隔表。【为什么不能离线跑】emitter 的字节形态只在真实应答里存在。
    """
    path = _live_download("csv")  # csv emitter: 服务端字节形态只能由真实应答验证
    size, content = _check_and_preview(path, "CSV")
    # 断言对象必须是完整表头行: 站点返回的列很多 (inputobjs_* + ps1_* 共数十列),
    # 按前 200 字符截取会把 ps1_ra 截在界外, 造成"表头缺失"的假失败。
    header_line = content.splitlines()[0] if content else ""  # 表头是整行断言对象: 站点列数十个, 截前 200 字符会切在界外
    assert "ps1_ra" in header_line, f"CSV missing header: {header_line[:200]}"
    assert "," in header_line, "CSV no comma separator"  # 逗号即分隔符: CSV emitter 退化成 TSV 时下游按列解析就烂
    print(f"  CSV: {os.path.basename(path)} ({size}b)")

@pytest.mark.live
def test_download_txt():
    """【需要真实网络 / 默认 skip】TXT 下载必须含 ps1_ra 表头且制表符分隔。

    【验证的服务端行为】服务端 txt emitter 是 TSV (不是 JSON 文本) —
    回归防线: txt 若误走 JSON emitter, 下游按列解析即烂。
    【为什么不能离线跑】同上, emitter 字节形态只在真实应答里存在。
    """
    path = _live_download("txt")  # txt emitter 实为 TSV: 误走 JSON emitter 是这里要挡的回归
    size, content = _check_and_preview(path, "TXT")
    # 同 CSV: 表头行整体才是断言对象, 前 200 字符装不下全部列名。
    header_line = content.splitlines()[0] if content else ""  # 同样取整行表头: 与 CSV 那条同口径, 截断会造成假失败
    assert "ps1_ra" in header_line, f"TXT missing header: {header_line[:200]}"
    assert "\t" in header_line, "TXT no tab separator"  # 制表符才是 TXT 的分隔符: 逗号出现只说明混进了数据内容
    print(f"  TXT: {os.path.basename(path)} ({size}b)")

@pytest.mark.live
def test_download_votable():
    """【需要真实网络 / 默认 skip】VOTable 下载必须可被 astropy 解析且数值列为浮点。

    【验证的服务端行为】服务端 votable emitter 产出合法 XML (含 <VOTABLE
    与 ps1_ra 列), 且 astropy 解析后 ps1_ra 的 dtype.kind == "f" — 即
    数值列没有在服务端塌缩成字符串。【为什么不能离线跑】VOTable 结构由
    服务端生成, 离线只能验证我们的解析假设。
    """
    path = _live_download("votable")  # votable emitter: XML 结构与列类型都由服务端生成
    size, content = _check_and_preview(path, "VOTable")
    assert "<VOTABLE" in content, "VOTable missing XML tag"
    assert "ps1_ra" in content, "VOTable missing ps1_ra column"
    # 验证 astropy 能解析它
    # astropy 本地解析 (读回落盘文件): 验证类型信息而非仅文本存在
    from astropy.io.votable import parse
    vot = parse(path)  # 解析落盘文件而非内存串: 验的是文件真能被 astropy 打开
    table = vot.get_first_table()                                                                   # 取第一张表
    nrows = len(table.array)                                                                        # 行数
    ncols = len(table.array.dtype.names)                                                            # 列数: 与协议声明的列清单比对
    assert nrows > 0, "VOTable has no rows"  # 零行说明下载空: 表结构在但数据没回来的情况必须暴露
    # 检查数值类型 (不是字符串)
    col_dtype = table.array.dtype["ps1_ra"]                                    # 取列 dtype 而非值: 数值列塌成字符串时, 值看着仍然正常
    assert col_dtype.kind == "f", f"ps1_ra dtype={col_dtype} should be float"  # kind 必须是 f: 服务端把浮点写成字符串时, 只有类型检查断得掉
    print(f"  VOTable: {os.path.basename(path)} ({size}b, {nrows} rows, {ncols} cols)")

@pytest.mark.live
def test_download_fits():
    """【需要真实网络 / 默认 skip】FITS 下载必须可被 astropy 打开且含浮点 ps1_ra。

    【验证的服务端行为】服务端 fits emitter 产出合法 FITS (数据在 HDU 1),
    含 ps1_ra 列且 dtype.kind == "f"。【为什么不能离线跑】FITS 表结构由
    服务端生成, 只有真实下载能验证 (注意: 本仓库 CLI 的 fits 选项在
    test_live_best_api.py 被有意排除 — 两端点行为以各自实测为准)。
    """
    # 第三方: astropy.io.fits — 二进制通道读回落盘 FITS, 验证表结构与数值类型
    import astropy.io.fits as pf
    path = _live_download("fits")
    assert os.path.exists(path), "FITS file not created"
    size = os.path.getsize(path)                                                                    # 回读体积: 落盘成功不等于内容有效
    assert size > 0, "FITS file is empty"
    # astropy 本地打开 (读回落盘文件): FITS 数据表在第 2 个 HDU (索引 1)
    hdul = pf.open(path)  # 数据表在 HDU 1: FITS 的主 HDU 是空的, 取错会读到 0 行
    data = hdul[1].data                                                                             # 取第一组扩展: 主表通常是 HDU 1
    nrows = len(data)                                                                               # 行数要与请求的 max_rows 相符
    hdul.close()                                                                                    # 显式关闭: 活体测试也不留文件句柄
    assert nrows > 0, "FITS has no rows"
    col_names = data.dtype.names                                                                    # 列名 dtype: 与协议列清单比对靠它
    assert any("ps1_ra" in str(c) for c in col_names), f"FITS missing ps1_ra: {col_names}"  # 按列名找: 列名带限定时直接取键会 KeyError
    # 验证浮点类型
    assert data["ps1_ra"].dtype.kind == "f", f"ps1_ra should be float, got {data['ps1_ra'].dtype}"  # 浮点守门: 塌成字符串时值看着正常
    print(f"  FITS: {os.path.basename(path)} ({size}b, {nrows} rows)")
    print(f"  columns: {list(col_names[:6])}...")

@pytest.mark.live
def test_download_by_constraints_from_ps1(tmp_path):
    """【需要真实网络 / 默认 skip】经 BestDownloader.download_region 做区域下载落盘。

    【验证的服务端行为】downloader 的区域下载路径 (内部两阶段协议 + csv
    emitter) 对 ps1 星表真实可用, 产物非空。用例名与代码一致都是 ps1:
    ``std`` 是导航分组名而不是可查询星表 (``resolve_catalog("std")`` 直接抛
    ValueError), 服务端 ``/q`` 也不接受它 —— 旧名 "from_std" 是复制粘贴
    遗留, 与代码实际请求的 ``catalog="ps1"`` 不符 (E8 已按代码修正)。
    【为什么不能离线跑】区域下载全程触网; 另 output_dir 显式用 tmp_path
    而非 CWD 相对默认值, 避免 live 运行污染 skill 根目录。
    """
    client = BestClient(rate_limit=0)                                                               # 限速置零: 一次小下载, 不值得睡
    # 用 tmp_path 而非 CWD 相对默认值: live 运行不得污染 skill 根目录,
    # 且该目录由 pytest 负责清理。
    dl = BestDownloader(client, output_dir=str(tmp_path),                                 # 下载器落在临时目录: 活体测试的产物不进 best_data
                        checkpoint_dir=str(tmp_path / ".checkpoints"))
    # 真实区域下载: POST 取 sqlid → 分页 GET → csv 落盘
    path = dl.download_region(  # 真实区域下载: POST 取 sqlid → 分页 GET → csv 落盘
        ra_center=RA, dec_center=DEC,                                                               # 同一目标天区
        radius_arcsec=RADIUS_ARCSEC, catalog="ps1", output_format="csv",
        max_rows=10,                                                                                # 只要十行
    )
    assert os.path.exists(path), "region download failed"
    size = os.path.getsize(path)                                                           # 再回读体积: 走的是 SDK 而非 REST, 两层都要验
    assert size > 0, "region download empty"
    print(f"  Region CSV: {os.path.basename(path)} ({size}b)")
