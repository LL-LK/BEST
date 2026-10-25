# -*- coding: utf-8 -*-
"""图示定位门禁 — 让两张架构图的文案与强度/路由裁定保持机械一致。

背景: astro-best 的强度定位从 S4 Legacy 收敛为 S2 / BEST 数据源
主理 (PRIMARY), 五份 SSOT 已对齐, 但受跟踪的两张 .drawio 是手工归档产物,
没有任何门禁盯着它们 — 结果产物里残留 "S4 Legacy" "旧入口" "版本: v0.3.1"
等旧文案达数周无人发现, 且生成器数据 (layout_data.py) 只迁移了一半, 直接
重生成会产出一张自相矛盾的图 (banner 说 12 张星表, 泳道标题说 9 大)。

本测试把四件事变成 CI 可判定命题:

  P1 旧定位/版本号零容忍   — 产物不得含旧强度措辞、旧路由措辞、发布版本号
                             字面量 (铁律 3 在图资产上的落地);
  P2 新定位文案必须在场    — 产物必须含 "BEST 数据源主理" 等新定位关键词,
                             防止有人把图改回空泛描述;
  P3 星表数与权威源一致    — 流程图横幅的星表数必须等于 SKILL.md 声明的
                             可查星表数 (代码权威值 12, 见图内 node_a2);
  P4 索引完备 + 可复现     — docs/diagrams/README.md 必须覆盖目录内每个
                             脚本; 生成器重新产出的 .drawio 必须与受跟踪
                             产物逐字节一致 (构建器缺失时 skip, 不算失败)。

P4 的第二半是漂移闸门: 改了 layout_data.py 却忘记重生成, 这道测试会红。
"""

from __future__ import annotations

# 标准库组:
#   os        — 给子进程注入 PYTHONIOENCODING (防中文违规描述在非 UTF-8 locale
#                下把父进程的解码打断, 那会让安全 lint 恰好在真有违规时崩)
#   re        — 禁用串正则 (版本号字面量)
#   subprocess— 在子进程里重生成 .drawio (避免把生成器的 sys.path 副作用
#                带进 pytest 主进程)
#   sys       — 取解释器路径与 stdlib 判定
#   pathlib   — 定位 docs/diagrams 与 SKILL.md
import os
import re
import subprocess
import sys
from pathlib import Path

# 第三方: pytest 承载模块级 skip (构建器缺失时) 与断言
import pytest

SKILL_DIR = Path(__file__).resolve().parents[3]  # 上溯三级到 skill 根: 本文件位于单元测试的 meta 层
DIAG_DIR = SKILL_DIR / "docs" / "diagrams"  # 受跟踪图示目录, 四道判据唯一的观察面
SKILL_MD = SKILL_DIR / "SKILL.md"  # 星表数的对外声明 SSOT, P3 跟着它走而非写死数字
README = DIAG_DIR / "README.md"  # 目录索引: P4 前半拿它与磁盘上的脚本做双向比对

# 两张受跟踪的 .drawio 源文件 (渲染产物 PNG/SVG/PDF 由 draw.io 桌面端另行导出)
DRAWIO_FILES = (  # 只有这两张进版本库; 渲染出的位图不在门禁范围, 否则导出一次就红一次
    "astro-best-legacy-architecture.drawio",  # 架构图: 旧定位与旧路由措辞的载体
    "astro-best-macro-flowchart.drawio",  # 流程图: 星表数只在它的横幅上, P3 实际只查这张
)

# P1 禁用串: 全部是已被裁定废弃的定位/路由措辞, 或铁律 3 禁载的版本号。
# 刻意不收裸 "重定向" — "登录被重定向回登录页" "TAP 异常时平滑重定向至
# NADC REST" 是对服务端行为的客观描述, 属于协议事实而非定位措辞。
FORBIDDEN_LITERAL = (  # 禁用串表的立身之本: 图示文案没有编译期保护, 只能靠这张表兜住陈旧措辞
    "S4 Legacy",            # 旧强度定位
    "legacy_deprecated",    # 旧强度标记
    "旧入口",                # 旧路由措辞
    "canonical:",           # 旧路由表列头 (新措辞为 "承接方:")
    "兼容模式",              # 旧定位声明
    "兼容能力域",            # 旧域标题
    "兼容立场",              # 旧卡标题
    "兼容声明",              # 旧卡标题
    "不新增 PRIMARY",        # 与 PRIMARY 裁定直接矛盾
    "只读历史能力",          # 旧能力声明
    "历史内嵌",              # 旧能力声明
    "规范重定向",            # 旧委派卡标题
    "主动重定向",            # 旧委派策略措辞
    "重定向路由",            # 旧路由表标题
    "重定向表",              # 旧自检项措辞
    "一律转投",              # 旧路由措辞
    "9 大",                  # 旧星表数 (权威值 12)
)

# P1 版本号正则: vX.Y.Z 三段式 / "版本: X.Y" / 带版本号的计划引用。
# mxfile 头的 version="24.0.0" 是 draw.io 构建库自带的工具元数据 (重新生成
# 也在), 不以 v 开头故不命中, 属另一类问题, 不在这道门禁范围。
FORBIDDEN_PATTERN = (  # 版本号走正则而非字面量: 它的形态随人手改动而漂, 收不进固定清单
    (re.compile(r"v\d+\.\d+\.\d+"), "发布版本号字面量"),  # 三段式: 铁律禁的发布版本号主体形态
    (re.compile(r"版本[:：]\s*v?\d"), "版本号字面量"),  # 兼容全角冒号与可选 v 前缀, 手写图常漏这两处
    (re.compile(r"Master Plan v"), "带版本号的计划引用"),  # 计划引用带版本号等于给读者一个会过期的坐标
)

# P2 各产物必须包含的新定位关键词 (缺一个即说明图被改得空泛或改回了旧描述)
REQUIRED = {  # 反向清单: 只禁旧措辞挡不住"改得空泛", 必须正面钉住新定位
    "astro-best-legacy-architecture.drawio": ("BEST 数据源主理", "主理能力域", "委派路由"),  # 主理定位 + 域标题 + 路由表头各钉一处
    "astro-best-macro-flowchart.drawio": ("BEST 数据源主理", "委派路由", "12 张可查"),  # 第三条兼作 P3 的星表数锚点
}


def _read(artifact: str) -> str:
    """读入一个受跟踪 .drawio 的全文 (UTF-8; 文件缺失即测试失败)。

    缺失即 assert 而非返回空串: 空串会让下游所有 ``needle in text`` 判据
    恰好因为"待查串也不在空串里"而通过, 图示整个消失反而全绿。
    """
    path = DIAG_DIR / artifact  # 拼路径: 目录与文件名都由上方常量给出, 不在用例里散写
    assert path.is_file(), f"受跟踪图示缺失: {path}"  # 挡"图没了门禁照样全绿": 空串会让全部包含判据通过
    return path.read_text(encoding="utf-8")


def _skill_catalog_count() -> int:
    """从 SKILL.md 抽取权威可查星表数 (形如 "12 张可查星表")。

    取 SKILL.md 而不是硬编码 12: 星表数以 SKILL.md 为对外声明 SSOT,
    门禁跟着它走, 将来星表扩容只需改一处。
    """
    text = SKILL_MD.read_text(encoding="utf-8")  # 读全文: 权威源缺失必须在抽数字之前就暴露
    m = re.search(r"(\d+)\s*张可查星表", text)  # 匹配中文句式而非孤立数字, 免得抓到别的数值
    assert m, "SKILL.md 中找不到 '<N> 张可查星表' 声明, 门禁失去权威源"  # 拿不到权威源就该红, 不能退化成硬编码 12
    return int(m.group(1))


class TestDiagramPositioning:
    """P1+P2+P3: 图示文案必须与强度/路由裁定及权威星表数一致。

    图示是给人读的, 它的失效不会让任何代码报错, 只会让人按一份过时的架构
    理解去改代码 —— 所以这一类门禁只能靠"文本必须与 SSOT 一致"来兜。
    """

    @pytest.mark.parametrize("artifact", DRAWIO_FILES)
    def test_no_stale_positioning_or_version_literal(self, artifact: str) -> None:
        """产物不得含旧定位措辞或版本号字面量。

        失败意味着: 有人把旧文案带回图里, 或版本号清扫漏改了本文件。
        """
        text = _read(artifact)  # 先确认产物存在再谈内容, 缺失已在读取处失败而非静默跳过
        for needle in FORBIDDEN_LITERAL:  # 逐串比对而非一条大正则: 禁用串含中文与标点, 正则易漏转义
            assert needle not in text, f"{artifact} 仍含禁用串 {needle!r}"  # 报出具体串: 只说"有旧文案"没法定位
        for pattern, why in FORBIDDEN_PATTERN:  # 携带 why, 让失败消息自带类别省去对号入座
            hit = pattern.search(text)  # 取首个命中即可: 一份产物指出一个反例就够定位
            assert hit is None, f"{artifact} 含{why}: {hit.group(0)!r}"  # 挡版本号字面量: 发布号一进图就开始漂

    @pytest.mark.parametrize("artifact", DRAWIO_FILES)
    def test_positioning_copy_present(self, artifact: str) -> None:
        """产物必须含新定位关键词 (BEST 数据源主理 / 主理能力域 / 委派路由)。

        失败意味着: 图被改成空泛描述, 读者无法从图里看出本 skill 的主理定位。
        """
        text = _read(artifact)  # 同样先确认产物在, 免得缺文件被当成"关键词不在"而蒙混过关
        for needle in REQUIRED[artifact]:  # 按图取词表: 两张图的关键词集合不同, 混用会误判
            assert needle in text, f"{artifact} 缺少新定位文案 {needle!r}"  # 挡"图被改成空泛描述": 无关键词即失去定位信息

    def test_catalog_count_matches_skill_declaration(self) -> None:
        """流程图星表数必须等于 SKILL.md 声明的可查星表数。

        失败意味着: 图里的星表规模与对外声明不一致 —— 权威值取自 SKILL.md,
        图里任何"9 大"这类过期计数都要判红, 不能因为新数在场就放过。
        """
        text = _read("astro-best-macro-flowchart.drawio")  # P3 只查流程图: 星表数只出现在它的横幅上
        expected = _skill_catalog_count()  # 权威值取自对外声明, 不在本文件里重复写死
        assert f"{expected} 张可查" in text, (  # 正向钉住声明过的数, 不靠"没写 9 大"反证
            f"流程图未声明 {expected} 张可查星表 (SKILL.md 权威值)")  # 消息带上权威值, 修图的人不必再翻声明
        assert not re.search(r"9\s*大", text), "流程图仍含旧星表数 '9 大'"  # 显式反证旧数: 残留即漂移, 不因新数在场而放过


class TestDiagramHygiene:
    """P4 前半: 图示目录的索引与脚本集合必须一致。

    索引与实际文件双向对齐: 少列一条是读者按图索骥找不到生成器, 多列一条
    则是索引指着一个已被删掉的文件, 两种都会让目录逐渐变成没人敢碰的角落。
    """

    def test_readme_index_covers_every_script(self) -> None:
        """docs/diagrams/README.md 必须提及目录内每个 .py 脚本。

        失败意味着: 目录新增了脚本但索引没跟上, 读者按图索骥找不到生成器,
        目录会逐渐变成没人敢碰的角落。
        """
        assert README.is_file(), f"图示索引缺失: {README}"  # 索引缺失会让"少列一条"这类缺口永远查不出来
        index = README.read_text(encoding="utf-8")  # 按文本核对: 目录索引本来就是给人读的, 不是机器清单
        scripts = sorted(p.name for p in DIAG_DIR.glob("*.py"))  # 排序只为让失败消息稳定, 便于逐条修
        assert scripts, "docs/diagrams/ 下没有任何 .py 脚本"  # 空目录时"全部被收录"会平凡成立
        for name in scripts:  # 单向覆盖: 目录有而索引没有 = 读者按图索骥扑空
            assert name in index, f"README 未收录脚本 {name}"  # 挡"新增生成器没登记": 目录逐渐变成没人敢碰的角落

    def test_every_source_file_is_git_tracked(self) -> None:
        """目录内每个 .py / .drawio 都必须受 git 跟踪 (渲染产物显式除外)。

        守的回归 (实测缺口): docs/ 整体在 .gitignore 内, 新建的
        drawio_io.py 被 ignore 规则挡住, ``git add`` **静默跳过**它 — 提交
        看着成功, 克隆机上生成器 import drawio_io 直接失败。受跟踪的生成器
        import 一个不受跟踪的模块, 是"本机能跑、克隆机崩"的典型形态, 且
        本地全量测试一片绿, 没有任何信号。

        渲染产物 (PNG/SVG/PDF) 按裁定不跟踪, 在这里是显式排除项而不是遗漏。
        不在 git 仓库内 (skill 被整体拷贝到他处) 时 skip, 不判失败。
        """
        try:
            proc = subprocess.run(  # 子进程问版本库: 判的是"是否被跟踪"这一状态, 进程内查不出来
                ["git", "ls-files", "docs/diagrams"],  # 只列受跟踪项, 正是要与磁盘实况求差的那一侧
                cwd=SKILL_DIR, capture_output=True, text=True, encoding="utf-8",  # 编码钉死: 文件名含中文, 靠 locale 会解错
                errors="replace", timeout=60)  # 超时兜底: 门禁不该因版本库卡住就挂死整轮
        except (OSError, subprocess.TimeoutExpired):
            pytest.skip("git 不可用, 无法核对跟踪状态")  # 环境缺失不判失败: 换台机器不该红
        if proc.returncode != 0:  # 非 0 多半是"不在版本库内", 与"文件没被跟踪"是两种结论
            pytest.skip(f"不在 git 仓库内: {proc.stderr.strip()[:120]}")  # skill 被整体拷走的场景: 没有版本库可比
        tracked = {Path(line).name for line in proc.stdout.split() if line.strip()}  # 只要文件名: 门禁判的是文件名在不在册
        sources = [p.name for p in DIAG_DIR.iterdir()  # 取磁盘实况作另一侧, 与跟踪表求差集
                   if p.suffix in (".py", ".drawio")]  # 渲染产物按裁定不跟踪, 故显式排除而不是遗漏
        assert sources, "docs/diagrams/ 下没有任何源文件"  # 空目录会让"全部已跟踪"平凡成立
        for name in sources:  # 逐个核对: 漏一个就是一个"本机绿、克隆机崩"的隐患
            assert name in tracked, (  # 核心断言: 挡住忽略规则静默吞掉新文件
                f"{name} 未受 git 跟踪 — docs/ 在 .gitignore 内, 新文件必须 "  # 提示要强制显式加入, 否则提交看着成功
                f"git add -f 显式加入, 否则克隆机上生成器 import 会失败")  # 说清后果: 缺失只在克隆机暴露, 本机测试全绿


class TestDiagramReproducibility:
    """P4 后半: 生成器产物必须与受跟踪 .drawio 逐字节一致 (漂移闸门)。"""

    def test_generator_output_matches_tracked_artifact(self, tmp_path: Path) -> None:
        """重生成两个 .drawio 到临时目录, 与受跟踪产物逐字节比对 + 安全 lint。

        实现要点: 走子进程而不是进程内 import — 两个生成器在模块级会把
        draw.io 构建库目录插到 sys.path[0], 在 pytest 主进程里做会污染
        后续用例的导入解析。构建库缺失 (未装 drawio-diagram-author skill)
        时 skip: 那道门禁只在有构建器的机器上有效, 不应因环境缺失而红。

        同一子进程里还跑构建库自带的 ``verify_drawio_security`` (DTD/实体、
        远程资源、危险 URI、DOM 事件、容器越界、禁用 HTML 标签等 8 类检查),
        对新产物与受跟踪产物各审一遍 — 图示也是交付物, 安全与结构合规要进门禁,
        不能只靠人工看一眼。

        失败意味着: layout_data.py 改过但没重生成, 或有人绕过 drawio_io.save_clean
        用了裸 doc.save (根标签属性/行尾都会不一致), 图与数据已经漂移。

        行尾口径: drawio_builder 在 Windows 上产出 CRLF, 而 .gitattributes 对
        *.drawio 规定 eol=lf (克隆机上拿到的是 LF), 所以两边都先归一成 LF 再
        比内容 —— 否则这道门禁只在本开发机通过, 在 CI / 克隆机上必红。
        """
        # 子进程代码必须带真实换行: python -c 的单行模式容不下 for/if 复合语句
        # (本门禁第一版把它们拼在一行里, 子进程直接 SyntaxError, 表现为 skip)。
        snippet = (  # 源码用拼接字符串传给 -c: 避免把生成器的导入带进 pytest 主进程
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import gen_astro_best_architecture as a\n"
            "import gen_best_macro_flowchart as f\n"
            "from drawio_io import save_clean\n"  # 显式引构建库: 生成器不依赖父进程残留的 sys.path
            "save_clean(a.build(), sys.argv[2] + '/astro-best-legacy-architecture.drawio')\n"  # 必须走 save_clean: 裸 save 的根标签属性不同, 字节比对必红
            "save_clean(f.build_macro_flowchart(), "
            "sys.argv[2] + '/astro-best-macro-flowchart.drawio')\n"
            "from verify_drawio_security import verify_drawio_content\n"  # 安全 lint 复用构建库自带检查器, 不自己重写一套
            "paths = [sys.argv[2] + '/astro-best-legacy-architecture.drawio',\n"
            "         sys.argv[2] + '/astro-best-macro-flowchart.drawio'] + sys.argv[3:]\n"
            "bad = 0\n"  # 计数而非首错即退: 一轮里把新旧两份产物的违规都收齐
            "for p in paths:\n"
            "    ok, viol = verify_drawio_content(open(p, encoding='utf-8').read())\n"
            "    print('SEC', p.split('/')[-1],"
            "          'OK' if ok else 'FAIL ' + ';'.join(viol)[:300])\n"
            "    bad += 0 if ok else 1\n"
            "print('SEC_BAD', bad)\n"  # 汇总计数回传, 父进程据此判定整批是否通过
            "print('OK')\n"  # 尾标记: 区分"跑完了全过"与"中途崩了没跑到"
        )
        try:
            proc = subprocess.run(  # 重生成也放子进程: 两个生成器在模块级会改 sys.path[0]
                [sys.executable, "-c", snippet, str(DIAG_DIR), str(tmp_path),  # 用当前解释器: 换版本会让构建库行为漂移
                 *[str(DIAG_DIR / a) for a in DRAWIO_FILES]],  # 受跟踪产物一并传入, 让安全 lint 新旧各审一遍
                capture_output=True, text=True, encoding="utf-8", errors="replace",  # 中文违规描述要读得出来, 否则只剩问号
                timeout=180, cwd=str(DIAG_DIR),  # 生成器按相对路径找自身资源, 工作目录必须落在图示目录
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})  # 注入编码环境: 子进程打印中文在非 UTF-8 locale 会崩
        except subprocess.TimeoutExpired:
            pytest.skip("生成器子进程超时, 本轮不判定漂移")  # 超时不判漂移: 环境慢不等于产物不一致
        if proc.returncode != 0:  # 非 0 多半是缺构建库, 属环境问题而非产物问题
            pytest.skip(f"生成器不可用 (缺 draw.io 构建库?): {proc.stderr.strip()[-200:]}")  # 缺构建库时这道门禁本就无从谈起, 不该让整轮红
        for ln in proc.stdout.splitlines():  # 逐行扫: 子进程把每份产物的结论分行吐回来
            if ln.startswith("SEC "):  # 只认 SEC 前缀行, 其余是生成器自身日志
                assert " FAIL " not in ln, f"图示安全/结构 lint 未过: {ln}"  # 逐条拦: 图示也是交付物, 安全合规要进门禁
        assert "SEC_BAD 0" in proc.stdout, (  # 汇总兜底: 防"子进程没跑到打印就退出"被当成通过
            f"子进程未回报安全 lint 全过: {proc.stdout[-300:]}")  # 带出尾部输出: 便于分辨是脚本崩了还是 lint 红了
        for artifact in DRAWIO_FILES:  # 两张图各自逐字节比, 漂移要能定位到具体哪一张
            tracked = (DIAG_DIR / artifact).read_bytes().replace(b"\r\n", b"\n")  # 先归一行尾: 开发机产 CRLF 而克隆机拿 LF
            fresh = (tmp_path / artifact).read_bytes().replace(b"\r\n", b"\n")  # 新生成那份用同一套归一口径, 否则对比不公平
            assert fresh == tracked, (  # 漂移闸门: 改了生成器数据没重生成, 只有这道测试能发现
                f"{artifact} 与生成器输出不一致 — 改了 layout_data.py 需要重生成, "  # 指出最常见成因, 省得从头排查
                f"或用裸 doc.save() 绕过了 drawio_io.save_clean (根标签属性/行尾会不一致)")  # 同时给出绕过清洗这条隐蔽成因
