"""内容搜索工具（基于 ripgrep 或 grep）。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from src.tools.base import Tool


class GrepTool(Tool):
    """在文件内容中搜索匹配模式。"""

    def __init__(self, working_dir: str = ".", max_output: int = 30000):
        self.working_dir = working_dir
        self.max_output = max_output

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "在文件内容中搜索正则表达式。"
            "使用 ripgrep (rg) 如果可用，否则回退到 grep。"
            "参数: pattern (正则表达式)，path (可选，搜索路径，默认当前目录)，"
            "include (可选，文件名 glob 过滤，如 '*.py')。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "正则表达式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索路径（默认当前目录）",
                },
                "include": {
                    "type": "string",
                    "description": "文件名 glob 过滤，如 '*.py'",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = ".", include: str = "", **kw) -> str:
        rg = shutil.which("rg")
        cmd = []

        if rg:
            cmd = [rg, "--line-number", "--no-heading", "--color=never"]
            if include:
                cmd.extend(["-g", include])
            cmd.extend([pattern, path])
        else:
            cmd = ["grep", "-rn", "--color=never"]
            if include:
                cmd.extend(["--include", include])
            cmd.extend([pattern, path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            return "错误: 搜索超时"
        except FileNotFoundError:
            return "错误: 未找到搜索工具（ripgrep 或 grep）"

        result = stdout.decode("utf-8", errors="replace").strip()
        if not result:
            return "未找到匹配结果"

        if len(result) > self.max_output:
            result = result[: self.max_output] + "\n\n... 结果截断"

        return result
