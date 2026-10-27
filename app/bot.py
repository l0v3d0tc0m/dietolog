"""Telegram bot: quick commands without the LLM, everything else goes to the agent."""
import asyncio
import base64
import io
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, Message

from . import nutrition
from .agent import Agent
from .tools import Toolbox

log = logging.getLogger(__name__)

HELP = (
    "Пиши как другу: «сколько мне ещё можно съесть», «купил 1 кг курицы и десяток яиц», "
    "«сварил плов на 4 порции», «что поесть на ужин». Можно прислать фото холодильника или чека.\n\n"
    "/today — сводка за сегодня\n/yesterday — итог вчера\n/week — последние 7 дней\n"
    "/new — начать диалог заново"
)


def _n(x, unit=""):
    return "—" if x is None else f"{x}{unit}"


def _sleep_line(sleep: list[dict]) -> str | None:
    if not sleep:
        return None
    total = sum(s["total_min"] or 0 for s in sleep)
    deep = sum(s["deep_min"] or 0 for s in sleep)
    rem = sum(s["rem_min"] or 0 for s in sleep)
    return f"Сон: {total // 60} ч {total % 60} мин (глубокий {deep} мин, REM {rem} мин)"


def format_day(s: dict) -> str:
    if "error" in s:
        return "Сначала заполни профиль: напиши пол, дату рождения, рост и вес."
    e, t = s["eaten"], s["targets"]
    lines = [f"📅 {s['date']}" + (" (сегодня)" if s["is_today"] else "")]
    lines.append(f"Норма: {s['target_kcal']} ккал (расход ~{s['expenditure_kcal']}, "
                 f"цель {s['goal_delta_kcal']:+d})")
    if s["food_logged"]:
        lines.append(f"Съедено: {e['kcal']} ккал · Б {e['protein_g']}/{t['protein_g']} "
                     f"Ж {e['fat_g']}/{t['fat_g']} У {e['carbs_g']}/{t['carbs_g']}")
    else:
        lines.append("Еда не внесена")
    if s["is_today"]:
        r = s["remaining"]
        lines.append(f"Осталось: {r['kcal']} ккал · Б {r['protein_g']} Ж {r['fat_g']} У {r['carbs_g']}")
    elif s["food_logged"]:
        v = s["vs_target_kcal"]
        word = "переел" if v > 0 else "недоел"
        lines.append(f"Итог: {word} {abs(v)} ккал относительно плана "
                     f"(чистый баланс {s['energy_balance_kcal']:+d})")
    lines.append(f"Шаги: {_n(s['steps'])} · активность {_n(s['active_kcal_from_watch'], ' ккал')}"
                 f" · пульс покоя {_n(s['resting_hr'])}")
    sl = _sleep_line(s["sleep"])
    if sl:
        lines.append(sl)
    return "\n".join(lines)


def format_week(p: dict) -> str:
    if "error" in p:
        return "Сначала заполни профиль: напиши пол, дату рождения, рост и вес."
    lines = ["📊 Последние 7 дней"]
    for d in p["days"]:
        v = d["vs_target_kcal"]
        lines.append(f"{d['date'][5:]}: " + (
            f"{d['eaten_kcal']}/{d['target_kcal']} ({v:+d})" if d["food_logged"] else "еда не внесена")
            + f" · {_n(d['steps'])} шагов")
    lines.append(f"Сумма относительно плана: {p['sum_vs_target_kcal']:+d} ккал "
                 f"за {p['days_with_food_logged']} дн.")
    lines.append(f"Чистый баланс энергии: {p['sum_energy_balance_kcal']:+d} ккал "
                 f"(≈ {p['sum_energy_balance_kcal'] / 7700:+.2f} кг)")
    if p["weight_log"]:
        w = p["weight_log"]
        lines.append(f"Вес: {w[0]['kg']} → {w[-1]['kg']} кг")
    return "\n".join(lines)


async def send_long(message: Message, text: str) -> None:
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i + 4000])


def build(bot_token: str, user_id: int, agent: Agent, toolbox: Toolbox):
    bot = Bot(bot_token)
    dp = Dispatcher()
    router = Router()
    # Only the owner can talk to the bot
    router.message.filter(F.from_user.id == user_id)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def start(m: Message):
        await m.answer("Привет! " + HELP)

    @router.message(Command("today"))
    async def today(m: Message):
        d = toolbox.today()
        await m.answer(format_day(nutrition.day_summary(toolbox.conn, d, d)))

    @router.message(Command("yesterday"))
    async def yesterday(m: Message):
        d = toolbox.today()
        await m.answer(format_day(nutrition.day_summary(toolbox.conn, d - timedelta(days=1), d)))

    @router.message(Command("week"))
    async def week(m: Message):
        await m.answer(format_week(nutrition.period_summary(toolbox.conn, 7, toolbox.today())))

    @router.message(Command("new"))
    async def new(m: Message):
        agent.reset(m.chat.id)
        await m.answer("Ок, начинаем заново.")

    @router.message(F.photo | F.text)
    async def chat(m: Message):
        images = []
        if m.photo:
            buf = await bot.download(m.photo[-1], destination=io.BytesIO())
            images.append(("image/jpeg", base64.b64encode(buf.getvalue()).decode()))
        typing = asyncio.create_task(_keep_typing(bot, m.chat.id))
        try:
            reply = await agent.ask(m.chat.id, m.text or m.caption or "", images)
        except Exception:
            log.exception("agent failed")
            reply = "Что-то сломалось, подробности в логе."
        finally:
            typing.cancel()
        await send_long(m, reply)

    dp.include_router(router)
    return bot, dp


async def _keep_typing(bot: Bot, chat_id: int):
    while True:
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(4)


async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="today", description="Сводка за сегодня"),
        BotCommand(command="yesterday", description="Итог вчера"),
        BotCommand(command="week", description="Последние 7 дней"),
        BotCommand(command="new", description="Начать диалог заново"),
    ])


async def morning_report(bot: Bot, user_id: int, toolbox: Toolbox, hour: int):
    """Sends yesterday's summary every day at `hour` local time."""
    if hour < 0:
        return
    while True:
        now = datetime.now(toolbox.tz)
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            d = toolbox.today()
            text = format_day(nutrition.day_summary(toolbox.conn, d - timedelta(days=1), d))
            await bot.send_message(user_id, "Доброе утро! Итоги вчера:\n\n" + text)
        except Exception:
            log.exception("morning report failed")
