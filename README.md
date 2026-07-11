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

- 流式输出：AI 回复实时显示
- 工具系统：read/write/edit/bash/grep/find
- 斜杠命令：/model /tools /history /clear /sessions /help /quit
- 会话持久化：JSONL 格式，自动保存和加载

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/model <name>` | 切换模型 |
| `/tools` | 列出已注册工具 |
| `/history` | 显示当前会话消息历史 |
| `/sessions` | 列出所有会话 |
| `/clear` | 清空当前会话 |
| `/quit` | 退出 |

## 环境变量

| 变量名 | 说明 |
|--------|------|
| `ZAI_CODING_CN_API_KEY` | 智谱 AI 国内版 Key（open.bigmodel.cn） |
| `ZAI_API_KEY` | 智谱 AI 国际版 Key（z.ai） |

## 架构

```
main.py                  ← 入口
src/
├── agent/
│   ├── types.py         ← 类型定义（Message, Tool, Config）
│   ├── loop.py          ← Agent Loop 核心（LLM ↔ Tool 循环）
│   └── session.py       ← JSONL 会话持久化
├── llm/
│   └── client.py        ← GLM/OpenAI 兼容 API 流式客户端
├── tools/
│   ├── base.py          ← 工具基类和注册表
│   ├── read.py          ← 文件读取
│   ├── write.py         ← 文件写入
│   ├── edit.py          ← 字符串替换编辑
│   ├── bash.py          ← Shell 命令执行
│   ├── grep.py          ← 内容搜索
│   └── find.py          ← 文件查找
├── prompt/
│   └── system.py        ← 系统提示词
└── tui/
    └── app.py           ← 交互式终端界面
```

## 支持的 GLM 模型

| 模型 | 说明 |
|------|------|
| glm-4-flash | 快速版（默认） |
| glm-4-plus | 增强版 |
| glm-4-long | 长文本版 |
| glm-4.5-air | GLM-4.5 轻量版 |
| glm-4.7 | GLM-4.7 |

## License

MIT
