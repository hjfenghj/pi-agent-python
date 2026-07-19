# pi-agent-python

Python 版 AI 编程助手，基于 GLM（智谱 AI）模型，支持工具调用循环。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 API Key（国内版）
export ZAI_CODING_CN_API_KEY="你的key"

# 启动交互式 TUI
python main.py

# 或指定模型
python main.py -m glm-4-flash

# Print 模式（一问一答）
python main.py -p "用 Python 写一个快速排序"

# 指定工作目录
python main.py -d /path/to/project
```

## 功能

- **流式输出**：AI 回复逐字实时显示（打字机效果）
- **工具系统**：read / write / edit / bash / grep / find / current_time
- **斜杠命令**：/model /tools /history /clear /sessions /help /quit
- **会话持久化**：JSONL 格式，自动保存和加载
- **双模式 LLM 调用**：流式（stream_chat）+ 非流式（chat）

## 运行模式

### 1. 交互式 TUI（默认）

```bash
python main.py
```

流式输出 + 工具调用 + 斜杠命令的完整交互体验。

### 2. Print 模式（一问一答）

```bash
python main.py -p "解释什么是递归"
```

执行一次对话后退出，适合脚本调用。

### 3. 非流式体验（examples）

```bash
python examples/chat_once.py "1+1=?"
```

体验非流式输出的效果（等待几秒后一次性返回）。详见 [examples/chat_once.md](examples/chat_once.md)。

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/model <name>` | 切换模型 |
| `/tools` | 列出已注册工具 |
| `/history` | 显示当前会话消息历史 |
| `/sessions` | 列出所有会话 |
| `/resume` | 选择并恢复历史会话（交互式选择） |
| `/clear` | 清空当前会话 |
| `/quit` | 退出 |

## 环境变量

| 变量名 | 说明 |
|--------|------|
| `ZAI_CODING_CN_API_KEY` | 智谱 AI 国内版 Key（open.bigmodel.cn） |
| `ZAI_API_KEY` | 智谱 AI 国际版 Key（z.ai） |

## 架构

```
main.py                        ← 入口
src/
├── agent/
│   ├── types.py               ← 类型定义（Message, Tool, Config）
│   ├── loop.py                ← Agent Loop 核心（LLM ↔ Tool 循环）
│   └── session.py             ← JSONL 会话持久化
├── llm/
│   └── client.py              ← LLM 客户端（流式 stream_chat + 非流式 chat）
├── tools/
│   ├── base.py                ← 工具基类和注册表
│   ├── read.py                ← 文件读取
│   ├── write.py               ← 文件写入
│   ├── edit.py                ← 字符串替换编辑
│   ├── bash.py                ← Shell 命令执行
│   ├── grep.py                ← 内容搜索
│   ├── find.py                ← 文件查找
│   └── current_time.py        ← 当前时间查询
├── prompt/
│   └── system.py              ← 系统提示词
└── tui/
    └── app.py                 ← 交互式终端界面
examples/
├── chat_once.py               ← 非流式调用体验脚本
└── chat_once.md               ← 体验脚本说明
docs/
├── architecture.md            ← 代码架构详解
├── learning-path.md           ← 学习路径（8 阶段）
└── q&a.md                     ← 常见问答汇总
```

## 核心概念

### Agent Loop（执行者）

Agent 的核心是一个循环：LLM 思考 → 调用工具 → 拿到结果 → 再思考，直到给出最终回答。

```
用户输入
   ↓
[LLM 思考] ←───────┐
   ↓               │
需要工具？          │
   ├─ 否 → 返回回答（结束）
   └─ 是           │
       ↓           │
   [执行工具]      │
       ↓           │
   [结果加入历史] ──┘
```

### 流式 vs 非流式

| 特性 | 流式 `stream_chat()` | 非流式 `chat()` |
|------|---------------------|-----------------|
| 输出方式 | 逐 token 推送 | 一次性返回 |
| 用户体验 | 打字机效果 | 等几秒后全部出现 |
| 适用场景 | TUI 交互 | 脚本/测试/批处理 |

详见 [examples/chat_once.md](examples/chat_once.md)。

### EventSink（事件回调）

Loop 通过事件回调向外广播执行进度，与 UI 解耦：

```
AgentLoop（执行者）──on_event(event)──→ TUIApp（响应者）
```

Loop 不依赖任何具体 UI，同一套逻辑可以接入 TUI、Web、测试等不同前端。

## 支持的 GLM 模型

| 模型 | 说明 |
|------|------|
| glm-4-flash | 快速版（默认） |
| glm-4-plus | 增强版 |
| glm-4-long | 长文本版 |
| glm-4.5-air | GLM-4.5 轻量版 |
| glm-4.7 | GLM-4.7 |

## 文档

- [代码架构详解](docs/architecture.md)
- [学习路径（8 阶段）](docs/learning-path.md)
- [常见问答汇总](docs/q&a.md)
- [非流式体验说明](examples/chat_once.md)

## License

MIT
