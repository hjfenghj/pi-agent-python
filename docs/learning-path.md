# pi-agent-python 学习路径

> 本项目是 TypeScript 版 Pi Agent 的简化 Python 实现，
> 总共约 1650 行代码，适合作为理解 Agent 架构的学习材料。
> 配套阅读：[代码架构全景](./architecture.md)

## 学习心法

1. **先跑通再读代码** — 先用真实 API Key 跑一次，观察行为
2. **自底向上** — 从类型定义开始，逐层往上
3. **一次只追一条线** — 比如「LLM 返回的工具调用怎么被执行的」
4. **对照架构图** — 读每个文件前，先看架构图定位它在哪一层

---

## 第一阶段：跑起来，建立感性认知（30 分钟）

### 目标

让 Agent 跑起来，观察它如何调用工具。

### 步骤

```bash
cd /Users/hjfeng/Documents/code/code/pi-agent-python

# 安装依赖（如果还没装）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 设置 API Key
export ZAI_CODING_CN_API_KEY="你的key"

# Print 模式测试（一问一答）
.venv/bin/python main.py -p "你好，你是谁"

# 让它用工具
.venv/bin/python main.py -p "读一下当前目录下的 README.md"

# 交互式 TUI
.venv/bin/python main.py
# 输入: 帮我在 /tmp 创建一个 hello.py，内容是打印 hello world
# 观察它如何调用 write 工具
# 然后输入: 运行它
# 观察它如何调用 bash 工具

# 试斜杠命令
# /tools — 看有哪些工具
# /history — 看消息历史
# /model — 看当前模型
```

### 检验标准

你能回答：Agent 是怎么知道当前目录有哪些文件的？（它用了什么工具）

---

## 第二阶段：读类型定义（15 分钟）

### 目标

理解 Agent 内部的数据结构。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/agent/types.py` | 120 | 全部读完，这是最简单的文件 |

### 需要理解的类型

```
Message         ← 一条对话消息（谁说的、内容、工具调用）
  ├── Role      ← 枚举: USER / ASSISTANT / TOOL
  ├── ToolCall  ← LLM 说"我要调用 read 工具"
  └── ToolResult ← 工具执行后的返回结果

ToolDefinition  ← 工具的"说明书"（名字、描述、参数schema）
AgentConfig     ← 全局配置（模型名、API Key、工作目录）
```

### 检验标准

你能解释 `Message` 的 `tool_calls` 和 `tool_call_id` 分别在什么时候使用。

---

## 第三阶段：读一个工具实现（20 分钟）

### 目标

理解「工具」到底是什么。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/tools/base.py` | 57 | Tool 抽象基类、ToolRegistry 注册表 |
| 2 | `src/tools/read.py` | 88 | 最典型的工具实现 |

### 关键理解

```python
class Tool(ABC):
    name        # 工具名（LLM 看到的）
    description # 描述（LLM 靠这个判断何时使用）
    parameters  # JSON Schema（LLM 据此生成参数）
    execute()   # 实际执行逻辑
```

工具的本质：**一个有类型安全参数的异步函数**，LLM 通过 description 和 parameters
决定何时、如何调用它。

### 练习

读完 `read.py` 后，快速浏览其他工具看它们的模式是否一致:
- `write.py` (56 行) — 写入文件
- `edit.py` (72 行) — 替换文件内容
- `bash.py` (74 行) — 执行命令

### 检验标准

你能照着 `read.py` 的模式，写一个新的工具（比如 `current_time`）。

---

## 第四阶段：读 LLM 客户端（30 分钟）

### 目标

理解 LLM API 的流式调用和工具调用解析。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/llm/client.py` | 145 | 全部读完 |

### 分段理解

**Part 1: stream_chat() 发送请求** (约 30 行)
- 构建 payload（model、messages、tools、stream=True）
- httpx 异步流式 POST
- 逐行读取 SSE（Server-Sent Events）格式

**Part 2: SSE 解析** (约 40 行)
- `data: {...}` 格式的行解析
- `[DONE]` 标记结束
- 从 delta 中提取文本增量和工具调用片段

**Part 3: build_assistant_message()** (约 20 行)
- 把流式累积的碎片拼装成完整 Message
- 工具参数从字符串反序列化为 dict

### 关键概念

```
SSE 流中的一行:
  data: {"choices":[{"delta":{"content":"你"}}]}
                              ↓
                    yield {"type": "text", "content": "你"}
                              ↓
                    TUI 实时打印 "你"
```

工具调用的流式传输更复杂——LLM 会分段返回参数 JSON:
```
tool_call_start  → {"id": "call_001", "name": "read"}
tool_call_args   → {"delta": "{\"file"}     ← 第一片
tool_call_args   → {"delta": "_path\": \""} ← 第二片
tool_call_args   → {"delta": \"main.py\"}"} ← 第三片
done             → 拼接得到完整 JSON: {"file_path": "main.py"}
```

### 检验标准

你能解释：为什么工具参数需要「增量拼装」而不是一次性返回。

---

## 第五阶段：读 Agent Loop 核心（30 分钟）

### 目标

理解整个系统的心脏——LLM ↔ 工具的循环。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/agent/loop.py` | 194 | 全部读完，这是最重要的文件 |

### 核心逻辑（重点理解）

```python
async def run(self, user_input, history, on_event):
    history.append(Message(role=USER, content=user_input))

    for turn in range(max_turns):         # 防止无限循环
        # 1. 调 LLM
        async for event in client.stream_chat(history, tools):
            if event is text:             # 文本增量 → 回调 TUI
                on_event(text_delta)
            if event is tool_call:        # 工具调用 → 累积参数
                collect(tool_call)

        # 2. 构建 assistant 消息
        history.append(assistant_message)

        # 3. 没有工具调用 → 结束
        if not assistant.tool_calls:
            break

        # 4. 执行工具
        for tc in assistant.tool_calls:
            result = await tool.execute()
            history.append(Message(role=TOOL, content=result))

        # 5. 回到步骤 1，LLM 拿到工具结果继续思考
```

### AgentEvent 事件系统

AgentLoop 通过事件回调（on_event）与 TUI 解耦:

```
AgentLoop                    TUIApp
    │                           │
    │ ──text_delta─────────────→│  实时打印 LLM 文本
    │ ──tool_start──────────────→│  显示工具调用面板
    │ ──tool_result─────────────→│  显示工具结果面板
    │ ──assistant_done──────────→│  换行
    │                           │
```

这是一个**观察者模式**——Loop 不知道 TUI 的存在，只管发事件。

### 检验标准

你能画出 Agent 执行 `"读一下 main.py 然后告诉我行数"` 时，messages 列表的变化过程。

<details>
<summary>参考答案</summary>

```
[USER]    "读一下 main.py 然后告诉我行数"
[ASSISTANT] tool_calls: [read(file_path="main.py")]
[TOOL]    read: "文件: main.py (173 行)..."
[ASSISTANT] "main.py 共有 173 行"
```

两次 LLM 调用，中间一次工具执行。
</details>

---

## 第六阶段：读 TUI 交互层（30 分钟）

### 目标

理解用户输入如何到达 Agent Loop，事件如何渲染到屏幕。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/tui/app.py` | 314 | 重点看 run()、_handle_command()、_handle_chat() |

### 分段理解

**Part 1: 初始化** (约 50 行)
- 注册工具到 ToolRegistry
- 创建 LLMClient、Session、AgentLoop
- 设置命令历史文件

**Part 2: 主循环 run()** (约 20 行)
- prompt_toolkit 异步接收输入
- 斜杠命令 → _handle_command()
- 普通文本 → _handle_chat()

**Part 3: 斜杠命令 _handle_command()** (约 40 行)
- /model、/clear、/history、/tools、/sessions、/help、/quit

**Part 4: 对话处理 _handle_chat()** (约 50 行) — 核心
- 创建事件回调函数 on_event
- 调用 agent_loop.run()
- on_event 内部根据事件类型用 rich 渲染

**Part 5: UI 辅助** (约 50 行)
- _print_banner() — 启动横幅
- _print_help() — 命令列表
- _show_sessions() — 会话列表
- _show_history() — 消息历史

### 检验标准

你能解释：用户输入 `/model glm-4-plus` 后发生了什么（从输入到模型切换的完整路径）。

---

## 第七阶段：读会话持久化（15 分钟）

### 目标

理解对话如何保存和恢复。

### 阅读

| 顺序 | 文件 | 行数 | 关注什么 |
|------|------|------|----------|
| 1 | `src/agent/session.py` | 149 | JSONL 读写逻辑 |

### 关键设计

- **存储格式**: 每行一个 JSON 对象（JSONL）
- **存储位置**: `~/.pi-agent-python/sessions/<id>.jsonl`
- **追加模式**: 每条消息 append 一行，不会重写整个文件
- **加载**: 逐行读取 JSON，反序列化为 Message

### 与 TS 版的区别

| 特性 | TS 版 | Python 版 |
|------|-------|-----------|
| 存储格式 | JSONL | JSONL（相同） |
| 分支树 | 支持（树形导航） | 不支持（线性） |
| 压缩 | 自动摘要 | 不支持 |
| 元数据 | 丰富的条目类型 | 仅消息 |

---

## 第八阶段：读入口和系统提示词（10 分钟）

### 阅读

| 文件 | 行数 | 关注什么 |
|------|------|----------|
| `main.py` | 173 | 参数解析、模式选择、API Key 解析逻辑 |
| `src/prompt/system.py` | 41 | 系统提示词的构建 |

### main.py 的两种模式

```
python main.py              → run_interactive() → TUIApp.run()
python main.py -p "prompt"  → run_print_mode()  → 直接调用 AgentLoop
```

Print 模式是交互模式的简化版——跳过了 TUI，直接循环输出。

---

## 学习总结

### 各文件难度和重要性

| 文件 | 行数 | 难度 | 重要性 | 建议阅读时间 |
|------|------|------|--------|-------------|
| `agent/types.py` | 120 | ★ | ★★★ | 15 min |
| `tools/base.py` | 57 | ★ | ★★ | 10 min |
| `tools/read.py` | 88 | ★ | ★★ | 15 min |
| `llm/client.py` | 145 | ★★★ | ★★★ | 30 min |
| `agent/loop.py` | 194 | ★★ | ★★★★★ | 30 min |
| `tui/app.py` | 314 | ★★ | ★★★ | 30 min |
| `agent/session.py` | 149 | ★★ | ★★ | 15 min |
| `main.py` | 173 | ★ | ★ | 10 min |
| `prompt/system.py` | 41 | ★ | ★ | 5 min |

### 核心知识点检查清单

- [ ] Agent 的本质是什么？（LLM + 工具调用循环）
- [ ] Message 的三种角色分别在什么时候出现？
- [ ] 工具的 parameters（JSON Schema）有什么用？
- [ ] SSE 流式响应是怎么解析的？
- [ ] 工具调用的参数为什么要增量拼装？
- [ ] Agent Loop 在什么条件下停止循环？
- [ ] on_event 回调是如何解耦 Loop 和 TUI 的？
- [ ] 会话持久化为什么用 JSONL 而不是 JSON？
- [ ] Print 模式和交互模式的区别是什么？

### 进阶练习

1. **添加一个新工具**: 写一个 `list_dir` 工具，列出指定目录的文件
2. **添加 /compact 命令**: 调用 LLM 对历史消息生成摘要，替换原始消息
3. **添加会话恢复**: `/load <session_id>` 命令加载历史会话
4. **添加中止功能**: 在 Agent 执行中支持 Ctrl+C 中断当前循环
