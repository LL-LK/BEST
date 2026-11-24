# docs/archive/ — 归档实体的退役登记（2026-10-08）

## 一句话

**归档 zip 实体已从版本库移除，只留清单。** 这是用户裁定的直接结果。

## 用户裁定（两条，合起来才是完整口径）

1. 「将隐私内容取消 git 推送，只推送带占位符和注释的版本」；
2. 清除已推归档时「**不授权重写历史**，只删当前分支上的文件」。

## 退役了什么

| 已移除的实体 | 清单（留在版本库） | 原内容 |
|---|---|---|
| `audit-2026-10-06-v1.zip` | `audit-2026-10-06-v1.MANIFEST.md` | 第 1 轮审计的问题文档与探针 |
| `audit-2026-10-07-v2.zip` | `audit-2026-10-07-v2.MANIFEST.md` | 第 2 轮审计的问题文档与探针 |
| `temp-artifacts-2026-10-07.zip` | `temp-artifacts-2026-10-07.MANIFEST.md` | temp/ 结论性产物（6334 文件） |
| `replay-backup/replay-assets-pre-retirement-2026-10-07.zip` | `replay-backup/MANIFEST.md` | 回放层退役前的完整备份（314 文件） |
| `temp-bulk/temp-bulk-01..13.zip` | `temp-bulk/MANIFEST-01..13.md` | temp/ 全量残留（68454 文件） |

清单里是逐文件 **sha256（占位符）** + 包内相对路径 + 隐私标注：收信人能核对
「当时这一批里有什么」，拿不到任何文件字节。

## 为什么必须退役（新门禁查出的实测数字）

新增门禁 `verify_archive_privacy`（N11）实测前 4 个包：

- 本机用户名 **63 处**、真实绝对路径 **4237 处**、邮箱 **93 处**、**1 个 PEM 私钥块**、
  口令赋值 75 处（多数为单测夹具假口令，已逐类核实）。

而这些包入库时报告的是「隐私两轮扫描全净」。**那个结论是错的。**

根因与本轮反复出现的是同一个：**扫描判据比要抹的东西窄**。
打包器自带的复验只认 `(Users|dev|home)`，本仓父目录（形如 `<ABSPATH>`）三条全不命中；
于是「扫一遍没命中」报了假绿。判据比规则窄 = 拿自己的盲区给自己作证。

## 代价（必须说清）

用户裁定**不授权重写历史**，故：

- 实体 zip 已从**工作区与后续提交**中删除；
- 但**旧提交里的 blob 仍在 git 对象库中**，已 clone 过的人仍能取到
  （`git show <sha>:<path>`）。

彻底清除需要 force-push 重写历史 + 配合 GitHub 支持删缓存。这是有意接受的代价，
不是疏漏。

## 门禁的两处演进

1. **新增 N11 `verify_archive_privacy`**：独立隐私复验，**不从打包器 import 任何符号**
   —— 同源时尺子坏了没人知道。它复验归档 zip **与**归档清单两类载体。
2. **N11 的负对照从「无 zip 即红」改为「无 zip 且无清单才红」**：实体退役后
   `docs/archive/` 下确实一个 zip 都不剩，那是政策达成的状态却撞上了负对照。
   修法不是删负对照（删了就成了"为了绿而改判据"），而是**扩大扫描面**到清单 ——
   实体没了，清单就是留在版本库里的隐私载体，必须被扫。本门禁因此比原来更严。

`test/unit/meta/test_gate_count_drift.py` 已把门禁数归一为 **12**（`CLAUDE.md` /
`README.md` / `run_all_gates.py::HARD_GATES` 三处同步）。

## 重来的话

脚本在 `temp/vfy/nc_test/`（gitignored，本机留存）：

- `extract_archive_manifests.py` —— 为归档包抽清单并独立复验
- `pack_bulk2.py` / `check_sanitize.py` —— temp/ 全量分批与脱敏正反对照
- `extract_manifests.py` / `scan_before_commit.py` —— 清单抽取与入库前独立闸
- `check_archive_privacy_gate.py` —— N11 门禁的变异体验证（清单侧有牙 + 负对照未失效）
- `dryrun_pack_bulk2.py` —— 写盘路径干跑
