"""Agent Loop 核心循环：LLM ↔ 工具调用的引擎。"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable


def _debug(msg: str):
    """调试输出到 stderr，不干扰正常 stdout 输出。"""
    print(f"[DEBUG] {msg}", file=sys.stderr)

from src.agent.types import (
    AgentConfig,
    Message,
    Role,
    ToolCall,
    ToolResult,
)
from src.llm.client import LLMClient, build_assistant_message
from src.tools.base import ToolRegistry


# --- 事件类型（供 TUI 消费） ---

@dataclass
class AgentEvent:
    """Agent Loop 产出的事件。"""
    kind: str  # text_delta | tool_start | tool_result | assistant_done | error | turn_start
    data: dict[str, Any] = field(default_factory=dict)


# 事件回调类型
EventSink = Callable[[AgentEvent], Awaitable[None]]


class AgentLoop:
    """
    Agent 核心循环。

    流程:
        1. 把用户消息加入历史
        2. 调用 LLM（流式）
        3. 如果 LLM 请求工具 → 执行工具 → 把结果加入历史 → 回到 2
        4. 如果 LLM 直接回复 → 返回结果
    """

    def __init__(
        self,
        config: AgentConfig,
        client: LLMClient,
        tools: ToolRegistry,
    ):
        self.config = config
        self.client = client
        self.tools = tools

    async def run(
        self,
        user_input: str,
        history: list[Message],
        on_event: EventSink | None = None,
    ) -> list[Message]:
        """
        执行一次完整的 Agent 循环。

        Args:
            user_input: 用户输入文本
            history: 历史消息列表（会被修改）
            on_event: 事件回调

        Returns:
            更新后的消息历史
        """
        # 添加用户消息
        history.append(Message(role=Role.USER, content=user_input))

        for turn in range(self.config.max_turns):
            _debug(f"{'='*60}")
            _debug(f"第 {turn + 1} 轮循环开始，当前历史消息数: {len(history)}")
            if on_event:
                await on_event(AgentEvent(
                    kind="turn_start",
                    data={"turn": turn + 1},
                ))

            # 调用 LLM
            tool_defs = self.tools.definitions()
            text_parts: list[str] = []
            tool_call_parts: dict[int, dict[str, Any]] = {}

            try:
                async for event in self.client.stream_chat(
                    history, tool_defs, system_prompt=self.config.system_prompt,
                ):
                    if event["type"] == "text" and on_event:
                        text_parts.append(event["content"])
                        await on_event(AgentEvent(
                            kind="text_delta",
                            data={"content": event["content"]},
                        ))
                    elif event["type"] == "tool_call_start":
                        idx = event["index"]
                        tool_call_parts[idx] = {
                            "id": event["id"],
                            "name": event["name"],
                            "arguments": "",
                        }
                    elif event["type"] == "tool_call_args":
                        idx = event["index"]
                        if idx in tool_call_parts:
                            tool_call_parts[idx]["arguments"] += event["delta"]
                    elif event["type"] == "done":
                        break
            except Exception as e:
                if on_event:
                    await on_event(AgentEvent(
                        kind="error",
                        data={"message": str(e)},
                    ))
                break

            # 构建 assistant 消息
            assistant_msg = build_assistant_message(text_parts, tool_call_parts)
            _debug(f"LLM 返回: content={'有' if assistant_msg.content else '无'}, "
                   f"tool_calls={len(assistant_msg.tool_calls or [])}")
            if assistant_msg.tool_calls:
                for tc in assistant_msg.tool_calls:
                    _debug(f"  → 工具调用: name={tc.name}, id={tc.id}, args={tc.arguments}")
            history.append(assistant_msg)

            if on_event:
                await on_event(AgentEvent(
                    kind="assistant_done",
                    data={
                        "content": assistant_msg.content,
                        "has_tool_calls": bool(assistant_msg.tool_calls),
                    },
                ))

            # 没有工具调用 → 循环结束
            if not assistant_msg.tool_calls:
                _debug("LLM 未请求工具，循环结束")
                break

            # 执行工具调用
            for tc in assistant_msg.tool_calls:
                result = await self._execute_tool(tc, on_event)
                history.append(Message(
                    role=Role.TOOL,
                    content=result.content,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        return history

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        on_event: EventSink | None,
    ) -> ToolResult:
        """执行单个工具调用。"""
        _debug(f"{'─'*60}")
        _debug(f"工具调用开始: {tool_call.name}")
        _debug(f"  调用 ID: {tool_call.id}")
        _debug(f"  参数: {json.dumps(tool_call.arguments, ensure_ascii=False)}")

        if on_event:
            await on_event(AgentEvent(
                kind="tool_start",
                data={
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            ))

        tool = self.tools.get(tool_call.name)
        if tool is None:
            _debug(f"  ✗ 未知工具: {tool_call.name}")
            result = ToolResult(
                tool_call_id=tool_call.id,
                content=f"错误: 未知工具 '{tool_call.name}'",
                is_error=True,
            )
        else:
            try:
                t0 = time.time()
                output = await tool.execute(**tool_call.arguments)
                elapsed = time.time() - t0
                preview = output[:200].replace('\n', '\\n')
                _debug(f"  ✓ 执行完成 ({elapsed:.3f}s)")
                _debug(f"  返回 {len(output)} 字符，预览: {preview}")
                result = ToolResult(
                    tool_call_id=tool_call.id,
                    content=output,
                )
            except Exception as e:
                _debug(f"  ✗ 执行异常: {e}")
                result = ToolResult(
                    tool_call_id=tool_call.id,
                    content=f"工具执行异常: {e}",
                    is_error=True,
                )

        if on_event:
            await on_event(AgentEvent(
                kind="tool_result",
                data={
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "content": result.content,
                    "is_error": result.is_error,
                },
            ))

        return result
