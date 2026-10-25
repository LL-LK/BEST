# 本轮冻结协议

```json
{
  "design": "当前对话助手主评＋独立天文专家全量盲评；不是原双专家主评协议",
  "groups": [
    "S-A",
    "S-B"
  ],
  "repeats": 3,
  "main_answers": 192,
  "live_answers": 24,
  "live_is_secondary": true,
  "slr_main_items": 14,
  "expert_answers": 216,
  "hidden_controls": 3,
  "pilot": [
    "E3-A01",
    "E3-A02",
    "E3-A03",
    "E3-D01",
    "E3-D02",
    "E3-G01",
    "E3-G02"
  ],
  "aggregation": "每次重复全主测计算指标，再报三次中位数和极差；配对合格取逐题三次多数",
  "bootstrap": {
    "resamples": 10000,
    "unit": "题号，两组及三次重复一起重抽",
    "seed": 20261006
  },
  "collection_concurrency": 4,
  "output_budget": "统一使用配置的max_output_tokens；本轮32768，按实际接口映射；旧16384预算批次不混用",
  "sampling": "未配置温度则不发送，不声明已固定；记录供应商实际模型与有效请求参数",
  "primary_judge": {
    "mode": "current_assistant",
    "api_called": false,
    "context_isolated": false,
    "model_verified_by_api": false
  },
  "self_rating_risk": "主评助手参与准备且看到组别映射，匿名材料不保证评阅人盲性；无独立评分上下文，专家结果独立保留",
  "live_method": "固定流程采集，同题同重复两组共享同一实际回包，只比较拿到数据后的解释",
  "limitations": "主測为32个独立题号，三次重复不视为96个独立样本；不宣称达到预设检验效力"
}
```
