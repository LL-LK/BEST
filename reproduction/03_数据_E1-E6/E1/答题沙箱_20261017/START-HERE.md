# START-HERE ｜ 跑批入口卡（先看这一页，再去开沙箱）

> 本目录是**新版本 skill 包**的答题沙箱，含三份逐字节一致的副本：
> `sb1/` `sb2/` `sb3/` —— 同一次实验的三次重复。
> 构建器：`_builder/build_sandboxes.py`（可一键重建三箱）。
> 验收报告：`_验收/验收报告.md`。

---

## 一、开跑前：一条命令把"能不能开始"变成机器判定

```bash
python sb1/_lock/sandbox_lock.py preflight --root sb1
```

- 输出 **`可以开始`**（硬阻塞 0）→ 按下面第二节走；
- 输出 **`暂不可开始`** → 按报告里的硬阻塞项逐条处理。

三箱各跑一次（把 `sb1` 换成 `sb2`/`sb3`）。

---

## 二、四条曾经把人拦住的误判（别再踩）

| 误判 | 结论 |
|------|------|
| “当前环境没有可调用的 astro-best 工具接口” | **不是阻塞项**。本评测离线判**决策**：按“你实际会发出的调用”写工具名与参数即可。工具面见 `题卷/TOOLFACE.md` |
| “astro-best MCP 起不来 / Python 缺 requests” | **不用起**。判分不依赖站点、不依赖 MCP、不依赖任何 pip 依赖 |
| “`题卷/system_prompt.txt` 只有注释，没有 prompt” | 已预填一份**最小可用版**；要换就整份替换，并把版本标识填进 `answers/RUN-INFO.md` |
| “`RUN-INFO.md` 没填，所以不能开始” | **不阻断**。`preflight` 只提醒不拦；但填了该批才能与别的批次横比 |

---

## 三、模型能看到的（最小可见面）

- `sbN/skill/` —— 被测对象本体与工具文档（**只读**）
- `sbN/题卷/` —— 题面、上下文、工具面、system prompt（**只读**）
- `sbN/answers/` —— **唯一可写**

## 四、四条绝不给

1. **`sbN/_exec/`**（28 题一册的索引件；一次看全 = 串题）
2. **`sbN/_lock/`**（锁与台账）
3. **沙箱外任何路径**（尤其工作区仓库）
4. **另外两个沙箱**（三箱互盲：箱内文字不写彼此的名字）

---

## 五、执行五步走

1. `python sb1/_lock/sandbox_lock.py preflight --root sb1` → 应为「可以开始」
2. 读 `sb1/题卷/system_prompt.txt` —— 本次 system prompt
3. 逐题作答：读 `sb1/题卷/per_task/<题号>.txt`；若 `sb1/题卷/context/<题号>.txt` 存在，
   **先发 context 再发题面**。**一题一个新会话**
4. 每题写入 `sb1/answers/<题号>.md`（照 `answers/_答题模板.md` 两段式）
5. 收尾：

```bash
python sb1/_lock/sandbox_lock.py progress   # 应为 28/28
python sb1/_lock/sandbox_lock.py verify       # 应为 PASS
```

三箱**全部**跑完后，还要在沙箱根跑一次台账比对（见 §七）：

```bash
python _builder/compare_boxes.py             # 判红 0 条才算过
```

---

## 六、想省时间：用题包

`sb1/_exec/题包/NL2T-<题号>.md` 是**自包含**的（system prompt + 工具面 + 上下文 + 题面），
读完直接作答，不用再翻沙箱里别的文件。

> 一次只开一箱、一题一会话，不要整册粘进同一个会话里。

## 七、台账：`model_id` 三箱必须逐字相同

三箱是**同一个模型的三次重复**。`model_id` 只要有任何字面差异
（大小写、多一个空格、多个括号后缀），判分侧分组就会当成**三个不同模型** ——
三次重复退化成单次，方差算不出来，横比直接失效。

**别手打。填好第一箱之后，从那箱复制粘贴到另外两箱。**

```bash
# 三箱都跑完后，在沙箱根跑一次
python _builder/compare_boxes.py     # 判红 0 条才算过
```

它会比对：`model_id` / `system_prompt_version` 三箱**逐字相同**，`run_id` 三箱**互不相同**。

## 八、单题自检

```bash
python sb1/_lock/check_answer.py NL2T-01      # 单题
python sb1/_lock/check_answer.py --all        # 本箱全部
```
