# pi-agent-python 问答汇总

> 本文档整理了学习 pi-agent-python 过程中的核心问答，涵盖概念理解、代码细节和知识点补充。

---

## Q1: tool_calls 和 tool_call_id 分别什么时候使用？

它们出现在**不同的 Message 上**，分别代表一次工具调用的**请求端**和**响应端**。

### 完整示例

```
用户: "读一下 main.py"

→ Message(role=USER, content="读一下 main.py")

→ Message(role=ASSISTANT,                         ← LLM 的回复
    content=None,
    tool_calls=[ToolCall(                          ← ★ 这里用 tool_calls
        id="call_abc123",
        name="read",
        arguments={"file_path": "main.py"}
    )]
)

→ Message(role=TOOL,                              ← 工具执行结果
    content="文件: main.py (173 行)...",
    tool_call_id="call_abc123",                    ← ★ 这里用 tool_call_id
    name="read"
)
```

| 字段 | 出现在 | 含义 |
|------|--------|------|
| `tool_calls` | `role=ASSISTANT` 的消息 | LLM 说「我要调用 read 工具」，附带调用的 id、名称、参数 |
| `tool_call_id` | `role=TOOL` 的消息 | 把工具执行结果关联回对应的那个调用请求 |

`call_abc123` 这个 id 是 LLM 生成的，目的是把请求和响应对上——因为一次 assistant 回复里可能包含**多个工具调用**：

```
→ ASSISTANT (tool_calls: [
      {id: "call_001", name: "read", args: {file_path: "a.py"}},
      {id: "call_002", name: "read", args: {file_path: "b.py"}},
  ])

→ TOOL (tool_call_id: "call_001", content: "a.py 的内容...")
→ TOOL (tool_call_id: "call_002", content: "b.py 的内容...")

→ ASSISTANT "a.py 和 b.py 的内容分别是..."
```

没有 id 的话，LLM 就不知道哪个结果对应哪个请求了。

---

## Q2: 怎么看到 read.py 工具调用过程中的细节？

在 `loop.py` 的 `_execute_tool` 方法里加调试输出（输出到 stderr，不干扰正常 stdout）：

```python
def _debug(msg: str):
    import sys
    print(f"[DEBUG] {msg}", file=sys.stderr)

async def _execute_tool(self, tool_call, on_event):
    _debug(f"工具调用开始: {tool_call.name}")
    _debug(f"  调用 ID: {tool_call.id}")
    _debug(f"  参数: {json.dumps(tool_call.arguments, ensure_ascii=False)}")

    import time
    t0 = time.time()
    output = await tool.execute(**tool_call.arguments)
    elapsed = time.time() - t0

    _debug(f"  ✓ 执行完成 ({elapsed:.3f}s)")
    _debug(f"  返回 {len(output)} 字符，预览: {output[:200]}")
```

运行效果：

```
[DEBUG] ────────────────────────────────────────────
[DEBUG] 工具调用开始: read
[DEBUG]   调用 ID: call_abc123
[DEBUG]   参数: {"file_path": "README.md"}
[DEBUG]   ✓ 执行完成 (0.001s)
[DEBUG]   返回 1234 字符，预览: 文件: README.md (86 行)...
```

如果想看 LLM 返回的**原始 SSE 数据**，在 `client.py` 的 `stream_chat` 里加：

```python
async for line in response.aiter_lines():
    if line.startswith("data: "):
        data = line[6:]
        print(f"[SSE] {data[:120]}")  # 看原始数据
```

---

## Q3: 为什么工具参数需要「增量拼装」而不是一次性返回？

**是的，因为流式模式下，任何内容都是逐个 token 推送的。**

LLM 生成文本的本质是**逐 token 预测**——每次只预测下一个 token，不可能"想好整个 JSON 再一次性发"。

拿 `read(file_path="main.py")` 举例，参数 JSON 也是逐 token 生成的：

```
第 1 步: 预测下一个 token → "{"         → 推给客户端
第 2 步: 预测下一个 token → "\"file"     → 推给客户端
第 3 步: 预测下一个 token → "_path"      → 推给客户端
第 4 步: 预测下一个 token → "\": \"main"  → 推给客户端
第 5 步: 预测下一个 token → ".py\"}"     → 推给客户端
```

每一轮推理只能产出一个 token，服务器拿到一个就推一个。客户端收到的就是碎片，必须自己拼。

**为什么不能攒在服务器端拼好了再推？** 因为那样就失去了流式的意义——用户要等所有 token 生成完才看到第一个字。流式的目的就是"边生成边推送"。

文本内容也是逐 token 推送的（`"你"` → `"好"` → `"，"`），只不过文本直接拼接字符串就行。工具参数多了一步：拼完字符串后还要 `json.loads()` 解析成 dict。

---

## Q4: async with 和 async for 是什么用法？

这是 Python 异步编程的核心语法，`async` 关键字告诉 Python：**这一步可能要等待，不要阻塞整个程序**。

### async with（异步上下文管理器）

```python
# 普通 with：打开文件，用完自动关闭
with open("file.txt") as f:
    content = f.read()

# async with：打开网络连接，用完自动关闭
async with self._client.stream("POST", url) as response:
    # 在这里可以异步读取响应
```

区别在于**等待时做什么**：

```
普通 with（同步）:
  发送请求 → 等待 3 秒（CPU 空闲，什么都不做）→ 收到响应 → 继续

async with（异步）:
  发送请求 → 等待期间 CPU 可以去干别的 → 收到响应 → 继续
```

### async for（异步迭代）

```python
# 普通 for：遍历一个已在内存中的列表
for line in lines:
    print(line)

# async for：边等待边逐个接收
async for line in response.aiter_lines():
    # 服务器还没推完，这里每次 yield 一行
    # 收到第 1 行 → 处理
    # 等待...（CPU 可以干别的）
    # 收到第 2 行 → 处理
```

这就是**流式输出**的关键——GLM 服务器生成一个 token 推送一行，`async for` 逐行接收：

```
0.03s  收到 "data: {\"你\"}"   → yield
0.06s  收到 "data: {\"好\"}"   → yield
0.09s  收到 "data: {\"，\"}"   → yield
1.20s  收到 "data: [DONE]"    → 结束
```

如果用普通 `for`，必须等 1.2 秒所有数据到齐才能开始处理。

### 总结

| 语法 | 同步版本 | 区别 |
|------|---------|------|
| `async with` | `with` | 申请/释放资源时不阻塞 |
| `async for` | `for` | 逐个接收数据时不阻塞 |
| `await xxx` | `xxx()` | 调用耗时操作时不阻塞 |

---

## Q5: EventSink 事件回调是怎么用的？

用一句话说：**EventSink 是 AgentLoop 向外「广播」发生了什么的通道，让 TUI 能实时显示，但 Loop 本身不需要知道 TUI 的存在。**

### 三个角色

```
AgentLoop（引擎）          EventSink（通道）           TUIApp（界面）
    │                           │                           │
    │  "LLM 输出了一个字"        │                           │
    │ ──on_event(text_delta)──→ │ ──console.print()───────→ │
    │                           │                           │
    │  "工具开始执行了"          │                           │
    │ ──on_event(tool_start)──→ │ ──Panel(工具调用)───────→ │
    │                           │                           │
    │  "工具执行完了"            │                           │
    │ ──on_event(tool_result)→ │ ──Panel(结果)───────────→ │
```

### 定义

```python
# loop.py 第 30 行
EventSink = Callable[[AgentEvent], Awaitable[None]]
```

翻译：EventSink 是一个异步函数，接收一个 AgentEvent 参数，不返回值。

### 发送端（AgentLoop）

Loop 只管发事件，不管谁在听：

```python
async def run(self, user_input, history, on_event: EventSink | None = None):
    for turn in range(max_turns):
        if on_event:
            await on_event(AgentEvent(kind="turn_start", data={...}))

        async for event in self.client.stream_chat(...):
            if event["type"] == "text" and on_event:
                await on_event(AgentEvent(
                    kind="text_delta",
                    data={"content": event["content"]},
                ))
```

### 接收端（TUIApp）

TUIApp 定义一个函数传进去：

```python
async def _handle_chat(self, user_input):
    async def on_event(event: AgentEvent):
        if event.kind == "text_delta":
            self.console.print(event.data["content"], end="")
        elif event.kind == "tool_start":
            self.console.print(Panel(..., title="工具调用"))
        elif event.kind == "tool_result":
            self.console.print(Panel(..., title="结果"))

    await self.loop.run(user_input, history, on_event=on_event)
```

### 为什么这样设计？

解耦。Loop 不依赖任何具体 UI：

```
Print 模式的回调:     print(event.data["content"])          # 简单打印
TUI 模式的回调:       console.print(Panel(...))             # rich 面板
测试模式的回调:       collected_events.append(event)        # 收集事件做断言
Web 模式的回调:       websocket.send(event.data)            # 推到前端
```

Loop 代码一行都不用改，只是传入不同的 `on_event` 函数。这是经典的**观察者模式**。

### 事件清单

| kind | 触发时机 | data 内容 |
|------|---------|-----------|
| `turn_start` | 每轮循环开始 | `{"turn": 1}` |
| `text_delta` | LLM 输出文字（逐 token） | `{"content": "你"}` |
| `tool_start` | 工具开始执行 | `{"name":"read", "arguments":{...}}` |
| `tool_result` | 工具执行完毕 | `{"name":"read", "content":"...", "is_error":false}` |
| `assistant_done` | 整条 assistant 消息完成 | `{"content": "...", "has_tool_calls": false}` |
| `error` | 发生错误 | `{"message": "API 错误..."}` |

---

## Q6: await on_event(...) 是什么用法？

`await on_event(...)` 就是**调用那个回调函数，然后等它执行完再继续往下走**。

### 拆解

```python
await on_event(AgentEvent(kind="text_delta", data={"content": "你"}))
```

**第 1 步：`on_event(...)`** — 调用函数

`on_event` 不是一个固定的方法名，它是一个**变量**，指向调用方传入的某个异步函数：

```python
on_event = my_callback   # 传进来的函数
on_event(event)           # 调用它，就像调用普通函数一样
```

**第 2 步：`await`** — 等它执行完

因为 `on_event` 是 `async def` 定义的异步函数，调用它返回的是协程对象，不会立即执行。`await` 就是启动它并等待完成：

```python
# 没有 await：函数不会被真正执行
on_event(event)  # 只是返回一个协程对象，什么都不做

# 有 await：函数被执行，等它 return 后才继续
await on_event(event)
```

### 为什么要 await？

回调函数内部可能有异步操作，必须等它完成才能保证输出顺序：

```python
# 如果不 await，Loop 不会等回调执行完就发下一个事件
# 可能导致输出顺序混乱

await on_event(event1)  # 等这个打印完
await on_event(event2)  # 再执行下一个
```

### 用同步代码类比

```python
# 同步版本
def run(self, on_event):
    on_event("开始")          # 普通函数调用，天然等它执行完

# 异步版本
async def run(self, on_event):
    await on_event("开始")    # 异步函数调用，必须 await 才能等它执行完
```

**一句话**：`await on_event(...)` = 调用传入的回调函数，等它做完再继续。和普通函数调用的区别只是多了一个 `await`。

---

## Q7: client.py 详细解析

### 文件定位

client.py 是 Agent 和 LLM 之间的「翻译官 + 信使」：

```
Agent Loop                     client.py                     GLM 服务器
    │                             │                             │
    │  messages + tools           │                             │
    │ ──────────────────────────→ │  POST /chat/completions     │
    │                             │ ──────────────────────────→ │
    │                             │  ←── data: {"你"}           │
    │                             │  ←── data: {"好"}           │  (SSE 流)
    │                             │  ←── data: {"tool_call"...} │
    │  yield {"type":"text"...}   │  解析 + 翻译                │
    │ ←──────────────────────────  │                             │
```

### 核心知识点

**1. 为什么用 httpx.AsyncClient 而不是 requests？**

requests 是同步的——必须等 LLM 生成完所有内容才返回。httpx.AsyncClient 是异步的——可以「边接收边处理」，实现打字机效果。

**2. 什么是 SSE（Server-Sent Events）？**

LLM 服务器用 SSE 协议逐行推送数据：

```
data: {"choices":[{"delta":{"content":"你"}}]}

data: {"choices":[{"delta":{"content":"好"}}]}

data: [DONE]
```

- 每行以 `data: ` 开头（6 字符前缀）
- `delta.content` 是这次的增量内容（一个 token）
- `[DONE]` 表示流结束

**3. 什么是 delta（增量）？**

LLM 每次只生成一个 token（约一个字），用一个 chunk 推送：

```
Chunk 1: delta.content = "你"      → 累积 = "你"
Chunk 2: delta.content = "好"      → 累积 = "你好"
Chunk 3: delta.content = "，我是"  → 累积 = "你好，我是"
Chunk 4: finish_reason = "stop"   → 结束
```

**4. 工具调用为什么复杂？**

参数 JSON 也是逐 token 分片返回的：

```
第1个 chunk: 有 id 和 name，但没有 arguments
第2个 chunk: 参数碎片 → "{\"file"
第3个 chunk: 参数碎片 → "_path\": \"main.py\"}"

拼装后: json.loads("{\"file_path\": \"main.py\"}") → {"file_path": "main.py"}
```

**5. build_assistant_message 做什么？**

把流式过程中收集的碎片拼装成完整 Message：
- text_parts → 拼接成 content 字符串
- tool_call_parts → 拼接参数字符串 → json.loads 成 dict

---

## Q8: 学习 client.py 需要补充什么知识？

### 必须掌握

| 知识点 | 为什么需要 |
|--------|----------|
| **asyncio 异步编程** | 整个项目基于 async/await |
| **HTTP 基础** | 调 LLM 就是发 HTTP 请求 |
| **JSON 数据结构** | messages、tool_calls 全是 JSON |

### 建议掌握

| 知识点 | 为什么需要 |
|--------|----------|
| **OpenAI Chat Completions API 格式** | client.py 说的"语言"，GLM/DeepSeek 都兼容 |
| **SSE 协议** | 流式输出全靠它 |
| **异步迭代器** | stream_chat 的核心 |
| **dataclass** | types.py 全用它定义数据模型 |

### 进阶方向

| 知识点 | 为什么需要 |
|--------|----------|
| **Function Calling / Tool Use** | Agent 的核心能力 |
| **Prompt Engineering** | 提示词质量决定 Agent 表现 |
| **Token / Context Window** | 理解为什么需要压缩 |
| **LangChain / LlamaIndex** | 业界主流框架对比 |

### 最快学习路径

```
第 1 步：用 curl 手动调一次 GLM API → 理解请求和响应格式
第 2 步：学 asyncio 基础（30 分钟）
第 3 步：读 types.py → 理解数据模型
第 4 步：读 client.py → 现在会发现没那么难
第 5 步：读 loop.py → 理解循环怎么串起一切
第 6 步：自己加一个新工具 → 从实践中理解工具系统
```

curl 手动调用示例：

```bash
curl https://open.bigmodel.cn/api/paas/v4/chat/completions \
  -H "Authorization: Bearer $ZAI_CODING_CN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-4-flash",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

看到返回的 JSON 结构后，client.py 里解析的 `choices[0].delta.content` 就一目了然了。

---

## Q9: 这个框架支持 skill 吗？

当前版本**不支持** skill。

在 TS 版 Pi 中，skill 是一种「按需加载的能力描述文件」——LLM 在系统提示词里看到技能列表，需要时才加载完整内容：

```
系统提示词: "你有这些技能：calendar（日程管理）、git-helper（Git 操作）..."
用户: "帮我看看明天有什么会议"
LLM: 我需要调用 calendar 技能 → 加载完整技能内容 → 按技能指引操作
```

如果要添加 skill 支持，需要：
1. 定义 skill 格式（一个 `.md` 文件，包含 name、description、content）
2. 启动时扫描技能目录，把技能列表注入系统提示词
3. 添加 `skill` 工具，让 LLM 需要时自行加载技能详情

---

## Q10: 一个 event 是否可以理解为「类型 + 内容」？

**是的**。一个 `AgentEvent` 就是「类型 + 内容」的组合。

### 代码定义

`loop.py:22-26`：

```python
@dataclass
class AgentEvent:
    kind: str                    # ← 类型：这是什么事件
    data: dict[str, Any] = ...   # ← 内容：事件携带的具体数据
```

翻译成大白话：

```
AgentEvent = {
    kind: "这是什么",    # 类型
    data: {"具体内容"}  # 内容
}
```

### 6 种事件的「类型 + 内容」

| kind（类型） | data（内容） | 大白话 |
|------|------|------|
| `"turn_start"` | `{"turn": 1}` | "第 1 轮开始了" |
| `"text_delta"` | `{"content": "你"}` | "LLM 输出了一个字：你" |
| `"tool_start"` | `{"name": "read", "arguments": {...}}` | "开始调用 read 工具" |
| `"tool_result"` | `{"name": "read", "content": "...", "is_error": false}` | "read 工具执行完了，结果是..." |
| `"assistant_done"` | `{"content": "...", "has_tool_calls": false}` | "整条回复完成了" |
| `"error"` | `{"message": "API 错误..."}` | "出错了" |

### 类比理解

```
Event 就像一个「快递包裹」：

  ┌─────────────┐
  │  kind: 标签  │  ← 贴在箱子上：「这是文件」「这是食品」「这是电子产品」
  │  data: 货物  │  ← 箱子里的具体东西
  └─────────────┘
```

接收方（`on_event`）根据**标签**决定怎么处理：

```python
async def on_event(event: AgentEvent):
    if event.kind == "text_delta":           # ← 看标签
        print(event.data["content"])          # ← 取货物

    elif event.kind == "tool_start":         # ← 看标签
        print(Panel(event.data["name"]))      # ← 取货物

    elif event.kind == "error":              # ← 看标签
        print(f"错误: {event.data['message']}") # ← 取货物
```

### 为什么分成「类型 + 内容」两部分？

**因为接收方需要不同的处理逻辑。**

如果只有内容没有类型，接收方不知道该怎么处理：

```python
# ❌ 没有类型，怎么知道该打印还是报错？
event = {"content": "你"}      # 这是文字？还是错误信息？
event = {"name": "read"}       # 这是工具开始？还是工具结果？
```

加上类型就清晰了：

```python
# ✅ 有类型，处理逻辑明确
AgentEvent(kind="text_delta",  data={"content": "你"})    # → 打印文字
AgentEvent(kind="tool_start",  data={"name": "read"})    # → 显示工具面板
AgentEvent(kind="error",       data={"message": "..."})  # → 显示错误
```

### 一句话总结

```
Event = 类型（kind）+ 内容（data）

类型告诉接收方：「这是什么事件」
内容告诉接收方：「具体发生了什么」
```

这就是为什么一个 `on_event` 函数能处理所有不同的事件——**通过 `kind` 分流，通过 `data` 取值**。

---

## Q11: LLM、Loop、on_event、execute 四个角色的职责怎么划分？

### 核心结论

```
LLM        → 决定使用什么 tool（以及传什么参数）
Loop       → 负责 tool 的编排（什么时候调、循环控制、结果回传）
on_event   → 负责中转消息（通知外部"发生了什么"）
execute    → 负责执行 tool（真正干活）
```

一句话归纳：**LLM 是决策者，Loop 是指挥官，on_event 是传令兵，execute 是干活的士兵。**

### 四个角色各司其职

| 角色 | 职责 | 代码位置 |
|------|------|---------|
| **LLM** | 决定调用哪个工具、传什么参数 | 返回 `tool_calls: [{name:"read", arguments:{...}}]` |
| **Loop** | 编排：解析 tool_calls → 执行 → 结果加入 history | `loop.py:74-144` |
| **on_event** | 中转：发出 `tool_start` / `tool_result` 通知 | `loop.py:152-192`（发通知）<br>`app.py:209-256`（收通知） |
| **execute** | 执行：真正读文件/写文件/跑命令 | 各工具的 `execute()` 方法（如 `tools/read.py`） |

### 关键澄清：工具执行不在 on_event 中

`on_event` **只负责"广播"，不负责"执行"**。真正执行工具的是 Loop 自己。

```python
# loop.py 的 _execute_tool() 方法（精简）
async def _execute_tool(self, tool_call, on_event):
    # ① 通知："我要开始了"（on_event 只通知，不执行）
    await on_event(tool_start)

    # ② ★ 真正执行工具的是这里 ★
    tool = self.tools.get(tool_call.name)             # Loop 取工具
    output = await tool.execute(**tool_call.arguments) # Loop 调用 execute

    # ③ 通知："我做完了"
    await on_event(tool_result)

    return result
```

### 完整调用链

```
用户: "读一下 main.py"
   │
   ▼
Loop: 把消息发给 LLM
   │
   ▼
LLM: 返回 tool_calls=[{name:"read", args:{file_path:"main.py"}}]
   │   ↑ LLM 决定用什么工具
   ▼
Loop: 解析出 tool_calls，开始编排
   │
   ├→ on_event(tool_start, name="read")
   │    ↓ on_event 中转消息
   │  TUI 显示: "工具调用: read"
   │
   ├→ tool.execute(file_path="main.py")
   │    ↓ execute 执行工具
   │  ReadTool 读取文件内容
   │
   ├→ on_event(tool_result, content="文件内容...")
   │    ↓ on_event 中转消息
   │  TUI 显示: "结果: 文件内容..."
   │
   ▼
Loop: 把结果加入 history，进入下一轮 LLM 调用
```

### 类比：餐厅运营

```
LLM（点菜的顾客）
    "我要一份宫保鸡丁"
        ↓
Loop（厨师长 + 餐厅经理）
    ① 接单
    ② 自己去做菜（tool.execute）
    ③ 通知服务员："开始做了" / "做完了"
        ↓
on_event（服务员）
    ① 听到通知 → 告诉客人"开始做了" / "做完了"
    ② ❌ 不会自己去做菜
```

### on_event 的扩展价值

虽然在本项目中 `on_event` 只做显示（打印），但它的本质是一个**通用扩展点（hook）**。在生产级 Agent 中，同一个钩子可以承载：

| 用途 | 本项目 | 生产级 Agent |
|------|-------|-------------|
| 显示 | ✅ console.print | ✅ 更复杂的渲染 |
| 审计日志 | ❌ | ✅ 每次 tool_call 记录 |
| 权限审批 | ❌ | ✅ 危险操作拦截 |
| 计费统计 | ❌ | ✅ token 计数 |
| 性能监控 | ❌ | ✅ 延迟/成功率上报 |

Loop 一行代码都不用改，只需要写一个新的 `on_event` 实现——这就是观察者模式的威力。
