"""Calorie math. Plain code, no LLM, so the numbers are always the same.

Expenditure for a day:
    BMR (Mifflin-St Jeor) * 1.1  (the 1.1 covers digestion and small movement)
  + active calories from the watch * active_kcal_factor  (watches overestimate)
Target = expenditure + goal_kcal_delta (negative for a deficit).
"""
import sqlite3
from datetime import date, timedelta

from . import db

BASE_MULTIPLIER = 1.1


def profile(conn: sqlite3.Connection) -> dict:
    return db.row(conn, "SELECT * FROM profile WHERE id=1")


def missing_profile_fields(p: dict) -> list[str]:
    return [k for k in ("sex", "birth_date", "height_cm", "weight_kg") if not p.get(k)]


def bmr(p: dict, on: date) -> float:
    born = date.fromisoformat(p["birth_date"])
    age = on.year - born.year - ((on.month, on.day) < (born.month, born.day))
    base = 10 * p["weight_kg"] + 6.25 * p["height_cm"] - 5 * age
    return base + (5 if p["sex"] == "m" else -161)


def _r(x):
    return None if x is None else round(x)


def day_summary(conn: sqlite3.Connection, d: date, today: date) -> dict:
    p = profile(conn)
    missing = missing_profile_fields(p)
    if missing:
        return {"error": f"profile is incomplete, missing: {', '.join(missing)}"}

    act = db.row(conn, "SELECT * FROM daily_activity WHERE date=?", (d.isoformat(),)) or {}
    food = db.row(
        conn,
        """SELECT COUNT(*) n, SUM(kcal) kcal, SUM(protein_g) p, SUM(fat_g) f, SUM(carbs_g) c
           FROM food_entries WHERE date=?""",
        (d.isoformat(),),
    )
    sleep = db.rows(
        conn,
        "SELECT start_time, end_time, duration_min, deep_min, light_min, rem_min, awake_min "
        "FROM sleep_sessions WHERE wake_date=? ORDER BY start_time",
        (d.isoformat(),),
    )

    base = bmr(p, d) * BASE_MULTIPLIER
    active = (act.get("active_kcal") or 0) * p["active_kcal_factor"]
    expenditure = base + active
    target = expenditure + (p["goal_kcal_delta"] or 0)

    protein_t = p["weight_kg"] * p["protein_g_per_kg"]
    fat_t = p["weight_kg"] * p["fat_g_per_kg"]
    carbs_t = max(0.0, (target - protein_t * 4 - fat_t * 9) / 4)

    eaten = food["kcal"] or 0
    logged = food["n"] > 0
    out = {
        "date": d.isoformat(),
        "is_today": d == today,
        "steps": act.get("steps"),
        "active_kcal_from_watch": _r(act.get("active_kcal")),
        "resting_hr": _r(act.get("resting_hr")),
        "expenditure_kcal": _r(expenditure),
        "target_kcal": _r(target),
        "goal_delta_kcal": p["goal_kcal_delta"],
        "food_logged": logged,
        "eaten": {"kcal": _r(eaten), "protein_g": _r(food["p"] or 0),
                  "fat_g": _r(food["f"] or 0), "carbs_g": _r(food["c"] or 0)},
        "targets": {"protein_g": _r(protein_t), "fat_g": _r(fat_t), "carbs_g": _r(carbs_t)},
        "sleep": [
            {"start": s["start_time"], "end": s["end_time"], "total_min": _r(s["duration_min"]),
             "deep_min": _r(s["deep_min"]), "rem_min": _r(s["rem_min"]),
             "light_min": _r(s["light_min"]), "awake_min": _r(s["awake_min"])}
            for s in sleep
        ],
    }
    if d == today:
        out["remaining"] = {
            "kcal": _r(target - eaten),
            "protein_g": _r(protein_t - (food["p"] or 0)),
            "fat_g": _r(fat_t - (food["f"] or 0)),
            "carbs_g": _r(carbs_t - (food["c"] or 0)),
        }
        out["note"] = "today is not over: activity and target can still grow"
    if logged:
        # + means ate more than planned / more than burned
        out["vs_target_kcal"] = _r(eaten - target)
        out["energy_balance_kcal"] = _r(eaten - expenditure)
    else:
        out["note"] = (out.get("note", "") + "; no food logged, balance unknown").lstrip("; ")
    return out


def period_summary(conn: sqlite3.Connection, days: int, today: date) -> dict:
    """The last `days` full days (today not included)."""
    items = [day_summary(conn, today - timedelta(days=i), today) for i in range(days, 0, -1)]
    if items and "error" in items[0]:
        return items[0]
    logged = [x for x in items if x["food_logged"]]

    def avg(key):
        vals = [x[key] for x in items if x.get(key) is not None]
        return _r(sum(vals) / len(vals)) if vals else None

    weights = db.rows(conn, "SELECT date, kg FROM weight_log WHERE date>=? ORDER BY time",
                      ((today - timedelta(days=days)).isoformat(),))
    return {
        "days": [{k: x.get(k) for k in ("date", "steps", "target_kcal", "food_logged",
                                         "vs_target_kcal", "energy_balance_kcal")}
                 | {"eaten_kcal": x["eaten"]["kcal"],
                    "sleep_min": sum(s["total_min"] or 0 for s in x["sleep"]) or None}
                 for x in items],
        "days_with_food_logged": len(logged),
        "sum_vs_target_kcal": sum(x["vs_target_kcal"] for x in logged),
        "sum_energy_balance_kcal": sum(x["energy_balance_kcal"] for x in logged),
        "avg_steps": avg("steps"),
        "avg_expenditure_kcal": avg("expenditure_kcal"),
        "weight_log": weights,
    }
