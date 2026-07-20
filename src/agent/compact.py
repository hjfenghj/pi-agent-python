"""对话历史压缩（compaction）。

参考原版 pi 的 packages/coding-agent/src/core/compaction/ 实现，
针对 pi-agent-python 的简化模型（仅 USER/ASSISTANT/TOOL 三种角色）裁剪。

核心流程：
    1. 从末尾向前累积 token 估算值，找到截断点
    2. 把要丢弃的前段消息序列化为文本
    3. 调用 LLM 生成结构化摘要
    4. 用 [摘要消息 + 保留消息] 替换原历史

YAGNI 取舍：暂不实现 split-turn、文件跟踪、分支摘要、扩展钩子。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.agent.types import Message, Role
from src.llm.client import LLMClient


# ============================================================================
# 默认配置
# ============================================================================

#: 压缩时为 LLM 响应保留的 token 预算
DEFAULT_RESERVE_TOKENS = 16384

#: 压缩时保留的最近消息 token 数（不摘要）
DEFAULT_KEEP_RECENT_TOKENS = 20000

#: 序列化时单条工具结果的最大字符数（避免巨长输出吃掉摘要预算）
TOOL_RESULT_MAX_CHARS = 2000


# ============================================================================
# Token 估算（chars/4 启发式，与原版 pi 一致）
# ============================================================================

def estimate_tokens(message: Message) -> int:
    """估算单条消息的 token 数。

    使用 chars/4 启发式（保守，偏高），与原版 pi 相同。
    """
    chars = 0

    # 文本内容
    if message.content:
        chars += len(message.content)

    # 工具调用（assistant 发起）
    if message.tool_calls:
        for tc in message.tool_calls:
            chars += len(tc.name)
            try:
                chars += len(json.dumps(tc.arguments, ensure_ascii=False))
            except (TypeError, ValueError):
                pass

    return (chars + 3) // 4  # 等价于 ceil(chars / 4)


def estimate_total_tokens(messages: list[Message]) -> int:
    """估算消息列表的总 token 数。"""
    return sum(estimate_tokens(m) for m in messages)


# ============================================================================
# 截断点查找
# ============================================================================

def find_cut_point(
    messages: list[Message],
    keep_recent_tokens: int = DEFAULT_KEEP_RECENT_TOKENS,
) -> int:
    """找到截断点索引。

    从末尾向前累积 token，到达 keep_recent_tokens 时停止。
    截断点必须是 USER 或 ASSISTANT 消息：
        - 不能是 TOOL（会丢失对应的 tool_call_id 关联）
        - USER 消息是 turn 起点，ASSISTANT 的 tool_calls 后面会跟着
          对应的 TOOL 结果（一起保留）

    Returns:
        截断点索引 messages[cut_idx]；消息太少时返回 0（无需压缩）。
    """
    if not messages:
        return 0

    accumulated = 0
    for i in range(len(messages) - 1, -1, -1):
        accumulated += estimate_tokens(messages[i])

        # 未达预算，继续向前
        if accumulated < keep_recent_tokens:
            continue

        # 已达预算，从此点向前找最近的合法截断位置
        # 合法截断点：USER 或 ASSISTANT
        # （TOOL 消息必须跟在 ASSISTANT 后面，不能作为起点）
        for j in range(i, -1, -1):
            role = messages[j].role
            if role in (Role.USER, Role.ASSISTANT):
                return j
        # 整段都是 TOOL 消息（异常情况），无法截断
        return 0

    # 全部消息累积起来都没达到预算 → 无需压缩
    return 0


# ============================================================================
# 消息序列化（防止 LLM 把对话当作要继续的会话）
# ============================================================================

def _truncate_for_summary(text: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    """截断长文本，保留前段并标注截断量。"""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... {omitted} more characters truncated]"


def serialize_conversation(messages: list[Message]) -> str:
    """把消息序列化为带角色标签的纯文本。

    输出格式：
        [User]: 用户说的内容
        [Assistant]: 助手回复
        [Assistant tool calls]: read({"path": "foo.py"}); edit(...)
        [Tool result]: 工具输出（截断到 2000 字符）

    这种标签化格式让 LLM 明确这是"待摘要的历史文本"，
    而不是要继续的对话——避免摘要请求变成回应用户。
    """
    parts: list[str] = []

    for msg in messages:
        if msg.role == Role.USER:
            content = msg.content or ""
            if content:
                parts.append(f"[User]: {content}")

        elif msg.role == Role.ASSISTANT:
            text_parts: list[str] = []
            tool_calls: list[str] = []

            if msg.content:
                text_parts.append(msg.content)

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args_str = json.dumps(tc.arguments, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_str = "{}"
                    tool_calls.append(f"{tc.name}({args_str})")

            if text_parts:
                parts.append(f"[Assistant]: {''.join(text_parts)}")
            if tool_calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(tool_calls)}")

        elif msg.role == Role.TOOL:
            content = msg.content or ""
            if content:
                truncated = _truncate_for_summary(content)
                name = msg.name or "tool"
                parts.append(f"[Tool result ({name})]: {truncated}")

    return "\n\n".join(parts)


# ============================================================================
# 摘要 Prompt（结构化格式，对齐原版 pi）
# ============================================================================

#: 系统 prompt：阻止 LLM 把对话当作要继续的会话
SUMMARIZATION_SYSTEM_PROMPT = (
    "你是一个上下文摘要助手。你的任务是阅读一段用户与 AI 助手的对话，"
    "然后按照指定格式生成结构化摘要。\n\n"
    "不要继续对话。不要回答对话中的任何问题。只输出结构化摘要。"
)

#: 初始摘要 prompt
SUMMARIZATION_PROMPT = """以上对话是需要摘要的内容。请生成一份结构化的上下文检查点摘要，供另一个 LLM 继续工作使用。

请严格使用以下格式：

## 目标
[用户试图完成什么？如果会话涉及多个任务，可以列多条。]

## 约束与偏好
- [用户提到的任何约束、偏好或要求]
- [如果没有，写 "(无)"]

## 进度
### 已完成
- [x] [已完成的任务/变更]

### 进行中
- [ ] [当前工作]

### 已阻塞
- [阻碍进度的问题，如果有]

## 关键决策
- **[决策]**：[简要理由]

## 下一步
1. [接下来应该发生什么，按顺序列出]

## 关键上下文
- [继续工作所需的数据、示例或引用]
- [如果没有，写 "(无)"]

各节保持简洁。务必保留精确的文件路径、函数名和错误信息。"""

#: 增量更新摘要 prompt（已有旧摘要时使用）
UPDATE_SUMMARIZATION_PROMPT = """以上对话是需要并入现有摘要的新内容。请根据 <previous-summary> 中的现有摘要更新结构化摘要。

规则：
- 保留现有摘要中的所有信息
- 从新消息中添加新的进度、决策和上下文
- 更新"进度"一节：完成的项从"进行中"移到"已完成"
- 根据已完成的工作更新"下一步"
- 务必保留精确的文件路径、函数名和错误信息
- 已不相关的内容可以删除

请严格使用以下格式：

## 目标
[保留现有目标，若任务扩展则添加新目标]

## 约束与偏好
- [保留现有内容，添加新发现的约束]

## 进度
### 已完成
- [x] [包含之前已完成项 + 新完成项]

### 进行中
- [ ] [当前工作 - 根据进度更新]

### 已阻塞
- [当前阻塞项 - 已解决则删除]

## 关键决策
- **[决策]**：[简要理由]（保留所有之前的，添加新的）

## 下一步
1. [根据当前状态更新]

## 关键上下文
- [保留重要上下文，按需添加]

各节保持简洁。务必保留精确的文件路径、函数名和错误信息。"""


# ============================================================================
# 摘要消息构造
# ============================================================================

#: 摘要消息前缀，让 LLM 明确这是历史摘要而非新用户输入
SUMMARY_MESSAGE_PREFIX = "[历史对话摘要 - 上下文续接]\n\n"


def build_summary_message(summary: str) -> Message:
    """把摘要文本包装成一条 USER 消息注入历史。

    用 USER 角色而非 SYSTEM：主流 OpenAI 兼容 API 对多个 system 消息
    的支持不一，USER 角色更通用。前缀标识确保 LLM 不会把它当作
    新的用户提问。
    """
    return Message(
        role=Role.USER,
        content=f"{SUMMARY_MESSAGE_PREFIX}{summary}",
    )


# ============================================================================
# 核心压缩函数
# ============================================================================

@dataclass
class CompactStats:
    """压缩过程的统计信息。"""
    tokens_before: int       # 压缩前估算总 tokens
    tokens_after: int        # 压缩后估算总 tokens
    summarized_count: int    # 被摘要的消息条数
    kept_count: int          # 保留的消息条数（不含新增的摘要消息）
    cut_index: int           # 截断点索引


async def compact_history(
    messages: list[Message],
    client: LLMClient,
    *,
    keep_recent_tokens: int = DEFAULT_KEEP_RECENT_TOKENS,
    custom_instructions: str | None = None,
    temperature: float = 0.3,
) -> tuple[list[Message], CompactStats]:
    """压缩对话历史。

    Args:
        messages: 当前完整历史（不会被修改，返回新列表）
        client: 用于生成摘要的 LLM 客户端
        keep_recent_tokens: 保留的最近消息 token 预算
        custom_instructions: 可选的摘要聚焦指令（如"重点保留代码相关讨论"）
        temperature: 摘要生成的温度（默认 0.3，偏低以保证稳定）

    Returns:
        (new_messages, stats):
            new_messages: 压缩后的新历史列表
            stats: CompactStats 统计信息

    Raises:
        ValueError: 消息太少无法压缩
        RuntimeError: LLM 调用失败
    """
    if len(messages) < 4:
        raise ValueError("消息太少，无需压缩（至少需要 4 条）")

    # 1. 找截断点
    cut_idx = find_cut_point(messages, keep_recent_tokens)
    if cut_idx <= 0:
        raise ValueError(
            f"无可压缩内容：累积 token 未达预算 ({keep_recent_tokens})"
        )

    tokens_before = estimate_total_tokens(messages)

    # 2. 切分
    to_summarize = messages[:cut_idx]
    kept = messages[cut_idx:]

    # 3. 序列化待摘要部分
    conversation_text = serialize_conversation(to_summarize)

    # 4. 构造摘要 prompt
    prompt_text = f"<conversation>\n{conversation_text}\n</conversation>\n\n"
    base_prompt = SUMMARIZATION_PROMPT
    if custom_instructions:
        base_prompt = f"{base_prompt}\n\n额外聚焦：{custom_instructions}"
    prompt_text += base_prompt

    # 5. 调用 LLM 生成摘要（非流式）
    summary_request: list[Message] = [
        Message(role=Role.USER, content=prompt_text),
    ]

    try:
        response = await client.chat(
            messages=summary_request,
            tools=None,
            temperature=temperature,
            system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
        )
    except Exception as e:
        raise RuntimeError(f"摘要生成失败: {e}") from e

    summary_text = (response.content or "").strip()
    if not summary_text:
        raise RuntimeError("摘要生成返回空内容")

    # 6. 构造新历史：[摘要消息] + [保留消息]
    summary_msg = build_summary_message(summary_text)
    new_messages = [summary_msg] + kept

    tokens_after = estimate_total_tokens(new_messages)

    stats = CompactStats(
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        summarized_count=len(to_summarize),
        kept_count=len(kept),
        cut_index=cut_idx,
    )

    return new_messages, stats
