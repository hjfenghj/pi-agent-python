"""文件编辑工具：精确字符串替换。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.base import Tool


class EditTool(Tool):
    """通过字符串替换编辑文件。"""

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "通过精确字符串替换编辑文件。"
            "在文件中找到 old_text 并替换为 new_text。"
            "如果 old_text 出现多次会报错，需要提供更长的唯一上下文。"
            "参数: file_path, old_text (要替换的原文), new_text (替换后的文本)。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要编辑的文件路径",
                },
                "old_text": {
                    "type": "string",
                    "description": "要被替换的原文（必须精确匹配）",
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的新文本",
                },
            },
            "required": ["file_path", "old_text", "new_text"],
        }

    async def execute(self, file_path: str, old_text: str, new_text: str, **kw) -> str:
        path = self._resolve(file_path)
        if not path.exists():
            return f"错误: 文件不存在: {file_path}"

        content = path.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)

        if count == 0:
            return f"错误: 在文件中未找到要替换的文本"
        if count > 1:
            return f"错误: 要替换的文本出现了 {count} 次，请提供更长的唯一上下文"

        new_content = content.replace(old_text, new_text, 1)
        path.write_text(new_content, encoding="utf-8")
        return f"成功编辑 {file_path}（1 处替换）"

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.working_dir) / p
        return p.resolve()
