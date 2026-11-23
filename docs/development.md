# 使用与开发

[文档导航](README.md) · [源码目录说明](../skill/README.md)

| 用途 | 入口 |
| --- | --- |
| 查询能力、适用范围和智能体入口 | [SKILL.md](../skill/SKILL.md) · [数据库指南](../skill/references/best-database-guide.md) · [BEST 站点用法](../skill/docs/BEST-SITE-USAGE.md) |
| 安装依赖与启动命令 | [依赖声明](../skill/pyproject.toml) · [本地入口](../skill/README.md#本地入口) |
| API 与接口契约 | [客户端参考](../skill/references/client-api-reference.md) · [输入输出契约](../skill/contracts/io-contract.md) · [数据格式](../skill/references/data-formats.md) · [算法规范](../skill/references/ALGORITHM-SPEC.md) |
| 认证、下载与失败处理 | [认证与 OAuth](../skill/references/auth-and-oauth.md) · [站点端点](../skill/references/site-endpoints-and-interactions.md) · [下载操作](../skill/references/download-playbook.md) · [回退协议](../skill/references/fallback-protocols.md) |
| 实现与操作脚本 | [源码](../skill/src/) · [操作脚本](../skill/ops/) |
| 单元测试、评测与代码审计 | [测试目录](../skill/test/) · [评测目录](../skill/evals/) · [覆盖矩阵](../skill/docs/architecture/coverage-matrix.md) · [审计工具说明](../skill/ops/audit/README.md) |
| 设计记录和变更 | [架构文档](../skill/docs/architecture/) · [图示说明](../skill/docs/diagrams/README.md) · [变更日志](../skill/CHANGELOG.md) |

从 `skill/` 目录执行 `python ops/astro_best_cli.py --help` 或 `python -m src --help` 查看命令行参数。原始整仓的 [架构与构建文件](../reproduction/04_复现源码/astro-best_skill源码仓/) 随论文封存，可用于核对当时的实现与目录布局。
