# E1 / E4 门禁清单（凭什么判定放行 / 阻断）

- 整理日期：2026-10-11
- 说明：**门禁代码**随各实验的 `runner.py` / `broken/` 一起收在本包对应目录；
  本目录收的是**门禁的接线与依据**（Makefile 目标、权重量规与台账、解锁清单）+ 本清单。

## 一、E1 门禁

| # | 门禁 | 判什么 | 开关 / 阻断码 | 实现位置 | CI 接线 |
|---|---|---|---|---|---|
| 1 | **逐维门禁** | 跑了的是否达标（六维各自过线） | `--require-threshold`<br>阻断码 `below_dimension_threshold` | `evals/nl2tool/runner.py:385` | ✅ **已接线**<br>`make eval-e1` 已带该开关 |
| 2 | **覆盖门禁** | 该跑的跑了没 | `--expect-attempts N`<br>`missing_traces` / `short_attempts` | `runner.py:383` | ⚠️ make 未传<br>（缺省 1，模型批须显式传 3） |
| 3 | **红线门禁** | 有没有科学性硬错 | `red_line_tasks`（S1 / 参数幻觉 / 伪造工具 / 硬执行） | `graders.py` | ✅ 每批实算 |
| 4 | **判定器自证门禁** | 判定器本身失效没有 | `metascore < 1.0` → `grader_selftest_failed` | `broken/` 6 条夹具 + `runner.py` | ✅ 每批实算 |
| 5 | **权重和门禁** | 权重量规是否被静默改掉 | 权重和 = 1.00；改量规而不留痕 → 红 | `evals/scoring-rubric.yaml` + `_data/scoring-weights-ledger.yaml` | ✅ 启动校验 |
| 6 | **防污染闸** | 题面/模型可见面是否夹带答案 | `check_leakage.py --dir` / `--model-root` | 本包 `E1/05-防污染工具/` | ⚠️ 手工跑（`make e1-batch-input`） |
| 7 | **逐维门禁单测** | 门禁判据本身成立 | `TestDimensionThresholdGate`（含「99 全对 + 1 转换错」反例） | `E1/03-自证与反证夹具/tests/test_e1.py` | ✅ pytest |

## 二、E4 门禁

| # | 门禁 | 判什么 | 开关 / 阻断码 | 实现位置 | CI 接线 |
|---|---|---|---|---|---|
| 1 | **执行门禁** | 该层真跑了没（「没跑」≠「跑了得零分」） | `--require-execution`<br>阻断码 `tier_p_not_executed` | `evals/robustness/runner.py:512` | ✅ **已接线（2026-10-11）**<br>`make eval-e4` 已带；无答案即阻断 |
| 2 | **判定器自证门禁** | 反证夹具是否全被抓住 | `metascore < 1.0` | `broken/` + `runner.py` | ✅ 每批实算 |
| 3 | **协议层事实守卫** | 缺字段时是否把「没得查」记成 1.0 | `guardscore < 1.0` | `guards.py` + `runner.py` | ✅ 每批实算 |
| 4 | **处置口径越界** | `disposal` 是否落在 A/B/C/D 四级之外 | 越界即 exit 1 | `evals/robustness/check_disposal_scope.py` | ⚠️ 新增，尚未接 make |
| 5 | **禁调红线** | `must_not_call` 违规 | 4 条（r1：RB-01/04/05/21） | `graders.py` | ✅ 每批实算 |
| 6 | **沙箱隔离检疫** | 答题面是否夹带标注/判分器/异源答卷 | `make_answer_box.py --build`（exit 0 才放行） | 本包 `E4/04-` 与 `06-` | ⚠️ 手工跑 |
| 7 | **方案 §12 阻断项** | 12 条文档级门禁 | 第 10 复合未跑 / 11 夹具不全 / ~~12 判定层未接线~~ | `docs/eval-E4-robustness-safety.md` §12 | 第 12 条 ✅ 已解除 |

## 三、接线后遗留的一处缺口（必须知道）

**`runner.py` 不支持 `--include-second-round`**（grep 计数 0）—— 复合故障 RB-C01..C18
（E4 自定的唯一增量）**至今无法实跑**：不是「没跑」，是「跑不了」。
这是「E4 不得出具通过 / 有效结论」最硬的一条理由，与执行门禁是否接线无关。

## 四、2026-10-11 接线动作记录

| 项 | 接线前 | 接线后 |
|---|---|---|
| `make eval-e4` | `--tier all --md`（无门禁） | 加 `--require-execution` + 可选的 `E4_ANSWERS` |
| 无答案时行为 | 静默「预检 = 过」 | **阻断**（`tier_p_not_executed`），exit ≠ 0 |
| 真判话术层 | 无通道 | `make eval-e4 E4_ANSWERS=temp/robustness/answers/r1` |
| 临时放行 | — | `make eval-e4 E4_SKIP_GATE=1` |
| 新增目标 | — | `make check-e4-disposal`（处置口径越界，越界即 exit 1） |

**验证**：无答案 → `P.blockers = ['tier_p_not_executed']`；
带 r1 答案 → `P.blockers` 为 22 条真实阻断项、**不含**该码（即不误伤）。

## 五、本目录文件

- `Makefile` —— `eval-e1` / `eval-e4` / `evals-all` 的实际命令（门禁接线现状以此为准）
- `scoring-rubric.yaml` —— 五维权重量规（真值，runner 只读这一份；权重和 = 1.00）
- `scoring-weights-ledger.yaml` —— 权重**变更登记簿**（守护的是「变必须留痕」，不是「值不许变」）
- `null_sentinel.yaml` —— 哨兵值判定口径（E1/E4 共用；哨兵当真值是两实验共同的阻断项）
- `tolerances.yaml` —— 数值容差口径
- `EVAL-UNLOCK-CHECKLIST.md` —— 六实验解锁清单（门禁分布：E2/E3/E4/E5 各一处、E6 两处、E1 一处）
