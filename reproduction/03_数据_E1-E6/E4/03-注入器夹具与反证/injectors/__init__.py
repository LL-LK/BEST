# -*- coding: utf-8 -*-
"""evals.robustness.injectors — E4 故障注入面 (Tier W 线路层剧本库)。

职责: 声明"故障从哪来"这一层 —— 本包只承载故障生产侧, 把一次干净回放包装成
特定故障现场, 供 graders 判定; 判定本身不在这里。

所属实验: E4 鲁棒与安全 (68 条标注 = Tier W 33 / Tier P 35, Tier W 主线 15 条
程序判定全过), 方案真值 docs/eval-E4-robustness-safety.md §4 的十一类故障矩阵。
本包对应矩阵的 F6 网络 / F7 内容不完整 / F8 字段缺失与类型漂移 / F11 安全注入
四组, 复合变体 RB-C01..RB-C18 标 second_round 延后、不计入主指标。

对外接口: 真正的入口是子模块 wire_faults (各注入器工厂 + apply_injectors 装配器
+ _FakeStatusResponse 回包载体); 本文件刻意不 re-export, 保持"包声明"与"实现"
分界清楚, 少一层间接就少一处 import 环的风险。

依赖与数据流: 输入 = items.yaml 每条 case 的 fault 段 (显式参数, 无随机) 与被测
client.session 的干净 get/post; 产物不落盘, 观测记录挂在包装函数上, 报告由
evals/robustness/runner.py 写。

关键契约与不变量: 离线回放 (SnapshotTransport 家族 + rate_limit 归零, 不接真实
模型、不打真实站点); 零跨实验 import (唯一共享件是 evals/_data/ 纯数据字典,
本包不碰); 注入必须确定性可复现 —— 没有 random / sleep / 隐式时间依赖, 同一
参数两次跑得到逐字节相同的故障序列; 与 E2 的语义等价性由 evals/equivalence 断言
守护。

陷阱与边界: 注入器只改回包不改调用序列 —— M3/M6 判的是重试预算与越界, 注入器
若自己伪造调用记录就把这两条判据的现场吃掉了; 软 404 是 200 + 错误体, 绝不能在
传输层就抛异常, 否则"看起来成功"的判定现场不存在了; second_round 的复合故障
只能报"已知延后"而不是"预期失败" —— 后者等于用注释掩盖尚未完成的判定。
"""
