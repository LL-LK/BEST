# BEST-Skill

**面向智能体的天文数据库访问技能**（AI-accessible scientific database skill）
—— 以 [BEST](https://nadc.china-vo.org/data/best/)（BEst STar）测光标准星数据库为实现与验证对象。

本仓库是论文的**代码与复现材料官方发布仓库**，对应稿件：
> *BEST-Skill：面向智能体的天文数据库访问技能*

---

## 1. 这个仓库解决什么问题

BEST 是一个测光标准星数据库，**不提供逐历元时序**，也**不是为自然语言交互设计的**。
本项目把 BEST 的访问面封装成一个可被大模型 / Agent 调用的技能，并回答一个具体问题：

> 能否把自然语言天文需求，**稳定地**转成正确的数据库查询，并返回
> **科学语义正确、来源可追溯、异常情况下不胡编**的结果？

### 主张与不主张

**主张**：分层设计（面向模型的指导信息 + 面向查询过程的执行机制）使请求映射正确、
科学陈述可溯源、越界请求被安全拒绝。

**不主张**：

- ❌ 不主张 BEST 数据库本身已经 AI-ready；
- ❌ 不主张 BEST 覆盖逐历元时序、周期恢复或变星识别——**Skill 对这类请求的正确行为是明确拒绝并说明边界**；
- ❌ 不主张任何单项指导模块的独立因果贡献（E5 的六项消融经 Holm 校正后 p 值全为 1.0）。

## 2. 技能的能力边界

只覆盖 BEST 确实支持的能力：

| 能力 | 说明 |
|---|---|
| 按 Gaia `source_id` 查询 | 单对象精确查询 |
| 按坐标 + 搜索半径锥形搜索 | 支持角秒单位与 RA 边界处理 |
| 按波段 / 星等 / 误差 / 质量标志筛选 | 多条件组合 |
| 返回库内已有字段 | Gaia 与 ZTF 合成测光字段 |
| 字段、单位、星等系统与质量标志解释 | 七类处置策略与四层处置级别 |
| 导出标准化 JSON / CSV / VOTable | 站点 `output.fmt` 原生支持 |
| 返回数据版本、查询参数与来源链接 | 结果血缘 |
| **对不支持的请求明确拒绝** | 例如时序需求、整表导出、上传建 job、影像请求、凭据入参 |

## 3. 仓库结构

```
.
├── README.md                 ← 本文件（审稿人入口）
├── LICENSE                   ← MIT
├── .gitattributes            ← Git LFS 追踪规则（大文件走 LFS）
├── skill/                    ← 完整源码仓（被测对象本体，已全量脱敏）
│   ├── src/                  ← 技能实现（TAP/ADQL 网关、结果信封、契约）
│   ├── contracts/            ← 输入 / 输出 / 字段 / 分页 / 来源 契约
│   ├── evals/                ← 六组实验的评测代码与用例集
│   ├── test/                 ← 单元测试
│   ├── docs/                 ← 架构与评测设计文档
│   ├── ops/ rag/ references/ ← 运维、知识库、外部参考快照
│   └── statcatalog/          ← TAP/ADQL 变量目录（大文件，LFS）
└── reproduction/             ← 投稿包（审稿人复现材料全集）
    ├── 01_稿件/              ← 稿件终版（main.tex / supplementary_material.tex / PDF / 图）
    ├── 02_图表/              ← 六幅图的生成器与源数据
    ├── 03_数据_E1-E6/        ← 六组实验的证据与结果
    ├── 04_复现源码/          ← 最小可运行版源码 + 六个脱敏最小复现包
    ├── 05_溯源台账/          ← 数字溯源台账（逐条：论文值→证据→重算命令→判定）
    ├── 06_专家盲评包/        ← E3 专家盲评工作簿（空白待真人填写）
    ├── 07_脱敏与README/      ← 替换规则表、脱敏日志、隐私扫描报告
    ├── 08_清单与SHA256/      ← 逐文件 MANIFEST、验收结果报告、扫描与清单脚本
    └── BEST-Skill投稿包_v72_20261024.zip   ← 上述内容的完整打包（LFS）
```

## 4. 怎么复现

### 4.1 开箱可跑（不需要模型凭据）

```bash
# E1 判定器接线检查
pytest skill/evals/nl2tool -q --co            # → 159 tests collected

# E4 接线检查
pytest skill/evals/robustness -q --co         # → 53 tests collected

# E2 冻结快照回放核验
python skill/reproduce_e2.py --verify-only    # → 冻结输入 / 代码 / Gold 全部一致
```

### 4.2 统计量独立复算（随包提供脚本）

```bash
# E5 全量统计复算：2016 格 → 各臂通过率、精确配对符号翻转、Holm、bootstrap CI
python reproduction/05_溯源台账/主会话独立复算件/verify_e5_independent.py
python reproduction/05_溯源台账/主会话独立复算件/verify_e5_contrasts.py

# E1 三箱加权分复算（旧链 vs 论文口径，两套不可混用）
python reproduction/05_溯源台账/主会话独立复算件/verify_e1_batches.py
```

### 4.3 投稿包自身的机器验收

```bash
# 隐私扫描（识别性命中应为 0）
python reproduction/08_清单与SHA256/scripts/scan_privacy.py \
    reproduction/01_稿件 reproduction/02_图表 reproduction/03_数据_E1-E6 \
    reproduction/04_复现源码 reproduction/05_溯源台账 reproduction/06_专家盲评包 \
    reproduction/07_脱敏与README reproduction/08_清单与SHA256

# 六项结构与可复现性验收
python reproduction/08_清单与SHA256/scripts/acceptance_check.py

# 逐文件 SHA256 清单
python reproduction/08_清单与SHA256/scripts/build_manifest.py
```

### 4.4 需要模型凭据的部分

完整重跑 E1 / E3 / E5 / E6 的模型调用需要：Harness 安装包、真实模型服务凭据、
隔离的 Windows 身份、WSL / bubblewrap 沙箱、原始 API 凭据。
**这些均不随包分发**，也不在本仓库内。

E3 / E6 的辅助程序按原交付说明属于「需要项目代码及原目录布局」的形态，
**不是一键可执行的独立软件**（`run_e3.py` 在 Windows 上缺 `src` 且受阻于 POSIX 专有 `fcntl`；
`run_e6_formal.py` 缺 `evals.repro`）。

## 5. 数据可用性与口径说明

- `reproduction/03_数据_E1-E6/` 与 `04_复现源码/` 采用**官方脱敏最小复现包**（`PACKAGE-MANIFEST.sha256.json` 自洽）。
  **包内哈希已按脱敏后内容重算，与原始批次哈希不可直接比对**，请以包内 `DESENSITIZATION-NOTICE.md` 为准。
- `skill/` 为**完整原始源码仓**经全量脱敏后的版本（补齐了最小包中省略的 `test/` 与 `statcatalog/`）。
- E4 有两批数据：论文正文报告的是 **r2 批次**（自然语言请求处置正确率 34/35、35/35、34/35），
  而 `reproduction/04_复现源码/最小复现包/E4_最小复现包.zip` 内含的是 **r1 批次**（26/35）。
  两者不可混用，详见 `reproduction/03_数据_E1-E6/E4/v70_E4重跑_20261023/`。
- E1 同样存在两套口径：论文口径来自 2026-10-20 的重新判分（均值 0.9530），
  最小复现包内为旧链（0.9089–0.9446）。

## 6. 脱敏与隐私

本仓库按既有 23 条替换规则（见 `reproduction/07_脱敏与README/REPLACEMENT-RULES.md`）脱敏，
并对全部产物做了增量隐私扫描：

- **识别性命中：0 条**
- 23 条规则逐条核对：**零原始形态残留**
- 替换为可逆占位符（`<WORKSPACE>`、`<USER_HOME>`、`<HOST>`、`user`、`session-<SESSION_ID>` 等），
  原始值不随包外发

扫描报告：`reproduction/07_脱敏与README/隐私扫描报告.md`
规则核对：`reproduction/05_溯源台账/既有23条规则核对表.csv`

## 7. 引用

请引用本仓库对应的论文。若使用了 `skill/` 中的代码，请保留 MIT 许可声明。
