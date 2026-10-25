# 从这里开始（三箱操作卡）

**目标**：用三个内容相同的答题箱，把 E4 跑三次（三次重复），且答案与历史跑批都不进箱。

## 一、每次实验只做一件事：选一个箱

| 第几次 | 模型 cwd | 答案落点 |
|---|---|---|
| 第 1 次 | `sb1/` | `_answers/sb1/r1/` |
| 第 2 次 | `sb2/` | `_answers/sb2/r1/` |
| 第 3 次 | `sb3/` | `_answers/sb3/r1/` |

> 不要同一个箱跑三次。三次重复要的是**三个独立箱**，不是同一箱的三个轮次。

## 二、开跑前（各 10 秒）

1. 确认 `sbN/` 下能看到 `SANDBOX-RULES.md` 与 `questions/per_item/`；
2. 把会话的工作目录**直接**指到 `sbN/`（不要指到沙箱根，也不要多给一层）；
3. 会话开场把 `SANDBOX-RULES.md` 的“你的世界就是这个目录”那段照抄给模型；
4. **上锁**（答案面在跑批期不可读）：

   ```bash
   cd "<USER_HOME>\E4-锁工具"
   python plane_lock.py lock
   python plane_lock.py verify     # 13 项应全部「拒读」，exit 0
   ```

   锁上之后，沙箱根下的 `_index`（题目索引，第三列就是处置）、`_验收`、`_batch`、
   `_answers`、`SANDBOX-MANIFEST.json`，以及评测仓的 `items.yaml` / 历史答卷 / 原始产物包，
   **连操作者本人都读不到** —— 这是有意为之：模型跑的就是同一个 Windows 账号，
   只 deny“模型账号”等于锁了个不存在的门。

## 三、跑的时候

- 题卷是 **53 条**（话术 35 + 复合 18），一题一个文件，**一题一会话**；
- 盒内**没有** `TASKS.md` 那种整卷手册——不要自己拼一份，也不要一次读一堆题；
- 题面照抄，不加任何提示（“这题该拒”“别用某工具”都属于泄题）；
- 每题答完把结论/调用写成 `_answers/sbN/r1/RB-xx.json`（格式同 r1 批次）；
  **2026-10-21 22:35 变更**：本批已完成，答案面改为**每箱放一份会话答卷原文**（不再拆 json）——
  `_answers/sb1/r1/答题结果-53题.md`、`_answers/sb2/r1/E4-sb2-53题答卷.md`、
  `_answers/sb3/r1/astro-best-答卷-sb3.md`。判分侧由 `E4-work/temp/e4_judge/parse_boxes.py`
  按各箱的标题层级切题，改箱子标题风格时要同步改它。
- 题号 → 原话/净化后题面的对照在 `_index/题目索引.md`，**需要看就先 `unlock`**，看完再 `lock`；
- `_answers/sbN/` 在开跑前是**空目录**（构建态 0 文件）。里面只该有你自己的答卷，
  不要往里放批次卡或任何预置件——批次元数据在 `_batch/sbN.json`（记录题数、题面集哈希、
  rubric/schema 版本，以及待填的 model_id / system_prompt_version / network）。
- **锁态下 `_answers/` 拒读写**。答卷是从会话记录整理出来的操作者动作，所以：
  跑批期只管跑，答案先攒在会话里；`unlock` 之后统一整理落盘到 `_answers/sbN/r1/`。

## 四、三次都跑完后才判分

> **本批（53 题 × 三箱）的判分可一键复现**，三个入口都在 `_复现/`：
> `python reproduce.py` 重算 159 个判定格并对账；
> `python reproduce_official.py` 走官方 `runner --tier P/W`（含判定器自证 metascore/正例）；
> `python check_judge.py --vs <源仓>` 体检判分器有没有被换成旧版。
> 详见 `_复现/README-复现.md`。该目录属操作者资产，**不得拷进 sbN**。


先解锁（判分要读 `items.yaml` 与 `_answers/`）：

```bash
cd "<USER_HOME>\E4-锁工具"
python plane_lock.py unlock
```

```bash
cd "…\AI-archive-pre-sinking-snapshot-20261010\E4-work"
for b in sb1 sb2 sb3; do
  PYTHONPATH=. python -m evals.robustness.runner --tier all --include-second-round \
    --answers "<USER_HOME>\E4-答题沙箱-2026-10-21\_answers\$b\r1" \
    --require-execution --json "evals/robustness/runs/r1-$b/report-all.json"
done
```

判分**永远在评测仓里做**，不要在箱内装判分器或跑 runner。

## 五、出问题先跑这两条

```bash
python _builder/audit_leak.py     # 箱里有没有答案/历史产物（命中即 exit 1）
python _builder/verify_all.py     # 三箱一致 / 静态隔离 / 负向反证 / 命令自检
```

- 审计报红：**先别跑实验**，按报告点名的文件处理后再跑；
- 验收 A 部报红（三箱不一致）：说明有人只重建了一箱 → 三箱一起重建；
- 重建会清空 `_answers/`，**先备份已有答卷**。
