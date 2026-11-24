# E5 采集表旧代际归档 (2026-10-10)

## 为什么有这个目录

E5 的 live 采集表是**承重实验输入**（`--require-live` 全靠它），但它原先放在 `temp/` ——
一个按设计会被定期「知识沉底」清扫的目录。2026-10-10 02:39 的合规沉底（提交 `1940efa`）
把 `temp/capture_live.json`（460 827 B，sha256 `543560b0860e4908…`）与
`temp/capture_b3_indep.json`（473 970 B，sha256 `403ce92da63d0d0d…`）**只留指纹、不留字节**地清掉了。
`temp/` 在 `.gitignore` 内，git 侧无副本。

为避免同类事故重演，这里把**只在 git 悬空对象里存活**的采集表旧代际固化下来。

## 这两个文件是什么

| 文件 | 字节 | sha256(前16) | 装配 | 来源 |
|---|---:|---|---|---|
| `capture-b3-prose-rebuild-0352.json` | 57 993 | `e87f77fa05f9b193` | B3 | `b3-prose-rebuild-independent-sessions`，`captured_at 2026-10-10T03:52:18+0900` |
| `capture-6systems-0924.json` | 307 574 | `6e1940f1f27331ef` | B0/B1/B2a/B2b/B3/A1 | `all-systems-prose-rebuild-independent-sessions`，`captured_at 2026-10-10T09:24:04+0900` |

两者都是**两段式独立采集流水线**的产物（ScriptedLLM 确定性规划 → 冻结快照真跑观测 → 独立子会话写表述），
`model_kind=subagent`、`same_family_bias=true`，`claim_scope` 仅限「决策形态变了」，**不得**用于声称任何模型的能力或性能。

**当前在用**的那一份不在这里，它在被跟踪路径 `evals/ablation/captures/all-systems-rebuild.json`（8 装配 / 211 对）。

## 怎么找到它们的（可复用）

这两个版本从未被提交，只是因为跑批流程会 `git add -A`，旧版本在重新写入后变成**悬空 blob**：

```bash
git fsck --no-progress --unreachable --dangling          # 列出悬空对象
git cat-file -p <blob-sha> > recovered.json              # 取出
```

批量按内容定位采集表（比按文件名可靠）：

```bash
# 列出所有 blob 里同时含 "schema_version" 与 "decisions" 的候选
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype) %(objectsize)'
# 再对候选逐个 git cat-file -p 做内容匹配
```

注意：`git gc` 之后悬空对象会被清除 —— 想留就必须像本目录这样落到被跟踪路径。
