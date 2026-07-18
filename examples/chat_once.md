# chat_once.py 说明文档

> 体验非流式 LLM 输出的示例脚本。

---

## 这个脚本是干什么的？

`chat_once.py` 是一个**体验工具**，让你直观感受**非流式输出**的效果。

运行后你会观察到：

```
$ python examples/chat_once.py "解释什么是递归"

问题: 解释什么是递归
模型: glm-4-flash
----------------------------------------
                                    ← 这里安静等待约 2 秒
----------------------------------------
回答: 递归是指一个函数在执行过程中调用自身的编程技巧...
```

**关键体验点**：等待几秒后，回答**一次性全部出现**——这就是非流式输出的感觉。

---

## 为什么要体验这个？

`pi-agent-python` 的 TUI 默认用**流式模式**（逐字显示，打字机效果）。但项目里也实现了**非流式模式**（一次性返回）。

两者的体验差异只有亲身体验才能感受到：

| 体验 | 流式（TUI 默认） | 非流式（本脚本） |
|------|-----------------|-----------------|
| 第一字出现时间 | 立刻（~0.1s） | 等待几秒 |
| 输出节奏 | 逐字蹦出 | 一次性全部出现 |
| 心理感受 | "AI 在思考并说出来" | "AI 想好了告诉我" |

**一句话总结**：
- 流式 = 边想边说（实时）
- 非流式 = 想好再说（一次性）

---

## 使用方式

### 1. 准备环境

```bash
cd /Users/hjfeng/Documents/code/code/pi-agent-python
source .venv/bin/activate
export ZAI_CODING_CN_API_KEY="你的key"
```

### 2. 运行

```bash
# 传入任何问题
python examples/chat_once.py "1+1=?"
python examples/chat_once.py "什么是 Agent 框架"
python examples/chat_once.py "用三句话介绍 Python"

# 不传参（使用默认问题）
python examples/chat_once.py
```

### 3. 体验对比

建议先运行流式 TUI 感受一下，再运行本脚本，对比两种输出的"手感"：

```bash
# 步骤 A: 体验流式（TUI）
python main.py
# 输入问题，观察逐字显示的效果
# /quit 退出

# 步骤 B: 体验非流式（本脚本）
python examples/chat_once.py "同样的问题"
# 观察一次性输出的效果
```

---

## 背后的原理（简要）

```
流式 (stream=True)              非流式 (stream=False)
───────────────                ───────────────────
LLM 生成 token → 立刻推送       LLM 生成 token → 攒在服务器端
       ↓                              ↓
客户端逐字收到                   等所有 token 生成完
       ↓                              ↓
逐字显示                         一次性返回完整 JSON
```

对应的代码：
- 流式：`async for event in client.stream_chat(...)`（`client.py:stream_chat`）
- 非流式：`response = await client.chat(...)`（`client.py:chat`）

---

## 相关文件

- [`examples/chat_once.py`](chat_once.py) - 本脚本
- [`src/llm/client.py`](../src/llm/client.py) - `chat()` 和 `stream_chat()` 的实现
- [`docs/q&a.md`](../docs/q&a.md) - Q3: 为什么工具参数需要「增量拼装」（涉及流式原理）
