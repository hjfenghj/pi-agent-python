"""核心类型定义：消息、工具、内容块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class TextContent:
    """文本内容块。"""
    text: str

    def to_dict(self) -> dict:
        return {"type": "text", "text": self.text}


@dataclass
class ToolCall:
    """工具调用请求（LLM 发起）。"""
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class ToolResult:
    """工具执行结果（返回给 LLM）。"""
    tool_call_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> dict:
        return {
            "tool_call_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error,
        }


@dataclass
class Message:
    """统一的对话消息。"""
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # role=tool 时使用
    name: str | None = None  # role=tool 时的工具名
    timestamp: float = field(default_factory=lambda: __import__("time").time())

    def to_openai_dict(self) -> dict:
        """转换为 OpenAI API 格式。"""
        if self.role == Role.TOOL:
            return {
                "role": "tool",
                "content": self.content or "",
                "tool_call_id": self.tool_call_id,
            }
        msg: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            import json
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


@dataclass
class ToolDefinition:
    """工具定义（注册到 LLM 的 schema）。"""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def to_openai_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class AgentConfig:
    """Agent 运行配置。"""
    model: str = "glm-4-flash"
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    system_prompt: str = ""
    max_turns: int = 30
    max_tool_output: int = 30000
    bash_timeout: int = 120
    working_dir: str = "."
    # 上下文管理（自动压缩）
    context_window: int = 128000              # 模型上下文窗口（tokens），用于自动压缩触发判断
    auto_compact: bool = True                 # 是否启用自动压缩
    compact_reserve_tokens: int = 16384       # 触发阈值 = context_window - 此值
    compact_keep_recent_tokens: int = 20000   # 自动压缩时保留末尾 tokens（与手动 /compact 共用）
