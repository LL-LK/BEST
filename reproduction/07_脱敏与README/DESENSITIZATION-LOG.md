# 脱敏汇总日志（全包）

共处理 6 个最小复现包。下表为每包的改动规模。

| 包 | 文本文件改动 | 规则命中 | 归档内改动条目 |
|---|---:|---:|---:|
| E1_最小复现包 | 2 | 2 | 0 |
| E2_最小复现包 | 10 | 135 | 5 |
| E3_最小复现包 | 7 | 233 | 116 |
| E4_最小复现包 | 2 | 2 | 0 |
| E5_最小复现包 | 58 | 51568 | 30883 |
| E6_最小复现包 | 14 | 6017 | 965 |

## E1_最小复现包

规则命中统计：R10 单仓根路径×1、R16 学号邮箱×1

| 文件 | 命中规则 |
|---|---|
| `00-可运行-原仓路径/ops/audit/README.md` | R10 单仓根路径×1 |
| `00-可运行-原仓路径/references/photometric-systems.md` | R16 学号邮箱×1 |

## E2_最小复现包

规则命中统计：R06 本机 Windows 家目录×23、R09 工作区仓库路径×111、R23 裸账号名 token×1

| 文件 | 命中规则 |
|---|---|
| `03-E2-结果一致性/accepted_run/preregistration.json` | R06 本机 Windows 家目录×4、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/audit/run-03/preregistration.json` | R06 本机 Windows 家目录×4、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/audit/run-04/preregistration.json` | R06 本机 Windows 家目录×4、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/audit/run-05/preregistration.json` | R06 本机 Windows 家目录×4、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/audit/run-06/preregistration.json` | R06 本机 Windows 家目录×4、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/code/statcatalog/chenZTF_variables.csv` | R23 裸账号名 token×1 |
| `03-E2-结果一致性/frozen-code-map.json` | R06 本机 Windows 家目录×3、R09 工作区仓库路径×18 |
| `03-E2-结果一致性/operations/execute_e2_v2.py` | R09 工作区仓库路径×1 |
| `03-E2-结果一致性/operations/freeze_prereg.py` | R09 工作区仓库路径×1 |
| `03-E2-结果一致性/operations/prepare_assets.py` | R09 工作区仓库路径×1 |

归档内部改动 5 条（前 40 条）：

- `E2_最小复现包::RECOMPUTED::03-E2-结果一致性/accepted_run/preregistration.json` — 重算 3 个哈希字段
- `E2_最小复现包::RECOMPUTED::03-E2-结果一致性/audit/run-03/preregistration.json` — 重算 7 个哈希字段
- `E2_最小复现包::RECOMPUTED::03-E2-结果一致性/audit/run-04/preregistration.json` — 重算 6 个哈希字段
- `E2_最小复现包::RECOMPUTED::03-E2-结果一致性/audit/run-05/preregistration.json` — 重算 6 个哈希字段
- `E2_最小复现包::RECOMPUTED::03-E2-结果一致性/audit/run-06/preregistration.json` — 重算 4 个哈希字段

## E3_最小复现包

规则命中统计：R07 POSIX 家目录×3、R10 单仓根路径×1、R16 学号邮箱×228、R20 外部用户显示名×1

| 文件 | 命中规则 |
|---|---|
| `00-可运行-原仓路径/ops/audit/README.md` | R10 单仓根路径×1 |
| `00-可运行-原仓路径/references/photometric-systems.md` | R16 学号邮箱×1 |
| `03-E3-科学忠实性/04_匿名审核材料/E3-全量匿名审核表.xlsx` | OOXML:xl/worksheets/sheet6.xml×{'R16 学号邮箱': 1} |
| `03-E3-科学忠实性/04_匿名审核材料/E3-匿名审核简表.xlsx` | OOXML:docProps/core.xml×{'R20 外部用户显示名': 1} |
| `03-E3-科学忠实性/05_原始实验归档/bundle.json` | R16 学号邮箱×2 |
| `03-E3-科学忠实性/05_原始实验归档/connection.json` | R16 学号邮箱×2 |
| `03-E3-科学忠实性/05_原始实验归档/manifest.json` | R07 POSIX 家目录×1 |

归档内部改动 116 条（前 40 条）：

- `E3_最小复现包::RECOMPUTED::03-E3-科学忠实性/05_原始实验归档/manifest.json` — 重算 1 个哈希字段
- `original-evidence.tar.gz::RECOMPUTED::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/manifest.json` — 重算 1 个哈希字段
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A01_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A01_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A01_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A02_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A02_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A02_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A03_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A03_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A03_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A04_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A04_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A04_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A05_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A05_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A05_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A06_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A06_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-A06_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B01_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B01_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B01_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B02_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B02_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B02_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B03_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B03_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B03_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B04_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B04_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B04_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B05_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B05_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-B05_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-C01_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-C01_r2.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-C01_r3.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-C02_r1.json` — R16 学号邮箱×2
- `original-evidence.tar.gz::temp/e3-formal/batches/e3-b5ad6d180c9f42ce/answers/S-A_E3-C02_r2.json` — R16 学号邮箱×2
- …其余 76 条见 `_desensitize-report.json`

## E4_最小复现包

规则命中统计：R10 单仓根路径×1、R16 学号邮箱×1

| 文件 | 命中规则 |
|---|---|
| `00-可运行-原仓路径/ops/audit/README.md` | R10 单仓根路径×1 |
| `00-可运行-原仓路径/references/photometric-systems.md` | R16 学号邮箱×1 |

## E5_最小复现包

规则命中统计：R01 私密审核归档名×1、R02 微软账号 SID×1、R03 机器标识 SID 段×25、R04 主机\本地账号×1、R05 主机名×8、R06 本机 Windows 家目录×38、R07 POSIX 家目录×3、R08 沙箱家目录×41007、R09 工作区仓库路径×18、R11 E5 工作根路径×42、R12 临时工作路径×10、R13 临时 spill 目录×4、R14 临时会话 id×2、R15 用户邮箱×1、R17 内部评分身份×8、R18 内部工人身份×10378、R19 pytest 临时目录名×8、R21 工具安装根路径×11、R22 连字符转义家目录×1、R23 裸账号名 token×1

| 文件 | 命中规则 |
|---|---|
| `01-复现脚本/README.md` | R01 私密审核归档名×1、R11 E5 工作根路径×1、R17 内部评分身份×1 |
| `02-正式结果/E5_结果报告.md` | R05 主机名×1 |
| `02-正式结果/scorer-receipt.json` | R05 主机名×1 |
| `04-执行过程/FINAL-DELIVERY.json` | R06 本机 Windows 家目录×1 |
| `04-执行过程/asset-construction-v5.json` | R11 E5 工作根路径×2 |
| `04-执行过程/audit_confirmatory_assets.py` | R09 工作区仓库路径×1 |
| `04-执行过程/build_confirmatory_assets.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/build_public_bundle.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/build_worker_rootfs.py` | R08 沙箱家目录×1 |
| `04-执行过程/collect_confirmatory_v5.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/collect_confirmatory_v51.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/collect_confirmatory_v51_packed.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/current-token.txt` | R02 微软账号 SID×1、R03 机器标识 SID 段×2、R04 主机\本地账号×1、R05 主机名×1、R15 用户邮箱×1 |
| `04-执行过程/domain_gateway.py` | R08 沙箱家目录×1 |
| `04-执行过程/domain_worker.py` | R08 沙箱家目录×1 |
| `04-执行过程/e5-bootstrap-composed.yaml` | R06 本机 Windows 家目录×12、R13 临时 spill 目录×1 |
| `04-执行过程/existing-os-accounts.json` | R03 机器标识 SID 段×14、R23 裸账号名 token×1 |
| `04-执行过程/export_inspection.py` | R21 工具安装根路径×1、R22 连字符转义家目录×1 |
| `04-执行过程/finalize_when_sealed.ps1` | R06 本机 Windows 家目录×1、R11 E5 工作根路径×2、R17 内部评分身份×1 |
| `04-执行过程/fixture_gateway.py` | R08 沙箱家目录×1 |
| `04-执行过程/full-nonlive.junit.xml` | R05 主机名×1、R09 工作区仓库路径×1、R12 临时工作路径×4、R19 pytest 临时目录名×4 |
| `04-执行过程/full-nonlive.log` | R06 本机 Windows 家目录×1 |
| `04-执行过程/grant_harness_runtime_traversal.ps1` | R06 本机 Windows 家目录×4、R11 E5 工作根路径×1 |
| `04-执行过程/headless-default.yaml` | R13 临时 spill 目录×1 |
| `04-执行过程/historical-v3.md` | R08 沙箱家目录×1 |
| `04-执行过程/identity_probe.ps1` | R06 本机 Windows 家目录×1、R11 E5 工作根路径×2 |
| `04-执行过程/import_worker_as_identity.ps1` | R11 E5 工作根路径×3、R18 内部工人身份×2 |
| `04-执行过程/install-gate-host.prompt.txt` | R11 E5 工作根路径×1 |
| `04-执行过程/install-science.prompt.txt` | R11 E5 工作根路径×1 |
| `04-执行过程/install_science_as_identity.ps1` | R06 本机 Windows 家目录×1、R11 E5 工作根路径×1 |
| `04-执行过程/install_worker_scripts.ps1` | R11 E5 工作根路径×1、R18 内部工人身份×1 |
| `04-执行过程/install_worker_scripts_v2.ps1` | R11 E5 工作根路径×1、R18 内部工人身份×1 |
| `04-执行过程/os-acl-attempt3-before.json` | R03 机器标识 SID 段×2、R21 工具安装根路径×1 |
| `04-执行过程/os-provision-attempt3-result.json` | R03 机器标识 SID 段×7、R06 本机 Windows 家目录×1、R09 工作区仓库路径×1、R11 E5 工作根路径×1、R17 内部评分身份×1、R21 工具安装根路径×3 |
| `04-执行过程/os-provision-result.json` | R11 E5 工作根路径×2 |
| `04-执行过程/path-ledger.junit.xml` | R05 主机名×1、R09 工作区仓库路径×1、R12 临时工作路径×4、R19 pytest 临时目录名×4 |
| `04-执行过程/path-ledger.log` | R06 本机 Windows 家目录×1 |
| `04-执行过程/prepare_domain_plugin.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/prepare_v4.py` | R06 本机 Windows 家目录×2、R09 工作区仓库路径×1 |
| `04-执行过程/protocol-amendment.json` | R06 本机 Windows 家目录×1、R09 工作区仓库路径×1 |
| `04-执行过程/provision_e5_identity.ps1` | R06 本机 Windows 家目录×2、R09 工作区仓库路径×1、R11 E5 工作根路径×1、R17 内部评分身份×2、R21 工具安装根路径×3 |
| `04-执行过程/provision_e5_identity_attempt3.ps1` | R06 本机 Windows 家目录×2、R09 工作区仓库路径×1、R11 E5 工作根路径×1、R17 内部评分身份×2、R21 工具安装根路径×3 |
| `04-执行过程/public-bundle-candidate.json` | R11 E5 工作根路径×1 |
| `04-执行过程/qualify_scorer_v5.py` | R11 E5 工作根路径×2 |
| `04-执行过程/recapture_public.py` | R09 工作区仓库路径×1 |
| `04-执行过程/recover_confirmatory_v51_final_drain.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/render_final_report.py` | R11 E5 工作根路径×1 |
| `04-执行过程/report-before-delivery-clarification.md` | R05 主机名×1 |
| `04-执行过程/revalidate-gate-host.prompt.txt` | R11 E5 工作根路径×1 |
| `04-执行过程/run_harness_process.ps1` | R06 本机 Windows 家目录×2、R11 E5 工作根路径×2 |
| `04-执行过程/runtime-inspection.events.redacted-v2.jsonl` | R06 本机 Windows 家目录×2、R12 临时工作路径×1、R13 临时 spill 目录×1、R14 临时会话 id×1 |
| `04-执行过程/runtime-inspection.events.redacted.jsonl` | R06 本机 Windows 家目录×2、R12 临时工作路径×1、R13 临时 spill 目录×1、R14 临时会话 id×1 |
| `04-执行过程/runtime-inspection.projected.jsonl` | R06 本机 Windows 家目录×1 |
| `04-执行过程/science-canary-seal-verification.json` | R11 E5 工作根路径×1 |
| `04-执行过程/seal_science_canary.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/verify_and_finalize_delivery.py` | R06 本机 Windows 家目录×1、R11 E5 工作根路径×1 |
| `04-执行过程/verify_backend_local.py` | R09 工作区仓库路径×1、R11 E5 工作根路径×1 |
| `04-执行过程/worker-sandbox/output/proof.json` | R07 POSIX 家目录×3 |

归档内部改动 30883 条（前 40 条）：

- `E5_public_reproduction.zip::RECOMPUTED::evidence/artifact-hashes.json` — 重算 30872 个哈希字段
- `E5_public_reproduction.zip::evidence/SEALED-COMPLETE.json` — R11 E5 工作根路径×1
- `E5_public_reproduction.zip::evidence/cells/c0099badd5d9f731c3b2a2674/calls/6f7157e5f82a17817c90ebdfb9a580cf0cafb93b4ca46fbff146c9878a6d65fd/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c0099badd5d9f731c3b2a2674/calls/6f7157e5f82a17817c90ebdfb9a580cf0cafb93b4ca46fbff146c9878a6d65fd/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c0099badd5d9f731c3b2a2674/calls/6f7157e5f82a17817c90ebdfb9a580cf0cafb93b4ca46fbff146c9878a6d65fd/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0772285760587ad0dc7b4e5d18b2b6ddd20035f15f7656571b4dc5448b616299/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0772285760587ad0dc7b4e5d18b2b6ddd20035f15f7656571b4dc5448b616299/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0772285760587ad0dc7b4e5d18b2b6ddd20035f15f7656571b4dc5448b616299/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/082aa726beaae2bedae6f3c7fbb65feb0602a4d9548276f632e537f582fb6448/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/082aa726beaae2bedae6f3c7fbb65feb0602a4d9548276f632e537f582fb6448/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/082aa726beaae2bedae6f3c7fbb65feb0602a4d9548276f632e537f582fb6448/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0cd6c244daf5379a3deb8ce7f1bf8f26b88940dda552c9df9e93886c46cf32ef/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0cd6c244daf5379a3deb8ce7f1bf8f26b88940dda552c9df9e93886c46cf32ef/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/0cd6c244daf5379a3deb8ce7f1bf8f26b88940dda552c9df9e93886c46cf32ef/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/17234916344abc80edbc68f395fabc1e29b5c442c2baf690946f787c193fbac1/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/17234916344abc80edbc68f395fabc1e29b5c442c2baf690946f787c193fbac1/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/17234916344abc80edbc68f395fabc1e29b5c442c2baf690946f787c193fbac1/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/1c4b6896e0f65a679d21e88217be8a6b598a535a028feca22776e43b077b50bd/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/34a58ef51cc54564d9b969a245d52d2490dc9b26d0bcafbfade42081801a00e8/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/34a58ef51cc54564d9b969a245d52d2490dc9b26d0bcafbfade42081801a00e8/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/34a58ef51cc54564d9b969a245d52d2490dc9b26d0bcafbfade42081801a00e8/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/470dd1e64da5d45b1b77aab4a79383971c65ea36e58e19228362979c2871e747/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/470dd1e64da5d45b1b77aab4a79383971c65ea36e58e19228362979c2871e747/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/470dd1e64da5d45b1b77aab4a79383971c65ea36e58e19228362979c2871e747/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/63f6e07d4ccb4469642511f37506e4dd5d7d5f2ec4c657f799e697983ac69015/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/63f6e07d4ccb4469642511f37506e4dd5d7d5f2ec4c657f799e697983ac69015/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/63f6e07d4ccb4469642511f37506e4dd5d7d5f2ec4c657f799e697983ac69015/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/674cf6b8ecb9051cbde812287650fe9349a2c7054bbf404aa12de4af430174e7/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/674cf6b8ecb9051cbde812287650fe9349a2c7054bbf404aa12de4af430174e7/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/674cf6b8ecb9051cbde812287650fe9349a2c7054bbf404aa12de4af430174e7/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/6e7cbb8c541709f0ae9e3838901f40c86b43a15493980e163b0d8a58d8f43025/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/6e7cbb8c541709f0ae9e3838901f40c86b43a15493980e163b0d8a58d8f43025/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/6e7cbb8c541709f0ae9e3838901f40c86b43a15493980e163b0d8a58d8f43025/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7601f9f6c509da27d483b32f893a3f38f6e80def16bc10a331a78a3e1a545da5/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7601f9f6c509da27d483b32f893a3f38f6e80def16bc10a331a78a3e1a545da5/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7601f9f6c509da27d483b32f893a3f38f6e80def16bc10a331a78a3e1a545da5/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7eff9580ea9ff63cb7953459b48ac8536ce26db64be93d5f07884d44f441e796/exit-code.json` — R18 内部工人身份×1
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7eff9580ea9ff63cb7953459b48ac8536ce26db64be93d5f07884d44f441e796/receipt.json` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/7eff9580ea9ff63cb7953459b48ac8536ce26db64be93d5f07884d44f441e796/stdout.bin` — R08 沙箱家目录×2
- `E5_public_reproduction.zip::evidence/cells/c00b85e52358bbc560e56b6e8/calls/97ef158a4408606a7d2bd6223c0b59e9ad35dbdbe09645bc5c5ade7321615a89/exit-code.json` — R18 内部工人身份×1
- …其余 30843 条见 `_desensitize-report.json`

## E6_最小复现包

规则命中统计：R07 POSIX 家目录×4410、R16 学号邮箱×1607

| 文件 | 命中规则 |
|---|---|
| `03-E6-可复现性/01_当前R3补测/DELIVERY-MANIFEST.json` | R07 POSIX 家目录×9 |
| `03-E6-可复现性/01_当前R3补测/FINAL-RESULTS.json` | R07 POSIX 家目录×3 |
| `03-E6-可复现性/01_当前R3补测/INTEGRITY-AUDIT.json` | R07 POSIX 家目录×160 |
| `03-E6-可复现性/01_当前R3补测/OFFLINE-FINALIZATION.json` | R07 POSIX 家目录×1 |
| `03-E6-可复现性/01_当前R3补测/OFFLINE-FINALIZATION.log` | R07 POSIX 家目录×2 |
| `03-E6-可复现性/01_当前R3补测/PROTOCOL-AMENDMENT-R2-CANCELLATION.json` | R07 POSIX 家目录×1 |
| `03-E6-可复现性/01_当前R3补测/SUPPLEMENT-PROTOCOL.json` | R07 POSIX 家目录×2 |
| `03-E6-可复现性/01_当前R3补测/run_manifest.json` | R07 POSIX 家目录×1 |
| `03-E6-可复现性/02_原批次结果与原始归档/FINAL-DELIVERY.json` | R07 POSIX 家目录×12 |
| `03-E6-可复现性/02_原批次结果与原始归档/canary-exact-rows-audit.json` | R07 POSIX 家目录×3 |
| `03-E6-可复现性/02_原批次结果与原始归档/delivery-audits.json` | R07 POSIX 家目录×411 |
| `03-E6-可复现性/02_原批次结果与原始归档/run_manifest.json` | R07 POSIX 家目录×1 |
| `03-E6-可复现性/02_原批次结果与原始归档/summary.json` | R07 POSIX 家目录×5 |
| `03-E6-可复现性/02_原批次结果与原始归档/wire-semantics-audits.json` | R07 POSIX 家目录×31 |

归档内部改动 965 条（前 40 条）：

- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/COLLECTION.log` — R07 POSIX 家目录×5
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/LATEST-REPORT.json` — R07 POSIX 家目录×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/OFFLINE-FINALIZATION.json` — R07 POSIX 家目录×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/OFFLINE-FINALIZATION.log` — R07 POSIX 家目录×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/ORIGINAL-INVENTORY.json` — R07 POSIX 家目录×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/SNAPSHOT-SOURCE-PATH-MAP.json` — R07 POSIX 家目录×94
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/SUPPLEMENT-PROTOCOL.json` — R07 POSIX 家目录×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/WORKSTATE.json` — R07 POSIX 家目录×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/delivery-audits/1791710960766467000/audit.json` — R07 POSIX 家目录×160
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/frozen/materials/references/photometric-systems.md` — R16 学号邮箱×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/frozen/system-prompt.txt` — R16 学号邮箱×1
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-01/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-01/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-01/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-01/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-01/repeat-5/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-02/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-02/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-02/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-02/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-02/repeat-5/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-03/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-03/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-03/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×3
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-03/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-03/repeat-5/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-04/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-04/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×3
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-04/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-04/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-04/repeat-5/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-05/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-05/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-05/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-05/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-05/repeat-5/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-06/repeat-1/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-06/repeat-2/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-06/repeat-3/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- `E6-R3-supplement-20261011-1791689271010679000-原始证据.zip::E6-R3-supplement-20261011-1791689271010679000/lanes/R3/REPRO-06/repeat-4/attempt-1.jsonl` — R07 POSIX 家目录×1、R16 学号邮箱×2
- …其余 925 条见 `_desensitize-report.json`
