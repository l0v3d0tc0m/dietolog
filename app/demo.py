"""Fills a separate database with two weeks of made-up data, so the bot can be tried without a phone.

    python -m app.demo            -> data/demo.db
then set DB_PATH=data/demo.db in .env and start the bot as usual.
"""
import random
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import config, db

MEALS = {
    "breakfast": [("Овсянка с бананом", 380, 12, 8, 65), ("Омлет из 3 яиц", 320, 21, 24, 3),
                  ("Творог 5% с мёдом", 290, 30, 10, 20), ("Сырники", 420, 25, 15, 45)],
    "lunch": [("Гречка с курицей", 560, 42, 12, 70), ("Борщ со сметаной", 350, 14, 16, 35),
              ("Паста болоньезе", 720, 35, 25, 85), ("Плов", 650, 25, 28, 75)],
    "dinner": [("Куриная грудка с овощами", 450, 48, 14, 25), ("Лосось с рисом", 620, 38, 24, 60),
               ("Пельмени", 680, 28, 30, 72), ("Салат с тунцом", 380, 32, 20, 15)],
    "snack": [("Протеиновый батончик", 210, 20, 7, 18), ("Яблоко", 80, 0, 0, 20),
              ("Шоколадка", 540, 6, 31, 58), ("Кефир 1%", 80, 6, 2, 8)],
}

INVENTORY = [
    ("Куриное филе", "product", 900, "g", 110, 23, 1.5, 0, 3),
    ("Яйца", "product", 8, "pcs", 157, 13, 11, 1, 14),
    ("Гречка", "product", 1500, "g", 343, 13, 3.4, 68, None),
    ("Рис", "product", 800, "g", 344, 7, 1, 78, None),
    ("Творог 5%", "product", 400, "g", 121, 17, 5, 3, 4),
    ("Помидоры", "product", 500, "g", 20, 1, 0.2, 4, 5),
    ("Огурцы", "product", 400, "g", 15, 0.8, 0.1, 3, 6),
    ("Сыр гауда", "product", 250, "g", 356, 25, 27, 2, 20),
    ("Плов (домашний)", "dish", 3, "portion", 180, 7, 7.5, 21, 2),
    ("Борщ", "dish", 4, "portion", 55, 2.5, 2.8, 5, 3),
]

PREFERENCES = [("dislikes", "не любит рыбу, кроме лосося"), ("likes", "любит гречку и курицу"),
               ("habit", "обычно не завтракает в выходные")]


def main():
    s = config.load(server=False)
    path = s.db_path.parent / "demo.db"
    if path.exists() and "--force" not in sys.argv:
        sys.exit(f"{path} already exists, run with --force to recreate it")
    path.unlink(missing_ok=True)
    conn = db.connect(path)
    rnd = random.Random(42)
    tz = s.tz
    today = datetime.now(tz).date()

    with conn:
        conn.execute("UPDATE profile SET sex='m', birth_date='1998-05-10', height_cm=180, "
                     "weight_kg=82.0, goal_kcal_delta=-400 WHERE id=1")
        for i in range(14, -1, -1):
            d = today - timedelta(days=i)
            is_today = i == 0
            steps = rnd.randint(2500, 6000) if is_today else rnd.randint(4000, 15000)
            conn.execute(
                "INSERT INTO daily_activity (date, steps, distance_m, active_kcal, resting_hr, avg_hr) "
                "VALUES (?,?,?,?,?,?)",
                (d.isoformat(), steps, steps * 0.75, steps * 0.04 + rnd.randint(50, 250),
                 rnd.randint(55, 63), rnd.randint(68, 80)))

            # sleep that ended this morning
            bed = datetime.combine(d - timedelta(days=1), time(23, 0), tz) + timedelta(minutes=rnd.randint(-60, 90))
            total = rnd.randint(330, 520)
            deep, rem, awake = int(total * 0.18), int(total * 0.22), rnd.randint(10, 40)
            conn.execute(
                "INSERT INTO sleep_sessions VALUES (?,?,?,?,?,?,?,?)",
                (bed.isoformat(), (bed + timedelta(minutes=total)).isoformat(), d.isoformat(), total,
                 deep, total - deep - rem - awake, rem, awake))

            if i in (5, 9):  # a couple of days with nothing logged, like in real life
                continue
            plan = [("breakfast", 9), ("lunch", 14)] + ([] if is_today else [("dinner", 19)])
            if not is_today and rnd.random() < 0.6:
                plan.append(("snack", 16))
            for n, (meal, hour) in enumerate(plan):
                name, kcal, p, f, c = rnd.choice(MEALS[meal])
                k = rnd.uniform(0.8, 1.4)
                conn.execute(
                    "INSERT INTO food_entries VALUES (?, 'health_connect', ?,?,?,?,?,?,?,?)",
                    (f"demo-{d}-{n}", datetime.combine(d, time(hour, rnd.randint(0, 59)), tz).isoformat(),
                     d.isoformat(), name, meal, round(kcal * k), round(p * k, 1), round(f * k, 1),
                     round(c * k, 1)))

            if i % 3 == 0:
                conn.execute("INSERT INTO weight_log VALUES (?,?,?)",
                             (datetime.combine(d, time(8, 0), tz).isoformat(), d.isoformat(),
                              round(82.0 + i * 0.05 + rnd.uniform(-0.3, 0.3), 1)))

        for name, kind, qty, unit, kcal, p, f, c, days in INVENTORY:
            conn.execute(
                "INSERT INTO inventory (name, kind, quantity, unit, kcal_per_100g, protein_per_100g, "
                "fat_per_100g, carbs_per_100g, expires_on) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, kind, qty, unit, kcal, p, f, c,
                 (today + timedelta(days=days)).isoformat() if days else None))
        for cat, text in PREFERENCES:
            conn.execute("INSERT INTO preferences (category, text) VALUES (?,?)", (cat, text))

    print(f"Demo data written to {path}\nSet DB_PATH=data/demo.db in .env to use it.")


if __name__ == "__main__":
    main()
