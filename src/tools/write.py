"""文件写入工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.base import Tool


class WriteTool(Tool):
    """写入文件内容（覆盖）。"""

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return (
            "将内容写入文件。如果文件已存在则覆盖，不存在则创建（含父目录）。"
            "参数: file_path (文件路径)，content (文件内容)。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要写入的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "文件内容",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, file_path: str, content: str, **kw) -> str:
        path = self._resolve(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        line_count = content.count("\n") + 1
        return f"成功写入 {file_path} ({line_count} 行)"

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.working_dir) / p
        return p.resolve()
