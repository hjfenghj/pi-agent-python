"""Agent Loop 核心循环：LLM ↔ 工具调用的引擎。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable

from src.agent.compact import compact_history, estimate_total_tokens
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
    """Agent Loop 产出的事件。

    kind 可能值：
        - turn_start: Agent 循环新一轮开始
        - text_delta: LLM 流式输出文本增量
        - tool_start / tool_result: 工具调用开始/结束
        - assistant_done: 一次完整的 assistant 回复结束
        - auto_compact_start / auto_compact_done: 自动压缩开始/结束
        - error: 错误
    """
    kind: str
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

        # ★ 自动压缩检查：用户消息入列后，进入对话循环前
        # 这里检查能确保最新用户消息一定被保留（它在 history 末尾，不会被截断）
        if self.config.auto_compact:
            await self._maybe_auto_compact(history, on_event)

        for turn in range(self.config.max_turns):
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
                # client发送请求以后，能返回多少事件这个是怎么决定的？
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
            result = ToolResult(
                tool_call_id=tool_call.id,
                content=f"错误: 未知工具 '{tool_call.name}'",
                is_error=True,
            )
        else:
            try:
                output = await tool.execute(**tool_call.arguments)
                result = ToolResult(
                    tool_call_id=tool_call.id,
                    content=output,
                )
            except Exception as e:
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

    # ------------------------------------------------------------------
    # 自动压缩（auto compaction）
    # ------------------------------------------------------------------

    async def _maybe_auto_compact(
        self,
        history: list[Message],
        on_event: EventSink | None,
    ) -> None:
        """检查并执行自动压缩。

        触发条件（对齐原版 pi 的 shouldCompact）：
            estimated_tokens(history + system_prompt) > context_window - reserve_tokens

        压缩成功后 in-place 修改 history：clear + extend(new_messages)。
        这样 self.session.messages 引用保持不变，TUI 能感知事件并重写 JSONL。

        失败（消息太少 / LLM 报错）降级为 error 事件，不阻塞对话。
        """
        # 1. 估算当前上下文 tokens（消息 + system_prompt）
        total = estimate_total_tokens(history)
        if self.config.system_prompt:
            # system_prompt 不是 Message，单独估算（chars/4 启发式）
            total += (len(self.config.system_prompt) + 3) // 4

        threshold = self.config.context_window - self.config.compact_reserve_tokens
        if total <= threshold:
            return  # 无需压缩

        # 2. 消息太少不压缩（至少 4 条才有压缩意义）
        if len(history) < 4:
            return

        # 3. 发出开始事件
        if on_event:
            await on_event(AgentEvent(
                kind="auto_compact_start",
                data={
                    "tokens_before": total,
                    "threshold": threshold,
                    "message_count": len(history),
                },
            ))

        # 4. 动态调整 keep_recent_tokens：
        #    防御配置不合理（context_window - reserve_tokens < keep_recent_tokens），
        #    否则 compact_history 会因为 total < keep_recent_tokens 抛 ValueError。
        #    规则：实际使用的 keep_recent 不超过 total / 2（至少留一半给摘要）
        effective_keep = min(
            self.config.compact_keep_recent_tokens,
            max(1, total // 2),
        )

        # 5. 调用 compact_history 生成新消息列表
        try:
            new_messages, stats = await compact_history(
                messages=history,
                client=self.client,
                keep_recent_tokens=effective_keep,
            )
        except (ValueError, RuntimeError) as e:
            # 业务异常（消息太少、LLM 失败）：降级为 error 事件，不阻塞对话
            if on_event:
                await on_event(AgentEvent(
                    kind="error",
                    data={"message": f"自动压缩失败（降级，继续对话）: {e}"},
                ))
            return

        # 5. in-place 替换 history（保留 list 引用）
        #    注意：必须先 snapshot new_messages，因为 compact_history 返回的
        #    [summary_msg] + kept 里 kept 是 history 的切片引用，
        #    history.clear() 不会影响新 list 本身，但要避免任何隐式引用问题
        snapshot = list(new_messages)
        history.clear()
        history.extend(snapshot)

        # 6. 发出完成事件
        if on_event:
            await on_event(AgentEvent(
                kind="auto_compact_done",
                data={
                    "tokens_before": stats.tokens_before,
                    "tokens_after": stats.tokens_after,
                    "summarized_count": stats.summarized_count,
                    "kept_count": stats.kept_count,
                },
            ))
