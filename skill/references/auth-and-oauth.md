# auth-and-oauth.md — BEST 双轨鉴权与「上鉴权」准备（智能体使用向）

> 本文回答两个问题：**skill 现在怎么鉴权**、**站点全面开启鉴权时 skill 缺什么**。
> 内容凝练自 `temp/oauth_deep_dive_2026-09-27.md`（逐条实跑取证）+ `src/auth/` 实现
> + `contracts/oauth.contract.yaml` 契约 + 2026-09-29 端点复核。
> 站点侧的登录态边界（哪些路由要登录）见 `site-endpoints-and-interactions.md` §5。

## 0. 一分钟结论

- **OAuth 是"身份层"，不是"数据通道"**：它不在查询主链上。未获批只损失 2 项能力
  （`provenance.identity` 块、依赖登录态的作业流），查询/匹配/下载/工具面全部
  匿名可用（已实证）。
- **`/jobs` 打不开的第一关是"没有 BEST 站点账号"**（数据轨），与本 skill 的
  OAuth 审批**无关**——OAuth 是站点登录页里的第二跳（见 §4）。
- 本 skill 是**双轨制**：数据轨 = BEST 站点 Django 会话（`BestAuth`）；
  身份轨 = NADC 通行证 OAuth2.0（`src/auth/nadc_oauth.py`）。两轨凭据不同、互不替代。

## 1. 双轨制总表

| 轨 | 实现 | 凭据（只走 env/交互，代码零字面量） | 作用 | 现状 |
|---|---|---|---|---|
| 数据轨 | `src/auth/session.py::BestAuth`（Django session + CSRF） | CLI `--auth-user` + env `ASTRO_BEST_PASSWORD`（或 getpass） | BEST 站点会话 cookie，查受保护路由（当前只有 `/jobs`） | 匿名查询已实证可用；未配置凭据时自动走匿名 |
| 身份轨 | `src/auth/nadc_oauth.py`（Authorization Code） | env `NADC_OAUTH_CLIENT_ID` / `NADC_OAUTH_CLIENT_SECRET` / `NADC_OAUTH_REDIRECT_URI` | 拿 NADC 身份（umtId/ldap_id/name/email）写信封 `provenance.identity` | **未获批 → 实网路径 blocked-on-approval**；46 个 mock 用例 + 9 个落盘保护用例覆盖代码形态 |

历史 env `BEST_API_USER`/`BEST_API_PASS` **已退役**（无任何消费方，`.env.example` 明示）；
当前真实凭据面是 `--auth-user` + `ASTRO_BEST_PASSWORD`（`src/__main__.py`，E10：口令
不走 argv，避免进 shell history / ps 输出）。

## 2. 数据轨：BestAuth（Django session + CSRF）

登录协议两步（`src/auth/session.py::login`）：

1. `GET {BEST_BASE_URL}/user/login` —— 从页面提取 `csrf_token="..."`（Django 把 token
   写在页面里），写入 session 的 `X-CSRFToken` 头；
2. `POST /user/login`（`username`/`password`/`csrf_token`/`next=BEST_BASE_URL`，
   带 `Referer` 头 —— Django CSRF 中间件校验项）。

**认证判定不看状态码**（成功/失败都可能回 200），只看最终 URL 是否还停在 login 页。
登录后页面可能轮换 CSRF，会再取一次。

关键契约：

- **登录失败返回 False，不抛异常** —— 匿名可查的星表不应因登录失败而整体不可用，
  由调用方决定是否降级；
- 会话材料经 `export_session()` **显式移交**给 `BestClient`（cookie + CSRF 头），
  不跨模块读私有属性；多个 `BestClient` 可共享同一 `BestAuth`；
- `close()`/`__enter__`/`__exit__` 已接线（长生命进程防 socket 泄漏）。

CLI 入口：`python -m src --auth-user <name> cone ...`（口令走 env 或 getpass）。

## 3. 身份轨：NADC 通行证 OAuth2.0（Authorization Code，无 PKCE）

契约权威：`contracts/oauth.contract.yaml`（协议来源
`oauth.china-vo.org/static/guide/passport.html`，2025-01-13，仅 Authorization Code 模式）。

**三个本地闸门**（缺凭据即在本地抛错、根本不发请求）：

| 闸门 | 位置 | 触发条件 |
|---|---|---|
| ① 授权 URL 构造 | `nadc_oauth.py` `build_authorize_url` | `client_id` 空 → `NadcOAuthError` |
| ② 令牌交换 | `nadc_oauth.py` `exchange_code` | `client_id`/`client_secret` 任一为空 |
| ③ profile 拉取 | `nadc_oauth.py` `get_profile` | 无 access_token（②的下游） |

实跑（凭据未设时）：`oauth status` → `{"authorized": false, ...}` rc=0；
`oauth url` / `oauth paste` → rc=1 带明确缺失提示。

**CLI 交互模式**（`ops/astro_best_cli.py oauth`）：`url`（无头，只拼 URL 自己开浏览器）、
`login`（本地回环 127.0.0.1:8765 自动收 code）、`paste`（手动粘回调 URL 或裸 code 兜底）、
`token`（无头管道面：打印可用 access_token，过期即 rc=1 带恢复命令）、
`status`（三态 `valid`/`expired`/`missing` + 恢复 hint）。
成功后 token 落 `~/.astro-best/nadc_token.json`（提前 60s 判过期）。

**已知边界（坑）**：

- **官方无 refresh_token**：token 典型 3600 s 过期，过期只能重走授权流 —— 长跑任务
  要预留重新授权中断点（恢复路径已接线，见 §5.5：`ensure_access_token`）；
- **Windows 静态保护已补 DPAPI**（2026-09-30）：`os.chmod(..., 0o600)` 在 Windows 上
  不设 ACL（只兑现只读标志，st_mode 恒 0o666），token 文件改走 **v2 信封 + DPAPI
  密文**（crypt32 `CryptProtectData`，CURRENT_USER 范围）——同机其他用户、换账号、
  整机外带都解不出；POSIX 仍 0600。残余边界：DPAPI 只防"文件离开本账号"，**同账号
  下的恶意进程仍可解**（那已等于本机失守）；v1 裸 JSON 旧缓存兼容读取、下次 save
  自动升级；DPAPI 调用失败时告警回退明文信封（可用性优先，风险留痕）；
- **V-6 未验证**：即使拿到 token，也不确定能拿它去调 BEST REST
  （`best_api_bearer_token: unverified`）—— 验证前不要把 OAuth 当成"能解锁更多数据"
  的钥匙来规划；
- **不能拿站点自己的 appid 顶替**：站点 OAuth 应用 `client_id=TfiNrZZBgQRVjxDd59FV9L4B`
  在跳转 URL 里可见，但 secret 不公开，且那是站点的应用不是本 skill 的应用 —— 复用
  既走不通（缺 secret）也是越权行为，不做。

## 4. `/jobs` 链路与站点账号

实测链（2026-09-27）：`GET /data/best/jobs` → **308** → `/jobs/` → **302** →
`/user/login?next=%2Fdata%2Fbest%2Fjobs%2F`（meta-refresh + JS 双跳
`oauth.china-vo.org/user/login?appid=TfiNrZZBgQRVjxDd59FV9L4B&redirect_uri=…/user/oauth2/login/nadc`）。

即：**`/jobs` 卡的第一关是"没有 BEST 站点账号"**（数据轨），不完全卡在 OAuth（身份轨）。
站点自身 OAuth 应用的完整授权链（client_id/redirect_uri=`/user/oauth2/callback/nadc`/scope=profile/state）
见 `site-endpoints-and-interactions.md` §5。

## 5. 「上鉴权」准备清单（站点开启鉴权时按序核对）

站点演进方向未知时，按以下顺序准备（每项标注了当前状态）：

1. **确认受保护面扩大范围**：当前只有 `/jobs` 要登录；若查询/分页/计数/解算转登录，
   数据轨 `BestAuth` 已覆盖（Django session + CSRF 是站点自己的机制），需补的是
   **每路由的会话保持验证**（匿名 302 的 route 逐一过一遍已登录会话）。
   *状态：阻塞中——需站点账号才能实测（见 §4）。*
2. **凭据面就绪**：`--auth-user` + `ASTRO_BEST_PASSWORD`（或 getpass）已接线；
   确认部署环境能注入 env（CI/守护进程场景优先 env，不用交互）。
   *状态：✅ 已完成。*
3. **OAuth 获批后三步**：向 support@china-vo.org 申请 NADC 应用 → 写 `.env`
   （`NADC_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` 三键由 `src/auth/nadc_oauth.py`
   直接读 env，**不在** `src/scripts/config.py` 的 Q-16 env_map 内——那个映射只覆盖
   `BEST_*` 十键）→ 跑 `oauth url` / `oauth login` / `oauth paste` 任一模，
   token 落缓存。*状态：阻塞中——未获批。*
4. **补 V-6 实网验证**：拿 Bearer token 打 BEST REST，把契约里的 `unverified` 转成
   结论；同时补一个 `test/live/` OAuth 用例（当前 live 三个文件只测 BEST API/下载）。
   *状态：阻塞中——依赖第 3 项获批。*
5. **长跑任务重新授权点**（过期 → 重走授权 → 续传）：**✅ 已接线（2026-09-30）**。
   `src/auth/nadc_oauth.py::ensure_access_token(store, reauth)` 是唯一恢复单点：
   有未过期 token 直通；过期时调用方注入 `reauth` 回调（典型是 `oauth login`/
   `paste` 流的薄包装）即自动重走授权并落缓存；无交互通道（批处理/CI/无头进程）
   则抛 `TokenExpiredError`（消息带 `python ops/astro_best_cli.py oauth login` 恢复命令），
   rc=1 —— **不把过期令牌当有效身份返回**。CLI 面对应 `oauth token`（管道取 token）
   与 `oauth status` 三态（`valid`/`expired`/`missing` + hint）。
   *剩余：`provenance.identity_from_token_store` 保持"未授权整块省略"的降级语义
   （匿名可查场景的正确行为，见 §6），需要"保证有身份"的长跑调用方应改走
   `ensure_access_token` —— 当前无此类生产调用方（OAuth 未获批），属预期空缺。*
6. **Windows token 权限**：**✅ 已接线（2026-09-30）**。缓存文件改 v2 信封 +
   DPAPI 密文（CURRENT_USER 范围），POSIX 仍 0600；v1 旧缓存兼容读取、save 自动升级。
   残余风险见 §3：DPAPI 不防同账号恶意进程；DPAPI 调用失败会告警回退明文信封。
7. **回归基线**：`test/unit/auth/` 46 个 mock 用例（全 mock 零网络零凭据）+
   `test/unit/scripts/test_nadc_oauth_permissions.py` 9 个落盘保护用例
   （含 Windows 实机 DPAPI round-trip / 篡改拒解密）+ evals 契约文本审计
   （端点表完整 + `NADC_OAUTH_CLIENT_ID/SECRET` 出现 + Bearer 空格规范）。
   获批后把这些升级为"至少一条 live smoke"。

## 6. 失败语义（调用方契约）

- 登录失败：`BestAuth.login` 返回 False（不抛异常），客户端按匿名继续；
- token 过期/缺失且需保证身份：`ensure_access_token` 抛 `TokenExpiredError`
  （`NadcOAuthError` 子类，消息带恢复命令）—— 无头调用方 rc=1 重登，有交互通道的
  调用方注入 `reauth` 自动续期；**没有任何路径会把过期令牌当有效身份返回**；
- HTTP 4xx/5xx：`BestClient` 显式失败（`raise_for_status` + 软错误体判定；P0-2 修复后 401/403/404 不再
  静默读成"无数据"）—— **401 token 过期被读成"天上没有源"的事故形态已消除**；
- `provenance.identity` 未授权时**整块省略**，不落空块 —— 这是预期行为，不是 bug
  （降级语义；要"保证有身份"请走 `ensure_access_token`，两者分工见 §5.5）；
- `evals` 只审计契约文本形态，不碰协议真身 —— "绿"只证明代码形态正确。

## 7. 证据锚点

| 内容 | 位置 |
|---|---|
| OAuth 逐条深挖（三闸门实跑输出/影响面/V-6/解除路径） | `temp/oauth_deep_dive_2026-09-27.md` |
| OAuth 契约（端点/凭据/生命周期/scope 边界/失败模式） | `contracts/oauth.contract.yaml` |
| 实现 | `src/auth/session.py`、`src/auth/nadc_oauth.py`（`ensure_access_token`/`TokenExpiredError`/DPAPI 静态保护） |
| 测试 | `test/unit/auth/`（46 mock）、`test/unit/scripts/test_nadc_oauth_permissions.py`（9 落盘保护，含 Windows 实机 DPAPI）、`test/live/`（无 OAuth live 用例） |
| 站点登录态边界 | `references/site-endpoints-and-interactions.md` §5/§9 |
| 算法白盒 | `references/ALGORITHM-SPEC.md` §4 |
