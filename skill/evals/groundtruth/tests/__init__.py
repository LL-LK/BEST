# -*- coding: utf-8 -*-
"""evals/groundtruth/tests/__init__.py — E2 单测包 (判定器自证 + 回放闭环)。

覆盖: 反证夹具 metascore=1.0 (判定器自证); SnapshotTransport 回放语义;
canonical 规范化 (主键/哨兵/三输出面); gold 生成器独立性守卫; 端到端
回放对账冒烟 (黄金路径必须全绿 — 证明"好答案能被判过", 与反证互补)。
"""
