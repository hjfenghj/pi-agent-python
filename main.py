#!/usr/bin/env python3
"""pi-agent-python 入口文件。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# 确保项目根目录在 sys.path 中
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.agent.types import AgentConfig
from src.tui.app import TUIApp


# 默认配置
DEFAULT_MODEL = "glm-4-flash"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ENV_KEYS = ["ZAI_CODING_CN_API_KEY", "ZAI_API_KEY", "GLM_API_KEY"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="pi-agent-python: Python 版 AI 编程助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-m", "--model",
        default=DEFAULT_MODEL,
        help=f"模型名称（默认: {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API Key（也可通过环境变量设置）",
    )
    parser.add_argument(
        "-d", "--dir",
        default=".",
        help="工作目录（默认: 当前目录）",
    )
    parser.add_argument(
        "-p", "--print",
        metavar="PROMPT",
        default=None,
        help="Print 模式：执行一次 prompt 后退出（非交互式）",
    )
    parser.add_argument(
        "--bash-timeout",
        type=int,
        default=120,
        help="bash 命令超时秒数（默认: 120）",
    )
    return parser.parse_args()


def resolve_api_key(cli_key: str | None) -> str:
    """解析 API Key：命令行 > 环境变量。"""
    if cli_key:
        return cli_key
    for env_key in ENV_KEYS:
        val = os.environ.get(env_key)
        if val:
            return val
    print(
        "错误: 未找到 API Key。\n"
        "请通过以下方式之一提供:\n"
        "  1. 命令行: --api-key YOUR_KEY\n"
        f"  2. 环境变量: export ZAI_CODING_CN_API_KEY=YOUR_KEY",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_base_url(model: str, cli_url: str | None) -> str:
    """解析 base URL。"""
    if cli_url:
        return cli_url
    # 根据环境变量自动选择
    if os.environ.get("ZAI_API_KEY") and not os.environ.get("ZAI_CODING_CN_API_KEY"):
        return "https://api.z.ai/api/paas/v4"
    return DEFAULT_BASE_URL


async def run_print_mode(config: AgentConfig, prompt: str):
    """Print 模式：一问一答。"""
    from src.agent.loop import AgentLoop
    from src.agent.types import Message, Role
    from src.llm.client import LLMClient
    from src.tools.base import ToolRegistry
    from src.tools.bash import BashTool
    from src.tools.edit import EditTool
    from src.tools.find import FindTool
    from src.tools.grep import GrepTool
    from src.tools.read import ReadTool
    from src.tools.write import WriteTool
    from src.tools.current_time import CurrentTimeTool
    from src.prompt.system import build_system_prompt

    config.system_prompt = build_system_prompt(config.working_dir)

    tools = ToolRegistry()
    wd = config.working_dir
    tools.register(ReadTool(wd))
    tools.register(WriteTool(wd))
    tools.register(EditTool(wd))
    tools.register(BashTool(wd, timeout=config.bash_timeout))
    tools.register(GrepTool(wd))
    tools.register(FindTool(wd))
    tools.register(CurrentTimeTool())

    client = LLMClient(config.api_key, config.base_url, config.model)
    loop = AgentLoop(config, client, tools)

    history: list[Message] = []

    async def on_event(event):
        if event.kind == "text_delta":
            print(event.data["content"], end="", flush=True)
        elif event.kind == "tool_start":
            print(f"\n[工具] {event.data['name']}({event.data.get('arguments', {})})")
        elif event.kind == "tool_result":
            content = event.data["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"[结果] {content}")
        elif event.kind == "error":
            print(f"\n错误: {event.data['message']}", file=sys.stderr)

    try:
        await loop.run(prompt, history, on_event=on_event)
        print()
    finally:
        await client.close()


async def run_interactive(config: AgentConfig):
    """交互式 TUI 模式。"""
    from src.prompt.system import build_system_prompt
    config.system_prompt = build_system_prompt(config.working_dir)
    app = TUIApp(config)
    await app.run()


async def main():
    args = parse_args()

    api_key = resolve_api_key(args.api_key)
    base_url = resolve_base_url(args.model, args.base_url)

    config = AgentConfig(
        model=args.model,
        api_key=api_key,
        base_url=base_url,
        working_dir=os.path.abspath(args.dir),
        bash_timeout=args.bash_timeout,
    )

    if args.print:
        await run_print_mode(config, args.print)
    else:
        await run_interactive(config)


if __name__ == "__main__":
    asyncio.run(main())
