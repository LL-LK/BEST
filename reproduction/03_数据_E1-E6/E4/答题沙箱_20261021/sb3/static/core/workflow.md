1. **INTAKE** — BestQuery() **无参构造**（约束经链式 `.catalog()/.cone()/…` 挂载,
   不是构造参数); 凭据由 `BestAuth.login(username, password)`
   显式传入 (**代码里没有"从 env 直读 token"的认证路径**; `BEST_API_TOKEN` 仅是
   `src/scripts/config.py` env_map 里覆盖 `api_token` 配置项用的键, 不是凭据来源)。
1b. **CONFIRM**（动手前，R1 2026-10-22 新增）— 请求缺**关键参数**时先回问一句，再进 VALIDATE:
   半径单位 / 目标星表该取哪张（含标准星表选哪张）/ 批量匹配的批次策略。
   **不得静默采用接口签名里的默认值替用户决定语义**；确认态记为 `handoff.status =
   needs_clarification`，不是 `blocked`。
   "关键"的判据: 该参数取不同值会让返回结果的**语义**不同，而不只是行数多少。
2. **VALIDATE** — ADQL/SQL 语法 (validate_adql_query) + 速率窗口。
3. **EXECUTE** — 两阶段查询 (POST→sqlid→GET 分页) → 流式下载 + 批量匹配隔离。
4. **GATE** — http/checksum 双门槛判定。
5. **EMIT** — BestResultSet(data/status) 原子落盘 + 查询审计。

客户端口径: 唯一生产客户端是 `src.client.BestClient` (两阶段 REST) —
          P1 合并后 pybest 单类门面已删除, 脚本式行字典消费改走
          `BestClient.query` (裸投影) 或 `BestDownloader`;
          回归底线是 `python -m pytest test -q` 0 failed。
