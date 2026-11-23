# E2 最新复现：v2 / run-07

> 从当前仓库使用本目录。已按预注册清单恢复冻结文件的原始字节，并通过本目录的 Git 属性保留 LF 或 CRLF。原论文 Release 中的早期 ZIP 含 E2 行尾差异，其余材料的入口见[复现说明](../../README.md)。

唯一接受批次是 `e2-v2-20d9fd4d7fdb4ee48cb7f81bd5e13105`：21场景×3次，共63个唯一逻辑重复，21/21通过，独立Gold核验21/21、34项N/A。协议、206个冻结输入文件与21个代码指纹都经过重新核验。

这是离线 query-aware 冻结快照/夹具回放；真实BestClient走正式协议与解析链。部分响应按冻结行集和查询参数重建，不冒称每个派生响应都是实站原始字节。经验PS1场来自2026-10-04实抓1000行、1800″半径；60,000行压力、NULL/ZERO等合成轴不能写成真实观测。适用项通过不等于所有指标都有观测证据，也不等于Gold经过天文学家人工验证。

解压后从E2目录执行：

```powershell
python reproduce_e2.py --verify-only
python reproduce_e2.py --output ./e2-reproduction-new
```

需要 Python 和 [离线复现依赖](../../portable/requirements-paper.txt)，环境快照见 `accepted_run/preregistration.json`。源码树由脚本加入导入路径。输出目录必须不存在；重现检查的 63 次为验证运行，保存在独立目录。脚本核验全部冻结输入、代码和独立 Gold，并逐条比对回放的输出和错误回执。

`operations/`保留原始预注册/执行脚本，含原机器绝对路径；跨机器使用上述可移植入口。`frozen-code-map.json`把原绝对路径映射到包内文件，原代码不改写。`audit/run-*`仅保留失败诊断轮的报告、trace和预注册，不混入run-07；其旧输入/旧版本代码未全部复制，因此不是失败轮的独立可运行包。历史总结末尾“E5未启动”反映当时日期，本次E5最新状态请看独立E5包。
