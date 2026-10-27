"""Runs the ingest server and the Telegram bot in one process: python -m app.main"""
import asyncio
import logging

import uvicorn

from . import bot as tg
from . import config, db, ingest
from .tools import Toolbox


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = config.load()
    conn = db.connect(s.db_path)
    toolbox = Toolbox(conn, s.tz)
    agent = config.make_agent(s, toolbox, s.db_path)
    logging.info("agent backend: %s", s.agent_backend)

    api = ingest.create_app(conn, s.ingest_token, s.tz)
    server = uvicorn.Server(uvicorn.Config(api, host=s.host, port=s.port, log_level="info"))
    bot, dp = tg.build(s.telegram_token, s.telegram_user_id, agent, toolbox)
    await tg.set_commands(bot)

    await asyncio.gather(
        server.serve(),
        dp.start_polling(bot, handle_signals=False),
        tg.morning_report(bot, s.telegram_user_id, toolbox, s.morning_report_hour),
    )


if __name__ == "__main__":
    asyncio.run(main())
