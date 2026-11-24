# deepseek harness（mimo-v2.6-flash）

- 框架与模型：`DeepSeek Harness 0.2.2-rc.3` × `mimo-v2.6-flash`
- 实验范围：E1 / E3 / E4 / E5（2,475 条评分记录；E2 与 E6 仅在主实验组开展）
- 许可：Apache License 2.0（见 `LICENSE`，Copyright 2026 The Authors）

## 运行

在解压根目录执行（Python 3.11+ 标准库，纯离线，无需安装第三方依赖）：

```bash
python recompute.py
```

## 说明

- E3 采用统一模型盲评计数，E5 沿用端到端机械成功判据；数据表中的 `D1` 为归档内部代号。
- 本包用于离线复算统计指标；重跑模型或重新判分需在对应运行环境中使用完整原始归档。
