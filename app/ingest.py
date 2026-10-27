"""HTTP endpoint the Android app pushes Health Connect data to."""
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


class DayIn(BaseModel):
    date: date
    steps: int | None = None
    distance_m: float | None = None
    active_kcal: float | None = None
    total_kcal: float | None = None
    resting_hr: float | None = None
    avg_hr: float | None = None


class SleepIn(BaseModel):
    start: datetime
    end: datetime
    deep_min: float | None = None
    light_min: float | None = None
    rem_min: float | None = None
    awake_min: float | None = None


class FoodIn(BaseModel):
    id: str
    time: datetime
    name: str | None = None
    meal: str | None = None
    kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None


class WeightIn(BaseModel):
    time: datetime
    kg: float


class Payload(BaseModel):
    # Food entries in [range_from, range_to] are replaced as a whole,
    # so entries deleted in FatSecret disappear here too.
    range_from: date
    range_to: date
    days: list[DayIn] = []
    sleep: list[SleepIn] = []
    food: list[FoodIn] = []
    weight: list[WeightIn] = []


def create_app(conn: sqlite3.Connection, token: str, tz: ZoneInfo) -> FastAPI:
    app = FastAPI(title="health-agent ingest")

    def local_date(ts: datetime) -> str:
        return ts.astimezone(tz).date().isoformat()

    @app.get("/health")
    def health():
        return {"ok": True}

    # async on purpose: runs on the event loop thread like the bot, so the shared
    # SQLite connection is never used from two threads at once
    @app.post("/ingest")
    async def ingest(p: Payload, authorization: str = Header(default="")):
        if authorization != f"Bearer {token}":
            raise HTTPException(401, "bad token")

        with conn:
            for d in p.days:
                conn.execute(
                    """INSERT INTO daily_activity
                       (date, steps, distance_m, active_kcal, total_kcal, resting_hr, avg_hr, updated_at)
                       VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(date) DO UPDATE SET
                         steps=excluded.steps, distance_m=excluded.distance_m,
                         active_kcal=excluded.active_kcal, total_kcal=excluded.total_kcal,
                         resting_hr=excluded.resting_hr, avg_hr=excluded.avg_hr,
                         updated_at=CURRENT_TIMESTAMP""",
                    (d.date.isoformat(), d.steps, d.distance_m, d.active_kcal,
                     d.total_kcal, d.resting_hr, d.avg_hr),
                )

            for s in p.sleep:
                conn.execute(
                    """INSERT OR REPLACE INTO sleep_sessions
                       (start_time, end_time, wake_date, duration_min, deep_min, light_min, rem_min, awake_min)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (s.start.isoformat(), s.end.isoformat(), local_date(s.end),
                     (s.end - s.start).total_seconds() / 60,
                     s.deep_min, s.light_min, s.rem_min, s.awake_min),
                )

            conn.execute(
                "DELETE FROM food_entries WHERE source='health_connect' AND date BETWEEN ? AND ?",
                (p.range_from.isoformat(), p.range_to.isoformat()),
            )
            for f in p.food:
                conn.execute(
                    """INSERT OR REPLACE INTO food_entries
                       (id, source, time, date, name, meal, kcal, protein_g, fat_g, carbs_g)
                       VALUES (?, 'health_connect', ?,?,?,?,?,?,?,?)""",
                    (f.id, f.time.isoformat(), local_date(f.time), f.name, f.meal,
                     f.kcal, f.protein_g, f.fat_g, f.carbs_g),
                )

            for w in p.weight:
                conn.execute(
                    "INSERT OR REPLACE INTO weight_log (time, date, kg) VALUES (?,?,?)",
                    (w.time.isoformat(), local_date(w.time), w.kg),
                )
            if p.weight:
                latest = max(p.weight, key=lambda w: w.time)
                conn.execute("UPDATE profile SET weight_kg=? WHERE id=1", (latest.kg,))

        return {"ok": True, "days": len(p.days), "sleep": len(p.sleep),
                "food": len(p.food), "weight": len(p.weight)}

    return app
