# pi-agent-python 代码架构全景

> 本文档梳理 pi-agent-python 的模块职责、数据流和核心设计，
> 配套阅读：[学习路径](./learning-path.md)

## 一、项目概述

pi-agent-python 是 TypeScript 版 Pi Agent 的 Python 简化实现。
它用 GLM（智谱 AI）模型驱动一个终端编码助手，支持工具调用循环、
流式输出、斜杠命令和会话持久化。

- **语言**: Python 3.10+
- **异步框架**: asyncio
- **终端 UI**: rich（输出渲染）+ prompt_toolkit（输入处理）
- **HTTP 客户端**: httpx（异步流式）
- **总代码量**: 约 1650 行（不含空文件和 __init__.py）

## 二、模块依赖关系

```
main.py (入口)
  │
  ├── src/prompt/system.py        ← 系统提示词构建
  │
  ├── src/tui/app.py (TUIApp)     ← 交互式终端界面
  │     │
  │     ├── src/agent/loop.py     ← Agent Loop 核心引擎
  │     │     │
  │     │     ├── src/agent/types.py    ← 类型定义
  │     │     ├── src/llm/client.py     ← LLM 流式客户端
  │     │     └── src/tools/base.py     ← 工具注册表
  │     │           ├── read.py
  │     │           ├── write.py
  │     │           ├── edit.py
  │     │           ├── bash.py
  │     │           ├── grep.py
  │     │           └── find.py
  │     │
  │     └── src/agent/session.py  ← JSONL 会话存储
  │
  └── (Print 模式直接组装 loop + tools，不经过 TUI)
```

## 三、分层架构

```
┌─────────────────────────────────────────────────────┐
│                  入口层 (main.py)                     │
│    参数解析 → 选择模式 → 启动                         │
├─────────────────────────────────────────────────────┤
│                  交互层 (tui/app.py)                  │
│    用户输入 → 斜杠命令分发 / 对话请求                  │
│    流式事件 → rich 渲染输出                           │
├─────────────────────────────────────────────────────┤
│                  引擎层 (agent/loop.py)               │
│    Agent Loop: 调LLM → 解析工具 → 执行 → 回调         │
├──────────────────┬──────────────────────────────────┤
│  接口层 (llm/)   │           工具层 (tools/)          │
│  SSE 流式解析    │    read / write / edit / bash      │
│  消息格式转换    │    grep / find                     │
│                  │                                    │
├──────────────────┴──────────────────────────────────┤
│                  存储层 (agent/session.py)            │
│    JSONL 会话持久化                                  │
├─────────────────────────────────────────────────────┤
│                  类型层 (agent/types.py)              │
│    Message / ToolCall / ToolResult / AgentConfig     │
└─────────────────────────────────────────────────────┘
```

## 四、核心数据流：一次完整的 Agent 交互

```
用户在终端输入: "帮我读一下 main.py"
  │
  ▼
┌─────────────────────────────────────────┐
│  TUIApp._handle_chat()                   │  tui/app.py
│  记录当前历史长度，准备接收事件           │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  AgentLoop.run(user_input, history)      │  agent/loop.py
│  ① 追加 Message(role=USER) 到 history    │
│  ② 进入 while 循环                       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  LLMClient.stream_chat()                 │  llm/client.py
│  发送 POST /chat/completions (stream)    │
│  逐行读取 SSE 响应                        │
└────────────────┬────────────────────────┘
                 │ 流式事件
                 ▼
┌─────────────────────────────────────────┐
│  事件回调 on_event()                      │  tui/app.py
│                                          │
│  text_delta  → console.print(实时输出)   │
│  tool_start  → Panel(工具调用展示)       │
│  tool_result → Panel(结果展示)           │
│  assistant_done → 换行                   │
└────────────────┬────────────────────────┘
                 │
     ┌───────────┴───────────┐
     │ LLM 是否请求了工具？  │
     └───────────┬───────────┘
          │ 是              │ 否
          ▼                 ▼
  执行工具            循环结束
  Tool.execute()      返回 history
          │
          ▼
  追加 Message(role=TOOL) 到 history
          │
          └──→ 回到"调用 LLM"
```

## 五、各模块详解

### 5.1 类型层 — `src/agent/types.py` (120 行)

定义了全局共享的数据结构，是所有模块的共同语言。

| 类型 | 职责 | 关键字段 |
|------|------|----------|
| `Role` | 消息角色枚举 | USER / ASSISTANT / TOOL |
| `Message` | 对话消息 | role, content, tool_calls, tool_call_id |
| `ToolCall` | LLM 发起的工具调用 | id, name, arguments |
| `ToolResult` | 工具执行结果 | tool_call_id, content, is_error |
| `ToolDefinition` | 工具的 JSON Schema 定义 | name, description, parameters |
| `AgentConfig` | 全局配置 | model, api_key, base_url, working_dir |

**关键方法**: `Message.to_openai_dict()` — 把内部消息格式转换为 OpenAI API 格式

### 5.2 LLM 接口层 — `src/llm/client.py` (145 行)

封装 GLM/OpenAI 兼容 API 的流式调用。

**核心方法**: `stream_chat()` — 发起流式请求，逐 chunk yield 事件

**输入输出**:
- 输入: `list[Message]` + `list[ToolDefinition]` + `system_prompt`
- 输出: 异步迭代器，yield 事件字典

**事件类型**:
```
{"type": "text", "content": "..."}                   ← 文本增量
{"type": "tool_call_start", "index": 0, "id": "...", "name": "read"}  ← 工具开始
{"type": "tool_call_args", "index": 0, "delta": "..."} ← 工具参数增量
{"type": "done", "finish_reason": "stop"}            ← 流结束
```

**辅助函数**: `build_assistant_message()` — 从流式累积结果构建完整 Message

### 5.3 工具层 — `src/tools/` (共 514 行)

| 文件 | 行数 | 工具名 | 功能 |
|------|------|--------|------|
| `base.py` | 57 | (基类) | Tool 抽象基类 + ToolRegistry 注册表 |
| `read.py` | 88 | read | 读取文件（带行号、支持 offset/limit） |
| `write.py` | 56 | write | 写入文件（覆盖模式，自动创建目录） |
| `edit.py` | 72 | edit | 精确字符串替换（唯一匹配检查） |
| `bash.py` | 74 | bash | Shell 命令执行（超时控制） |
| `grep.py` | 89 | grep | 内容搜索（ripgrep 优先，回退 grep） |
| `find.py` | 78 | find | 文件查找（glob 模式匹配） |

**设计模式**: 模板方法 — Tool 基类定义接口，子类实现 execute()

### 5.4 引擎层 — `src/agent/loop.py` (194 行)

Agent Loop 是整个系统的心脏。

**AgentLoop 类**:
- `run(user_input, history, on_event)` — 执行完整循环
- `_execute_tool(tool_call, on_event)` — 执行单个工具

**循环逻辑**:
```
for turn in range(max_turns):
    1. 流式调用 LLM
    2. 收集文本增量 + 工具调用片段
    3. 构建 assistant Message，追加到 history
    4. 如果没有 tool_calls → break
    5. 逐个执行 tool_calls
    6. 追加 tool result Messages 到 history
    7. 回到 1
```

**AgentEvent 事件类型** (供 TUI 消费):
- `turn_start` — 新的一轮开始
- `text_delta` — LLM 文本增量
- `tool_start` — 工具调用开始
- `tool_result` — 工具执行完成
- `assistant_done` — assistant 消息完成
- `error` — 错误

### 5.5 交互层 — `src/tui/app.py` (314 行)

基于 rich + prompt_toolkit 的终端交互界面。

**TUIApp 类** 职责:
- 注册工具、初始化 LLM 客户端和会话
- 主循环: prompt_toolkit 接收输入 → 分发
- 斜杠命令处理: /model /tools /history /clear /sessions /help /quit
- 对话处理: 调用 AgentLoop + 事件回调实时渲染
- rich Panel 渲染工具调用和结果

### 5.6 存储层 — `src/agent/session.py` (149 行)

JSONL 格式的会话持久化。

- 存储路径: `~/.pi-agent-python/sessions/<session_id>.jsonl`
- 每行一个 JSON 条目，包含 role、content、tool_calls、timestamp
- 支持 append（追加）、append_batch（批量）、clear（清空）
- Session.list_sessions() — 列出所有历史会话

### 5.7 入口 — `main.py` (173 行)

命令行入口，两种运行模式:
- **交互式 TUI**: `python main.py` — 进入全交互模式
- **Print 模式**: `python main.py -p "prompt"` — 一问一答后退出

### 5.8 系统提示词 — `src/prompt/system.py` (41 行)

根据工作目录构建系统提示词，包含:
- 工具使用说明
- 工作原则
- 环境信息（目录、主机名、操作系统）

## 六、与 TypeScript 版 Pi 的对比

| 方面 | TS 版 Pi | Python 版 |
|------|---------|-----------|
| 代码量 | ~80,000 行 | ~1,650 行 |
| Agent Loop | agent-loop.ts + agent-harness.ts (分层) | loop.py (单层) |
| LLM 接口 | 77 个提供商，统一 streamSimple() | OpenAI 兼容 API（覆盖 GLM/OpenAI/DeepSeek） |
| 工具系统 | 9 个工具 + 扩展注入 | 6 个内置工具 |
| 会话管理 | JSONL + 分支树 + 压缩 + 导航 | JSONL 线性存储 |
| TUI | 自研差分渲染引擎 (230KB) | rich + prompt_toolkit |
| 扩展系统 | TypeScript 动态 import() | 无 |
| 状态管理 | 快照隔离 + save point | 直接追加 |

Python 版是 TS 版核心逻辑的**教学级简化实现**，
保留了 Agent 的核心设计（Loop + Tool + Stream + Session），
省略了工程化层（Harness、扩展系统、差分渲染）。

## 七、扩展指南

### 添加新工具

```python
# src/tools/my_tool.py
from src.tools.base import Tool

class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "做一件很酷的事"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "输入"}
            },
            "required": ["input"],
        }

    async def execute(self, input: str, **kw) -> str:
        return f"结果: {input}"
```

然后在 `tui/app.py` 的 `_register_tools()` 中注册:
```python
from src.tools.my_tool import MyTool
self.tools.register(MyTool(working_dir))
```

### 添加斜杠命令

在 `tui/app.py` 的 `_handle_command()` 中添加:
```python
elif cmd == "mycmd":
    self.console.print("执行自定义命令")
```
