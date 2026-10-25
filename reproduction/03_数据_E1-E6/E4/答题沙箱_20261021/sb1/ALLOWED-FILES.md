# 本箱允许存在的文件（白名单）

顶层文件：SKILL.md、README.md、manifest.yaml、architecture.md、SANDBOX-RULES.md、ALLOWED-FILES.md

目录：contracts/、static/、references/、src/、agents/、templates/、rag/、questions/per_item/

除此之外的一切（评测标注、判分器、轨迹、历史跑批、答案、注入剧本、操作手册）都不应出现；出现即为构建事故，由 `_builder/audit_leak.py` 判红。
