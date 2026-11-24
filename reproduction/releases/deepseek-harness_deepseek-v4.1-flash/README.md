# deepseek harness（deepseek-v4.1-flash）

- 框架与模型：`DeepSeek Harness 0.2.0-rc.2` × `deepseek-v4.1-flash`（主实验）
- 实验范围：E1–E6（E1/E3/E4/E5 共 2,475 条评分记录；E2 含 21 场景 × 3 轮 = 63 次离线冻结回放；E6 含原批与 R3 补测重复性）
- 许可：Apache License 2.0（见 `LICENSE`，Copyright 2026 The Authors）

## 运行

在解压根目录执行（Python 3.13 / 3.11+，纯离线）：

```bash
python -m pip install -r requirements.txt
python recompute.py
```

## 说明

- `E2/accepted_run/snapshots/` 中的实采快照来自公开 Gaia DR3 与 Pan-STARRS1 查询响应片段，6 万行压力夹具为合成数据；`preregistration.json` 仅清理了本机 `pip_freeze` 中的路径与无关包，受哈希锁定的冻结文件均未改动。
- 评分表中的 `D0` 为归档内部代号。
