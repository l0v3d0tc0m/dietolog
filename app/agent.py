"""Claude agent loop with the nutrition tools."""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import anthropic
from anthropic import AsyncAnthropic

from .tools import TOOLS, Toolbox

log = logging.getLogger(__name__)

SYSTEM = """Ты — личный ассистент по питанию и восстановлению одного человека. Общаешься в Telegram, по-русски, коротко и по делу, как друг, который разбирается в нутрициологии.

Что у тебя есть:
- данные с часов Redmi Watch (шаги, активные калории, пульс, сон) и дневник питания из FatSecret — всё приходит через Health Connect и лежит в базе;
- холодильник и кладовка (продукты и готовые блюда), предпочтения, профиль и цель.

Как работать:
- Цифры (сколько съедено, норма, остаток, баланс) бери только из инструментов, не считай калории дня в уме. Если еда за день не внесена, так и скажи, а не делай выводов о дефиците.
- Сегодняшняя норма растёт по ходу дня вместе с активностью, упоминай это, когда важно.
- Когда предлагаешь, что съесть, опирайся на то, что реально есть в холодильнике, и на предпочтения; называй порцию в граммах и её КБЖУ. Готовые блюда — в приоритете, особенно если скоро испортятся.
- Когда человек пишет, что купил, приготовил, съел или выкинул что-то — обнови холодильник. Приготовил блюдо из продуктов — спиши продукты и добавь блюдо с оценкой КБЖУ на 100 г.
- Еду в дневник записывай сам только если человек явно просит записать её здесь: по умолчанию он ведёт дневник в FatSecret, и запись в двух местах даст двойной счёт.
- Упомянул вкус, аллергию, привычку или цель — запомни через add_preference.
- Если профиль не заполнен (пол, дата рождения, рост, вес), сначала попроси эти данные.
- Ты не врач: при тревожных симптомах советуй обратиться к специалисту.
- Форматирование: обычный текст, можно короткие списки. Без таблиц и markdown-заголовков."""

MAX_STEPS = 15
IDLE_RESET_SECONDS = 2 * 60 * 60


@dataclass
class Conversation:
    messages: list = field(default_factory=list)
    last_active: float = 0.0


class Agent:
    def __init__(self, toolbox: Toolbox, model: str, effort: str):
        self.client = AsyncAnthropic()
        self.toolbox = toolbox
        self.model = model
        self.effort = effort
        self.chats: dict[int, Conversation] = {}
        self.locks: dict[int, asyncio.Lock] = {}

    def reset(self, chat_id: int) -> None:
        self.chats.pop(chat_id, None)

    async def ask(self, chat_id: int, text: str, images: list[tuple[str, str]] = ()) -> str:
        # Messages sent in quick succession are answered one by one, so the history stays in order.
        lock = self.locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            return await self._ask(chat_id, text, images)

    def _conversation(self, chat_id: int) -> Conversation:
        conv = self.chats.get(chat_id)
        # History is append-only; a long pause starts a fresh conversation instead of trimming.
        if conv is None or time.time() - conv.last_active > IDLE_RESET_SECONDS:
            conv = self.chats[chat_id] = Conversation()
        conv.last_active = time.time()
        return conv

    async def _ask(self, chat_id: int, text: str, images: list[tuple[str, str]]) -> str:
        """images: list of (media_type, base64 data)."""
        conv = self._conversation(chat_id)
        now = datetime.now(self.toolbox.tz)
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
                   for mt, data in images]
        # The current time goes into the message, not the system prompt, so the prompt cache holds.
        content.append({"type": "text",
                        "text": f"[{now:%Y-%m-%d %H:%M}, {now:%A}]\n{text or 'Что на фото?'}"})
        conv.messages.append({"role": "user", "content": content})

        for _ in range(MAX_STEPS):
            try:
                response = await self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=SYSTEM,
                    tools=TOOLS,
                    messages=conv.messages,
                    output_config={"effort": self.effort},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            # On any API failure the conversation restarts, so history never stays half-written.
            except anthropic.RateLimitError:
                self.reset(chat_id)
                return "Упёрся в лимит запросов к Claude, попробуй через минуту."
            except anthropic.APIConnectionError:
                self.reset(chat_id)
                return "Не достучался до Claude: проверь интернет."
            except anthropic.APIStatusError as e:
                log.exception("Claude API error")
                self.reset(chat_id)
                return f"Ошибка Claude API ({e.status_code}). Начал диалог заново."

            conv.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "Claude отказался отвечать на это сообщение. Попробуй сформулировать иначе."
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                text_out = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text_out += "\n\n(ответ обрезан)"
                return text_out or "…"

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                    out = self.toolbox.run(block.name, args)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except Exception as e:  # tool errors go back to Claude so it can fix the call
                    log.warning("tool %s failed: %s", block.name, e)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"error: {e}", "is_error": True})
            conv.messages.append({"role": "user", "content": results})

        return "Слишком много шагов, остановился. Попробуй переформулировать."
