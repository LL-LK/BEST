# fallback-protocols.md — astro-best 优雅降级与备用源协议 (Phase 3-A)

原则: 降级必须留痕 (WARN + `status` 字段), 门禁 (http_status==200, checksum_match==true) 不因降级放松。

> 2026-09-29 严谨性审计修正: 本文早期的 `status` 字符串 (`query_failed`/
> `not_configured`/`auth_failed`/`rate_limited`/`checksum_mismatch`) 在 src/ 中
> **均无产出方** — 它们是协议文档侧的约定名, 不是运行期真实状态。以下各条已按
> 代码实况改写; 约定名仅在与外部契约对齐时使用, 引用前先 grep 确认产出方存在。

## FB-1 网络不可达 / DNS 失败

- CLI/库全部请求前不做网络假设; `requests.ConnectionError` 等网络异常 →
  查询路径返回 `BestQueryResult(success=False, error=…, error_code=…)`
  或异常上抛 (下载栈由 DownloadManager 置任务 failed 并记 error) —
  离线单测一律走 fixtures ([已净化]cases 缓存响应)。
- 不伪造 BestResultSet; 空数据与失败严格区分。

## FB-2 认证失败 / 凭据缺失

- 登录凭据面 (SA-P2-4 回正): CLI 交互入口是 `--auth-user` 参数 + `ASTRO_BEST_PASSWORD`
  环境变量 (src/__main__.py, E10 后明文 `--auth-pass` 已移除); 用户名有而口令缺失时
  打印 stderr Warning (只含变量名, 不打日志明文) 后**按匿名继续**
  (auth=None)。历史 env `BEST_API_USER`/`BEST_API_PASS` 已退役: 无消费方, 已从
  .env.example 移除。**没有 TAP Bearer 环境变量通道**: 网关侧 Bearer 由调用方**注入的
  `token_validator` 回调**校验 (src/tap/service.py; 未注入回调则任何 token 一律 401),
  `src/tap/` 零读 env 凭据 (只有 BEST_TAP_URL 端点与 BEST_TAP_* 配额调参)。
  `BEST_API_TOKEN` 无此通道 —— 它只覆盖 `AstroBestConfig.api_token` 这一个配置字段,
  BEST 数据面不拿它做 Bearer、不加请求头。REST 侧能否直接吃 NADC Bearer 仍是
  **未验证**项 (contracts/oauth.contract.yaml 的 `best_api_bearer_token: status: unverified`)。
- 登录失败判定不看状态码 (成功/失败都可能回 200), 看最终 URL 是否仍含
  "login" (src/auth/session.py); `BestAuth.login` 返回 False 且**不重试**
  (单次尝试), 调用方决定是否降级匿名 — 匿名可查的星表不因登录失败整体不可用。

## FB-3 限流 (HTTP 429) / 5xx

- 指数退避由 urllib3 `Retry` 单层兑现: 基数取协议常量 `RETRY_BACKOFF_S`
  (2.0 s), `max_retries=3`, 状态集 `RETRY_STATUS_CODES={429,500,502,503,504}`,
  `respect_retry_after_header=True` (Retry-After 由 urllib3 层尊重, 不自写第二层)。
- 下载栈的网络失败另走 `download_hooks.run_network`: 同类重试耗尽后抛
  `HookBlockedError` (`network_exhausted`) → 任务 blocked 待 ask。
  (退避基数与礼貌限速 rate_limit 是两个独立常量, 数值巧合相同, 不要互相推导。)
- 打包云侧批量改约窗口; 绝不让 CLI 进程内部大循环高频重试。

## FB-4 内容漂移 / 解析失败

- 取数路径的门控是**状态码 + 软错误体** (200 + `{"error":…}` 判失败),
  不校验 Content-Type; 响应体判定见 `src/protocol.py: is_soft_error`。
- `csv_safety` 消毒时检测到公式注入 (以 = + - @ 开头的单元格) → 该字段转义为文本
  (纯数字含负数透传, 不误伤)。

## FB-5 完整性失败 (checksum mismatch)

现行行为 (与早期文档宣称的多步协议不同, 如实记账):

- **两个同名不同物, 别混**:
  ① `checksum_match` —— **门禁字段**, 落盘时取 `写前意图摘要 == 写后读回摘要`
     (`digests_match`, 恒定时间比较) 的**真布尔**。**无期望值也照样求值**,
     所以 `checksum_match==True` 这条 blocking 门禁在生产中**可达** (A3-05 修的是
     "此前恒写 unknown 导致该门禁永不可满足")。实现: `src/downloader.py::_save_result`
     与 `src/download_artifacts.py`; 消费侧 `gates_passed()` 要求它 `is True`。
  ② `verify_checksum(expected_sha256)` —— **外部基准核对**, 站点不提供摘要,
     生产链路 (region/sqlid/download) **无一传入期望值**, 故这条路径零触发。
- 字节级单文件路径只有大小回核 (Range 续传的 .part 拼装后), 不符返回 None →
  上层 RuntimeError → 任务 failed; 查询落盘路径若未来接入期望值, mismatch 语义是
  立即 raise ValueError (无重试、无删半成品)。
- `SEVERE_CHECKSUM` hook 模板已定义但生产零触发 (未接线); "删半成品→重试 1 次→
  checksum_mismatch+failed" 是目标协议, 当前未实现。
- 半成品绝不进入下游 (astro-catalog/astro-clean) 的纪律对 failed 任务成立。

## FB-6 下游委派回退

- 需要交叉匹配而 BEST 返回缺失星表时: 不在本地拼凑匹配 → 建议 astro-catalog
  (本地星表几何) 或 astro-clean (清洗); 明确"本 skill 只交付采集结果"。
