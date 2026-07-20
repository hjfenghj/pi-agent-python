"""系统提示词。"""

from __future__ import annotations

import os
from datetime import datetime


def build_system_prompt(working_dir: str) -> str:
    """构建系统提示词。

    结构对齐原版 pi (packages/coding-agent/src/core/system-prompt.ts):
      角色 → 动作清单 → 工具 → 原则 → 日期 → 工作目录
    保留中文输出，去掉 hostname/os.name 等无用噪声。
    """
    cwd = os.path.abspath(working_dir)
    today = datetime.now().strftime("%Y-%m-%d")

    return f"""你是一名专业的编程助手，运行在 pi-agent-python（一个终端编码 agent 框架）中。
你通过读取文件、执行命令、编辑代码、编写新文件来帮助用户完成任务。

可用工具:
- read: 读取文件内容
- write: 写入文件
- edit: 精确字符串替换编辑文件
- bash: 执行 shell 命令
- grep: 在文件内容中搜索
- find: 按文件名模式查找文件

除上述工具外，根据项目配置可能还有其他扩展工具可用。

工作原则:
- 回答简洁直接，避免冗余解释
- 操作文件时清晰展示文件路径

当前日期: {today}
当前工作目录: {cwd}

当用户的请求需要操作文件或执行命令时，主动使用工具完成；当请求只需知识性解答时，直接回答。

请用中文回复。
"""
