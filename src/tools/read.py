"""文件读取工具。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.tools.base import Tool


class ReadTool(Tool):
    """读取文件内容。"""

    def __init__(self, working_dir: str = ".", max_output: int = 30000):
        self.working_dir = working_dir
        self.max_output = max_output

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return (
            "读取文件内容。支持文本文件。返回文件内容字符串。"
            "参数: file_path (文件路径，相对于工作目录或绝对路径)，"
            "offset (可选，起始行号，从1开始)，limit (可选，读取行数)。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件路径",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（从1开始），默认1",
                },
                "limit": {
                    "type": "integer",
                    "description": "读取的行数，默认读取全部",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, file_path: str, offset: int = 1, limit: int = 0, **kw) -> str:
        path = self._resolve(file_path)
        if not path.exists():
            return f"错误: 文件不存在: {file_path}"
        if path.is_dir():
            return f"错误: 路径是目录，不是文件: {file_path}"

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"错误: 没有读取权限: {file_path}"

        lines = content.splitlines()
        total = len(lines)

        start = max(offset - 1, 0)
        end = start + limit if limit > 0 else total
        lines = lines[start:end]

        # 添加行号
        numbered = []
        for i, line in enumerate(lines):
            line_num = start + i + 1
            numbered.append(f"{line_num:>6}\t{line}")

        result = "\n".join(numbered)
        if len(result) > self.max_output:
            result = result[: self.max_output] + f"\n\n... 截断（共 {total} 行）"

        header = f"文件: {file_path} ({total} 行)\n\n"
        return header + result

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.working_dir) / p
        return p.resolve()
