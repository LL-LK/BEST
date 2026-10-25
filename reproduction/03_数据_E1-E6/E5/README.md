# E5 最新复现：v5.1 / 2016格完整封存

设计为原56题×12臂×3重复。固定Harness CLI0.2.0-rc.2、实际挂载的受限Claude Science预设、`opencode-go/deepseek-v4.1-flash`。真实LLM和生产ToolBox/BestClient使用匹配公开数据的冻结传输，不是每格重新访问NADC，不是脚本代答。冻结协议SHA256为 `269a03a9a360629a7ad6260093e018fa23cceef28fb10d0d04d09ae1d7ed06a5`。

本包只含最终2016格及其来源。旧ScriptedLLM、30题重建、历史decision-only会话不作为当前实验结果。

## 核验与分析复现

解压后可执行：

```powershell
python E5\verify_e5.py E5_latest_v51_2016.zip
python E5\analysis\analyze_e5.py --results E5\results --output C:\temp\e5-diagnosis-new
```

核验脚本检查全部包内SHA256、原始RunJournal封存manifest/trace/逐格ZIP和2016个唯一会话。分析脚本重新计算主检验精确符号翻转p，并导出逐题差值、类别和失败条件描述；没有新增确认性检验，没有删掉预算失败，没有重评分。

`audit/sealed_journal/confirmatory-v51-packed`包含原始账本和原始逐格ZIP字节；`evidence/cells`是可直接阅读的逐格来源。两者有意重复，以支持既核验封存承诺又审查原始证据。`MANIFEST.sha256.json`是此次分类重新打包的清单，原冻结承诺仍原样保留。

独立评分由Windows身份E5Scorer执行；`scoring/scorer.py`与`confirmatory_stats.py`原文保留。之后添加的存储兼容层处理无worker回执目录和原生JSON字符串参数，不改变模型事件、评分条件或统计。收集器最后一格重扫、旧PowerShell启动器兼容也有操作记录。573格无回执目录中564格无模型工具调用、9格有调用事件但无worker回执，不豁免失败或引用检查。

## 复现范围与人工复核

该公开包支持证据核验和分析重算。新运行完整2016格仍需要匹配的Harness安装包、真实模型凭据、预设插件、隔离Windows身份、WSL/bubblewrap环境及受保护Gold。二进制指纹和协议在包内，安装包、凭据和账号密码不分发。操作脚本保留原路径；在其他机器重新部署必须建立新运行及冻结，不能把修改后的部署伪称原批次。

私有Gold未加入公开包；作者审核材料另存于 `<WORK_ROOT>\private\<AUTHOR_PRIVATE_ARCHIVE>`，只供作者授权审核。人工表见 `results/human-review-pending.csv`。重新独立评分需访问该Gold并满足专用身份与隔离约束；公开包单独不能完成Gold评分复核。

主比较B3−B2b为+7.14个百分点，精确p=.08848，未达到预设.05；六项Holm均未显著，A2−sham差0、p=1。236格触及4096 token预算并保留为失败。结果是机械规则代理分数，人工复核尚未完成。
