"""src.auth — NADC 通行证 OAuth2.0 身份层 (Phase 6) 的公开门面。

职责: 身份层的**唯一**对外入口。全部实现在 :mod:`src.auth.nadc_oauth`, 本模块
只做再导出: 调用方一律 ``from src.auth import X``, 不允许直接引用
``src.auth.nadc_oauth`` 的路径 —— 否则换实现文件就要改遍调用点。

所属子系统: 位于 src/ 的身份子层。上游是需要带凭证访问 NADC 的脚本与
TAP 客户端 (``src/tap/client.py`` 用它换网关 API key); 下游是唯一的实现模块
``src.auth.nadc_oauth``。它自己不读配置、不发网络, 只做符号转发。

对外接口 (16 个符号, 全部是外部可依赖的 seam):
- 端点与环境变量名: ``OAUTH_BASE_URL`` / ``ENV_CLIENT_ID`` / ``ENV_CLIENT_SECRET`` /
  ``ENV_REDIRECT_URI`` / ``DEFAULT_TOKEN_CACHE`` —— 供部署方与测试对齐口径。
- ``NadcOAuthError`` / ``TokenExpiredError``: 异常契约, 调用方靠它们区分
  "可重试的过期" 与 "不可重试的授权失败"。
- ``TokenStore``: 令牌持久化后端。
- ``OAuthProfile``: 授权成功后解析出的用户身份。
- ``build_authorize_url`` / ``build_logout_url`` / ``exchange_code``: 授权三步的
  纯函数部件, 可脱离交互单独单测。
- ``run_local_callback_flow`` / ``run_manual_paste_flow``: 两种交互式授权流程
  (本地回调 / 手工粘贴), 二者产出同一份令牌, 供无浏览器的环境切换。
- ``ensure_access_token``: 过期恢复单点 —— 长跑任务的"检测过期 → 重走授权 →
  续用"收敛处, 无交互通道时抛带命令的错。

依赖与数据流: 唯一依赖 ``from src.auth.nadc_oauth import ...``。凭证经环境变量
进、经 ``TokenStore`` 落盘 (默认 ``DEFAULT_TOKEN_CACHE``); 授权码交换是**跨进程
的 HTTPS 往返** (NADC 授权服务器), 其余全部进程内内存。

关键契约与不变量:
- ``__all__`` 必须与再导出的符号严格一致: 少列会让 ``import *`` 静默丢能力。
- 再导出层**不得**加包装: 任何 try/except 或签名改写都会让
  ``src.auth`` 与 ``src.auth.nadc_oauth`` 的错误语义分叉, 而调用方的 except
  分支是按实现层的异常类型写的。

陷阱与边界: 客户端密钥只在环境变量里, 因此本层任何异常消息都不得回显 secret
或完整 token (实现层已做脱敏, 这里不要新增日志)。另外, ``ensure_access_token``
在无交互通道时会抛错而不是返回 None, 这是刻意的"禁 fail-open": 静默返回
匿名身份会让请求以错误的权限级别打到上游。
"""
# 本地: 从唯一实现模块再导出身份层公开面 (调用方只依赖 src.auth 门面)。
# 逐项说明写在 import 块**上方**而不是每行行尾: 多行 import 括号内的行尾注释
# 会让 isort 无法格式化整个块, 直接触发 ruff I001。
#   DEFAULT_TOKEN_CACHE  令牌落盘默认路径: 无环境变量时用它, 部署方按此对齐
#   ENV_CLIENT_ID        客户端 id 的环境变量名, 凭证只从环境进
#   ENV_CLIENT_SECRET    客户端密钥的环境变量名; 任何日志都不得回显其值
#   ENV_REDIRECT_URI     回调地址的环境变量名, 须在 NADC 后台白名单内
#   OAUTH_BASE_URL       NADC 授权服务器基址: 全部授权请求的 URL 根
#   NadcOAuthError       授权失败基类: 不可重试, 调用方据此终止
#   OAuthProfile         授权成功后解析出的用户身份 (get_profile 返回)
#   TokenExpiredError    令牌过期的子类: 与上条分开, 调用方按"可重试"处理
#   TokenStore           令牌持久化后端: 长跑任务跨进程复用靠它
#   build_authorize_url  授权第一步: 纯拼 URL, 无 IO, 可单独单测
#   build_logout_url     登出 URL 拼装: 换账号时用, 同样不触网
#   ensure_access_token  过期恢复单点 (2026-09-30): 过期→重走授权→续用;
#                       无交互通道则抛错而不是退化成匿名身份
#   exchange_code        授权第二步: 授权码换 token (跨进程 HTTPS 往返)
#   get_profile          拿 access token 换取用户 profile
#   run_local_callback_flow  交互式授权: 本地起回调端口收 code
#   run_manual_paste_flow     交互式授权: 手工粘贴 code, 供无浏览器环境
from src.auth.nadc_oauth import (
    DEFAULT_TOKEN_CACHE,  # 令牌落盘默认路径: 无环境变量时用它
    ENV_CLIENT_ID,  # 客户端 id 的环境变量名: 凭证只从环境进
    ENV_CLIENT_SECRET,  # 客户端密钥的环境变量名: 任何日志都不得回显其值
    ENV_REDIRECT_URI,  # 回调地址的环境变量名: 须在后台白名单内
    OAUTH_BASE_URL,  # 授权服务器基址: 全部授权请求的 URL 根
    NadcOAuthError,  # 授权失败基类: 不可重试, 调用方据此终止
    OAuthProfile,  # 授权成功后解析出的用户身份
    TokenExpiredError,  # 令牌过期的子类: 与授权失败分开, 按可重试处理
    TokenStore,  # 令牌持久化后端: 长跑任务跨进程复用靠它
    build_authorize_url,  # 授权第一步: 纯拼 URL 不触网, 可单独单测
    build_logout_url,  # 登出 URL 拼装: 换账号时用, 同样不发起请求
    ensure_access_token,  # 过期恢复单点: 无交互通道时抛错而不是退成匿名
    exchange_code,  # 授权第二步: 授权码换令牌, 跨进程 HTTPS 往返
    get_profile,  # 用令牌换用户档案: 只在已认证时调用
    run_local_callback_flow,  # 交互式授权: 本地起回调端口收授权码
    run_manual_paste_flow,  # 交互式授权: 手工粘贴授权码, 供无浏览器环境
)

# 公开面白名单: 端点/环境变量名/异常/令牌缓存/授权流与登出/取 profile。
# __all__ 必须与上面那条 import 的符号严格一一对应: 少列会让 `import *` 丢掉
# 能力, 多列会在静态检查侧报不存在的属性。逐项说明见 import 块上方的清单
# (它们写在块上方而不是括号内, 是因为括号内的行尾注释会触发 isort I001)。
__all__ = [  # 公开面白名单: 必须与上面那条 import 的符号严格一致
    # 端点与凭证环境变量名: 部署方按这些名字注入, 不改代码即可换环境
    "OAUTH_BASE_URL", "ENV_CLIENT_ID", "ENV_CLIENT_SECRET", "ENV_REDIRECT_URI",
    "DEFAULT_TOKEN_CACHE",                                                # 令牌落盘默认路径 (无环境变量时)
    "NadcOAuthError", "OAuthProfile", "TokenStore",                      # 异常契约 / 身份模型 / 持久化后端
    "TokenExpiredError",                                                 # 可重试的过期 (与上条的授权失败分开)
    "ensure_access_token",                                               # 过期恢复单点: 无交互通道则抛错而非退匿名
    "build_authorize_url", "build_logout_url",                           # 授权第一步 / 登出: 纯拼 URL 不触网
    "exchange_code", "get_profile",                                      # 授权第二步 (跨进程 HTTPS) / 取 profile
    "run_local_callback_flow", "run_manual_paste_flow",                  # 两种交互式授权, 无浏览器环境用后者
]
