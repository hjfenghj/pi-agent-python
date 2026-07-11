"""JSONL 会话持久化。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from src.agent.types import Message, Role, ToolCall


class Session:
    """
    会话存储：JSONL 格式，每行一个条目。

    文件位置: ~/.pi-agent-python/sessions/<session_id>.jsonl
    """

    def __init__(self, session_dir: str = "~/.pi-agent-python/sessions", session_id: str | None = None):
        self.session_dir = Path(session_dir).expanduser()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.file_path = self.session_dir / f"{self.session_id}.jsonl"
        self.messages: list[Message] = []
        self._load()

    def _load(self):
        """从 JSONL 文件加载历史消息。"""
        if not self.file_path.exists():
            return

        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = self._entry_to_message(entry)
            if msg:
                self.messages.append(msg)

    def _entry_to_message(self, entry: dict) -> Message | None:
        """JSONL 条目 → Message 对象。"""
        role_str = entry.get("role", "")
        try:
            role = Role(role_str)
        except ValueError:
            return None

        tool_calls = None
        if entry.get("tool_calls"):
            tool_calls = []
            for tc in entry["tool_calls"]:
                args = tc.get("arguments", {})
                if isinstance(args, str):
                    import json as _json
                    try:
                        args = _json.loads(args)
                    except _json.JSONDecodeError:
                        args = {"_raw": args}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", tc.get("function", {}).get("name", "")),
                    arguments=args,
                ))

        return Message(
            role=role,
            content=entry.get("content"),
            tool_calls=tool_calls,
            tool_call_id=entry.get("tool_call_id"),
            name=entry.get("name"),
            timestamp=entry.get("timestamp", time.time()),
        )

    def _message_to_entry(self, msg: Message) -> dict:
        """Message 对象 → JSONL 条目。"""
        entry: dict = {
            "role": msg.role.value,
            "timestamp": msg.timestamp,
        }
        if msg.content is not None:
            entry["content"] = msg.content
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ]
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        if msg.name:
            entry["name"] = msg.name
        return entry

    def append(self, msg: Message):
        """追加一条消息并持久化。"""
        self.messages.append(msg)
        entry = self._message_to_entry(msg)
        with self.file_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def append_batch(self, msgs: list[Message]):
        """批量追加消息。"""
        self.messages.extend(msgs)
        with self.file_path.open("a", encoding="utf-8") as f:
            for msg in msgs:
                entry = self._message_to_entry(msg)
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def clear(self):
        """清空会话。"""
        self.messages.clear()
        if self.file_path.exists():
            self.file_path.unlink()

    @classmethod
    def list_sessions(cls, session_dir: str = "~/.pi-agent-python/sessions") -> list[dict]:
        """列出所有会话。"""
        d = Path(session_dir).expanduser()
        if not d.exists():
            return []

        sessions = []
        for f in sorted(d.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
            # 读取第一行获取预览
            first_user_msg = ""
            line_count = 0
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    line_count += 1
                    if not first_user_msg:
                        entry = json.loads(line.strip())
                        if entry.get("role") == "user":
                            first_user_msg = (entry.get("content") or "")[:80]
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            sessions.append({
                "id": f.stem,
                "messages": line_count,
                "preview": first_user_msg,
                "mtime": f.stat().st_mtime,
            })
        return sessions
