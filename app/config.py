"""Settings come from the .env file next to the project root."""
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} in .env (see .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_user_id: int
    ingest_token: str
    tz: ZoneInfo
    db_path: Path
    host: str
    port: int
    model: str
    effort: str
    morning_report_hour: int  # -1 disables it
    agent_backend: str        # 'claude_code' (subscription) or 'api' (ANTHROPIC_API_KEY)


def load(server: bool = True) -> Settings:
    """server=False skips the Telegram and ingest settings (for the demo data and terminal chat)."""
    get = _req if server else (lambda name: os.getenv(name, "").strip() or "0")
    return Settings(
        telegram_token=get("TELEGRAM_BOT_TOKEN"),
        telegram_user_id=int(get("TELEGRAM_USER_ID")),
        ingest_token=get("INGEST_TOKEN"),
        tz=ZoneInfo(os.getenv("TZ_NAME", "Europe/Moscow")),
        db_path=ROOT / os.getenv("DB_PATH", "data/health.db"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8765")),
        model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
        effort=os.getenv("CLAUDE_EFFORT", "medium"),
        morning_report_hour=int(os.getenv("MORNING_REPORT_HOUR", "9")),
        agent_backend=os.getenv("AGENT_BACKEND", "").strip()
        or ("api" if os.getenv("ANTHROPIC_API_KEY", "").strip() else "claude_code"),
    )


def make_agent(s: Settings, toolbox, db_path: Path):
    if s.agent_backend == "api":
        from .agent import Agent
        return Agent(toolbox, s.model, s.effort)
    from .agent_cc import ClaudeCodeAgent
    return ClaudeCodeAgent(toolbox, db_path, s.model, s.effort)
