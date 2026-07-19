# 核心知识检查清单 Q&A

> 本文逐一回答 [`learning-path.md`](./learning-path.md) 末尾「核心知识点检查清单」的 9 个问题，
> 作为完整读完代码后的自我检测参考答案。
> 配合 [`q&a.md`](./q&a.md)（13 个进阶问答）一起看效果更好。

---

## Q1: Agent 的本质是什么？

### 答案

**Agent = LLM + 工具调用循环（Agent Loop）**

单靠 LLM 只能"说话"，加上工具才能"做事"。Agent 的本质就是让 LLM 反复地**思考 → 调用工具 → 看结果 → 继续思考**，直到解决问题。

### 代码定位

`src/agent/loop.py:33-42` 的 `AgentLoop` 类注释：

```python
class AgentLoop:
    """
    Agent 核心循环。

    流程:
        1. 把用户消息加入历史
        2. 调用 LLM（流式）
        3. 如果 LLM 请求工具 → 执行工具 → 把结果加入历史 → 回到 2
        4. 如果 LLM 直接回复 → 返回结果
    """
```

### 流程图

```
用户输入
   ↓
[LLM 思考] ←─────────┐
   ↓                 │
需要工具？           │
   ├─ 否 → 返回回答（结束）
   └─ 是             │
       ↓             │
   [执行工具]        │
       ↓             │
   [结果加入 history]─┘
```

### 类比

```
LLM 单独使用 = 一个会说话的脑（只能聊天）
Agent        = 脑 + 手 + 眼（能调用工具改变世界）
```

LLM 是决策者（决定用什么工具），Loop 是执行者（真正调用工具），二者结合就是 Agent。

---

## Q2: Message 的三种角色分别在什么时候出现？

### 答案

`src/agent/types.py` 定义了三种 `Role`，对应对话中的不同角色：

| Role | 谁产生的 | 什么时候出现 | 例子 |
|------|---------|------------|------|
| `USER` | 用户 | 用户每次输入时 | `"读一下 main.py"` |
| `ASSISTANT` | LLM | LLM 每次回复时（可能带工具调用） | `"我调用 read 工具"` 或 `"main.py 有 173 行"` |
| `TOOL` | 工具执行 | 工具执行完返回结果时 | `"文件: main.py (173 行)..."` |

### 一次完整对话的 messages 变化

用户问 `"读一下 main.py"`：

```python
# ① 用户输入
[
    {"role": "USER", "content": "读一下 main.py"}
]

# ② LLM 决定调用 read 工具
[
    {"role": "USER", "content": "读一下 main.py"},
    {"role": "ASSISTANT", "tool_calls": [{"name": "read", "args": {"file_path": "main.py"}}]}
]

# ③ 工具执行完，结果加入
[
    {"role": "USER", "content": "读一下 main.py"},
    {"role": "ASSISTANT", "tool_calls": [{"name": "read", ...}]},
    {"role": "TOOL", "content": "文件: main.py (173 行)...", "tool_call_id": "call_001"}
]

# ④ LLM 看到工具结果，给出最终回答
[
    {"role": "USER", "content": "读一下 main.py"},
    {"role": "ASSISTANT", "tool_calls": [{"name": "read", ...}]},
    {"role": "TOOL", "content": "文件: main.py (173 行)..."},
    {"role": "ASSISTANT", "content": "main.py 共有 173 行"}
]
```

### 关键规则

- **USER 和 ASSISTANT 交替出现**（一问一答）
- **ASSISTANT 后面可以跟多个 TOOL**（一次调用多个工具）
- **TOOL 消息必须带 `tool_call_id`**，告诉 LLM 这是哪个工具调用的结果

---

## Q3: 工具的 parameters（JSON Schema）有什么用？

### 答案

`parameters` 是工具的**参数说明书**，告诉 LLM「这个工具接受什么参数、什么类型、是否必填」。LLM 据此生成合法的调用参数。

### 代码定位

`src/tools/read.py:25-45` 的 ReadTool：

```python
@property
def parameters(self) -> dict:
    return {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要读取的文件路径",
            },
            "start_line": {
                "type": "integer",
                "description": "起始行号（可选）",
            },
            "end_line": {
                "type": "integer",
                "description": "结束行号（可选）",
            },
        },
        "required": ["file_path"],   # ← 必填参数
    }
```

### 工作流程

```
1. 启动时: Loop 把所有工具的 parameters 发给 LLM
    POST /chat/completions
    body: {
        "tools": [
            {
                "name": "read",
                "description": "读取文件内容",
                "parameters": { ... JSON Schema ... }   ← LLM 看这个
            },
            ...
        ]
    }

2. 用户: "读一下 main.py"

3. LLM 根据 parameters 生成调用:
    "file_path 是 string，必填 → 我传 'main.py'"
    "start_line 是 integer，可选 → 我不传"

4. LLM 返回:
    tool_calls: [{"name": "read", "arguments": {"file_path": "main.py"}}]
```

### 没有 parameters 会怎样？

```
没有 parameters:
    LLM 不知道工具需要什么参数
    可能传错类型（file_path=123 而不是 "main.py"）
    可能漏传必填参数

有 parameters:
    LLM 按规范生成参数
    类型对、必填项不漏
```

**JSON Schema 是 LLM 和工具之间的"契约"**。

---

## Q4: SSE 流式响应是怎么解析的？

### 答案

SSE（Server-Sent Events）是 HTTP 长连接协议，服务器**逐行推送**数据，客户端**逐行接收并解析**。

### SSE 格式

```
data: {"choices":[{"delta":{"content":"你"}}]}

data: {"choices":[{"delta":{"content":"好"}}]}

data: [DONE]
```

每行格式：`data: <JSON>`，以空行分隔，`[DONE]` 表示结束。

### 解析代码

`src/llm/client.py:168-192`：

```python
async for line in response.aiter_lines():           # 逐行读取
    if not line.startswith("data: "):
        continue                                    # 不是 SSE 格式，跳过
    data = line[6:]                                 # 去掉 "data: " 前缀
    if data.strip() == "[DONE]":
        yield {"type": "done", ...}                 # 结束信号
        return
    chunk = json.loads(data)                        # 解析 JSON
    delta = chunk["choices"][0]["delta"]
    if "content" in delta:
        yield {"type": "text", "content": delta["content"]}      # 文本碎片
    elif "tool_calls" in delta:
        yield {"type": "tool_call_start" / "tool_call_args", ...} # 工具碎片
```

### 关键点

| 步骤 | 做什么 |
|------|-------|
| `aiter_lines()` | 异步逐行读取响应流（不阻塞） |
| `startswith("data: ")` | 过滤非 SSE 格式的行（注释、心跳等） |
| `line[6:]` | 去掉 `"data: "` 前缀，只留 JSON |
| `"[DONE]"` | 流结束标记 |
| `json.loads()` | 把 JSON 字符串解析成 Python dict |

### 为什么用 SSE 不用 WebSocket？

```
SSE:
    单向（服务器 → 客户端）
    基于 HTTP，简单
    自动重连
    适合 LLM 流式输出

WebSocket:
    双向
    协议升级复杂
    适合实时聊天室、游戏
```

LLM 响应是单向的（服务器推送），SSE 足够且更简单。

---

## Q5: 工具调用的参数为什么要增量拼装？

### 答案

因为**流式模式下，所有内容（包括工具参数 JSON）都是逐 token 推送的**，服务器不会等参数生成完才发。

### 流式工具调用过程

LLM 要调用 `read(file_path="main.py")`，SSE 流这样推送：

```
data: {"delta": {"tool_calls": [{"id": "call_001", "name": "read"}]}}
                                                            ↑ 先发 id 和 name

data: {"delta": {"tool_calls": [{"arguments": "{\"file"}]}}
                                                ↑ 参数第一片

data: {"delta": {"tool_calls": [{"arguments": "_path\": \""}]}}
                                                ↑ 参数第二片

data: {"delta": {"tool_calls": [{"arguments": "main.py\"}"}]}}
                                                ↑ 参数第三片

data: [DONE]
```

### 拼装逻辑

`src/llm/client.py:206-220`：

```python
elif event["type"] == "tool_call_start":
    tool_call_parts[idx] = {
        "id": event["id"],
        "name": event["name"],
        "arguments": "",          # ← 初始化空字符串
    }
elif event["type"] == "tool_call_args":
    tool_call_parts[idx]["arguments"] += event["delta"]    # ← 逐片追加
```

最终：

```python
# 累积过程:
"{\"file" + "_path\": \"" + "main.py\"}" = "{\"file_path\": \"main.py\"}"

# 解析成 dict:
json.loads("{\"file_path\": \"main.py\"}") = {"file_path": "main.py"}
```

### 为什么不一次性返回？

```
非流式（一次性）:
    服务器等 LLM 把整个 JSON 生成完 → 一次性返回
    用户体验: 等 2 秒，啥都没有，然后突然出现

流式（增量）:
    LLM 每生成一个 token 就推送
    用户体验: 立刻看到输出在"打字"
```

**LLM 本质上是逐 token 生成的**（自回归模型），服务器无法"等一下再发"，只能来一个 token 推一个。所以客户端必须自己拼装。

---

## Q6: Agent Loop 在什么条件下停止循环？

### 答案

两个退出条件（看 `src/agent/loop.py:74-144`）：

### 条件 1: LLM 不再请求工具（正常结束）

```python
# loop.py:130-132
if not assistant_msg.tool_calls:
    break    # ← LLM 直接回复了文本，不需要工具，循环结束
```

这是最常见的退出方式。LLM 觉得"我已经知道答案了"，直接给出文本回复。

### 条件 2: 达到最大轮数（防止死循环）

```python
# loop.py:74
for turn in range(self.config.max_turns):    # ← 最多 max_turns 轮
    ...
```

兜底机制，防止 LLM 反复调用工具停不下来。

### 例子

```
用户: "1+1=?"

第 1 轮:
    LLM 直接回复 "1+1=2"（没有 tool_calls）
    → 触发条件 1，循环结束

用户: "读一下 main.py 然后告诉我行数"

第 1 轮:
    LLM: tool_calls=[read(file_path="main.py")]    ← 需要工具
    工具执行 → 结果加入 history
    → 继续下一轮

第 2 轮:
    LLM: "main.py 共有 173 行"（没有 tool_calls）    ← 直接回答
    → 触发条件 1，循环结束
```

### 何时触发条件 2？

```
配置 max_turns=10

如果 LLM 一直调用工具（比如 bug 导致反复读文件）:
    第 1 轮 → 工具
    第 2 轮 → 工具
    ...
    第 10 轮 → 工具
    → for 循环结束，强制退出
```

### 完整退出逻辑

```python
for turn in range(max_turns):        # 退出条件 2: 达到上限
    # ... 调用 LLM ...
    if not assistant.tool_calls:
        break                        # 退出条件 1: LLM 不需要工具
    # ... 执行工具 ...

return history                       # 最终返回
```

---

## Q7: on_event 回调是如何解耦 Loop 和 TUI 的？

### 答案

`on_event` 是一个**事件回调函数**，Loop 通过它广播事件，TUI 通过它接收事件——两者互不依赖。

### 解耦前的耦合设计（反面教材）

```python
# ❌ 假设没有 on_event，Loop 直接操作 TUI:
class AgentLoop:
    async def run(self, user_input, history, tui: TUIApp):
        for event in self.stream_chat(...):
            if event is text:
                tui.console.print(event.content)    # ← 直接调用 TUI
            if event is tool_start:
                tui.show_tool_panel(event.name)    # ← Loop 必须知道 TUI 的 API
```

问题：
- Loop 依赖具体的 TUI 类
- 想换成 Web UI？改 Loop
- 想做测试？必须 mock TUI
- 加新功能（审计、日志）？改 Loop

### 解耦后的设计（本项目）

```python
# ✅ 用 on_event 解耦
class AgentLoop:
    async def run(self, user_input, history, on_event=None):
        for event in self.stream_chat(...):
            if event is text and on_event:
                await on_event(AgentEvent(kind="text_delta", ...))
                                    # ↑ Loop 不知道 on_event 具体做什么
```

Loop 只管"发生了一件事，通知一下"，**完全不知道**接收方是谁、做什么。

### TUI 的实现

```python
# src/tui/app.py:211-258
async def on_event(event: AgentEvent):
    if event.kind == "text_delta":
        self.console.print(event.data["content"])   # ← TUI 选择"打印"
    elif event.kind == "tool_start":
        self.console.print(Panel(...))              # ← TUI 选择"显示面板"

await self.loop.run(input, history, on_event=on_event)
                    # ↑ 把回调函数传给 Loop
```

### 解耦的价值

同一个 Loop，接入不同前端，**Loop 一行都不改**：

```
TUI 模式:      on_event → console.print(Panel(...))
Print 模式:    on_event → print(content, end="")
Web 模式:      on_event → websocket.send(event.data)
测试模式:      on_event → events_list.append(event)
审计模式:      on_event → audit_log.write(event)
```

这是经典的**观察者模式（Observer Pattern）**——定义"发生了什么"，不管"谁来处理"。

---

## Q8: 会话持久化为什么用 JSONL 而不是 JSON？

### 答案

JSONL（JSON Lines）每行一个 JSON 对象，**天然支持追加写入**；JSON 整个文件是一个对象，每次修改都要**重写整个文件**。

### JSONL vs JSON

```
JSONL（本项目用）:
    {"role": "user", "content": "你好"}
    {"role": "assistant", "content": "你好！"}
    {"role": "user", "content": "1+1=?"}
    {"role": "assistant", "content": "2"}

JSON（不用）:
    [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
        {"role": "user", "content": "1+1=?"},
        {"role": "assistant", "content": "2"}
    ]
```

### 核心差异：追加写入

```python
# JSONL 追加（O(1)，快）:
with file.open("a") as f:
    f.write(json.dumps(msg) + "\n")    # ← 只写一行

# JSON 追加（O(n)，慢）:
data = json.loads(file.read_text())    # 1. 读整个文件
data.append(msg)                       # 2. 修改
file.write_text(json.dumps(data))      # 3. 重写整个文件
```

### 对比表

| 特性 | JSONL | JSON |
|------|-------|------|
| 写入方式 | 追加一行 | 重写整个文件 |
| 写入性能 | O(1) | O(n) |
| 读取方式 | 逐行读 | 一次性读 |
| 流式处理 | ✅ 天然支持 | ❌ 必须全部读完 |
| 崩溃恢复 | ✅ 只丢最后一行 | ❌ 整个文件损坏 |
| 可读性 | 每行一条 | 整体缩进 |
| 部分加载 | ✅ 读前 N 行 | ❌ 全读 |

### 代码定位

`src/agent/session.py:100-113` 的追加写入：

```python
def append(self, msg: Message):
    """追加一条消息并持久化。"""
    self.messages.append(msg)
    entry = self._message_to_entry(msg)
    with self.file_path.open("a", encoding="utf-8") as f:   # ← "a" = append
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

### 崩溃恢复的例子

```
写到一半程序崩溃:

JSONL:
    {"role": "user", "content": "你好"}
    {"role": "assistant", "content": "你好！"}
    {"role": "user", "content": "1+1"     ← 最后一行损坏
    → 重启时跳过损坏行，前面的消息完整保留

JSON:
    [
        {"role": "user", ...},
        {"role": "assistant", ...},
        {"role": "user", "content": "1+1"    ← JSON 不完整
    → 重启时 json.loads() 失败，整个文件不可用
```

---

## Q9: Print 模式和交互模式的区别是什么？

### 答案

两种模式共用同一套 Agent 核心（`AgentLoop`），区别在**入口和输出方式**。

### 对比

| 特性 | Print 模式 | 交互模式（TUI） |
|------|-----------|---------------|
| 启动命令 | `python main.py -p "prompt"` | `python main.py` |
| 入口函数 | `run_print_mode()` | `run_interactive()` → `TUIApp.run()` |
| 输入次数 | 一次（命令行参数） | 多次（交互式输入） |
| 输出方式 | 简单 print | rich（颜色、面板、Markdown） |
| 斜杠命令 | ❌ 不支持 | ✅ 支持 |
| 会话持久化 | ❌ 不保存 | ✅ 自动保存 |
| on_event 实现 | 简单 print | rich Panel 渲染 |
| 适用场景 | 脚本、测试、CI | 日常对话、开发 |

### 代码定位

`main.py` 的两种模式：

```python
# main.py
if args.print:
    asyncio.run(run_print_mode(args.print, config))   # Print 模式
else:
    asyncio.run(run_interactive(config))              # 交互模式
```

### Print 模式的 on_event

`main.py:126-137`：

```python
async def on_event(event):
    if event.kind == "text_delta":
        print(event.data["content"], end="", flush=True)    # ← 简单 print
    elif event.kind == "tool_start":
        print(f"\n[工具] {event.data['name']}(...)")        # ← 简单文本
    elif event.kind == "tool_result":
        print(f"[结果] {content}")
```

### 交互模式的 on_event

`src/tui/app.py:211-258`：

```python
async def on_event(event: AgentEvent):
    if event.kind == "text_delta":
        self.console.print(event.data["content"], style=COLOR_ASSISTANT)   # ← rich 样式
    elif event.kind == "tool_start":
        self.console.print(Panel(                                          # ← rich 面板
            Text(f"{name}({args_str})", style=COLOR_TOOL),
            border_style=COLOR_TOOL,
            title=f"工具调用: {name}",
        ))
    elif event.kind == "tool_result":
        self.console.print(Panel(...))                                     # ← rich 面板
```

### 共用核心

```python
# 两种模式都调用同一个 Loop:
await loop.run(
    user_input,
    history,
    on_event=on_event,    # ← 唯一差异：on_event 的实现不同
)
```

**这是解耦的最佳证明**——同一套 Agent 逻辑，只换 `on_event` 就能适配完全不同的使用场景。

---

## 总结对照表

| 问题 | 一句话答案 |
|------|----------|
| Q1 Agent 本质 | LLM + 工具调用循环 |
| Q2 三种角色 | USER（用户输入）、ASSISTANT（LLM 回复）、TOOL（工具结果） |
| Q3 parameters | 工具参数的 JSON Schema，LLM 据此生成合法参数 |
| Q4 SSE 解析 | 逐行读 → 过滤 `data: ` 前缀 → JSON 解析 → yield 事件 |
| Q5 增量拼装 | 流式模式下参数是逐 token 推送的，必须自己拼 |
| Q6 停止条件 | LLM 不再请求工具 / 达到 max_turns |
| Q7 on_event 解耦 | 观察者模式，Loop 只发事件，不知道接收方是谁 |
| Q8 用 JSONL | 支持追加写入（O(1)）、崩溃恢复、流式读取 |
| Q9 Print vs 交互 | 共用 Loop，差异只在 on_event 实现 |

---

## 相关文档

- [`learning-path.md`](./learning-path.md) - 8 阶段学习路径
- [`architecture.md`](./architecture.md) - 代码架构详解
- [`q&a.md`](./q&a.md) - 13 个进阶问答
