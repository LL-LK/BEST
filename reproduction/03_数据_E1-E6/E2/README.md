# E2 最新复现：v2 / run-07

唯一接受批次是 `e2-v2-20d9fd4d7fdb4ee48cb7f81bd5e13105`：21场景×3次，共63个唯一逻辑重复，21/21通过，独立Gold核验21/21、34项N/A。协议、206个冻结输入文件与21个代码指纹都经过重新核验。

这是离线 query-aware 冻结快照/夹具回放；真实BestClient走正式协议与解析链。部分响应按冻结行集和查询参数重建，不冒称每个派生响应都是实站原始字节。经验PS1场来自2026-10-04实抓1000行、1800″半径；60,000行压力、NULL/ZERO等合成轴不能写成真实观测。适用项通过不等于所有指标都有观测证据，也不等于Gold经过天文学家人工验证。

解压后从E2目录执行：

```powershell
python reproduce_e2.py --verify-only
python reproduce_e2.py --output C:\temp\e2-reproduction-new
```

需要Python及原始环境中用到的依赖，环境快照见 `accepted_run/preregistration.json`，依赖声明见 `code/requirements.txt`。源码树通过脚本加入sys.path，不需要安装为wheel。输出目录必须不存在；重现检查的63次不计入原始确认性样本，不覆盖 accepted_run。脚本核验全部冻结输入、代码、独立Gold，再要求重现的63份行输出哈希与原接受批次一致。

`operations/`保留原始预注册/执行脚本，含原机器绝对路径；跨机器使用上述可移植入口。`frozen-code-map.json`把原绝对路径映射到包内文件，原代码不改写。`audit/run-*`仅保留失败诊断轮的报告、trace和预注册，不混入run-07；其旧输入/旧版本代码未全部复制，因此不是失败轮的独立可运行包。历史总结末尾“E5未启动”反映当时日期，本次E5最新状态请看独立E5包。
