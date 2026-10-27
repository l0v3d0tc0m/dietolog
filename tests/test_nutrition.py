from datetime import date, timedelta

import pytest

from app import nutrition


def add_food(conn, d, kcal, p=0, f=0, c=0, id_=None):
    conn.execute("INSERT INTO food_entries VALUES (?, 'health_connect', ?,?,?,?,?,?,?,?)",
                 (id_ or f"{d}-{kcal}", f"{d}T12:00:00+03:00", d.isoformat(), "x", None,
                  kcal, p, f, c))


def test_bmr_mifflin():
    p = {"sex": "m", "birth_date": "1990-01-01", "height_cm": 180, "weight_kg": 80}
    assert nutrition.bmr(p, date(2020, 6, 1)) == pytest.approx(1780)
    p["sex"] = "f"
    assert nutrition.bmr(p, date(2020, 6, 1)) == pytest.approx(1614)


def test_age_counts_birthday(conn):
    p = {"sex": "m", "birth_date": "1990-06-15", "height_cm": 180, "weight_kg": 80}
    # one day before the 30th birthday the person is still 29
    assert nutrition.bmr(p, date(2020, 6, 14)) - nutrition.bmr(p, date(2020, 6, 15)) == 5


def test_incomplete_profile(conn, today):
    assert "error" in nutrition.day_summary(conn, today, today)


def test_today_remaining(conn, profile, today):
    conn.execute("INSERT INTO daily_activity (date, active_kcal) VALUES (?, 400)", (today.isoformat(),))
    add_food(conn, today, 500, p=40)
    s = nutrition.day_summary(conn, date(2020, 6, 1), today)  # sanity: other day has no remaining
    assert "remaining" not in s

    s = nutrition.day_summary(conn, today, today)
    age_bmr = nutrition.bmr(nutrition.profile(conn), today)
    expected_target = round(age_bmr * 1.1 + 400 * 0.85 - 400)
    assert s["target_kcal"] == expected_target
    assert s["remaining"]["kcal"] == expected_target - 500
    assert s["remaining"]["protein_g"] == round(80 * 1.8 - 40)


def test_yesterday_balance(conn, profile, today):
    y = today - timedelta(days=1)
    add_food(conn, y, 3000)
    s = nutrition.day_summary(conn, y, today)
    assert s["vs_target_kcal"] == 3000 - s["target_kcal"]
    assert s["energy_balance_kcal"] == 3000 - s["expenditure_kcal"]


def test_no_food_means_unknown_balance(conn, profile, today):
    s = nutrition.day_summary(conn, today - timedelta(days=1), today)
    assert not s["food_logged"]
    assert "vs_target_kcal" not in s
    assert "no food logged" in s["note"]


def test_period_skips_unlogged_days(conn, profile, today):
    add_food(conn, today - timedelta(days=1), 1000)
    add_food(conn, today - timedelta(days=3), 1000)
    add_food(conn, today, 9999)  # today is not part of the period
    p = nutrition.period_summary(conn, 7, today)
    assert len(p["days"]) == 7
    assert p["days_with_food_logged"] == 2
    logged = [d for d in p["days"] if d["food_logged"]]
    assert p["sum_vs_target_kcal"] == sum(d["vs_target_kcal"] for d in logged)
