"""GLM/OpenAI 兼容 API 客户端，支持流式输出和工具调用。

这个文件是 Agent 和 LLM 之间的「翻译官 + 信使」：
  1. 把 Agent 内部的 Message 格式 → 翻译成 LLM 能理解的 OpenAI API 格式
  2. 发送 HTTP 请求，以流式（SSE）模式等待响应
  3. 逐行解析 LLM 返回的流式数据，翻译成统一的「事件」yield 出去

整体流程：
  Agent Loop                     本文件                      GLM 服务器
      │                             │                             │
      │  messages + tools           │                             │
      │ ──────────────────────────→ │  POST /chat/completions     │
      │                             │ ──────────────────────────→ │
      │                             │                             │
      │                             │  ←── data: {"你"}           │
      │                             │  ←── data: {"好"}           │  (SSE 流)
      │                             │  ←── data: {"tool_call"...} │
      │                             │                             │
      │  yield {"type":"text"...}   │  解析 + 翻译                │
      │ ←──────────────────────────  │                             │
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from src.agent.types import Message, Role, ToolCall, ToolDefinition


class LLMClient:
    """调用 OpenAI 兼容 API（GLM、OpenAI、DeepSeek 等）。

    GLM、OpenAI、DeepSeek、Kimi 等主流 LLM 都兼容同一个 API 格式
    （即 OpenAI 的 /chat/completions 接口），所以一个 client 通吃。
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        """创建 LLM 客户端。

        Args:
            api_key:  API 密钥（如 ZAI_CODING_CN_API_KEY 的值）
            base_url: API 基础地址（如 https://open.bigmodel.cn/api/paas/v4）
            model:    模型名称（如 glm-4-flash）

        为什么用 httpx.AsyncClient 而不是 requests？
            requests 是同步的——必须等 LLM 生成完所有内容才返回，用户要干等几秒。
            httpx.AsyncClient 是异步的——可以「边接收边处理」，实现打字机效果。
            而且复用同一个 client 实例，底层 TCP 连接池会被复用，比每次新建连接快。
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")  # 去掉末尾的 /，避免拼接出双斜杠
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),  # 总超时 5 分钟，连接超时 30 秒
            headers={
                "Authorization": f"Bearer {api_key}",  # 身份认证：告诉服务器"我是谁"
                "Content-Type": "application/json",     # 告诉服务器"我发的是 JSON"
            },
        )

    async def stream_chat(  # 发送请求
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """流式调用 chat/completions，yield 事件字典。

        什么是 AsyncIterator（异步迭代器）？
            普通函数 return 一次就结束了。
            迭代器 yield 可以返回多次。
            异步迭代器 async yield 可以「边等网络边返回」——
            每收到 LLM 的一个字，就立刻 yield 出去，不等后续。

        这就是 ChatGPT 那种「逐字显示」效果的底层原理：
            async for event in client.stream_chat(...):
                # 0.03s 收到 "你" → 立刻显示
                # 0.06s 收到 "好" → 立刻显示
                # 0.09s 收到 "，" → 立刻显示

        yield 的事件类型:
            {"type": "text", "content": "..."}                    — 文本增量（一小段文字）
            {"type": "tool_call_start", "index":0, "id":..., "name":"read"}  — 工具调用开始（第一次出现时带 id 和 name）
            {"type": "tool_call_args", "index":0, "delta":"..."}  — 工具参数增量（参数 JSON 的一个碎片）
            {"type": "done", "finish_reason": "stop"}             — 流结束

        Args:
            messages:      对话历史（包含所有之前的 user/assistant/tool 消息）
            tools:         可用工具列表（LLM 会据此决定是否调用工具）
            temperature:   创造性程度（0=严谨确定, 1=发散随机, 默认 0.7）
            system_prompt: 系统提示词（设定 AI 的角色和规则，如"你是编程助手"）
        """
        # ── 第 1 步：构建请求体 ──
        # 这就是发给 LLM 服务器的 JSON payload，遵循 OpenAI API 格式。
        #
        # messages 示例:
        #   [
        #     {"role": "system",    "content": "你是一个编程助手..."},
        #     {"role": "user",      "content": "读一下 main.py"},
        #     {"role": "assistant", "tool_calls": [{"id":"call_001", ...}]},
        #     {"role": "tool",      "tool_call_id": "call_001", "content": "文件: ..."},
        #     {"role": "assistant", "content": "main.py 共 173 行"}
        #   ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai_dict() for m in messages],  # 把内部 Message 转成 API 格式
            "stream": True,   # ★ 关键：启用流式返回（SSE），不用等整个响应生成完
            "temperature": temperature,
        }

        # system_prompt 放在 messages 的第一条，设定 AI 的"人设"
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})

        # tools 告诉 LLM「你有这些工具可以用」
        # tool_choice="auto" 表示让 LLM 自己决定是否调用工具
        # 也可以设为 "none"（禁用工具）或 {"type":"function","function":{"name":"read"}}（强制调用某个工具）
        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"

        # ── 第 2 步：发送请求，以流式模式等待响应 ──
        # self._client.stream("POST", ...) 发起请求但不断开连接，
        # 后续可以逐行读取服务器推送的数据。
        async with self._client.stream("POST", url, json=payload) as response:
            # 非 200 状态码：Key 错误(401)、模型名错(400)、限流(429) 等
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"API 错误 {response.status_code}: {body.decode()}"
                )

            # ── 第 3 步：逐行解析 SSE（Server-Sent Events）流 ──
            #
            # 什么是 SSE？
            #   LLM 服务器不是一次性返回完整 JSON，而是用一种叫 SSE 的协议，
            #   一行一行地推送数据。每行格式固定：
            #
            #   data: {"choices":[{"delta":{"content":"你"}}]}
            #
            #   data: {"choices":[{"delta":{"content":"好"}}]}
            #
            #   data: {"choices":[{"delta":{"content":"，"}}]}
            #
            #   data: [DONE]
            #
            # 特征：
            #   - 每行以 "data: " 开头（6 个字符的前缀）
            #   - 行之间有空行（心跳/分隔）
            #   - 最后一行是 [DONE] 表示流结束
            #
            # 什么是 delta（增量）？
            #   LLM 生成文本时，不是一次性想好整句话。它每次生成一个 token
            #   （大约一个字或词），就用一个 chunk 推送过来。
            #   delta.content 就是这次新生成的那一小段：
            #
            #   Chunk 1: delta.content = "你"      → 累积 = "你"
            #   Chunk 2: delta.content = "好"      → 累积 = "你好"
            #   Chunk 3: delta.content = "，我是"  → 累积 = "你好，我是"
            #   Chunk 4: finish_reason = "stop"   → 结束
            #
            async for line in response.aiter_lines():
                # 跳过空行和非数据行（SSE 协议中可能有注释行、心跳行等）
                if not line.startswith("data: "):
                    continue

                # 去掉 "data: " 前缀（6 个字符），拿到真正的数据部分
                data = line[6:]

                # [DONE] 是流结束标记
                if data.strip() == "[DONE]":
                    yield {"type": "done", "finish_reason": "stop"}
                    return

                # 解析 JSON 字符串为 Python dict
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue  # 跳过无法解析的行

                # chunk 结构示例:
                #   {
                #     "id": "chatcmpl-abc123",
                #     "model": "glm-4-flash",
                #     "choices": [{
                #       "index": 0,
                #       "delta": {"content": "你"},     ← 这就是增量内容
                #       "finish_reason": null            ← null 表示还没结束
                #     }]
                #   }
                choices = chunk.get("choices", [])
                if not choices:
                    continue

                # 只取第一个 choice（本实现不支持多候选）
                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")

                # ── 第 4a 步：提取文本增量 ──
                # delta.content 存在 → 这是文本内容
                # 每次可能只有一个字或几个字（一个 token 的量）
                if delta.get("content"):
                    yield {"type": "text", "content": delta["content"]}

                # ── 第 4b 步：提取工具调用 ──
                #
                # 工具调用是最复杂的部分，因为参数也是分块流式返回的：
                #
                #   第1个 chunk: tool_calls: [{"index":0, "id":"call_001", "function":{"name":"read"}}]
                #                                                ↑ 有 id 和 name，但没有 arguments
                #
                #   第2个 chunk: tool_calls: [{"index":0, "function":{"arguments":"{\"file"}}]
                #                                                ↑ 参数碎片1: {"file
                #
                #   第3个 chunk: tool_calls: [{"index":0, "function":{"arguments":"_path\": \"main.py\"}"}}]
                #                                                ↑ 参数碎片2: _path": "main.py"
                #
                # 拼接后: arguments = "{\"file_path\": \"main.py\"}" → json.loads → {"file_path": "main.py"}
                #
                # 为什么要分片？
                #   因为参数是一个 JSON 字符串，LLM 生成 JSON 也是逐 token 生成的。
                #   流式模式下任何内容都是逐块推送的，JSON 参数也不例外。
                #
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)     # 第几个工具调用（一次可能调多个工具）
                        tc_id = tc.get("id", "")      # 工具调用 ID（用于后续关联结果）
                        fn = tc.get("function", {})   # function 包含 name 和 arguments

                        # tc_id 非空 → 说明这是该工具调用的「第一次出现」
                        # 此时携带了工具名（如 "read"），但 arguments 通常还是空的
                        if tc_id:
                            yield {
                                "type": "tool_call_start",
                                "index": idx,
                                "id": tc_id,
                                "name": fn.get("name", ""),
                            }

                        # arguments 非空 → 这是参数的一个碎片
                        # loop.py 中会把这些碎片拼起来：arguments += delta
                        if fn.get("arguments"):
                            yield {
                                "type": "tool_call_args",
                                "index": idx,
                                "delta": fn["arguments"],
                            }

                # ── 第 5 步：检测流结束 ──
                # finish_reason 非 null 表示生成完毕
                # 可能值: "stop"（正常结束）、"tool_calls"（需要执行工具）、"length"（达到 token 上限）
                if finish:
                    yield {"type": "done", "finish_reason": finish}
                    return

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> Message:
        """非流式调用 chat/completions，一次性返回完整 Message。

        与 stream_chat 的区别：
            stream_chat：逐 token yield 事件，适合交互式 TUI（打字机效果）
            chat：       等全部生成完，一次性返回完整消息，适合：
                           - 后台批处理任务
                           - 单元测试（结果确定，便于断言）
                           - 简单脚本（一行命令拿结果）

        响应格式差异（为什么 stream_chat 解析不了非流式响应）：
            流式（SSE）:
                data: {"choices":[{"delta":{"content":"你"}}]}
                data: {"choices":[{"delta":{"content":"好"}}]}
                data: [DONE]
                ↑ 字段是 delta.content，逐行推送

            非流式（单个 JSON）:
                {
                  "choices": [{
                    "message": {"role":"assistant", "content":"你好"},
                    "finish_reason": "stop"
                  }]
                }
                ↑ 字段是 message.content，一次性返回

        Args:
            messages:      对话历史
            tools:         可用工具列表
            temperature:   创造性程度（0=严谨, 1=发散）
            system_prompt: 系统提示词

        Returns:
            完整的 assistant Message（包含 content 和 tool_calls）
        """
        # 构建请求体（和 stream_chat 相同，只是 stream=False）
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai_dict() for m in messages],
            "stream": False,  # ★ 关键区别：关闭流式
            "temperature": temperature,
        }
        if system_prompt:
            payload["messages"].insert(0, {"role": "system", "content": system_prompt})
        if tools:
            payload["tools"] = [t.to_openai_dict() for t in tools]
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        response = await self._client.post(url, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"API 错误 {response.status_code}: {response.text}"
            )

        # 非流式响应是完整的 JSON，一次性解析
        data = response.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})

        # 提取文本内容
        content = msg.get("content")
        if content:
            content = content.strip() or None

        # 提取工具调用（非流式模式下，参数是完整的 JSON 字符串，不需要拼装）
        tool_calls: list[ToolCall] | None = None
        if msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    args = {"_raw": args_str}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                ))

        return Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

    async def close(self):
        """关闭底层 HTTP 连接池，释放资源。"""
        await self._client.aclose()


def build_assistant_message(
    text_parts: list[str],
    tool_call_parts: dict[int, dict[str, Any]],
) -> Message:
    """从流式事件累积的结果构建完整的 assistant 消息。

    在 stream_chat 的流式过程中，loop.py 会收集所有碎片：
      - text_parts: 所有文本增量 ["你","好","，","我是","AI"]
      - tool_call_parts: 工具调用的拼装结果 {0: {"id":..., "name":..., "arguments":...}}

    这个函数把它们组装成一条完整的 Message，加入历史记录。

    类比：流式过程中不断收到乐高零件，这个函数是最后把零件拼成成品的步骤。

    Args:
        text_parts: 所有文本增量碎片（按顺序）
        tool_call_parts: {index: {"id":"call_001", "name":"read", "arguments":"{\"file_path\":...}"}}
    """
    # 拼接所有文本碎片：["你","好","，","我是","AI"] → "你好，我是AI"
    # .strip() 去掉首尾空白；or None 表示空字符串时设为 None（API 规范要求）
    content = "".join(text_parts).strip() or None
    tool_calls: list[ToolCall] | None = None

    if tool_call_parts:
        tool_calls = []
        # 按 index 排序（一次可能调用多个工具，index 标识第几个）
        for idx in sorted(tool_call_parts.keys()):
            tc = tool_call_parts[idx]
            # arguments 在流式过程中是一个个字符串碎片拼起来的
            # 现在把它从 JSON 字符串解析成 Python dict
            # 例如: '{"file_path": "main.py"}' → {"file_path": "main.py"}
            args_str = tc.get("arguments", "")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                # 兜底：如果 LLM 返回的 JSON 不合法（偶尔会发生），保留原始字符串
                args = {"_raw": args_str}
            tool_calls.append(ToolCall(
                id=tc["id"],         # 如 "call_001"，用于关联后续的 tool result
                name=tc["name"],     # 如 "read"
                arguments=args,      # 如 {"file_path": "main.py"}
            ))

    return Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)
