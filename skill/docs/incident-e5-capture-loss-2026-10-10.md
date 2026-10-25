# E5 live 采集表丢失事故与恢复路径 (2026-10-10)

> 性质: **数据事故** —— E5 live 臂的输入采集表被 `temp/` 沉底清理删除, 且 `temp/` 被 gitignore, 无版本副本。
> 结论一句话: **E5 live 臂在重建采集表之前无法再跑**; E2 不受影响, 本会话的代码与文档成果已入库且完好。

---

## 一、发生了什么

`temp/capture_live.json` (460 827 B) 与本次重采产物 `temp/capture_b3_indep.json` (473 970 B) 在磁盘上已不存在。

它们**不是被误删**, 而是被一次**符合仓规的沉底行动**清理掉了。证据: 提交
`1940efa chore(knowledge): 完成 temp/ 活跃资产知识沉底，生成沉底台账 [sanitized]`
新增了 `docs/archive/sinking-manifest-2026-10-10.md` (1 224 行) 与 `ops/sink_temp_knowledge.py`,
其口径写得很清楚:

> 生成时间: 2026-10-10 · 沉底资产总数: 1208 文件 · 物理体积: 196.17 MB
> 沉底口径: 2026-10-08 之后新增的 E2/E5 评测跑批、T5 错误谱系、M7 确定性探针与消融假设集。

而被删文件在台账里**只留下了指纹**:

| 相对路径 (temp/) | 体积 (Bytes) | SHA-256 |
|---|---:|---|
| `capture_live.json` | 460 827 | `543560b0860e490808a8f0684e554ca021828168eea1e841701979694b1bc530` |
| `capture_b3_indep.json` | 473 970 | `403ce92da63d0d0db53060d2c8ad5e066cbd09864abe88d6e4c183e30b75a853` |

**指纹可用于对账"曾经存在过且是哪一份", 但无法还原内容。**

## 二、为什么这是真损失

`temp/` 在 `.gitignore` 中, 铁律 3 又规定"临时产物只进 `temp/`" —— 两条合起来意味着
`temp/` 里的东西**按设计就是易失的**, 且沉淀工具会定期"登记指纹后清理"。

问题在于: **E5 的 live 采集表不是临时产物, 它是承重的实验输入。**
`--require-live` 全靠它; 丢了它, `make eval-e5` 只能回落替身批并被门禁判 `scripted_not_live`。
把它放进 `temp/` 是**定位错误**, 不是清理工具的错 —— 清理工具严格按既定口径执行。

## 三、损失边界 (已逐项核实)

| 资产 | 状态 |
|------|------|
| 本会话代码改动 (`assertions.py` / `prereg.py` / `stats.py` 标定与域闸 / `report.py` / `runner.py` / `m7_determinism.py` / `run_e2.py`) | ✅ 完好, 已入库 (`eec2b6f`, `1940efa`, `bb04581`) |
| 本会话文档 (`e2-e5-rerun-2026-10-10.md` / `e2-e5-rigor-upgrade.md` / 两份方案 §14 §15) | ✅ 完好 |
| `evals/ablation/REPORT.md` (2026-10-10 01:57 的 live 判定: 通道标定 + 采集侧阻断) | ✅ 完好 (12994 B, 已跟踪) |
| `evals/groundtruth/REPORT.md` + 全部 E2 快照/场景/金标准 | ✅ 完好 (E2 实跑不读 `temp/`) |
| **E5 live 采集表** (`capture_live.json`) | ❌ **丢失, 仅存指纹** |
| 本次独立重采产物 (`capture_b3_indep.json`, 90 份 v1 作答) | ❌ **丢失, 仅存指纹** |
| v2 重采的部分作答 | ⚠️ 部分残留于 `temp/indep/` (33/90, 会话已中止) |

## 四、恢复路径

1. **E2 无需恢复** —— 重新实跑即可复现 21/21:
   `python evals/groundtruth/run_e2.py --mode live --require-independent-verify --repeat 3`
2. **E5 必须先重建采集表**。两段式流水线本身已经建成并跑通一次
   (`temp/build_indep_prompts.py` → workflow 独立作答 → `temp/merge_indep_capture.py`),
   但它的**输入**(旧采集表)没了, 所以要先产出基线采集表, 再谈表述通道重采。
   **重建规模**: 11 装配 × 30 题 × 3 attempt = 990 单元 (每单元一次决策 + 一次观测作答)。
3. **本次踩到的一条真实教训 (必须落到结构上)**: 承重的实验输入**不得住在 `temp/`**。
   建议把采集表提升为**入库资产**, 例如 `evals/ablation/captures/<批次>.json`
   (带 `provenance` 段, 与 `subagent_capture.build_capture` 的形态一致),
   并由一道门禁断言"live 臂引用的采集表必须是被跟踪文件"。
   否则任何一次例行沉底都会再次抹掉它。

## 五、流程教训 (与我自己的操作有关)

* 我在**未对输入做快照**的前提下, 让 90 个子代理在同一工作目录里读写文件 ——
  输入与被写产物同处 `temp/`, 而该目录有**自动清理策略**, 两者叠加使损失不可避免。
* 正确做法: 启动大规模并发写之前, 先把**不可再生的输入**复制到不会被清扫的位置并核对指纹;
  写入范围也应限定在独立子目录 (本次 v2 的 `temp/indep/` 就是对的, 只是输入没保护)。
* 沉底工具本身按既定口径运行且留了指纹台账 —— **它没有错**, 错在依赖关系没有被告知它。
