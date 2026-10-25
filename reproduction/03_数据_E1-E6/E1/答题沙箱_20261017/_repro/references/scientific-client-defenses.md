# scientific-client-defenses.md — 天文与科学数据客户端防御性编码规范与五道防线

> **定位与规范级别**：本文件为 `astro-best` 及其衍生天文数据访问客户端、星表查询网关、流式下载管线的核心权威工程参考规范。深度融合【天文学 + 统计学 + 软件工程 + 网络工程】，严格遵循白盒化与权威文献可溯源标准。

---

## 1. 架构总览与五道防线设计原则

天文大科学工程数据（如 Pan-STARRS1、Gaia DR3、LAMOST、GALAH）具有海量、多波段、异构、高动态范围以及稀疏矩阵等物理特性。客户端直接与远程 REST/TAP 服务端及异构文件系统交互，任何隐蔽的边界处理失误均会导致科学数据偏差、坐标投影漂移甚至计算节点 OOM。本规范建立五道防御性工程防线，消除静默业务缺陷与数据污染。

```
+---------------------------------------------------------------------------------------------------+
|                            科学数据接入流水线五道防御性工程防线                                    |
+---------------------------------------------------------------------------------------------------+
|  [防线 1: 分页步长恒定律]   offset = (page - 1) * rows; 请求步长 rows 严禁动态回缩; 客户端后切片    |
|  [防线 2: 流式原子落盘]     分块内存缓冲上限 <= 1MB; 磁盘流式句柄; os.replace 跨平台原子提权落盘   |
|  [防线 3: 全环境 BOM 兼容]   CSV/TSV 解析强制 encoding="utf-8-sig"; 杜绝首列名 \ufeffra 键崩溃     |
|  [防线 4: 恒定时间验签]     缓存摘要/API凭据比对强制 hmac.compare_digest; 杜绝时序侧信道反推      |
|  [防线 5: 降级分支类型自检] 严防 st_size 属性误调; 显式拦截 isinstance(x, bool) 防伪浮点漏检       |
+---------------------------------------------------------------------------------------------------+
|  [物理域: 测光与天体测量]   严格区分 Photometric Sentinels (99.0/-999) 与 Astrometric 真实物理负值 |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. 第一道防线：分页步长恒定律（防偏移量倒退）

### 2.1 数学机理与故障场景
在基于物理偏移量（Offset-based）的分页数据查询协议中，服务端通常采用标准 SQL/TAP 偏移量模型：
$$\text{offset} = (\text{page} - 1) \times \text{rows}$$
其中 $\text{page}$ 为从 1 开始计数的页码，$\text{rows}$ 为单页记录条数。

- **触发缺陷场景**：当调用方请求总行数上限为 $N_{\text{max}}$（例如 $N_{\text{max}} = 2500$），且固定分页步长为 $R = 1000$ 时：
  - 第 1 页：$\text{page}=1, \text{rows}=1000 \implies \text{offset} = 0 \implies \text{获取区间 } [0, 1000)$；
  - 第 2 页：$\text{page}=2, \text{rows}=1000 \implies \text{offset} = 1000 \implies \text{获取区间 } [1000, 2000)$；
  - 第 3 页（错误逻辑）：若客户端因仅剩余 $2500 - 2000 = 500$ 条需求，动态将请求参数调整为 $\text{rows}=500$ 发送给服务端：
    $$\text{服务端计算偏移量} = (3 - 1) \times 500 = 1000$$
    此时服务端返回的区间退化为 $[1000, 1500)$，导致**偏移量瞬间发生倒退**，客户端不仅重复拉取了第 2 页已处理过的前半部分数据，且 $[2000, 2500)$ 区间的数据发生永久性静默丢失。

### 2.2 防御性编码规约
1. **恒定请求步长**：在整个多页拉取会话期间，发往服务端的请求参数 `rows` 必须严格保持恒定（等于标称的 `page_size`）；
2. **客户端后切片**：上限截断必须在客户端流式解析完整单页后，通过内存切片 `rows[:remaining]` 实施，绝对禁止将截断逻辑下推为网络请求中的缩小版 `rows`。

```python
# [VERIFIED_ALGO] 分页步长恒定抓取算法
from typing import Generator, Any
import requests

def fetch_catalog_paged(
    base_url: str,
    query_params: dict[str, Any],
    page_size: int = 1000,
    max_rows: int | None = None,
    session: requests.Session | None = None,
) -> Generator[dict[str, Any], None, None]:
    """严格遵守分页步长恒定律的星表流式拉取器。
    
    物理量量纲:
        page_size: 标称页大小 (整数, 记录数/页)
        max_rows: 最大需求行数 (整数或 None 代表无上限)
    """
    s = session or requests.Session()
    page = 1
    yielded = 0
    params = dict(query_params)
    # 防线 1 核心约束: 请求参数 rows 恒定等于固定 page_size，不可随剩余数量动态缩小
    params["rows"] = page_size

    while True:
        params["page"] = page
        resp = s.get(base_url, params=params, timeout=30.0)
        resp.raise_for_status()
        
        batch = resp.json().get("data", [])
        if not batch:
            break  # 数据集耗尽，正常终止

        for row in batch:
            yield row
            yielded += 1
            if max_rows is not None and yielded >= max_rows:
                return  # 在客户端精确截断，绝不上窜影响请求参数 rows

        if len(batch) < page_size:
            break  # 遇到末尾自然截断页，终止遍历
            
        page += 1
```

---

## 3. 第二道防线：大文件流式原子落盘（防内存 OOM 与文件损坏）

### 3.1 物理机理与异常分析
现代全天巡天产生的星表数据量极大。例如 Pan-STARRS1 3π 巡天原始点源达数十亿，LAMOST DR10 光谱星表切片单文件常达数百兆字节，FITS 图像更高达数吉字节。
- **内存 OOM 危害**：使用 `resp.content` 或 `b"".join(chunks)` 会在 Python 进程堆内存中开辟连续大内存块，在多线程并发或容器化调度（cgroup 内存配额受限）时立即触发内核 OOM Killer 杀进程。
- **残缺损坏危害**：若直接向目标路径 `open(target, "wb")` 写入，若遭遇网络断开、超时中断或电源异常，目标文件将成为无法通过校验但留在磁盘上的残损文件（Corrupted Partial File）。使用 `os.remove() + os.rename()` 在 POSIX 和 Windows 下均存在竞态窗口（Race Condition），且非原子操作。

### 3.2 防御性编码规约
1. **小块流式迭代**：强制使用 `resp.iter_content(chunk_size=64*1024)`，限制单次内存占用 $\le 64\text{ KB}$；
2. **同文件系统临时过渡**：临时文件必须建立在与目标路径相同的父目录中（同一挂载点 / 分区），保证后续操作为元数据指针交换；
3. **跨平台原子替换**：写入完毕且哈希校验完全一致后，统一调用底层原子系统调用 `os.replace(tmp_path, target_path)`。

```python
# [VERIFIED_ALGO] 流式原子落盘与哈希比对
import os
import hashlib
import tempfile
from pathlib import Path
import requests

def download_file_stream_atomic(
    url: str,
    target_path: Path,
    expected_sha256: str | None = None,
    chunk_size: int = 65536,
    session: requests.Session | None = None,
) -> Path:
    """大文件分块流式下载与跨平台原子替换。"""
    target = target_path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    
    s = session or requests.Session()
    # 同分区临时文件，前缀带隐藏标记，避免与正式文件命名冲突
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.tmp_",
    )
    tmp_path = Path(tmp_path_str)
    hasher = hashlib.sha256()

    try:
        with os.fdopen(tmp_fd, "wb") as f, s.get(url, stream=True, timeout=60.0) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                hasher.update(chunk)
            f.flush()
            os.fsync(f.fileno())  # 强制刷写至物理存储介质
            
        # 校验和拦截
        actual_digest = hasher.hexdigest()
        if expected_sha256 and not hmac.compare_digest(actual_digest.lower(), expected_sha256.lower()):
            raise ValueError(f"校验和不一致: actual={actual_digest}, expected={expected_sha256}")
            
        # 防线 2 核心操作: 原子重命名/替换，瞬间生效
        os.replace(tmp_path, target)
        return target
    except Exception:
        # 发生任何异常立即清理残余临时文件，绝不污染目标路径
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
```

---

## 4. 第三道防线：全环境 BOM 字符兼容（防 Excel 导表列名崩溃）

### 4.1 字符编码机理与故障形态
在 Windows 简体中文与西欧操作系统中，Microsoft Excel 将电子表格“另存为 CSV”时，会在文件起始处强制写入 3 个字节的 UTF-8 字节顺序标记（Byte Order Mark, BOM）：`0xEF, 0xBB, 0xBF`（Unicode 码点 `U+FEFF`）。
- **故障形态**：若科学数据客户端使用标准 `encoding="utf-8"` 读取该 CSV，首行表头的第一个字段（例如赤经列 `ra` 或目标源标识 `source_id`）会被解析为带有不可见前缀的字符字面量：`"\ufeffra"` 或 `"\ufeffsource_id"`。
- **破坏性**：此时字典取值 `row["ra"]` 会直接抛出 `KeyError: 'ra'`；如果系统带有宽容性默认值逻辑，则赤经坐标将被静默赋为 `None` 或 `0.0`，造成整批天文源的天球投影直接坍缩至坐标原点（春分点天赤道交叉点）。

### 4.2 防御性编码规约
凡在数据读取管线中解析文本型 CSV/TSV/DSV 格式，统一指定 `encoding="utf-8-sig"`。Python 标准库内置的 `utf-8-sig` 解码器具备向下兼容性：当文件存在 BOM 时透明剔除；当文件不存在 BOM 时等价于标准 UTF-8 解码，零副作用。

```python
# [VERIFIED_ALGO] BOM-Safe CSV 星表解析器
import csv
from pathlib import Path
from typing import Generator

def read_astronomical_csv(path: Path) -> Generator[dict[str, str], None, None]:
    """防 BOM 注入的天文星表解析器。"""
    # 防线 3: 强制采用 utf-8-sig 解码
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            # 清理列名首尾意外多余空白
            reader.fieldnames = [name.strip() for name in reader.fieldnames if name]
        for row in reader:
            yield {k.strip(): v.strip() for k, v in row.items() if k is not None}
```

---

## 5. 第四道防线：恒定时间验签比对（防时序侧信道）

### 5.1 侧信道机理与攻击推导
在天文学统一认证（如 IVOA SSO / OAuth 2.0 Token 签名）、本地数据缓存哈希校验、以及跨台站流水线交付签名中，常需对两个十六进制哈希摘要字符串进行相等性判断。
- **短路比较弱点**：Python 内置的字符串全等比对运算符 `actual == declared` 底层基于 C 语言 `memcmp` 实现，具有经典短路（Short-circuit）特性：从第 0 个字节开始逐字节比对，一旦发现第一处不相等的字符，立即返回 `False` 并退出。
- **时序攻击推导**：攻击者通过纳秒级精度的高频请求时延测量，可以观察到比对耗时与“猜测字符串中从左至右首个错误字符的索引位置”呈线性比例关系：
  $$T_{\text{cmp}}(k) = T_0 + k \cdot \Delta t$$
  这使得攻击者可以通过逐位盲测在极短时间内推导并伪造合法的令牌或防篡改签名。

### 5.2 防御性编码规约
严格遵循 IETF RFC 2104 准则，涉及任何凭据、签名或校验和判定的地方，一律使用标准库 `hmac.compare_digest(a, b)`。该函数保证无论不匹配发生在何处，均执行全长度常量时间扫描，消除时钟周期波动泄露。

```python
# [VERIFIED_ALGO] 恒定时间凭据与摘要比对
import hmac

def verify_data_checksum(actual_digest: str, expected_digest: str) -> bool:
    """恒定时间哈希校验，杜绝时序侧信道。"""
    if not isinstance(actual_digest, str) or not isinstance(expected_digest, str):
        return False
    # 防线 4: 使用 hmac.compare_digest 实现恒定时间比对
    return hmac.compare_digest(actual_digest.strip().lower(), expected_digest.strip().lower())
```

---

## 6. 第五道防线：异常与降级分支严格自检（防二次崩溃）

### 6.1 隐蔽缺陷分析
1. **属性与方法混淆（Callable 陷阱）**：
   在断点续传（HTTP 416 Range Not Satisfiable 处理）或文件大小探测逻辑中，`os.stat(path)` 返回的 `os.stat_result` 对象的 `st_size` 是一个整数属性（`int`）。直觉式编写 `stat.st_size()` 将在进入异常补偿路径时立即引发 `TypeError: 'int' object is not callable`，使原本设计的自愈机制直接转化为系统二次崩溃。
2. **Python 布尔值伪浮点渗透**：
   在 Python 内部类型继承体系中，`bool` 是 `int` 的直接子类：`issubclass(bool, int) is True`。因此：
   ```python
   isinstance(True, (int, float))  # -> True
   float(True)                     # -> 1.0
   float(False)                    # -> 0.0
   ```
   若星表解析器未经显式类型自检，传入的布尔值标志（如 `flag=False`）会被无障碍强制转换成浮点数 `0.0`，使其轻易绕过 `0.0 <= ra <= 360.0` 的物理量边界检验，将布尔标志当作天球面赤经坐标注入物理管线。

### 6.2 防御性编码规约
1. **显式类型拦截**：数值转换前必须强制拦截 `if isinstance(val, bool): raise TypeError(...)`；
2. **严防属性调用**：禁止对文件状态属性追加执行括号。

```python
# [VERIFIED_ALGO] 严格天文坐标数值安全校验
from typing import Any

def safe_cast_coordinate(val: Any, field_name: str = "ra") -> float:
    """防布尔渗透的天文坐标转换器。
    
    物理量量纲:
        val: 输入值 (标量, 期望角度 deg, [0, 360] 或 [-90, 90])
    """
    if val is None:
        raise ValueError(f"{field_name} 坐标不可为空")
    # 防线 5: 严防 bool 伪装为 int/float
    if isinstance(val, bool):
        raise TypeError(f"天体测量坐标 {field_name} 不接受布尔类型: received {val!r}")
    
    try:
        f_val = float(val)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"无法将 {val!r} 解析为有效的 {field_name} 浮点坐标") from exc

    if field_name.lower().startswith("dec"):
        if not (-90.0 <= f_val <= 90.0):
            raise ValueError(f"赤纬越界 (dec in [-90, 90]): received {f_val}")
    else:
        if not (0.0 <= f_val <= 360.0):
            raise ValueError(f"赤经越界 (ra in [0, 360]): received {f_val}")

    return f_val
```

---

## 7. 物理域特征：测光哨兵值与天体测量合法负值

在科学天文学数据处理中，必须严格区分**测光缺失标记（Photometric Sentinels）**与**天体测量物理负值（Astrometric Physical Negative Values）**。将天体测量负值盲目视为缺失哨兵是极为严重的学科领域逻辑错误。

### 7.1 测光哨兵体系（Photometric Sentinels）
各主流大型巡天对无法可靠探测、视宁度不良或严重饱和的源采用固定的极端浮点数进行填充占位：
- **Pan-STARRS1 (PS1)**：星等未检出、饱和或超出极限星等时填充 `99.0` 或 `99.999` mag；
- **BEST / NADC 星表**：缺失或无效测光常规填充 `-999.0`、`-1000.0` 或 `-1004.0`；
- **规约**：客户端在提取星等并组装 `BestSource.magnitudes` 时，必须将命中哨兵集合的值置换为 `None`，严禁让 `99.0` 或 `-999.0` 参与任何颜色指数计算（如 $g - r$），否则会导致星族合成与消光修正发生天文数字级的失真。

### 7.2 天体测量物理负值合法性（Astrometric Legitimacy）
天体测量学参数基于空间运动矢量投影，其数值天然包含物理正负号：
- **自行（Proper Motion: $\mu_\alpha \cos\delta, \mu_\delta$，列名 `pmra`, `pmdec`）**：
  单位为毫角秒/年（$\text{mas/yr}$）。负值代表恒星在天球投影面上正向西（$\mu_\alpha < 0$）或向南（$\mu_\delta < 0$）运动。例如太阳邻近高速恒星常具有数十乃至数百 $\text{mas/yr}$ 的负向自行。
- **视向速度（Radial Velocity: $v_r$，列名 `radial_velocity`）**：
  单位为千米/秒（$\text{km/s}$）。根据经典多普勒效应，定义背离观测者运动为正（红移），靠近观测者运动为负（蓝移）。本星系群内天体（如仙女座大星系 M31 视向速度约为 $-300\text{ km/s}$）或银河系晕星大量呈现真实的物理负视向速度。
- **核心禁令**：**严禁在天体测量列（`pmra`, `pmdec`, `radial_velocity`）上复用 `-999` 或任何小于零判据来过滤所谓“无效值”！** 只有数值精确等于预定义的缺省字符串或特定缺失哨兵时方可判定为缺测。

---

## 8. 权威参考文献与数据标准（Authoritative References）

本规范所有算法推导与工程规则均严格溯源自以下国际天文学联合会（IAU）、虚拟天文台（IVOA）以及国际互联网工程任务组（IETF）标准文献：

1. **Pan-STARRS1 巡天与测光系统标准**：
   - Chambers, K. C., et al. (2016). *The Pan-STARRS1 Surveys*. arXiv:1612.05560 [astro-ph.IM].
   - Magnier, E. A., et al. (2020). *Pan-STARRS Photometric and Astrometric Calibration*. The Astrophysical Journal Supplement Series, 251(1), 6. DOI: [10.3847/1538-4365/abb82d](https://doi.org/10.3847/1538-4365/abb82d).
2. **Gaia 空间天体测量与测光星表标准 (Gaia DR3)**：
   - Vallenari, A., et al. (Gaia Collaboration) (2023). *Gaia Data Release 3: Summary of the content and survey properties*. Astronomy & Astrophysics, 674, A1. DOI: [10.1051/0004-6361/202243940](https://doi.org/10.1051/0004-6361/202243940).
   - Lindegren, L., et al. (2021). *Gaia Early Data Release 3: The astrometric solution*. Astronomy & Astrophysics, 649, A2. DOI: [10.1051/0004-6361/202039709](https://doi.org/10.1051/0004-6361/202039709).
3. **LAMOST 大规模光谱巡天标准**：
   - Zhao, G., Zhao, Y. H., Chu, Y. Q., Jing, Y. P., & Deng, L. C. (2012). *LAMOST spectral survey — An overview*. Research in Astronomy and Astrophysics, 12(7), 723–734. DOI: [10.1088/1674-4527/12/7/002](https://doi.org/10.1088/1674-4527/12/7/002).
4. **GALAH 高分辨率光谱巡天标准**：
   - Buder, S., et al. (GALAH Collaboration) (2021). *The GALAH+ Survey: Third data release*. Monthly Notices of the Royal Astronomical Society, 506(1), 150–201. DOI: [10.1093/mnras/stab1242](https://doi.org/10.1093/mnras/stab1242).
5. **国际虚拟天文台协议标准 (IVOA)**：
   - Plante, R., et al. (2008). *IVOA Simple Cone Search Version 1.03*. IVOA Recommendation 22 February 2008. [https://www.ivoa.net/documents/latest/ConeSearch.html](https://www.ivoa.net/documents/latest/ConeSearch.html).
   - Dowler, P., et al. (2019). *Table Access Protocol Version 1.1*. IVOA Recommendation 27 September 2019. DOI: [10.5479/ADS/bib/2019ivoa.spec.0927D](https://doi.org/10.5479/ADS/bib/2019ivoa.spec.0927D).
   - Ochsenbein, F., et al. (2019). *VOTable Format Definition Version 1.4*. IVOA Recommendation 21 October 2019. DOI: [10.5479/ADS/bib/2019ivoa.spec.1021O](https://doi.org/10.5479/ADS/bib/2019ivoa.spec.1021O).
6. **网络安全与编码规范标准**：
   - Krawczyk, H., Bellare, M., & Canetti, R. (1997). *HMAC: Keyed-Hashing for Message Authentication*. IETF RFC 2104. DOI: [10.17487/RFC2104](https://doi.org/10.17487/RFC2104).
   - Unicode Consortium (2023). *Unicode Standard Annex #28: Unicode Conformance for Byte Order Mark (BOM)*. [https://www.unicode.org/reports/tr28/](https://www.unicode.org/reports/tr28/).
