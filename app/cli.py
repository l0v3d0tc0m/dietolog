"""Talk to the agent in the terminal, without Telegram: python -m app.cli

Works with either backend (Claude subscription or API key). Add --demo to use data/demo.db.
"""
import asyncio
import sys
from datetime import timedelta

from . import config, db, nutrition
from .bot import format_day, format_week
from .tools import Toolbox


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    s = config.load(server=False)
    path = s.db_path.parent / "demo.db" if "--demo" in sys.argv else s.db_path
    toolbox = Toolbox(db.connect(path), s.tz)
    agent = config.make_agent(s, toolbox, path)
    print(f"Режим: {s.agent_backend}, база: {path}\n/today /yesterday /week /new, пустая строка или /exit — выход\n")

    while True:
        try:
            text = (await asyncio.to_thread(input, "ты> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("", "/exit"):
            break
        today = toolbox.today()
        if text == "/today":
            print(format_day(nutrition.day_summary(toolbox.conn, today, today)))
        elif text == "/yesterday":
            print(format_day(nutrition.day_summary(toolbox.conn, today - timedelta(days=1), today)))
        elif text == "/week":
            print(format_week(nutrition.period_summary(toolbox.conn, 7, today)))
        elif text == "/new":
            agent.reset(0)
            print("Начали заново.")
        else:
            print("\nбот>", await agent.ask(0, text))
        print()


if __name__ == "__main__":
    asyncio.run(main())
