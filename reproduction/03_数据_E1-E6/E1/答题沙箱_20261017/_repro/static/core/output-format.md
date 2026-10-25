# output-format.md — 输出格式规范 (与 contracts/output.contract.yaml 对齐)

```yaml
best_result:                     # 逐字形状 = src.models.BestResultSet.to_dict() 实跑输出
  data: {...}                    # 结果载荷 (自由结构, 契约要求恒为映射; 缺省 {})
  status: "ready"                # 取值域以 handoff.status 为准: ready | needs_review | blocked (没有 "ok")
  handoff:                       # 缺省从 manifest.yaml 的 redirects 表派生 (G3), 读不到则降级为空清单
    status: "ready"              # 默认随 status 同步; 显式传入 handoff 时以传入的为准
    next_skills: ["astro-catalog", "astro-clean"]
  gates:                         # 两条阻断性门禁收在此段, **不在**顶层
    http_status: 200             # count (门禁 ==200); 缺省 null = 未知 -> 判否
    checksum_match: true         # bool (门禁); 缺省 false = 未校验 -> 判否
```

> **缺省态 fail-closed**: 未回填门禁字段时 `gates` = `{http_status: null, checksum_match: false}`,
> `gates_passed()` 返回 `False`。恒真的门禁等于没有门禁, 缺省一律取"不通过"那一侧。
> **这里没有** `rows_returned`、没有顶层 `provenance`、也没有 `status: "ok"` —— 三者都是旧文档虚构的。
> `sources` / `returned_count` / `total_count` 属 `BestQueryResult` (查询层), **不在** `BestResultSet` 里。
> `source_id` 是星表原始 ID 字符串 (ps1 实测 19 位整数串, 如 `2449913804508125824`), 不是 `BEST001` 这类占位符。
> **接线状态**: `manifest.yaml` 的 `result_json` sink 以 `data/status` 指名本信封, `contracts/output.contract.yaml`
> 以 `BestResultSet` 为 schema (契约 SSOT); 但本类在 `src/` 内**零生产构造点** (仅 `test/unit/models/` 两处用例构造),
> 属"按契约声明保留、尚未接线"。逐字形状以实跑 `to_dict()` 为准, 不以本文件示例为准。

## 硬规则

1. 量纲必须随字段走 (每个数值一个单位注释);
2. needs_review 时字段保留 (只增不减), 必附原因码;
3. 禁 wall-clock 值进数值字段; 时间一律 UTC ISO8601。
