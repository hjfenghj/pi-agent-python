"""GLM/OpenAI 兼容 API 客户端，支持流式输出和工具调用。"""

from __future__ import annotations

import json
import types
from typing import Any, AsyncIterator

import httpx

from src.agent.types import Message, Role, ToolCall, ToolDefinition


class LLMClient:
    """调用 OpenAI 兼容 API（GLM、OpenAI、DeepSeek 等）。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def stream_chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """
        流式调用 chat/completions，yield 事件字典。

        事件类型:
          {"type": "text", "content": "..."}        — 文本增量
          {"type": "tool_call_start", "id": "...", "name": "..."}  — 工具调用开始
          {"type": "tool_call_args", "id": "...", "delta": "..."} — 工具参数增量
          {"type": "done", "finish_reason": "..."}  — 流结束
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai_dict() for m in messages],
            "stream": True,
            "temperature": temperature,
        }
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})
        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"

        async with self._client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"API 错误 {response.status_code}: {body.decode()}"
                )

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    yield {"type": "done", "finish_reason": "stop"}
                    return

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")

                # 文本内容
                if delta.get("content"):
                    yield {"type": "text", "content": delta["content"]}

                # 工具调用
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        tc_id = tc.get("id", "")
                        fn = tc.get("function", {})

                        if tc_id:  # 首次出现，带 id 和 name
                            yield {
                                "type": "tool_call_start",
                                "index": idx,
                                "id": tc_id,
                                "name": fn.get("name", ""),
                            }
                        if fn.get("arguments"):
                            yield {
                                "type": "tool_call_args",
                                "index": idx,
                                "delta": fn["arguments"],
                            }

                # 结束
                if finish:
                    yield {"type": "done", "finish_reason": finish}
                    return

    async def close(self):
        await self._client.aclose()


def build_assistant_message(
    text_parts: list[str],
    tool_call_parts: dict[int, dict[str, Any]],
) -> Message:
    """
    从流式事件累积的结果构建 assistant 消息。

    Args:
        text_parts: 所有文本增量
        tool_call_parts: {index: {"id":..., "name":..., "arguments":...}}
    """
    content = "".join(text_parts).strip() or None
    tool_calls: list[ToolCall] | None = None

    if tool_call_parts:
        tool_calls = []
        for idx in sorted(tool_call_parts.keys()):
            tc = tool_call_parts[idx]
            args_str = tc.get("arguments", "")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

    return Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)
