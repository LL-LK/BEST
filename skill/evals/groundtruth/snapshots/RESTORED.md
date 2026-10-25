# 最小快照集 (按需还原, 2026-10-07)

本目录是 2026-10-07 回放层退役时**被删掉**的素材里, 仍被存活代码逐文件读取的
那一小部分。完整备份见 `docs/archive/replay-backup/`。

## 为什么只还原这些

退役删的是**回放臂** (E2 的 `--mode replay` 与它的 transport), 不是所有引用
这些素材的东西。实测仍引用 `rows_full.csv` 的有三处: E5 消融基线
(`evals/ablation/items.yaml` 的 `data_anchor`)、TAP/导出两件套的实测对账, 以及
事实门禁 `test_snapshot_facts_vs_docs.py`。

全量还原 (11 目录 / 290 文件 / 20.1 MB) 等于把刚做完的退役一笔勾销; 而**只还原
被引用的 11 个目录**, 既保住承重面, 又让「哪些是真需要的」显式可见 —— 上面这份
清单就是那张账单。

## 逐条: 谁在引用

- `live-2026-10-04/live_gaia_dr3_18_ra286.1_dec15.7_r300.0as` — E5 题集 gaia 锥搜
- `live-2026-10-04/live_ps1_proximity_n3_5d2580ec` — E5 题集 batch 邻近 (in3)
- `live-2026-10-04/live_ps1_ra10.0_dec-45.0_r60.0as` — E5 题集 ps1 南天极
- `live-2026-10-04/live_ps1_ra180.0_dec30.0_r120.0as` — E5 题集 120as 半径
- `live-2026-10-04/live_ps1_ra180.0_dec30.0_r300.0as_max4000` — E5 题集 max4000 截断
- `live-2026-10-04/live_ps1_ra180.0_dec30.0_r5.0as` — E5 题集 5as 小半径
- `live-2026-10-04/live_ps1_ra180.0_dec30.0_r60.0as_fps1_gpsfbetween-ps1_gpsf_errless` — E5 题集 投影/errless 形态
- `live-2026-10-04/live_ps1_ra180.0_dec30.0_r60.0as` — E5 题集 60as 主样本
- `live-2026-10-04/live_raw_ps1_r0.0as` — E5 题集 裸 ps1 0as
- `syn_missing` — E5 题集 缺列形态 (反证夹具底座)
- `live-2026-10-04/live_ps1_ra359.5_dec0.0_r1800.0as` — 事实门禁: ps1 1000 行 / source_id 重复
- `ps1_ra180.0_dec30.0_r60as` — E5 反证夹具 E5-D04 底座 (合成, BEST_SIM_*)
- `syn_huge` — E5 反证夹具 万行截断底座 (合成)
- `live-2026-10-04/live_xpsp_ra10.68_dec41.27_r300.0as` — test_fixsent_real_snapshot_parity (双引擎空值语义)

## 什么时候可以再删

三条路径都能去掉对素材的逐文件依赖时, 本目录即可再随回放层一起退役:

1. E5 改走实跑或自带可测装置 (与 E4/E6 保留 `replay.py` 同款裁定);
2. TAP/导出两件套改用现场构造的合成行集;
3. 事实门禁的实跑重算版与快照版**交叉验证通过**后, 快照版退役。

在那之前删掉本目录 = 26 条测试当场红, 且红的原因与被测代码无关。
