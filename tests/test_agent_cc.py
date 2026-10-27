"""Claude Code backend with a fake `claude -p` process."""
import asyncio
import base64
import json

import pytest

from app import agent_cc
from app.agent_cc import ClaudeCodeAgent


class FakeProc:
    def __init__(self, reply: dict, delay=0):
        self.reply, self.delay, self.returncode = reply, delay, 0
        self.stdin_text = None

    async def communicate(self, data):
        self.stdin_text = data.decode()
        await asyncio.sleep(self.delay)
        return json.dumps(self.reply).encode(), b""

    def kill(self):
        pass


@pytest.fixture
def cc(toolbox, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_BIN", "claude-fake")
    monkeypatch.setattr(agent_cc, "ROOT", tmp_path)
    agent = ClaudeCodeAgent(toolbox, tmp_path / "x.db", "claude-opus-5-5", "medium")
    calls, replies = [], []

    async def fake_exec(*cmd, **kw):
        proc = FakeProc(replies.pop(0), delay=0.05)
        calls.append((list(cmd), kw, proc))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return agent, calls, replies


def ok(text, sid="s1"):
    return {"type": "result", "is_error": False, "result": text, "session_id": sid}


def test_command_and_resume(cc):
    agent, calls, replies = cc
    replies += [ok("привет"), ok("ещё", "s1")]
    assert asyncio.run(agent.ask(1, "a")) == "привет"
    assert asyncio.run(agent.ask(1, "b")) == "ещё"

    first, second = calls[0][0], calls[1][0]
    assert first[:2] == ["claude-fake", "-p"]
    assert "--strict-mcp-config" in first and "--resume" not in first
    assert second[second.index("--resume") + 1] == "s1"
    assert "\nb" in calls[1][2].stdin_text  # prompt goes through stdin


def test_mcp_config_points_at_db(cc, tmp_path):
    agent, _, _ = cc
    cfg = json.loads(agent.mcp_file.read_text(encoding="utf-8"))["mcpServers"]["health"]
    assert cfg["args"] == ["-m", "app.mcp_server"]
    assert cfg["env"]["DB_PATH"].endswith("x.db")


def test_empty_api_key_not_passed(cc, monkeypatch):
    agent, calls, replies = cc
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    replies.append(ok("x"))
    asyncio.run(agent.ask(1, "a"))
    assert "ANTHROPIC_API_KEY" not in calls[0][1]["env"]


def test_not_logged_in_message(cc):
    agent, _, replies = cc
    replies.append({"is_error": True, "result": "Not logged in · Please run /login"})
    assert "setup-token" in asyncio.run(agent.ask(1, "a"))


def test_photo_saved_and_mentioned(cc):
    agent, calls, replies = cc
    replies.append(ok("вижу курицу"))
    data = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    asyncio.run(agent.ask(1, "что тут?", [("image/jpeg", data)]))
    prompt = calls[0][2].stdin_text
    path = prompt.split("Пользователь прислал фото: ")[1].strip()
    assert open(path, "rb").read() == b"\xff\xd8fakejpeg"


def test_parallel_messages_serialized(cc):
    agent, calls, replies = cc
    replies += [ok("1", "s1"), ok("2", "s1")]

    async def both():
        return await asyncio.gather(agent.ask(1, "a"), agent.ask(1, "b"))

    assert asyncio.run(both()) == ["1", "2"]
    assert "--resume" in calls[1][0]  # second waited for the first and continued its session
