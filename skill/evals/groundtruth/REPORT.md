# E2 查询结果与金标准一致性 — 跑批报告 (REPORT)

> **本文件是人工撰写的归档，不由跑批覆盖**（`make eval-e2` 将结果打印到终端）。
> 原因：runner 的 `--md` 输出只是本文件的一个子集，逐 case 明细、七指标汇总表与
> 「已知登记」是人写的深度分析，覆盖会导致内容丢失。
> 重跑命令：`python evals/groundtruth/run_e2.py --mode live --require-independent-verify --md --repeat 3 --json temp/e2_report.json`。

> **本次 PASS 的准确含义（2026-10-08 起为实跑批，2026-10-10 域闸固化）**：
> `pass=true` 证明的是 **21 个场景** 在**实连站点**下的判定管线自洽（M1–M7 全过 + 反证夹具 metascore=1.00 +
> §4.3.1 七项独立核验 21/21 PASS），**不含**"金标准经独立人工复核"这一层 ——
> 人工签字一族已于 2026-10-04 整链取消并删除（闸门 `--require-human-review`、签字单联、指纹台账、
> 回填工具链及签字指引均已彻底移除，以客观指纹漂移 `provenance_drift=0` 披露替代阻断）。
> 回放层（`QueryAwareTransport`）已于 2026-10-07 整链退役（承接登记见 `docs/REPLAY-RETIREMENT-CRITERIA.md`）。
>
> **现存放行判据**：21 个 case 全过 / 无缺件 / `metascore = 1.00` / §4.3.1 七项独立核验全过 / 无阻断项。

## 头部

- 接线模式: `mode: live`（直连真站点放行闸；回放层已于 2026-10-07 整链退役）
- 金标准与场景集: **21 份金标准**，**21 个场景**（`gold/*.json` 与 `scenarios/*.yaml` 100% 一一对应，0 孤儿资产）
- 快照库存: `evals/groundtruth/snapshots/` 下 **41 个 `snapshot.yaml` 目录 / 283 个已入库文件**（其中 `live-2026-10-04/` 32 个目录 / 223 个文件，是 `ops/live_fetch.py` 逐表实抓素材；另有 `syn_*` 合成夹具 9 个）。该数字是底层库存与普查素材，各场景按需消费。
- 反证夹具 metascore: **1.00**（10 个反证夹具全部抓获 — 判定器自证有效）
- 血缘漂移 (provenance_drift): **无**（0 漂移，生成器指纹完全吻合）
- 独立核验 (§4.3.1 七项): **21/21 PASS**（N/A 项 43，零 src 依赖隔离核验）
- 判定: **21/21 PASS**（加权分 0.9500–1.0000，全数 ≥ pass_score 0.90）

## 七指标汇总 (实连不变量口径)

| 指标 | 权重 | 结果 |
|------|------|------|
| M1 行集一致 | 0.30 | 全 21 case 内部不变量检验通过 (主键唯一、行数不超预算、分页无重无漏、空结果态 degenerate 由 M5 接管) |
| M2 字段一致率 | 0.25 | 全 21 case 1.0 (类型与语义对齐、缺列显式 null、哨兵语义类别比对生效) |
| M3 单位/精度 | 0.10 | 全 21 case 1.0 (量纲探针与有效位数下限校验通过) |
| M4 排序/分页/截断 | 0.15 | 全 21 case pass (满页续翻空页、max_rows 恰够不截断、proximity 序列单调性) |
| M5 四态区分 | 0.10 | 全 21 case pass (soft404 显式 E_SOFT_404、radius0 显式 E_INVALID_INPUT、空结果 success+0 行) |
| M6 版本一致 | 0.05 | 实连真站点不暴露版本面，如实记录 reconcilable=False 与 not_reconcilable=["snapshot_id"] (缺证据而非假满分) |
| M7 确定性/计数 | 0.05 | 3 次重复 data_hash 一致；http_requests 契约解释性校验通过；集成传输层瞬断 (RemoteDisconnected 等) 豁免域闸 |

## 21 个 Case 完整明细表

| case | 加权分 | 阻断项 |
|------|--------|--------|
| batch_proximity | 1.0000 | — |
| boundary_maxrows | 1.0000 | — |
| boundary_page_exact | 1.0000 | — |
| boundary_pole_dec | 0.9500 | — |
| boundary_radius0 | 1.0000 | — |
| boundary_wrap_ra | 1.0000 | — |
| cone_5as | 1.0000 | — |
| cone_60as | 1.0000 | — |
| empty_field | 1.0000 | — |
| huge_3700rows | 1.0000 | — |
| huge_batch_1000 | 1.0000 | — |
| huge_over_cap | 1.0000 | — |
| missing_arg_catalog | 1.0000 | — |
| missing_arg_coords | 1.0000 | — |
| missing_arg_radius | 1.0000 | — |
| missing_cell | 1.0000 | — |
| missing_column | 1.0000 | — |
| multi_filter_mag_snr | 1.0000 | — |
| sentinel_value | 1.0000 | — |
| single_exact | 0.9500 | — |
| soft404_page | 1.0000 | — |

## 阻断项

无 (metascore=1.00; 无 ERROR→EMPTY; 无跨版本污染; 无孤儿资产)。
放行判据四条：case 全过 (21/21) / 无缺件 / metascore=1.00 / §4.3.1 独立核验全过 (21/21)。

## 已知登记与工程经验沉淀

1. **M7 确定性传输层域闸 (2026-10-10 固化)**：原先「同场景 repeat 次 data_hash 全等」在实跑臂下因外部站点偶发 `RemoteDisconnected` 瞬断会随机挂掉不同 case。专项探针证实连接成功时 3 轮有序/无序/主键指纹完全一致，行数据不漂。修法：只要某轮属网络传输层异常，确定性记 N/A（不进分母），并在 `transport_error_repeats` 披露，消除网络天气对代码质量的干扰。
2. **PS1 点源 vs 对象记录主键量化判定**：`ps1` 回包实为对象记录与点源记录混排。覆盖比例随天区变，判型依据为 `ps1_source_id` 是否非空；全为点源记录时降级至 `(ra,dec)@9` 量化键，机制完整记录于 `references/data-formats.md` §5c。
3. **软 404 与会话过期突破**：实跑暴露出远端站点返回 `SqlidExpiredError` 会话过期场景，推动了实跑客户端显式捕获与会话重建能力的落地，属于回放层永远无法检出的真实验证收益。
4. **独立核验器（verify_independent.py）零 import 隔离铁律**：核验器自写几何 haversine、独立重算主键与截断三元组，严禁 import 被测库算法，防止生成器与核验器同源共振；对不适用项一律记 N/A（43 项），严禁记 PASS。
