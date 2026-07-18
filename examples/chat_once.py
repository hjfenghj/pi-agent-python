#!/usr/bin/env python3
"""单次问答示例：使用非流式 chat() 方法。

用法:
    # 方式 1: 命令行传参
    python examples/chat_once.py "1+1=?"
    python examples/chat_once.py "解释什么是递归"

    # 方式 2: 不传参，使用默认问题
    python examples/chat_once.py

环境变量:
    ZAI_CODING_CN_API_KEY - API 密钥
"""

from __future__ import annotations

import asyncio
import os
import sys

# 确保项目根目录在 sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.agent.types import Message, Role
from src.llm.client import LLMClient


async def chat_once(prompt: str, api_key: str, base_url: str, model: str) -> str:
    """单次问答：一问一答，不涉及工具，不涉及循环。

    流程:
        用户提问 → LLM 回答 → 返回结果
        (没有工具调用，没有多轮循环)
    """
    # 1. 创建客户端
    client = LLMClient(api_key=api_key, base_url=base_url, model=model)

    try:
        # 2. 构建消息（只有一条 user 消息）
        messages = [Message(role=Role.USER, content=prompt)]

        # 3. 调用非流式 chat，一次性拿到完整回答
        response = await client.chat(
            messages=messages,
            temperature=0.7,
            system_prompt="你是一个简洁的助手，回答要精炼。",
        )

        return response.content or "(无内容)"
    finally:
        # 4. 关闭客户端
        await client.close()


async def main():
    # 解析参数
    prompt = sys.argv[1] if len(sys.argv) > 1 else "什么是 Agent 框架？一句话回答。"

    # 读取配置
    api_key = os.environ.get("ZAI_CODING_CN_API_KEY") or os.environ.get("ZAI_API_KEY")
    if not api_key:
        print("错误: 请设置环境变量 ZAI_CODING_CN_API_KEY", file=sys.stderr)
        sys.exit(1)

    base_url = "https://open.bigmodel.cn/api/paas/v4"
    model = "glm-4-flash"

    print(f"问题: {prompt}")
    print(f"模型: {model}")
    print("-" * 40)

    # 调用 chat_once
    answer = await chat_once(prompt, api_key, base_url, model)

    print("-" * 40)
    print(f"回答: {answer}")


if __name__ == "__main__":
    asyncio.run(main())
