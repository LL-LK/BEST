# E5 三项隔离门禁核查：落地了吗？(2026-10-11)

> **结论先行**：三项里 **1 项真落地、1 项半落地、1 项未落地**。
> 声称「修法（结构性）已落地」的 `docs/e5-isolation-defects-d17-d18-2026-10-11.md`
> **只对了一半**：预防面真做了，**检测面是假的**，而**并发保护根本没做**。
> 下列每条都附可复现命令，不依赖"我记得修过"。

---

## 一、判定表

| # | 门禁 | 声称的修法 | 实测 | 判定 |
|---|------|-----------|------|------|
| G1 | **答案键隔离** | scratch 移出仓库树（`%TEMP%\e5_scratch`）+ 投放时 fail-closed 禁词自检 | 结构迁移 ✓（向上 6 层无 `astro-best` / `items.yaml`）；禁止词自检 ✓；**后验审计器路径未同步，10 个新批全漏审** | ⚠ **半落地**：预防真、检测假 |
| G2 | **批次唯一性** | `stage_scratch.py` 拒绝复用已存在的批次名 | `python temp/stage_scratch.py b3_s1 B3` → `exit=3` 拦截 ✓ | ✅ 真落地，**但无保障**（gitignored、零测试、零门禁登记） |
| G3 | **并发写入保护** | 文档把 G2 当作 G3（"拒绝复用 ⇒ 防并发覆盖"） | 无锁、无 `O_EXCL`、无写者标记；`dst.exists()` 是 TOCTOU 检查；D-18 的真实形态不在其防护路径上 | ❌ **未落地** |

---

## 二、逐条取证

### G1 答案键隔离：预防真、检测假

**做对的部分（实测）**

```
scratch: <USER_HOME>\AppData\Local\Temp\e5_scratch
  ...\e5_scratch            astro-best=False items.yaml=False
  ...\Temp                  astro-best=False items.yaml=False
  ...\Local / AppData / user / Users  全 False
```

向上走满 6 层都够不着仓库 ⇒ D-17 的结构性修法**成立**。
`temp/stage_scratch.py:99-114` 的 fail-closed 禁词自检也在（命中即 `rmtree` 撤销投放）。

**做假的部分（实测）**

```
$ python temp/audit_scratch.py b3_s1 24
没有该批次: <SKILLS_ROOT>\astro-best\temp\scratch\b3_s1     exit=1
```

`temp/audit_scratch.py:34` 仍写死 `ROOT / "temp" / "scratch" / argv[1]`，
而 `temp/stage_scratch.py:35` 已把 `SCRATCH` 改成 `tempfile.gettempdir()/e5_scratch`。
两者 mtime：audit **10-10 23:29** < stage **10-11 02:09** —— 路径迁移没带上审计器。

⇒ **新位置的 10 个批次从未被后验审计覆盖**：
`a1_w1 a3_w1 a4_w1 a5_w1 b3_s1 b3_s2 b3_s3 b3_v2 b3_v3 b3_v4`（各 24 格，共 240 格）。
方案 §11 缺陷 12 自称"已修（`stage_scratch.py` 投放 + `audit_scratch.py` 检测）"，
**检测那一半实际从未对新数据生效过**。

### G2 批次唯一性：实现了，但不在任何人的视野里

```
$ python temp/stage_scratch.py b3_s1 B3
✗ 批次 b3_s1 已存在: <USER_HOME>\AppData\Local\Temp\e5_scratch\b3_s1
  批次名**不得复用** (D-18: 并发写会互相覆盖)。
exit=3
```

拦截生效 ✓。但：

* 唯一实现在 `temp/stage_scratch.py`，`git check-ignore -v` → `.gitignore:104:temp/` ⇒ **不入库**；
* `src/ ops/ evals/ test/ Makefile contracts/` 全部零引用；
* `ops/audit/run_all_gates.py` 的 12 道硬门禁**没有它**；
* `grep -rIln "scratch|decision_iso" test/ evals/` → 只有 `evals/ablation/REPORT.md`（叙述性提及），**零测试**。

⇒ 它能工作，但**改坏了不会有人知道** —— 这正是 D-17/D-18 教训（"我以为禁住了"）的同形复发。

### G3 并发写入保护：未实现，且检测门也看不见它

1. **无任何锁原语**：`grep -n "lock|O_EXCL|fcntl|msvcrt" temp/stage_scratch.py` → 零命中；
   `find %TEMP%\e5_scratch -name "*.lock"` → 零文件。批次目录只有 `prompts/ out/ MANIFEST.txt`。
2. **`dst.exists()` 是 TOCTOU**：检查与 `mkdir` 之间有窗口，两个并发投放都能通过。
3. **更根本：G2 防不住 D-18 的真实形态**。D-18 是"批次**已投放**后，我往**同一个** scratch
   又派了一个代理" —— 批次名自始至终是唯一的，两个写者写的是同一批文件。
   批次名唯一性与这件事无关。
4. **`--force` 是一条新的破坏路径**：`shutil.rmtree(dst)` 会删掉正在里面跑的代理的工作目录。
5. **后验门对该失效模式零覆盖**（决定性证据）：对文档已判定为"两个写者混合"的
   `rep_b3_r2`（out 双簇 mtime `02:05:12/02:05:25` 与 `02:07:00/02:07:11`，间隔 95s）：

   ```
   $ python temp/audit_scratch.py rep_b3_r2 24
   ④ 覆盖: 24/24
   审计通过: scratch 未被越界读写, 输出形状与约定全部合规。   exit=0
   ```

   **已知不干净的批，审计器判通过。** ⇒ G3 不但没有预防，也没有检测。

---

## 三、残留面（如实披露）

| 项 | 状态 |
|---|---|
| `temp/scratch/` 旧位置 | **仍在仓库树内**，含 `rep_b3_r2` / `rep_b3_r3` / `dcs_pilot` 等污染批；答案键仍可从它们向上三级到达 |
| `<SKILLS_ROOT>\_e5_scratch` | 仍在（文档自述的被否决方案目录，未清理） |
| 新批次是否复发 D-18 | **未复发**：10 批 out 的 mtime 跨度 0–175s、最大间隔 ≤29.5s，无双写簇 —— 但这是**概率性安全**，不是结构性安全 |
| 指令注入通道 | `CLAUDE.md` 已量化为"零题号、零答案键字样"，但采集代理若从主会话继承仓库路径仍可绝对路径访问；**该通道仍未消除** |

---

## 四、修复建议（按性价比）

| 优先级 | 动作 |
|---|---|
| **P0** | 把 batch root 抽成**单一常量**（如 `e5_paths.SCRATCH`）供 `stage_scratch` 与 `audit_scratch` 共同 import —— 路径漂移从此不可能单边发生；改完对 10 个新批补跑一次后验审计 |
| **P0** | 并发保护落地：投放时**原子**创建 `dst/.owner`（`mkdir(exist_ok=False)` / `O_EXCL`，失败即拒并报"该批次已被占用"）；`--force` 前先校验无活跃写者 |
| **P1** | 两个脚本从 `temp/` 移入受管目录（如 `evals/ablation/harness/`），至少补 3 条单测：① 复用批次名被拒 ② scratch 不在仓库树内 ③ 禁词命中即撤销投放 |
| **P1** | 后验审计增加**单写者判据**（out 文件 mtime 单簇检测 / 写者标记校验），让 `rep_b3_r2` 这类批**必须判红** |
| **P2** | 清理 `temp/scratch/` 旧污染批与 `_e5_scratch`；把它们移出仓库树或封存到不可达位置 |

---

## 五、一句话

**结构隔离这条做对了，但它只做了一半：投放器搬了家，审计器没跟着搬，于是"检测"这道门
对着 240 格新数据一直是关着的；而"并发写保护"从头到尾没被实现过 —— 文档里那句
"拒绝复用批次名 ⇒ 防并发覆盖"是把「名字唯一」误当成了「写者唯一」。**

---

## 六、修复（2026-10-11 同日落地）与复验

### 6.1 改了什么

| 优先级 | 动作 | 落点 |
|---|---|---|
| **P0** | 根目录收成 SSOT：投放器与审计器**共用** `paths.batch_dir()`，路径漂移在结构上不可能发生 | `evals/ablation/iso/paths.py` |
| **P0** | 建批改为**原子** `mkdir(exist_ok=False)`（无 TOCTOU 窗口）+ `O_EXCL` 写者标记 `.owner.json`（pid / 时间 / 格数） | `evals/ablation/iso/stage.py` |
| **P0** | 后验审计加**单写者判据**：out 的 mtime 相邻空档 > 60s 即判"疑似两个写者"；无写者标记亦判红 | `evals/ablation/iso/audit.py` |
| **P0** | `write_traces()` 由 `write_text()` 直写改为**目录互斥锁 + 临时文件 + `os.replace` 原子提交 + 同名拒写**；报告内撞 (system,item,attempt) 即判错 | `evals/ablation/harness/run_batch.py` |
| **P1** | 实现搬进仓内受管目录（`temp/` 被 `.gitignore` 排除，交付包里翻不到）；`temp/` 下两份旧脚本降级为**转发入口**，消除"两份实现" | `evals/ablation/iso/` + `temp/stage_scratch.py` / `temp/audit_scratch.py` |
| **P1** | 15 条单测钉住三条门禁（含失效形态反证） | `evals/ablation/tests/test_e5_isolation_gates.py` |
| **P1** | 两个新 env 键在 `env_scope.py` 逐条裁定（非部署期输入），`verify_crossrefs` 转绿 | `ops/audit/env_scope.py` |

### 6.2 复验（实测，非声称）

```
$ pytest evals/ablation/tests/test_e5_isolation_gates.py -q     ->  15 passed
$ pytest evals/ablation/tests/test_e5*.py -q                    ->  89 passed   (write_traces 改动无回归)
$ python ops/audit/verify_crossrefs.py                          ->  0 个问题    (修复前 1 个)
```

**单写者判据抓到了它该抓的那批**（旧事故批，双簇 mtime 相隔 94.854s）：

```
$ E5_SCRATCH_ROOT=.../temp/scratch python -m evals.ablation.iso.audit rep_b3_r2 24
  ✗ 无写者标记 .owner.json: 该批无法归属到单一投放者
  ✗ 疑似多写者: 输出最大空档 94.854s > 60.0s —— D-18 形状        exit=1
$ ... audit dcs_pilot 24        # 旧干净批
  单写者判据 max_gap 46.0s 不判红, 仅"无主"判红                  exit=1
```

**10 个新位置批次补跑后验审计**（此前从未被审过）：

| 批次 | 输出 | 最大空档 | 单写者 | 结论 |
|---|---|---|---|---|
| a1_w1 / a3_w1 / a4_w1 / a5_w1 | 24×4 | 14.3 / 29.5 / 0.007 / 0.002 s | 通过 | 仅"无主"判红 |
| b3_s1 / s2 / s3 | 24×3 | 5.4 / 8.8 / 4.3 s | 通过 | 仅"无主"判红 |
| b3_v2 / v3 / v4 | 24×3 | 12.6 / 6.2 / 6.5 s | 通过 | 仅"无主"判红 |

⇒ **单写者判据对 10 个新批全部通过（未复发 D-18），但全部"无主"** ——
它们由旧投放器生成，早于写者标记。所以基于这些批次（含 8.3% 路由噪声底）的结论
须写成"**观测到**"，不能写成"**已归属到单一投放者**"。

### 6.3 仍未修的（如实披露）

* `temp/decision_iso`（5.6 MB 逐格提示词）与其生成器 `temp/build_isolated_prompts.py`
  仍在 gitignored 的 `temp/` 下 ⇒ 评审者**无法自行复现投放**；
* 2026-10-11 前的全部批次都没有写者标记，归属不可证（见上表）；
* 三位一体的"活跃写者"判定目前靠**事后时间戳**，不是实时互斥 ——
  真正的实时互斥要在代理进程侧配合（超出本仓能单点修的范围）；
* 门禁**未接进** `ops/audit/run_all_gates.py` 的 12 道硬门禁（目前靠 pytest 守）。

---

## 七、G3 补完（2026-10-11 第二轮）：从"名字唯一"到"会话唯一"

第一轮只把"批次名不得复用"做实了，但**那挡不住 D-18** —— D-18 的形状是批次**已投放**
之后往同一 scratch 再派一个代理，批次名自始至终唯一。补的是三件事。

### 7.1 写会话（真正的拦截点）

`begin_write(batch)` / `end_write(batch)`：同一批次**同时只允许一个未关闭的写会话**，
只有显式 `end_write` 能关。派代理前先 `--begin-write`，第二个必然撞上 `.writing`。

**⚠ 中间踩过的一个坑（实测否决了第一版设计）**：第一版按"上一个会话的 pid 还活不活"
来判断能不能开新会话，**实测门禁形同虚设** —— 开会话的 CLI 进程调完就退出，pid 被判死，
于是第二次 `begin_write` **照样成功**：

```
### 开写会话 ###  ✓ 写会话已开 pid=26572
### 同批第二次 ### ✓ 写会话已开 pid=19824        # ← 该被挡却没被挡
```

改为"标记在不在"：在，就是有人没关；要清必须由人显式 `force=True`，并把被清掉的旧会话
记进新标记（`forced` / `forced_from`）留痕。**不靠猜进程死没死。** 改后：

```
### 同批再开(2) ### ✗ 批次 demo_g3 已有一个未关闭的写会话 (pid=27080, 该 pid 当前已退出)
                    —— 同一时刻只许一个写者, 这正是 D-18 的形状        exit=5
```

同一条教训的第二形态：**开会话的进程 ≠ 真正的写者**（写者是被派出去的代理，不在本进程树里）。
这与 D-17/D-18 同源 —— 又是一次"我以为它结束了"。

### 7.2 写者令牌

`.owner.json` 增加一次性 `token`（`uuid4`）。**pid 会被操作系统复用**，只比 pid 会把
"旧批的主人"误认成"当前会话"；token 只有真正持有它的投放会话才拿得到。

### 7.3 审计新增三条判据（都不依赖时间戳）

| 判据 | 抓什么 | 为什么时间戳抓不到 |
|---|---|---|
| 写了**未分配**的格 | 越界写入（`.cells.json` 比对） | 越界与分配内写入可能同一秒完成 |
| **收尾后**新增/重写 | 第二波写者 | 实测追加文件的空档只有 **1.77s**，远低于 60s 阈值 |
| **无收尾快照** | 没走 begin/end 流程 | 单写者根本没被记录，时间戳无从判 |

实测对照（同一批 demo，先干净再追加一个文件）：

```
审计(干净)      ✓ 五项判据全过                                        exit=0
收尾后追加 1 个  ✗ 写了未分配的格 1 个 (B3/E5-D03)
                ✗ 收尾后又新增 1 个输出 (B3\E5-D03.json)              exit=1
                  （此时空档仅 1.77s —— 时间戳判据 singles 完全看不出来）
```

### 7.4 复验

```
pytest evals/ablation/tests/test_e5_isolation_gates.py -q   ->  26 passed  (G3 补完前 15)
```

新增用例覆盖：pid 判不出来按活处理（fail-closed）、第二个写者被挡、令牌不符被挡、
未投放批次不许开写、采集进行中不得 --force 覆盖、强制开会话必须留痕、
越界写入 / 收尾后追加 / 无快照 / 会话未关 各自判红、走完全流程的干净批必须放行。
