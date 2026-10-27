"""Agent backend that runs Claude Code (`claude -p`) on the user's Claude subscription.

No API key needed: Claude Code authenticates with CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`.
The nutrition tools reach Claude through the MCP server in app/mcp_server.py.
"""
import asyncio
import base64
import glob
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from .agent import IDLE_RESET_SECONDS, SYSTEM
from .config import ROOT
from .tools import Toolbox

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 300

CC_SYSTEM = SYSTEM + """

Инструменты с данными называются mcp__health__* (дневник, холодильник, профиль, предпочтения). Если пользователь прислал фото, открой его инструментом Read по указанному пути."""


def find_claude() -> str:
    """CLAUDE_BIN, then `claude` on PATH, then the copy bundled with the Claude desktop app."""
    if os.getenv("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    found = shutil.which("claude")
    if found:
        return found
    bundled = glob.glob(os.path.join(os.getenv("LOCALAPPDATA", ""), "Claude-Data", "*",
                                     "claude-code", "*", "*", "claude.exe"))
    if bundled:
        return max(bundled, key=os.path.getmtime)
    raise RuntimeError("Claude Code not found: install it or set CLAUDE_BIN in .env")


class ClaudeCodeAgent:
    def __init__(self, toolbox: Toolbox, db_path: Path, model: str, effort: str):
        self.toolbox = toolbox
        self.bin = find_claude()
        self.model = model
        self.effort = effort
        self.sessions: dict[int, tuple[str, float]] = {}
        self.locks: dict[int, asyncio.Lock] = {}

        self.workdir = ROOT / "data" / "cc-workdir"
        self.inbox = self.workdir / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.system_file = self.workdir / "system.txt"
        self.system_file.write_text(CC_SYSTEM, encoding="utf-8")
        self.mcp_file = self.workdir / "mcp.json"
        self.mcp_file.write_text(json.dumps({"mcpServers": {"health": {
            "command": sys.executable,
            "args": ["-m", "app.mcp_server"],
            "env": {"PYTHONPATH": str(ROOT), "DB_PATH": str(db_path.resolve())},
        }}}, indent=2), encoding="utf-8")
        log.info("Claude Code backend: %s", self.bin)

    def reset(self, chat_id: int) -> None:
        self.sessions.pop(chat_id, None)

    async def ask(self, chat_id: int, text: str, images: list[tuple[str, str]] = ()) -> str:
        lock = self.locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            return await self._ask(chat_id, text, images)

    async def _ask(self, chat_id: int, text: str, images) -> str:
        now = datetime.now(self.toolbox.tz)
        prompt = f"[{now:%Y-%m-%d %H:%M}, {now:%A}]\n{text or 'Что на фото?'}"
        for media_type, data in images:
            ext = media_type.split("/")[-1]
            path = self.inbox / f"{uuid.uuid4().hex[:10]}.{ext}"
            path.write_bytes(base64.b64decode(data))
            prompt += f"\n\nПользователь прислал фото: {path}"

        session = self.sessions.get(chat_id)
        if session and time.time() - session[1] > IDLE_RESET_SECONDS:
            session = None
        result = await self._run(prompt, session[0] if session else None)
        if result.get("is_error") and session and "session" in str(result.get("result", "")).lower():
            result = await self._run(prompt, None)  # the old session is gone, start a new one

        if result.get("session_id"):
            self.sessions[chat_id] = (result["session_id"], time.time())
        answer = str(result.get("result") or "").strip()
        if result.get("is_error"):
            log.warning("claude -p error: %s", answer)
            if "login" in answer.lower():
                return ("Claude Code не залогинен: выполни `claude setup-token` и впиши токен "
                        "в CLAUDE_CODE_OAUTH_TOKEN в .env, потом перезапусти бота.")
            if "limit" in answer.lower():
                return "Упёрся в лимит подписки Claude. Попробуй позже."
            self.reset(chat_id)
            return f"Claude Code вернул ошибку: {answer[:300]}"
        return answer or "…"

    async def _run(self, prompt: str, resume: str | None) -> dict:
        cmd = [self.bin, "-p", "--output-format", "json",
               "--system-prompt-file", str(self.system_file),
               "--mcp-config", str(self.mcp_file), "--strict-mcp-config",
               "--tools", "Read",
               "--allowedTools", "mcp__health", "Read",
               "--effort", self.effort, "--model", self.model]
        if resume:
            cmd += ["--resume", resume]
        env = dict(os.environ)
        if not env.get("ANTHROPIC_API_KEY"):
            env.pop("ANTHROPIC_API_KEY", None)  # an empty key would shadow the subscription login

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.workdir, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")),
                                              TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            return {"is_error": True, "result": "timeout: Claude Code думал слишком долго"}
        try:
            return json.loads(out.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            log.error("claude -p exit %s: %s %s", proc.returncode, out[-500:], err[-500:])
            return {"is_error": True, "result": err.decode("utf-8", errors="replace")[-300:]
                    or f"exit code {proc.returncode}"}
