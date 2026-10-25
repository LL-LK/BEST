# astro-best — BEST Database Skill
# Standardized test/lint/eval/verify commands

.PHONY: help install test test-cov test-unit test-integration lint lint-fix format doctor eval eval-e1 eval-e2 eval-e3 eval-e4 eval-e5 eval-e6 evals-all e1-batch-input e4-batch-input batch-input check-e4-disposal verify audit check clean distclean all

help:
	@echo "astro-best standard targets:"
	@echo "  make install         Install runtime dependencies"
	@echo "  make test            Run pytest suite on test/"
	@echo "  make test-cov        Run test suite with coverage report"
	@echo "  make lint            Run ruff on src/ test/ evals/ rag/ ops/ examples/"
	@echo "  make doctor          Run self-diagnostics"
	@echo "  make eval            Run evaluation runner"
	@echo "  make eval-e1..e6     Run per-experiment runners (E1 NL2T / E2 groundtruth / E3 semantics / E4 robustness / E5 ablation / E6 repro)"
	@echo "  make evals-all       Run all six experiment runners in sequence"
	@echo "  make verify          Verify file tree integrity against README SSOT"
	@echo "  make audit           Run ops/audit governance guardrails (9 hard gates)"
	@echo "  make check           Run test, lint, verify and audit"
	@echo "  make clean           Clean caches (keeps best_data/ research data)"
	@echo "  make distclean       Also remove runtime data (best_data/, .checkpoints/) - DESTRUCTIVE"
	@echo "  make all             Run lint, test, eval, verify, audit, and clean"

install:
	pip install requests pyyaml astropy numpy pandas pytest pytest-cov ruff

test:
	python -m pytest test/ evals/ -q --tb=short

test-cov:
	python -m pytest test/ evals/ -q --tb=short --cov=src --cov-report=term-missing

test-unit:
	python -m pytest test/unit/ -v

test-integration:
	python -m pytest test/integration/ -v

lint:
	ruff check src/ test/ evals/ rag/ ops/ examples/

lint-fix:
	ruff check --fix src/ test/ evals/ rag/ ops/ examples/

format:
	ruff format src/ test/ evals/ rag/ ops/ examples/

doctor:
	python ops/astro_best_cli.py doctor

eval:
	python evals/eval_runner.py

# ── 六个实验跑批 ─────────────────────────────────────────────────────────
# REPORT.md 分两类, 不要一视同仁地覆盖:
#   * 生成型 (E1/E3/E5): runner 全量输出即报告本身, 每次跑批覆盖刷新。
#   * 人工归档 (E2/E4/E6): runner 输出只是子集 (E4 的 F-E4-01 发现叙述、
#     E2 的七指标与已知登记、E6 的 7 条交付后修复记录都是人写的),
#     跑批只打印到终端, **不覆盖** —— 覆盖会造成内容丢失。
# E1/E3/E5 的 --md-out 是为了把文档 §8/§13/§14 列的 REPORT.md 永久资产真正落盘
# (原先只打印到终端, 报告实际不入库)。
#
# ── 实验级门禁开关的接线口径 (N1-05, 逐个实测过, 别凭印象改) ──────────
# 四个开关的现状**不是"忘了接线"**, 是逐个实测后的不同处置:
#   E1 --require-threshold  → **已接线**。逐维不过线即阻断的反作弊判据本来
#     就存在且有效 (evals/nl2tool/tests/test_e1.py 有反作弊测试), 但 make 不传
#     等于"写好了没人跑"。实测金标准自证批开闸仍 exit 0, 接上不误伤。
#   E3 --require-coverage   → **故意不接**。实测开闸 exit 1: 当前 answers 覆盖
#     为 0/37, 门禁会立刻判红。这是真欠账 (E3 题集还没接真实回答), 但把它
#     接到 make 上只会让 `make evals-all` 永远红 —— 那不是守护, 是噪声。欠账
#     登记在 docs/eval-E3-semantics.md, 补齐 answers 后再接线。
#   E4 --require-execution  → **故意不接**, 理由同 E3。实测开闸 exit 1: Tier P
#     是纯标注预检 (evaluated=false), 话术层评测需 LLM agent + 专家盲评。
#     REPORT.md 已在抬头如实披露 "Tier P 不等于已评测"。
#   E2 --require-human-review → **已取消** (2026-10-04 裁定): 改为报告字段
#     如实披露, 不再阻断跑批。开关在代码里已不存在, 无需接线。
# 判据: 开关的缺省值是"离线自检批不该被打红"; 接线的前提是该批真的跑过。
# ── E1 跑批前的答案隔离 (docs/eval-E1-nl2tool.md §9.1) ──────────────────
# 两步都要跑, 少一步隔离就是空的:
#   1) make_batch_input 只抽用户原话, 答案全剥离 (白名单提取, 非黑名单);
#   2) check_leakage 扫**实际要喂给模型的文本** —— 生成器管不到剪贴板,
#      人在输入框里补的那几句只能靠它事后扫。不干净即阻断 (exit 1)。
# 注意: 这不替代 eval-e1; 它是跑批**之前**的闸, 判分是跑批**之后**的事。
e1-batch-input:
	python evals/nl2tool/make_batch_input.py --with-primers
	python evals/nl2tool/check_leakage.py --dir temp/nl2tool/batch_input

# ── E4 跑批前的答案隔离 (docs/eval-E4-robustness-safety.md §11.1) ────────
# 与 E1 同构, 但 E4 多两处泄漏面, 所以这一步更不可省:
#   1) Tier P 的 reject.suggest / stop.report / clarify.options 就是标准答案原话;
#   2) Tier W 的 fault.inject 是**隐藏变量** —— 写进题面等于提前剧透故障,
#      模型于是老实报错, M5 (失败不包装率, 红线) 假绿。注入只由注入器现场施加。
# 按铁律 6 (零跨实验 import) 自带一套判定逻辑, 与 E1 那份的漂移由
# evals/equivalence/tests 的双胞胎断言守护。
e4-batch-input:
	python evals/robustness/make_batch_input.py
	python evals/robustness/check_leakage.py --dir temp/robustness/batch_input

# ── E4 答题沙箱: 答题面与答案面物理隔离 ────────────────────────────────
# 题卷干净 (上一个 target) 只解决一半: 模型在**哪里**答题没有约束。工作目录
# 开在仓库里, evals/ 就在眼前; 开在堆着历史产物的文件夹里, 别家的答卷就在
# 眼前 (E1 的 NL2T-*.json trace 含完整 answer_text)。照抄别人答卷与独立作答
# 在分数上无法区分 —— 这是比答案泄漏更隐蔽的污染。
# 沙箱把两处切开: 答题面 answer_box/ (只有被测对象+干净题卷), 答案面
# answers/<run_id>/ 在答题面**之外**, 下一轮砍不到前一轮的答案。
e4-answer-box: e4-batch-input
	python evals/robustness/make_answer_box.py --build

batch-input: e1-batch-input e4-batch-input

# --primers 不能省: 金标准合成器 (gen_golden) 与判分器现在读**同一份**台账填占位符,
# 少传它两边取值就会各走一套 (实测自证批从 1.0 掉到 0.9530 判 FAIL)。
eval-e1:
	python evals/nl2tool/gen_golden.py
	python evals/nl2tool/runner.py --traces evals/nl2tool/traces/golden --require-threshold --primers evals/nl2tool/context_primers.yaml --json temp/nl2tool/report.json --md-out evals/nl2tool/REPORT.md

eval-e2:
	python evals/groundtruth/run_e2.py --md --repeat 3 --json temp/e2_report.json

eval-e3:
	python evals/semantics/runner.py --json temp/semantics/report.json --md-out evals/semantics/REPORT.md

# ── E4 执行门禁 (2026-10-11 接线) ────────────────────────────────────────────
# 判据此前已写好 (runner.py:512 --require-execution / 阻断码 tier_p_not_executed),
# 但 make 从不传该开关 —— 「Tier P 压根没跑」不会让 make 变红, 与 E1 当年
# 「逐维门禁写了没接线」是同一个洞 (E1 已于 Makefile:114 修好)。
#
# 接线后**缺省会阻断**: 不给 --answers 时 Tier P 恒 evaluated=False
# (「标注齐」不等于「跑过」, 铁律 5 禁 fail-open)。这是**预期行为**, 不是故障。
# 要真判话术层, 显式给答案面:
#     make eval-e4 E4_ANSWERS=temp/robustness/answers/r1
# 需要在 evals-all 里放行而不判话术层时: make eval-e4 E4_SKIP_GATE=1
eval-e4:
	@if [ -z "$(E4_SKIP_GATE)" ] && [ -z "$(E4_ANSWERS)" ]; then \
		echo "[eval-e4] 未提供 E4_ANSWERS —— Tier P 将按『未执行』阻断 (这是门禁本意, 不是报错)"; \
		echo "[eval-e4] 真判话术层: make eval-e4 E4_ANSWERS=<答案面目录>"; \
		echo "[eval-e4] 临时放行  : make eval-e4 E4_SKIP_GATE=1"; \
	fi
	python evals/robustness/runner.py --tier all --md \
		$(if $(E4_ANSWERS),--answers $(E4_ANSWERS),) \
		$(if $(E4_SKIP_GATE),,--require-execution)

# E4 处置口径越界复检 (只读, 不改冻结 items.yaml; 越界即 exit 1)
check-e4-disposal:
	python evals/robustness/check_disposal_scope.py

eval-e5:
	python evals/ablation/runner.py --scripted --md evals/ablation/REPORT.md --json temp/ablation/report.json

eval-e6:
	python evals/repro/run_e6.py --lane R0 --repeat 5 --selftest --md

evals-all: eval-e1 eval-e2 eval-e3 eval-e4 eval-e5 eval-e6
	@echo "=== 六个实验跑批完毕 (E1/E2/E3/E4/E5/E6) ==="

verify:
	python ops/verify_tree_integrity.py

# 治理护栏硬门禁: 八条都必须 exit 0 (README §7 的口径)。
# 报告型工具 (verify_no_code_loss / scan_code_smells / version_scan* /
# check_line_endings) 刻意**不**接入: 它们的输出需要人判读 (如合法清理重复定义
# 会被 verify_no_code_loss 报成 token 减少), 强行阻断会误伤正常重构。
# 第七条 verify_no_version_keys 是铁律 1 的阻断式门禁 (2026-10-04 A6-02 补):
# version_scan* 扫的是**文本字面量**且恒 return 0, 挡不住 SSOT 之外 YAML 里
# 的 `version:` 键 —— 突变实验实测七道门禁全绿。
# 第八条 verify_evidence_anchors 是 E3 证据指针的阻断式门禁 (2026-10-04
# A8-01 补): evidence 字段此前无门禁无消费者, 实测 7 题锚点指向与断言无关的
# 代码 —— 指针失准即那道题的事实基座不存在。
audit:
	python ops/audit/count_code_lines.py
	python ops/audit/comment_audit.py
	python ops/audit/code_fingerprint.py check
	python ops/audit/verify_import_graph.py
	python ops/audit/verify_crossrefs.py
	python ops/audit/verify_doc_consistency.py
	python ops/audit/verify_no_version_keys.py
	python ops/audit/verify_evidence_anchors.py
	python ops/audit/verify_counting_claims.py

check: test lint verify audit

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True) for p in list(pathlib.Path('.').rglob('__pycache__')) + list(pathlib.Path('.').rglob('*.py[co]')) + list(pathlib.Path('.').rglob('__test_tmp__')) + list(pathlib.Path('.').glob('*.egg-info')) + [pathlib.Path(d) for d in ['.pytest_cache', '.ruff_cache', '.coverage', 'htmlcov']] if p.exists()]"

distclean: clean
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('best_data'), pathlib.Path('.checkpoints')] if p.exists()]"

all: lint test eval verify audit clean
	@echo "=== astro-best validation passed ==="
