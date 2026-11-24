"""守护: 知识面 / 模板面 不得宣称代码里不存在的能力 (H2-01 / H2-02 / H2-03)。

缺陷形态 (2026-10-05 H2 审计, 三条都是"文档说的"与"代码真实做的"相反):

  * **H2-01 死路凭据**: ``rag/knowledge/domain_rules.yaml`` 与
    ``best_practices.yaml`` 两条最高权重知识 (DOMAIN_BOOST 0.2 / 0.25) 教
    "凭据走 env BEST_API_TOKEN", 而 ``src/scripts/config.py`` 明写"客户端无此
    通道"、``src/core/__init__.py`` 明写"全链是死路, 已删"。agent 问"怎么鉴权"
    必然命中这条死路知识, 照做则拿不到任何凭据。
  * **H2-02 伪造阶段声明**: ``templates/report_template.yaml`` 写死"已按五状态
    机 (INTAKE->VALIDATE->EXECUTE->GATE->EMIT) 完成", 而这五个状态名在
    src/ ops/ evals/ 的 .py 里零命中 —— 模板替一段从未跑过的流程背书。
  * **H2-03 severe 分类**: ``best_practices.yaml`` 把"校验失败/磁盘失败/会话过期/
    分页不一致"四类当成现行 severe 策略, 但生产 ``.severe(`` 调用点只触发
    精准下载两类, 这四类**有定义无触发**; 真正会触发的两类它反而不列。

本组测试不重述知识内容, 只钉**知识与代码的一致性**: 事实一律从代码现场取
(``src.download_hooks`` 的常量表、AST 扫出的 ``.severe(`` 调用点、
``src.__main__.AUTH_PASSWORD_ENV``), 知识侧只被检查"有没有说错", 判据一旦
失配即红。知识文本改了、代码没改, 或者反过来, 都会在这里现形。
"""
from __future__ import annotations

# 标准库: ast 静态扫调用点 (不 import 被扫模块, 免得副作用进测试进程) /
# importlib 取 hook 常量表的真实值 / pathlib 锚定仓根与知识目录 / re 切句
import ast
import importlib
import re
from pathlib import Path

# 第三方: PyYAML 是解析知识与契约 YAML 的唯一依赖 (硬依赖, 缺失即整模块失败)
import yaml

# 路径锚点: 本文件位于 test/unit/meta/, 上溯 3 层即仓根
SKILL_ROOT = Path(__file__).resolve().parents[3]       # parents[3] 是硬编码层级: 文件挪一层就静默指向错目录
KNOWLEDGE_DIR = SKILL_ROOT / "rag" / "knowledge"        # 知识面: 本组测试的左侧
SRC_DIR = SKILL_ROOT / "src"                            # 代码面: 本组测试的右侧 (唯一权威)

# 已废弃的凭据通道: env 键名 + 它们在代码里的"死亡证明" (docstring 位置)
RETIRED_CHANNELS = ("BEST_API_TOKEN", "BEST_API_USER", "BEST_API_PASS")   # 三个都只在 config env_map / 历史文档里出现过, 客户端零消费
# 判定"这条知识已经把它标成死路"的措辞锚: 只认明说退役/无消费方的那几类说法,
# 不认泛泛的"安全""隔离" —— 放得太宽就成了永远绿的橡皮图章
RETIRED_MARKERS = ("死路", "无消费方", "无此通道", "存而不用", "已退役", "死参数")   # 逐句命中其一即算已标死路
# 旧版 bp-download-hook-ask 用这四个**中文类目名**把有定义无触发的常量说成现行
# 策略 (原句: "severe 类(校验失败/磁盘失败/会话过期/分页不一致)立即拦截")。它们
# 不含 kind 字面量, 上面按 kind 的判据抓不到, 故单列一条回归锁: 与"立即拦截"
# 同句出现即违规, 知识里要讲这四类只能用 kind 字面量 + "有定义无触发"。
FORBIDDEN_SEVERE_CLAIMS = ("校验失败", "磁盘失败", "会话过期", "分页不一致")   # 逐个点名, 不抽样
FORBIDDEN_CLAIM_VERB = "立即拦截"                                     # 旧版那半句的动词, 也是判据的另一半
# 五状态机状态名: 模板与报告都不得声称跑过它 (契约里那份是设计意图, 未实现)
STAGE_STATES = ("INTAKE", "VALIDATE", "EXECUTE", "GATE", "EMIT")   # 逐状态点名: 漏一个就还能被渲染出去


def _flatten(node) -> str:
    """把 YAML 子树里的所有字符串叶子拼成一段文本 (条目全文)。

    条目正文分散在 content/description/lesson/workaround 等多个键上, 只看
    一个键会漏判: 一条知识完全可以把死路写在 title、把真实面写在 content。

    Args:
        node: 任意 YAML 节点 (dict / list / 标量)。

    Returns:
        全部字符串叶子按深度优先顺序用换行拼成的文本; 无字符串时返回空串。
    """
    if isinstance(node, str):                                          # 标量叶子: 直接就是文本
        return node                                                  # 字符串叶子原样返回: 标量不再往里拆
    if isinstance(node, dict):                                         # 映射: 逐值下推
        return "\n".join(_flatten(v) for v in node.values())     # 映射按插入序遍历: 键名本身不入正文 (判据只看给人读的那部分)
    if isinstance(node, list):                                         # 列表: 逐项下推
        return "\n".join(_flatten(v) for v in node)              # 列表逐项拼: tags 之类的短串也进文本, 拼出即检索面
    return ""                                                     # 数字/布尔/None 无检索价值, 不入正文


def _iter_entries() -> list[tuple[str, str, str]]:
    """逐条产出知识条目 (文件名, 条目标识, 条目全文)。

    结构自适应: 仓库里五种布局并存 (``{rules: [{id, title, description}]}`` /
    ``{entries: [...]}`` / ``{issues: [...]}`` / ``{lessons: [...]}`` /
    ``{citations: [...]}``), 靠"带 id 或 title 的 dict 即一条目"这个不变量
    统一识别 —— 认死布局的话, 新增一种布局就会静默漏扫, 守护随即失效。

    Returns:
        ``(文件名, 条目标识, 条目全文)`` 三元组列表; 某份 YAML 坏掉即抛
        (不静默跳过: 知识面读不出来时, 下面的判据全部恒真通过)。
    """
    out: list[tuple[str, str, str]] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.y*ml")):            # 排序遍历: 报错时的条目顺序跨平台可复现
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        stack = [data]                                            # 显式栈: 递归深度由数据决定, 不设上限
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                ident = node.get("id") or node.get("title")       # 条目标识: 有 id 用 id, 否则用 title
                if ident:
                    out.append((path.name, str(ident), _flatten(node)))   # 自认条目即收: 不再往里拆
                    continue
                stack.extend(node.values())                        # 非条目映射: 继续往子层找
            elif isinstance(node, list):
                stack.extend(node)                                # 列表逐项下推
    assert out, "知识面必须非空 (否则下面所有判据都是恒真的空集断言)"   # 非空断言: 空知识库不该让本文件全绿
    return out


def _sentences(text: str) -> list[str]:
    """把一段文本切成句子 (句号/分号/换行皆为句界)。

    本仓知识条目大量用分号分点陈述, 把分号当句界才能让"同句"判据真的落在
    一句话上; 不切分的话, 一条里任何位置的免责话都能替所有话背书。

    Args:
        text: 任意文本。

    Returns:
        去空白后的非空句子列表。
    """
    return [s for s in re.split(r"[。；;\n]", text) if s.strip()]


def _entry(ident: str) -> str:
    """按标识取单条知识条目的全文 (缺失即抛, 不返回空串蒙混)。

    Args:
        ident: 条目标识 (``id`` 或 ``title``)。

    Returns:
        该条目的全文 (键名不入正文)。

    Raises:
        AssertionError: 知识面里找不到该标识时 —— 条目被改名/删除必须让守护变红。
    """
    hits = [text for _name, entry_id, text in _iter_entries() if entry_id == ident]   # 逐条比对标识: 标题形态也认 (id 缺失的老条目)
    assert len(hits) == 1, f"知识面里 {ident!r} 应恰好一条, 实得 {len(hits)} 条"  # 0 条=被删, 多条=标识撞车
    return hits[0]


def _declared_hook_kinds() -> set[str]:
    """取代码里**声明**过的全部 hook 类别 (常量表 + 建议方案模板表)。

    两张表都读: ``SEVERE_*`` 常量是 severe 类, ``_OPTION_TEMPLATES`` 还多出
    ``network_exhausted`` 与 ``post_not_retried`` 两类 —— 只看前者会漏掉
    run_network 实际会抛的两类, 于是"知识面必须说全"这条判据会放过缺口。

    Returns:
        全部已声明类别的字符串集合。
    """
    hooks = importlib.import_module("src.download_hooks")          # 真导入: 常量值必须是代码的真实值, 不靠正则抄一遍
    return set(hooks.SEVERE_KINDS) | set(hooks._OPTION_TEMPLATES)   # 两表并集: 声明面比 severe 常量更宽


def _triggered_hook_kinds() -> tuple[set[str], list[str]]:
    """AST 静态扫生产 ``.severe(`` / ``._interrupt(`` 调用点, 返回真实会触发的类别。

    为什么不 import 每个下载模块再 monkeypatch: 那等于执行被测生产代码, 一次
    真实 IO 就可能把测试变成活体测试。AST 只读调用点的**第一实参**: 字面量直接
    取值, 裸名字 (从 ``src.download_hooks`` import 进来的常量) 查该模块真实值 ——
    两侧口径同源, 不会出现"知识面抄了常量名但代码改了值"的漏判。

    两个调用形态都要扫, 少一个就会把真实会拦的类别误判成"有定义无触发":
    ``.severe(`` (调用方直接判严重级) 与 ``._interrupt(`` (分级出口, 网络类
    耗尽与非幂等护栏经它升级)。``severe()`` 自身转调 ``_interrupt(kind, ...)``
    传的是形参名, 查不到常量值即被跳过, 不会把类别算重。

    Returns:
        ``(类别集合, "相对路径:行号" 清单)``; 清单非空是判据能成立的前提。
    """
    hooks = importlib.import_module("src.download_hooks")          # 常量解析的查表对象
    kinds: set[str] = set()                                          # 扫出来的类别集合
    sites: list[str] = []                                            # 调用点清单 (判据红了要能直接跳过去看)
    for path in sorted(SRC_DIR.rglob("*.py")):                      # 只扫 src/: 测试与 evals 的调用不算生产触发
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))   # utf-8-sig: 与仓内其他读取口径一致
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in ("severe", "_interrupt")):
                continue                                            # 只认这两个方法调用, 不认同名属性
            if not node.args:
                continue                                            # 无参调用不是合法的拦截契约, 跳过不猜
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                kind: str | None = first.value                      # 字面量类别: 直接取
            elif isinstance(first, ast.Name):
                kind = getattr(hooks, first.id, None)               # 裸常量名: 查 hook 模块的真实值 (形参名查不到即 None)
            else:
                kind = None                                         # 动态表达式: 本守护不猜, 交给下面的非空断言报警
            if isinstance(kind, str):
                kinds.add(kind)
                sites.append(f"{path.relative_to(SKILL_ROOT).as_posix()}:{node.lineno}")   # 行号进清单: 判据红了要能直接跳过去看
    return kinds, sites


class TestRetiredCredentialChannels:
    """H2-01: 知识面不得把已废弃的凭据通道写成可用通道。"""

    def test_retired_channels_are_never_advertised_as_usable(self):
        """知识里提到废弃通道时, 同**一句**必须同时把它标成死路。

        判据落在句级而不是条目级: 死路登记写在同一文件的另一句里, 对检索无效
        —— agent 命中的是整条, 但引用与转述时只摘走那半句, 于是"凭据走
        BEST_API_TOKEN"又被当成可用通道传下去。句界按句号/分号/换行切。
        """
        offenders: list[str] = []
        for name, ident, text in _iter_entries():                   # 逐条扫: 命中名不等于违规, 没标死路才是违规
            hit_channels = [c for c in RETIRED_CHANNELS if c in text]  # 本条目提到的废弃通道
            if not hit_channels:
                continue                                            # 没提就是没提, 不算问题
            for channel in hit_channels:                            # 逐通道判: 一个名字标了死路不代表另一个也标了
                sentences = [s for s in _sentences(text) if channel in s]   # 只看提到它的那些句子
                if not any(any(m in s for m in RETIRED_MARKERS) for s in sentences):
                    offenders.append(f"{name}:{ident} 的 '{channel}' 同句没标死路")   # 报出条目与通道名: 整改的人要看得见是谁
        assert not offenders, offenders                              # 知识面宣称死路可用 = 知识在骗 agent

    def test_severe_policy_does_not_claim_untriggered_categories(self):
        """旧版四类中文类目名不得与"立即拦截"同句 (H2-03 的原句回归锁)。

        这四类对应的 kind 常量在生产零触发: 把它们写成现行 severe 策略, agent
        排障就会去等一个永远不会来的 ask。要讲这四类, 只能用 kind 字面量配
        "有定义无触发"标注 (见 TestSevereHookKindsMatchCode)。
        """
        offenders: list[str] = []
        for name, ident, text in _iter_entries():                   # 全知识面扫, 不只 best_practices: 同样的错可能落在别的文件
            for sentence in _sentences(text):
                if FORBIDDEN_CLAIM_VERB not in sentence:
                    continue                                        # 不是"立即拦截"的断言句不管
                bad = [c for c in FORBIDDEN_SEVERE_CLAIMS if c in sentence]   # 同句出现的禁列类目名
                if bad:
                    offenders.append(f"{name}:{ident} 把 {bad} 说成现行 severe 策略")
        assert not offenders, offenders

    def test_auth_knowledge_names_the_real_credential_face(self):
        """鉴权知识必须点名**代码里的**真实凭据面, 而不是某个 env 键名。

        口令环境变量名从 ``src.__main__.AUTH_PASSWORD_ENV`` 现场取, 不写死:
        代码改名而知识没跟上时本判据自动变红, 而不是继续教一个失效的键名。
        """
        main = importlib.import_module("src.__main__")              # CLI 真实消费面所在模块
        password_env = main.AUTH_PASSWORD_ENV                        # 口令 env 键名的唯一权威来源
        assert password_env, "CLI 必须仍声明口令 env 键名 (取不到说明 CLI 口径变了, 知识需重写)"  # 取不到即拦: 防止下面的 in 判据空转
        text = _entry("auth-surface-real")                           # 域规则里那条 (权重 0.2 档, 问鉴权必命中)
        assert password_env in text, f"鉴权知识未点名真实口令 env {password_env}"  # 键名漂移即红
        assert "--auth-user" in text, "鉴权知识未点名真实凭据入口 --auth-user"     # 入口漂移即红

    def test_domain_rules_no_longer_teaches_token_only_channel(self):
        """``env-token-only`` 这条知识已被真实鉴权面取代, 不得复活。

        保留这条是因为"标题里带 only 的单通道规则"是本仓已经踩过的坑形态:
        它在 DOMAIN_BOOST 最高两档里, 复活即等于把死路重新挂回检索首位。
        """
        idents = {ident for _name, ident, _text in _iter_entries()}     # 全量标识集: 逐条扫, 不靠预置白名单
        assert "env-token-only" not in idents, "env-token-only (凭据只读 env BEST_API_TOKEN) 是已删除的死路知识, 不得复活"  # 复活即红


class TestSevereHookKindsMatchCode:
    """H2-03: 知识里的 severe 分类必须与生产真实触发点一致。"""

    def test_production_call_sites_were_actually_found(self):
        """AST 扫不到调用点即判据失效 —— 先证明扫法本身有效。

        没有这一步, 一次 AST 写法回归 (比如 hook 被改成 ``hooks.severe_ask``)
        会让"知识必须说全"变成"知识一个字都不用写", 守护静默失效。
        """
        kinds, sites = _triggered_hook_kinds()                          # 扫法自检: 先证明扫得到, 再谈判据
        assert sites, "扫不到任何 .severe( 生产调用点: 判据前提不成立 (方法改名 / 移到别的包?)"  # 前提断言: 扫不到就停
        assert kinds, "调用点存在但类别解析全空: 常量名解析口径坏了"      # 第二前提: 位置找到了但类别没解析出来同样停

    def test_every_triggered_kind_is_named_in_knowledge(self):
        """生产真会触发的 severe 类别, 知识面必须逐个点名。

        漏列的代价是双向的: agent 按知识排障会去等一个永远不会来的 ask, 也会
        把"没 ask"读成"不是严重问题" —— 真正拦下来的那两类反而不被当回事。
        """
        triggered, _sites = _triggered_hook_kinds()                     # 触发面来自 AST, 不是人抄的清单
        text = _entry("bp-download-hook-ask")
        missing = sorted(kind for kind in triggered if kind not in text)   # 逐个点名: 不抽样
        assert not missing, f"生产会触发但知识面没列的 severe 类别: {missing}"   # 漏列即红

    def test_untriggered_kinds_are_labelled_as_such(self):
        """有定义无触发的 severe 类别, 知识里必须与"无触发"同句出现。

        判据落在**同一句**上 (按句号/分号切句): 把免责话写在相邻句子里的效果
        等于没写 —— agent 检索到的是整条, 但引用时会只摘走那半句。
        """
        triggered, _sites = _triggered_hook_kinds()                     # 触发面: AST 实扫
        untriggered = sorted(_declared_hook_kinds() - triggered)        # 声明面减触发面 = 有定义无触发的那批
        assert untriggered, "有定义无触发的类别应非空 (全触发时本判据失去意义, 需重写判据)"  # 前提断言
        text = _entry("bp-download-hook-ask")
        sentences = _sentences(text)                                # 切句: 分号也算句界 (本仓知识条目大量用分号分点)
        unlabelled = [kind for kind in untriggered                      # 逐类别找那句: 同句有名字且有"无触发"标注才算交代过
                      if not any(kind in s and "有定义无触发" in s for s in sentences)]
        assert not unlabelled, f"这些 severe 类别生产零触发, 知识面却没标'有定义无触发': {unlabelled}"  # 当现行策略宣称即红

    def test_every_declared_kind_is_covered_by_knowledge(self):
        """代码里声明的全部 hook 类别, 知识面必须都有一句交代 (说全, 不只是说对)。

        "说对"与"说全"是两条判据: 知识面只列真正会触发的两类不算错, 但会把
        剩下五类的处置讲成空白, 读者无从判断是遗漏还是不存在。
        """
        triggered, _sites = _triggered_hook_kinds()                     # 触发面: AST 实扫 (下面还要拿它做反向断言)
        text = _entry("bp-download-hook-ask")
        for kind in sorted(_declared_hook_kinds()):                     # 逐类别点名, 不抽样
            assert kind in text, f"代码声明的 hook 类别 {kind} 在知识面里没有交代"  # 逐类别点名
        assert triggered <= _declared_hook_kinds(), "触发面出现了未声明的类别 (常量表与调用点脱节)"   # 反向: 触发集必须是声明集的子集


class TestNoFabricatedStageClaims:
    """H2-02: 模板/报告不得声称跑过一个从未实现的状态机。"""

    def test_report_template_does_not_claim_the_five_states(self):
        """报告模板正文里不得出现五状态机任何一个状态名, 也不得写"五状态机"。

        模板是渲染骨架: 它写死的那句话会以"已完成"的语气出现在每一份报告里,
        而这段流程在代码里不存在 —— 比没有这句话更糟的是它看起来像事实。
        """
        text = (SKILL_ROOT / "templates" / "report_template.yaml").read_text(encoding="utf-8")  # 全文读: 注释里也不许留"已按五状态机完成"的措辞
        hits = [state for state in STAGE_STATES if state in text]     # 逐状态点名: 漏一个就还能被渲染出去
        assert not hits, f"templates/report_template.yaml 仍提到未实现的状态: {hits}"
        assert "五状态机" not in text, "templates/report_template.yaml 仍声称按五状态机完成"

    def test_contract_marks_the_state_machine_as_unimplemented(self):
        """契约必须把五状态机明确标成"未实现/设计意图", 而不是让它读起来像可执行契约。

        处置取 (a)+(b): 模板不再声称 + 契约写清状态。一个从未运行的状态机被
        文档断言为已完成, 比没有这个状态机更糟; 而删掉状态名又会丢掉设计意图,
        所以保留清单 + 标注状态, 并由本测试守住这份标注。
        """
        data = yaml.safe_load((SKILL_ROOT / "contracts" / "pipeline-stage.contract.yaml").read_text(encoding="utf-8"))  # 契约本体
        assert data.get("state_machine") == list(STAGE_STATES), "状态清单若变动, 需同步核对本守护的 STAGE_STATES"  # 清单动了就显式改判据, 不让它静默失配
        status = str(data.get("state_machine_status", ""))           # 状态标注键: 缺键即"没标"
        assert status, "pipeline-stage.contract.yaml 缺 state_machine_status: 未实现的状态机必须显式标注"  # 缺标注即红
        assert ("未实现" in status) or ("unimplemented" in status), f"状态标注没说是未实现: {status!r}"  # 标注内容即判据

    def test_the_five_states_really_have_no_implementation(self):
        """五状态名在 src/ 的 .py 里必须零命中 —— 契约那份标注才成立。

        反向判据: 哪天真有人实现了状态机, 本测试会红, 那时正确动作是删掉契约
        里的"未实现"标注 (而不是把本测试改成放行), 因为模板能否声称"已完成"
        完全取决于这个事实。
        """
        hits: list[str] = []
        for path in sorted(SRC_DIR.rglob("*.py")):                    # 只扫生产代码: 测试与 evals 不构成实现
            text = path.read_text(encoding="utf-8-sig")
            found = [state for state in STAGE_STATES if state in text]  # 文本级即可: 状态名是专用大写词, 不必上 AST
            if found:
                hits.append(f"{path.relative_to(SKILL_ROOT).as_posix()}: {found}")
        assert not hits, f"src/ 里出现了五状态机实现, 契约的'未实现'标注已过期: {hits}"  # 实现出现即要求同步改标注
