"""Shell 命令执行工具。"""

from __future__ import annotations

import asyncio
from typing import Any

from src.tools.base import Tool


class BashTool(Tool):
    """执行 shell 命令。"""

    def __init__(self, working_dir: str = ".", timeout: int = 120, max_output: int = 30000):
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_output = max_output

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "执行 shell 命令并返回输出。"
            "命令在指定工作目录下执行，有超时限制。"
            "参数: command (要执行的命令)。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, **kw) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return f"错误: 命令执行超时（{self.timeout}秒）"

        output_parts = []
        if stdout:
            output_parts.append(stdout.decode("utf-8", errors="replace"))
        if stderr:
            output_parts.append("STDERR:\n" + stderr.decode("utf-8", errors="replace"))

        result = "\n".join(output_parts).strip()
        if not result:
            result = f"(命令执行完成，退出码 {proc.returncode}，无输出)"
        else:
            result += f"\n\n(退出码 {proc.returncode})"

        if len(result) > self.max_output:
            result = result[: self.max_output] + "\n\n... 输出截断"

        return result
