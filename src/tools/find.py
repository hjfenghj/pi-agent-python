"""文件查找工具（基于 glob 模式）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.base import Tool


class FindTool(Tool):
    """按 glob 模式查找文件。"""

    def __init__(self, working_dir: str = ".", max_results: int = 200):
        self.working_dir = working_dir
        self.max_results = max_results

    @property
    def name(self) -> str:
        return "find"

    @property
    def description(self) -> str:
        return (
            "按 glob 模式查找文件。"
            "参数: pattern (glob 模式，如 '**/*.py')，"
            "path (可选，搜索根路径，默认当前目录)。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 '**/*.py'",
                },
                "path": {
                    "type": "string",
                    "description": "搜索根路径（默认当前目录）",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = ".", **kw) -> str:
        root = Path(path)
        if not root.is_absolute():
            root = Path(self.working_dir) / root

        if not root.exists():
            return f"错误: 路径不存在: {path}"

        matches = sorted(root.glob(pattern))
        if not matches:
            return "未找到匹配文件"

        # 限制结果数量
        truncated = False
        if len(matches) > self.max_results:
            matches = matches[: self.max_results]
            truncated = True

        # 转为相对路径显示
        lines = []
        for m in matches:
            try:
                rel = m.relative_to(Path(self.working_dir))
                lines.append(str(rel))
            except ValueError:
                lines.append(str(m))

        result = "\n".join(lines)
        if truncated:
            result += f"\n\n... 结果截断（最多显示 {self.max_results} 条）"

        return result
