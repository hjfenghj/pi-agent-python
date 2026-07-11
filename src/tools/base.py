"""工具基类和注册器。"""

from __future__ import annotations

import abc
from typing import Any, Callable, Awaitable

from src.agent.types import ToolDefinition


class Tool(abc.ABC):
    """工具抽象基类。子类实现 name, description, parameters, execute。"""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def description(self) -> str: ...

    @property
    @abc.abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def execute(self, **kwargs) -> str: ...

    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


# 工具执行器类型：接收参数字典，返回结果字符串
ToolExecutor = Callable[..., Awaitable[str]]


class ToolRegistry:
    """工具注册表。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def definitions(self) -> list[ToolDefinition]:
        return [t.to_definition() for t in self._tools.values()]
