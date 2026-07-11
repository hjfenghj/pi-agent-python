"""交互式 TUI：基于 rich + prompt_toolkit。"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from prompt_toolkit import PromptSession as PtPromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax

from src.agent.loop import AgentLoop, AgentEvent
from src.agent.session import Session
from src.agent.types import AgentConfig, Message, Role
from src.llm.client import LLMClient
from src.tools.base import ToolRegistry
from src.tools.bash import BashTool
from src.tools.edit import EditTool
from src.tools.find import FindTool
from src.tools.grep import GrepTool
from src.tools.read import ReadTool
from src.tools.write import WriteTool
from src.prompt.system import build_system_prompt


# 颜色主题
COLOR_USER = "cyan"
COLOR_ASSISTANT = "green"
COLOR_TOOL = "yellow"
COLOR_ERROR = "red"
COLOR_INFO = "dim blue"
COLOR_BANNER = "magenta"


class TUIApp:
    """交互式终端应用。"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.console = Console()
        self.tools = ToolRegistry()
        self._register_tools()
        self.client = LLMClient(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
        )
        self.session = Session()
        self.loop = AgentLoop(config, self.client, self.tools)
        self._running = True
        self._history_file = os.path.expanduser("~/.pi-agent-python/history")

        # 确保历史文件目录存在
        os.makedirs(os.path.dirname(self._history_file), exist_ok=True)

    def _register_tools(self):
        """注册内置工具。"""
        wd = self.config.working_dir
        self.tools.register(ReadTool(wd))
        self.tools.register(WriteTool(wd))
        self.tools.register(EditTool(wd))
        self.tools.register(BashTool(wd, timeout=self.config.bash_timeout))
        self.tools.register(GrepTool(wd))
        self.tools.register(FindTool(wd))

    # --- 主循环 ---

    async def run(self):
        """启动交互式 TUI。"""
        self._print_banner()
        self._print_help()

        pt_session = PtPromptSession(
            history=FileHistory(self._history_file),
        )

        while self._running:
            try:
                # 获取用户输入
                user_input = await pt_session.prompt_async(
                    [("bold cyan", "> ")],
                    multiline=False,
                )
            except (EOFError, KeyboardInterrupt):
                print()
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # 斜杠命令
            if user_input.startswith("/"):
                await self._handle_command(user_input)
                continue

            # 普通对话
            await self._handle_chat(user_input)

        await self._cleanup()

    # --- 斜杠命令 ---

    async def _handle_command(self, cmd_line: str):
        """处理斜杠命令。"""
        parts = cmd_line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "q", "exit"):
            self._running = False
            self.console.print("[dim]再见！[/dim]")

        elif cmd == "clear":
            self.session.clear()
            self.session = Session()
            self.console.print("[dim]会话已清空[/dim]")

        elif cmd == "model":
            if args:
                self.config.model = args
                self.client.model = args
                self.console.print(f"[dim]模型切换为: {args}[/dim]")
            else:
                self.console.print(f"[dim]当前模型: {self.config.model}[/dim]")

        elif cmd == "history":
            await self._show_history()

        elif cmd == "sessions":
            self._show_sessions()

        elif cmd == "tools":
            self._show_tools()

        elif cmd == "help":
            self._print_help()

        elif cmd == "save":
            self.console.print(f"[dim]当前会话已保存: {self.session.session_id}[/dim]")

        elif cmd in ("compact", "c"):
            self.console.print("[dim]压缩功能待实现（需要 LLM 生成摘要）[/dim]")

        else:
            self.console.print(f"[red]未知命令: /{cmd}[/red]")
            self._print_help()

    def _show_sessions(self):
        """列出所有会话。"""
        sessions = Session.list_sessions()
        if not sessions:
            self.console.print("[dim]暂无历史会话[/dim]")
            return

        for s in sessions[:10]:
            current = " ← 当前" if s["id"] == self.session.session_id else ""
            self.console.print(
                f"  [{COLOR_INFO}]{s['id']}[/{COLOR_INFO}] "
                f"({s['messages']} 条消息) "
                f"{s['preview']}{current}"
            )

    def _show_tools(self):
        """列出已注册工具。"""
        self.console.print("[bold]已注册工具:[/bold]")
        for t in self.tools.all():
            self.console.print(f"  [{COLOR_TOOL}]{t.name}[/{COLOR_TOOL}] - {t.description[:60]}...")

    async def _show_history(self):
        """显示当前会话历史。"""
        if not self.session.messages:
            self.console.print("[dim]暂无历史消息[/dim]")
            return

        for msg in self.session.messages:
            if msg.role == Role.USER:
                self.console.print(f"[{COLOR_USER}]用户[/{COLOR_USER}]: {msg.content or ''}")
            elif msg.role == Role.ASSISTANT:
                content = msg.content or ""
                if msg.tool_calls:
                    names = ", ".join(tc.name for tc in msg.tool_calls)
                    self.console.print(f"[{COLOR_ASSISTANT}]助手[/{COLOR_ASSISTANT}]: {content} [工具: {names}]")
                else:
                    self.console.print(f"[{COLOR_ASSISTANT}]助手[/{COLOR_ASSISTANT}]: {content}")
            elif msg.role == Role.TOOL:
                preview = (msg.content or "")[:100]
                self.console.print(f"  [{COLOR_TOOL}]{msg.name}[/{COLOR_TOOL}]: {preview}...")

    # --- 对话处理 ---

    async def _handle_chat(self, user_input: str):
        """处理一次用户对话。"""
        # 显示用户输入
        self.console.print()

        # 收集 Agent 响应
        full_text = ""

        async def on_event(event: AgentEvent):
            nonlocal full_text

            if event.kind == "text_delta":
                # 流式输出（直接 print，不使用 Live 避免闪烁）
                self.console.print(event.data["content"], end="", style=COLOR_ASSISTANT, highlight=False)

            elif event.kind == "tool_start":
                name = event.data["name"]
                args = event.data.get("arguments", {})
                args_str = json.dumps(args, ensure_ascii=False, indent=2)
                if len(args_str) > 200:
                    args_str = args_str[:200] + "..."
                self.console.print()
                self.console.print(Panel(
                    Text(f"{name}({args_str})", style=COLOR_TOOL),
                    border_style=COLOR_TOOL,
                    title=f"工具调用: {name}",
                    title_align="left",
                    expand=False,
                ))

            elif event.kind == "tool_result":
                name = event.data["name"]
                content = event.data["content"]
                is_error = event.data.get("is_error", False)
                style = COLOR_ERROR if is_error else "dim"

                # 截断长输出
                display = content
                if len(display) > 500:
                    display = display[:500] + f"\n... ({len(content)} 字符)"

                self.console.print(Panel(
                    Text(display, style=style),
                    border_style=COLOR_ERROR if is_error else COLOR_INFO,
                    title=f"结果: {name}",
                    title_align="left",
                    expand=False,
                ))

            elif event.kind == "assistant_done":
                if event.data.get("content") and not event.data.get("has_tool_calls"):
                    self.console.print()  # 最终换行

            elif event.kind == "error":
                self.console.print()
                self.console.print(f"[{COLOR_ERROR}]错误: {event.data['message']}[/{COLOR_ERROR}]")

        # 执行 Agent 循环
        # 先记录当前历史长度，用于后续持久化新消息
        prev_len = len(self.session.messages)

        try:
            updated_history = await self.loop.run(
                user_input,
                self.session.messages,
                on_event=on_event,
            )

            # 持久化新增的消息
            new_msgs = updated_history[prev_len:]
            self.session.append_batch(new_msgs)

        except Exception as e:
            self.console.print(f"\n[{COLOR_ERROR}]执行错误: {e}[/{COLOR_ERROR}]")

        self.console.print()

    # --- UI 辅助 ---

    def _print_banner(self):
        """打印启动横幅。"""
        banner = r"""
  ____    _                _____              _      _        ____
 |  _ \  (_)___ _ __   __|  ___| __ ___  __| | __ _| |__    / ___|___  _ __ __ _
 | |_) | | / __| '_ \ / _ \ |_ | '__/ _ \/ _` |/ _` | '_ \  | |   / _ \| '__/ _` |
 |  __/  | \__ \ |_) |  __/  _|| | | (_) | (_| | (_| | |_) | | |__| (_) | | | (_| |
 |_|     | ||___/ .__/ \___|_|   |_|  \___/ \__,_|\__,_|_.__/   \____\___/|_|  \__, |
          /___|_|    agent-python                                            |___/
        """
        self.console.print(banner, style=COLOR_BANNER)
        self.console.print(
            f"  [dim]模型: {self.config.model} | "
            f"工作目录: {self.config.working_dir} | "
            f"会话: {self.session.session_id}[/dim]"
        )
        self.console.print()

    def _print_help(self):
        """打印帮助信息。"""
        commands = [
            ("/help", "显示帮助"),
            ("/model <name>", "切换模型"),
            ("/tools", "列出工具"),
            ("/history", "显示当前会话历史"),
            ("/sessions", "列出所有会话"),
            ("/clear", "清空当前会话"),
            ("/quit", "退出"),
        ]
        self.console.print("[bold]斜杠命令:[/bold]")
        for cmd, desc in commands:
            self.console.print(f"  [{COLOR_INFO}]{cmd:20s}[/{COLOR_INFO}] {desc}")
        self.console.print()

    async def _cleanup(self):
        """清理资源。"""
        await self.client.close()
