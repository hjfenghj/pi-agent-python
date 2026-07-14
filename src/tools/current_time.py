"""获取当前时间工具。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.tools.base import Tool


class CurrentTimeTool(Tool):
    """获取当前系统时间。"""

    @property
    def name(self) -> str:
        return "current_time"

    @property
    def description(self) -> str:
        return (
            "获取当前系统时间。"
            "参数: timezone (可选，时区，如 'Asia/Shanghai'，默认本地时区)，"
            "format (可选，时间格式，默认 '%Y-%m-%d %H:%M:%S')。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "时区名称，如 'Asia/Shanghai'、'UTC'、'America/New_York'。默认本地时区",
                },
                "format": {
                    "type": "string",
                    "description": "时间格式字符串，默认 '%Y-%m-%d %H:%M:%S'",
                },
            },
            "required": [],
        }

    async def execute(self, timezone: str = "", format: str = "%Y-%m-%d %H:%M:%S", **kw) -> str:
        if timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(timezone)
                now = datetime.now(tz)
                return f"当前时间 ({timezone}): {now.strftime(format)}"
            except Exception:
                return f"错误: 无法识别的时区: {timezone}"

        now = datetime.now()
        return f"当前时间: {now.strftime(format)}"
