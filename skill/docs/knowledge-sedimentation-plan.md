# 知识沉底体系设计（astro-best）

> 目标：把"运行时踩到的坑"自动变成"下次能复用的知识"，并提供**两套取用方式**——
> 一套不依赖 RAG（确定性槽位），一套依赖 RAG（模糊召回）。

## 一、现状盘点（2026-09-28 实测）

| 层 | 资产 | 状态 |
|----|------|------|
| 事件源 | `src/task_log.py` → `.logs/task_log.jsonl` | ✅ 已有，event 枚举含 hook/ask/failed/blocked |
| 决策源 | `src/download_hooks.py` 的 `HookInterrupt` / ask | ✅ 已有，能产出"拦截原因 + 用户选择" |
| 常驻规则 | `static/core/{workflow,stance,output-format}.md` | ✅ 已有 |
| 场景切片 | `static/fragments/{algo_mode,data_source,target_type}/` | ✅ 已有雏形（槽位机制） |
| 结构化知识 | `rag/knowledge/*.yaml` | ✅ 已有 65 条（5 类） |
| 检索器 | `rag/astro_rag.py` | ⚠️ 已有但有粒度 bug（65 条被压成 6 块） |
| **沉淀通道** | **事件 → 知识条目** | ❌ **缺失，全靠人肉手写 YAML** |

结论：缺的不是"存知识的柜子"，而是"把经验搬进柜子的传送带"。

## 二、总体架构：一条管道进，两条路出

```
   运行时事件流  .logs/task_log.jsonl        HookInterrupt / ask 决策
        │                                            │
        └──────────────────┬─────────────────────────┘
                           ▼
              【沉淀管道】 ops/knowledge_capture.py
              扫 failed/blocked/hook/ask → 归类 → 去重 → 生成候选条目
                           ▼
              【暂存区】 .knowledge/inbox/*.yaml      ← 待审，不入索引
                           ▼  人工确认 / 规则自动批准
              【唯一真源】 rag/knowledge/*.yaml       ← 只增不减
                    │                    │
       ┌────────────┘                    └────────────┐
       ▼  A 路：不依赖 RAG                 B 路：依赖 RAG  ▼
  槽位直注（确定性）                          检索召回（模糊）
  src/knowledge_slots.py                   rag/astro_rag.py
  按 (维度,值) 拼 key 精确查表              把上下文拼成查询 → top-k
       │                                            │
       └──────────────► 合流去重 ◄──────────────────┘
                           ▼
                    注入到执行上下文
```

**关键决策：知识只存一份**（`rag/knowledge/`），两条路只是**取用方式**不同。
避免"两套知识库各自漂移"这个经典坑。

## 三、A 路：不依赖 RAG（确定性沉底）

### 思路（类比）
工具箱：每样工具挂在**固定挂钩**上。要螺丝刀就直接去"螺丝刀挂钩"拿，不用翻箱倒柜。
好处是快、准、可预测；坏处是"没挂上钩的东西"找不到。

### 三层结构

| 层 | 位置 | 注入时机 | 内容 |
|----|------|----------|------|
| L0 常驻核 | `static/core/*.md` | 每次必注 | 工作流、立场、输出格式 |
| L1 场景槽位 | `static/fragments/{维度}/{值}.yaml` | 按 key 命中 | 算法模式/数据源/目标类型/错误类别 |
| L2 规则库 | `rag/knowledge/*.yaml` | 按 id/tags 精确查 | 65 条结构化规则 |

### 槽位 key 规范

```
维度 ∈ {algo_mode, data_source, target_type, catalog, error_kind}
key  = f"{维度}/{值}"

例：
  catalog/ps1               → static/fragments/data_source/best_catalogs.md 的 ps1 段
  algo_mode/two_phase       → static/fragments/algo_mode/best_two_phase.yaml
  error_kind/network_exhausted → 新增槽位（由沉淀管道自动补）
```

### 取用接口

```python
from src.knowledge_slots import resolve_slots

ctx = resolve_slots({
    "catalog": "ps1",
    "algo_mode": "two_phase",
    "error_kind": "network_exhausted",
})
# → [Slot(key=..., path=..., text=...)]  未命中的维度不返回，不猜、不模糊
```

### 优点 / 代价
- ✅ 完全确定性：同样的输入永远同样的输出，可复核、可写单测
- ✅ 零依赖、离线、微秒级
- ✅ 命不中就是命不中，不会"似是而非"地污染上下文
- ❌ 覆盖不到没预设槽位的长尾经验 → 这部分交给 B 路

## 四、B 路：依赖 RAG（模糊召回）

### 思路（类比）
图书馆：你描述个大概，管理员从书海里找出最相关的几本。
好处是长尾也能捞到；坏处是找什么有随机性，需要调参。

### 前置修复（必做，否则 B 路无效）

`rag/astro_rag.py::_entries_from_doc` 的 dict 分支当前把**每个顶层键的整坨 YAML 原文**
当成 1 条：

```python
# 现状（错）：dict 布局 → 每个 key 一条，value 整块 dump
content = f"{key}\n{yaml.safe_dump({key: value}, ...)}"
```

5 个文件都是 `{lessons: [...], issues: [...]}` 这种"字典套列表"，
于是 65 条真知识被压成 **6 块整文件**索引 → 检索粒度 = 整个文件，
实测 top3 分数 0.0328 / 0.0323 / 0.0317，几乎无区分度。

**修法**：dict 分支遇 list 值时**逐项展开**，每项独立成条目：

```python
elif isinstance(data, dict):
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):      # 新增：列表逐项展开
            out.extend(_entries_from_doc(value, source, category))
        else:
            ...  # 标量/字典仍按原配置式处理
```

修完条目数 6 → 65，粒度 = 单条知识。

### 取用接口

```python
from rag.astro_rag import AstroRAG
rag = AstroRAG(); rag.load()
hits = rag.search("ps1 精准下载 0 行", top_k=5)
```

### 升级路径（可选，按需）
1. 现阶段：BM25 + 中文单字桶（零依赖，够用）
2. 需要语义：换 TF-IDF / 哈希向量后端（`_shared.rag_engine` 已提供）
3. 需要真语义向量：接 BGE-M3（**注意**：实测本机无 CUDA + HF 下载 502，需先解决网络与权重）

### 优点 / 代价
- ✅ 能捞长尾、模糊说法也能命中
- ❌ 不确定，分数不可解释，需要调 top_k / 阈值
- ❌ 粒度 bug 未修前等于摆设

## 五、沉淀管道（两套共用）

### 候选条目 schema

```yaml
# .knowledge/inbox/2026-09-28_hook_network_exhausted.yaml
- id: C-20260928-001
  candidate_type: known_issues      # 归类：lessons_learned / known_issues / domain_rules
  title: "ps1 锥搜重试 3 次仍 5xx"
  body: "2026-09-28 14:22 实测：catalog=ps1, endpoint=/ps1/q, 重试 3 次 503…"
  evidence:                          # 可溯：来自哪条日志
    log_file: .logs/task_log.jsonl
    task_id: file_bbd33e800248
    event: hook
  tags: [network, live-verified, ps1]
  slot_hint: error_kind/network_exhausted   # 建议升格后挂哪个槽位（A 路用）
  status: pending                    # pending / approved / rejected
```

### 流程
1. `ops/knowledge_capture.py` 扫 `.logs/task_log.jsonl`
2. 只取有信息量的事件：`failed` / `blocked` / `hook` / `ask`
3. 按 `message` 指纹（前 N 字符 + event）**去重**，不重复堆条目
4. 写入 `.knowledge/inbox/`，`status: pending`
5. 人工改 `status: approved` → 升格脚本并入 `rag/knowledge/` 对应文件 + 建槽位

### 为什么要有 inbox 这道闸
知识库一旦被脏数据污染，A 路和 B 路会一起坏。
"只增不减硬锁"意味着写进去就很难清掉，所以**入正库前必须过审**。

### 别名机制（实测必需的补丁）

目录里真实文件叫 `best_two_phase.yaml`，而调用方自然会说 `two_phase`。
没有别名表时这类调用**全部静默落空** —— A 路会变成"看起来能用、实际永远
不命中"的摆设，比没有更危险。所以在 `SLOT_ALIASES` 里显式登记短名：

```python
SLOT_ALIASES = {
    ("algo_mode", "two_phase"): "best_two_phase",
    ("algo_mode", "auth"): "best_auth_mode",
    ("data_source", "endpoints"): "nadc_endpoints",
    ...
}
```

别名是**显式清单**而非前缀模糊匹配，一个值只映射到确定的一个文件，
保证 A 路的确定性不被破坏。

## 六、验收标准

- [ ] `python ops/knowledge_capture.py --since 7d` 能从真实日志产出候选条目
- [ ] A 路：`resolve_slots({"catalog":"ps1"})` 稳定返回 ps1 槽位文本
- [x] B 路：修粒度后条目数 6 → **68**，返回单条知识而非整坨 YAML（已实测）
- [ ] B 路：查询"ps1 精准下载 0 行"的 top1 精准命中 `L-precise-ps1-source-id-empty`

> 注：不要用"top1 分数显著高于 top3"当验收标准。RRF 融合分是 `1/(60+rank)`，
> rank 1/2/3 必然是 0.0328/0.0323/0.0317，天然接近 —— 分数差小是 RRF 的正常
> 特性，不是缺陷。真正该看的是**返回的条目内容对不对**。
- [x] `python -m pytest test -q` → **842 passed, 24 skipped, 0 failed**（已跑）

## 七、本次已落地（2026-09-28 实测）

| 交付 | 路径 | 状态 |
|------|------|------|
| 方案文档 | `docs/knowledge-sedimentation-plan.md` | ✅ |
| **A 路**槽位取用 | `src/knowledge_slots.py`（含别名表、越界防护、截断保护） | ✅ 8 槽位可查 |
| **管道**第一棒 | `ops/knowledge_capture.py`（事件→候选，数字归一化去重+噪声过滤） | ✅ 实测产出候选 |
| **B 路前置修复** | `rag/astro_rag.py::_entries_from_doc` 列表展开 + 正文键扩容 | ✅ 条目 6→68 |
| CLI 接线 | `ops/astro_best_cli.py` 新增 `slots` / `capture` 子命令 | ✅ 已验证 |

### 尚未落地（下一步）
1. **升格器**：`inbox(status=approved)` → 并入 `rag/knowledge/*.yaml` + 自动建槽位文件
2. **A/B 合流**：`resolve_slots()` 结果 + `rag.search()` top-k 去重合并后注入上下文
3. **catalog / error_kind 槽位**：目前目录不存在，由升格器按 `slot_hint` 自动建
4. pipeline 阶段点埋入：在 EXECUTE/GATE 阶段真正调用上面两路
