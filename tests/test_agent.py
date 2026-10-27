"""Agent loop against a fake Claude client (no network, no API key needed)."""
import asyncio

import anthropic
import httpx
import pytest
from anthropic.types.beta import BetaMessage

from app.agent import Agent


def msg(content, stop):
    return BetaMessage.model_validate({
        "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1}})


def text(t):
    return msg([{"type": "text", "text": t}], "end_turn")


def tool_call(name, args, id_="t1"):
    return msg([{"type": "tool_use", "id": id_, "name": name, "input": args}], "tool_use")


class FakeClaude:
    def __init__(self, replies, delay=0):
        self.replies = list(replies)
        self.calls = []
        self.delay = delay

    async def create(self, **kw):
        self.calls.append([dict(m) for m in kw["messages"]])
        assert kw["fallbacks"] == "default"
        await asyncio.sleep(self.delay)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_agent(toolbox, replies, delay=0):
    agent = Agent(toolbox, "claude-opus-5-5", "medium")
    fake = FakeClaude(replies, delay)
    agent.client.beta.messages.create = fake.create
    return agent, fake


def test_tool_call_then_answer(toolbox, profile):
    agent, fake = make_agent(toolbox, [tool_call("get_day_summary", {}), text("Осталось 1500")])
    assert asyncio.run(agent.ask(1, "сколько осталось?")) == "Осталось 1500"
    result = fake.calls[1][-1]["content"][0]
    assert result["type"] == "tool_result" and "target_kcal" in result["content"]


def test_tool_error_goes_back_to_claude(toolbox):
    agent, fake = make_agent(toolbox, [tool_call("remove_preference", {"bogus": 1}), text("ок")])
    assert asyncio.run(agent.ask(1, "x")) == "ок"
    result = fake.calls[1][-1]["content"][0]
    assert result["is_error"] is True


def test_history_kept_between_messages(toolbox):
    agent, fake = make_agent(toolbox, [text("первый"), text("второй")])
    asyncio.run(agent.ask(1, "a"))
    asyncio.run(agent.ask(1, "b"))
    assert len(fake.calls[1]) == 3  # user, assistant, user


def test_refusal(toolbox):
    agent, _ = make_agent(toolbox, [msg([], "refusal")])
    assert "отказался" in asyncio.run(agent.ask(1, "x"))


def test_api_error_resets_conversation(toolbox):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.InternalServerError("boom", response=httpx.Response(500, request=req), body=None)
    agent, fake = make_agent(toolbox, [text("раз"), err, text("заново")])
    asyncio.run(agent.ask(1, "a"))
    assert "500" in asyncio.run(agent.ask(1, "b"))
    asyncio.run(agent.ask(1, "c"))
    assert len(fake.calls[2]) == 1  # fresh history after the error


def test_parallel_messages_answered_in_order(toolbox):
    agent, fake = make_agent(toolbox, [text("1"), text("2")], delay=0.05)

    async def both():
        return await asyncio.gather(agent.ask(1, "a"), agent.ask(1, "b"))

    assert asyncio.run(both()) == ["1", "2"]
    # second request must see the full first exchange, not two user messages in a row
    roles = [m["role"] for m in fake.calls[1]]
    assert roles == ["user", "assistant", "user"]


@pytest.mark.parametrize("stop,suffix", [("max_tokens", "(ответ обрезан)")])
def test_truncated_answer_marked(toolbox, stop, suffix):
    agent, _ = make_agent(toolbox, [msg([{"type": "text", "text": "длинный"}], stop)])
    assert asyncio.run(agent.ask(1, "x")).endswith(suffix)
